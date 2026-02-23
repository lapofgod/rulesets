#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = ROOT / "sources"
OUTPUT_ROOT = ROOT / "generated"
RULESET_BASELINE = "mihomo"
TARGETS = ["surge", "mihomo", "shadowrocket", "loon", "sing-box"]

DOMAIN_KINDS = {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-WILDCARD"}
DOMAINSET_CAPABLE_KINDS = {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-WILDCARD"}
ENDPOINT_KINDS = {
    "IP-CIDR",
    "IP-CIDR6",
    "SRC-IP-CIDR",
    "DST-PORT",
    "DEST-PORT",
    "SRC-PORT",
    "GEOIP",
    "URL-REGEX",
}
UA_KINDS = {"USER-AGENT"}


@dataclass(frozen=True)
class Rule:
    kind: str
    value: str
    extras: tuple[str, ...] = ()

    @property
    def as_line(self) -> str:
        return ",".join([self.kind, self.value, *self.extras])


@dataclass(frozen=True)
class Bundle:
    name: str
    source: Path


@dataclass(frozen=True)
class RuleGroups:
    domain: list[Rule]
    endpoint: list[Rule]
    ua: list[Rule]
    upgradable_domainset: bool


def normalize_kind(kind: str) -> str:
    normalized = kind.strip().upper().replace("_", "-")
    if normalized == "DEST-PORT":
        return "DST-PORT"
    return normalized


def parse_conf_line(raw: str) -> Rule | None:
    line = raw.strip()
    if not line or line.startswith("#"):
        return None

    if line.startswith("."):
        return Rule("DOMAIN-SUFFIX", line[1:])
    if line.startswith("+.") or line.startswith("*."):
        return Rule("DOMAIN-SUFFIX", line[2:])

    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 2:
        return None

    kind = normalize_kind(parts[0])
    value = parts[1]
    extras = tuple(parts[2:]) if len(parts) > 2 else ()

    if kind == "DOMAIN-SUFFIX" and value.startswith("."):
        value = value[1:]

    return Rule(kind, value, extras)


def parse_file(file_path: Path) -> list[Rule]:
    rules: list[Rule] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        parsed = parse_conf_line(line)
        if parsed:
            rules.append(parsed)
    return rules


def write_lines(file_path: Path, lines: Iterable[str]) -> bool:
    line_list = list(lines)
    if not line_list:
        return False
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("\n".join(line_list).rstrip() + "\n", encoding="utf-8")
    return True


def write_lines_with_header(file_path: Path, lines: Iterable[str]) -> bool:
    line_list = list(lines)
    if not line_list:
        return False

    header = [
        "# Auto-generated file. Do not edit manually.",
        f"# Rule count: {len(line_list)}",
        "",
    ]
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("\n".join([*header, *line_list]).rstrip() + "\n", encoding="utf-8")
    return True


def write_yaml_with_header(file_path: Path, payload: dict, rule_count: int) -> None:
    header = [
        "# Auto-generated file. Do not edit manually.",
        f"# Rule count: {rule_count}",
        "",
    ]
    body = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("\n".join(header) + body, encoding="utf-8")


def dedupe_sort_strings(items: Iterable[str]) -> list[str]:
    return sorted(set(items))


def map_rule_for_target(target: str, rule: Rule) -> Rule | None:
    kind = rule.kind
    value = rule.value
    extras = rule.extras

    if kind == "DST-PORT" and target in {"surge", "shadowrocket"}:
        kind = "DEST-PORT"

    if kind == "DOMAIN-WILDCARD":
        if target == "loon":
            if value.startswith("*."):
                return Rule("DOMAIN-SUFFIX", value[2:], extras)
            return None
        if target == "sing-box":
            if value.startswith("*."):
                return Rule("DOMAIN-SUFFIX", value[2:], extras)
            return None

    if kind == "USER-AGENT" and target in {"mihomo", "sing-box"}:
        return None

    return Rule(kind, value, extras)


def map_rules_for_target(target: str, rules: list[Rule]) -> list[Rule]:
    mapped: list[Rule] = []
    for rule in rules:
        converted = map_rule_for_target(target, rule)
        if converted is not None:
            mapped.append(converted)
    return mapped


def split_rules(rules: list[Rule]) -> RuleGroups:
    domain: list[Rule] = []
    endpoint: list[Rule] = []
    ua: list[Rule] = []

    for rule in rules:
        if rule.kind in DOMAIN_KINDS:
            domain.append(rule)
        elif rule.kind in UA_KINDS:
            ua.append(rule)
        else:
            endpoint.append(rule)

    upgradable_domainset = bool(rules) and all(rule.kind in DOMAINSET_CAPABLE_KINDS for rule in rules)
    return RuleGroups(domain=domain, endpoint=endpoint, ua=ua, upgradable_domainset=upgradable_domainset)


def output_path(target: str, bundle: Bundle, filename: str) -> Path:
    return OUTPUT_ROOT / target / bundle.name / filename


def to_domainset_entry(target: str, rule: Rule) -> str | None:
    if rule.kind == "DOMAIN":
        return rule.value

    if rule.kind == "DOMAIN-SUFFIX":
        prefix = "+." if target == "mihomo" else "."
        return f"{prefix}{rule.value}"

    if rule.kind == "DOMAIN-WILDCARD":
        if rule.value.startswith("*."):
            suffix = rule.value[2:]
            prefix = "+." if target == "mihomo" else "."
            return f"{prefix}{suffix}"
        return None

    return None


def domainset_entries_for_target(target: str, rules: list[Rule]) -> list[str]:
    entries: list[str] = []
    for rule in rules:
        entry = to_domainset_entry(target, rule)
        if entry:
            entries.append(entry)
    return dedupe_sort_strings(entries)


def to_mihomo_payload(rules: list[Rule]) -> dict:
    return {"payload": [rule.as_line for rule in rules], "metadata": {"ruleset_baseline": RULESET_BASELINE}}


def to_sing_box_rules(rules: list[Rule]) -> dict:
    grouped: dict[str, list[str]] = {
        "domain": [],
        "domain_suffix": [],
        "domain_keyword": [],
        "ip_cidr": [],
    }

    for rule in rules:
        if rule.kind == "DOMAIN":
            grouped["domain"].append(rule.value)
        elif rule.kind == "DOMAIN-SUFFIX":
            grouped["domain_suffix"].append(rule.value)
        elif rule.kind == "DOMAIN-KEYWORD":
            grouped["domain_keyword"].append(rule.value)
        elif rule.kind in {"IP-CIDR", "IP-CIDR6"}:
            grouped["ip_cidr"].append(rule.value)

    mapped: list[dict] = []
    for key in ["domain", "domain_suffix", "domain_keyword", "ip_cidr"]:
        values = dedupe_sort_strings(grouped[key])
        if values:
            mapped.append({key: values})

    return {
        "version": 1,
        "rules": mapped,
    }


def compile_sing_box(source_json: Path, out_srs: Path) -> None:
    binary = shutil.which("sing-box")
    if not binary:
        raise RuntimeError("sing-box binary not found in PATH; cannot compile .srs")
    out_srs.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([binary, "rule-set", "compile", "--output", str(out_srs), str(source_json)], check=True)


def emit_one(bundle: Bundle, raw_rules: list[Rule], compile_srs: bool) -> None:
    base_groups = split_rules(raw_rules)

    for target in ["surge", "shadowrocket", "loon"]:
        mapped = map_rules_for_target(target, raw_rules)
        groups = split_rules(mapped)

        if base_groups.upgradable_domainset:
            write_lines_with_header(output_path(target, bundle, "domain.list"), domainset_entries_for_target(target, groups.domain))
        else:
            endpoint_rules = [*groups.domain, *groups.endpoint]
            write_lines_with_header(output_path(target, bundle, "endpoint.conf"), [rule.as_line for rule in endpoint_rules])
            write_lines_with_header(output_path(target, bundle, "ua.conf"), [rule.as_line for rule in groups.ua])

    mihomo_mapped = map_rules_for_target("mihomo", raw_rules)
    mihomo_groups = split_rules(mihomo_mapped)
    if base_groups.upgradable_domainset:
        write_lines_with_header(output_path("mihomo", bundle, "domain.list"), domainset_entries_for_target("mihomo", mihomo_groups.domain))
    else:
        endpoint_rules = [*mihomo_groups.domain, *mihomo_groups.endpoint]
        if endpoint_rules:
            out = output_path("mihomo", bundle, "endpoint.yaml")
            write_yaml_with_header(out, to_mihomo_payload(endpoint_rules), len(endpoint_rules))

    sing_mapped = map_rules_for_target("sing-box", raw_rules)
    sing_groups = split_rules(sing_mapped)
    if base_groups.upgradable_domainset:
        domain_json = output_path("sing-box", bundle, "domain.json")
        domain_json.parent.mkdir(parents=True, exist_ok=True)
        domain_json.write_text(
            json.dumps(to_sing_box_rules(sing_groups.domain), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if compile_srs:
            compile_sing_box(domain_json, output_path("sing-box", bundle, "domain.srs"))
    else:
        endpoint_rules = [*sing_groups.domain, *sing_groups.endpoint]
        if endpoint_rules:
            endpoint_json = output_path("sing-box", bundle, "endpoint.json")
            endpoint_json.parent.mkdir(parents=True, exist_ok=True)
            endpoint_json.write_text(json.dumps(to_sing_box_rules(endpoint_rules), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if compile_srs:
                compile_sing_box(endpoint_json, output_path("sing-box", bundle, "endpoint.srs"))

    output_path("mihomo", bundle, "ua.conf").unlink(missing_ok=True)
    output_path("sing-box", bundle, "ua.conf").unlink(missing_ok=True)
    output_path("sing-box", bundle, "ua.unsupported.list").unlink(missing_ok=True)
    output_path("sing-box", bundle, "domain.list").unlink(missing_ok=True)
    output_path("sing-box", bundle, "other.source.json").unlink(missing_ok=True)
    output_path("sing-box", bundle, "other.json").unlink(missing_ok=True)
    output_path("sing-box", bundle, "other.srs").unlink(missing_ok=True)
    output_path("mihomo", bundle, "other.yaml").unlink(missing_ok=True)
    output_path("surge", bundle, "other.conf").unlink(missing_ok=True)
    output_path("shadowrocket", bundle, "other.conf").unlink(missing_ok=True)
    output_path("loon", bundle, "other.conf").unlink(missing_ok=True)


def iter_sources() -> list[tuple[Bundle, list[Rule]]]:
    entries: list[tuple[Bundle, list[Rule]]] = []
    for source in sorted(SOURCE_ROOT.glob("*.conf")):
        if source.name.startswith("."):
            continue
        bundle = Bundle(name=source.stem, source=source)
        entries.append((bundle, parse_file(source)))
    return entries


def write_manifest(entries: list[tuple[Bundle, list[Rule]]]) -> None:
    manifest = {
        "single_source_of_truth": "sources/*.conf (non-hidden)",
        "ruleset_baseline": RULESET_BASELINE,
        "sources": [
            {
                "name": bundle.name,
                "source": str(bundle.source.relative_to(ROOT)),
                "rule_count": len(rules),
                "group_count": {
                    "domain": len(split_rules(rules).domain),
                    "endpoint": len(split_rules(rules).endpoint),
                    "ua": len(split_rules(rules).ua),
                    "upgradable_domainset": split_rules(rules).upgradable_domainset,
                },
            }
            for bundle, rules in entries
        ],
        "targets": TARGETS,
    }
    out = OUTPUT_ROOT / "manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate multi-client rules from sources/*.conf")
    parser.add_argument(
        "--skip-sing-box-compile",
        action="store_true",
        help="Skip sing-box .srs compilation (keeps .json only)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    entries = iter_sources()
    for bundle, rules in entries:
        emit_one(bundle, rules, compile_srs=not args.skip_sing_box_compile)
    write_manifest(entries)
    print(f"Generated {len(entries)} rule bundles.")


if __name__ == "__main__":
    main()

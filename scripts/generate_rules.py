#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = ROOT / "sources"
OUTPUT_ROOT = ROOT / "generated"
RULESET_BASELINE = "mihomo"
GITHUB_REPO = "lapofgod/ruleset"
PUBLISH_BRANCH = "generated"
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


def write_lines_with_header(file_path: Path, lines: Iterable[str], generated_at: str) -> bool:
    line_list = list(lines)
    if not line_list:
        return False

    header = [
        "# Auto-generated file. Do not edit manually.",
        f"# Rule count: {len(line_list)}",
        f"# Generated at: {generated_at}",
        "",
    ]
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("\n".join([*header, *line_list]).rstrip() + "\n", encoding="utf-8")
    return True


def write_yaml_with_header(file_path: Path, payload: dict, rule_count: int, generated_at: str) -> None:
    header = [
        "# Auto-generated file. Do not edit manually.",
        f"# Rule count: {rule_count}",
        f"# Generated at: {generated_at}",
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

    if kind == "URL-REGEX" and target == "mihomo":
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


def write_bundle_readme(target: str, bundle: Bundle, filenames: list[str]) -> None:
    if not filenames:
        return

    sorted_files = sorted(set(filenames))
    base_path = f"{target}/{bundle.name}"
    lines: list[str] = [
        f"# {target}/{bundle.name}",
        "",
        "This directory is auto-generated.",
        "",
    ]

    if target == "mihomo":
        lines.extend(["## Mihomo Usage", ""])
        for filename in sorted_files:
            rel_path = f"{base_path}/{filename}"
            raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{PUBLISH_BRANCH}/{rel_path}"

            if filename == "domain.list":
                lines.extend(
                    [
                        f"### {filename}",
                        "- Format: text",
                        "- Behavior: domain",
                        "```yaml",
                        "rule-providers:",
                        f"  {bundle.name}_domain:",
                        "    type: http",
                        "    behavior: domain",
                        "    format: text",
                        f"    url: {raw_url}",
                        f"    path: ./ruleset/{bundle.name}_domain.list",
                        "    interval: 86400",
                        "```",
                        "",
                    ]
                )
            elif filename == "endpoint.yaml":
                lines.extend(
                    [
                        f"### {filename}",
                        "- Format: yaml",
                        "- Behavior: classical",
                        "```yaml",
                        "rule-providers:",
                        f"  {bundle.name}_endpoint:",
                        "    type: http",
                        "    behavior: classical",
                        "    format: yaml",
                        f"    url: {raw_url}",
                        f"    path: ./ruleset/{bundle.name}_endpoint.yaml",
                        "    interval: 86400",
                        "```",
                        "",
                    ]
                )

    lines.extend(["## External URLs", ""])

    for filename in sorted_files:
        rel_path = f"{base_path}/{filename}"
        lines.extend(
            [
                f"### {filename}",
                "",
                f"- raw.githubusercontent.com: https://raw.githubusercontent.com/{GITHUB_REPO}/{PUBLISH_BRANCH}/{rel_path}",
                f"- cdn.jsdelivr.net: https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@{PUBLISH_BRANCH}/{rel_path}",
                f"- fastly.jsdelivr.net: https://fastly.jsdelivr.net/gh/{GITHUB_REPO}@{PUBLISH_BRANCH}/{rel_path}",
                f"- testingcf.jsdelivr.net: https://testingcf.jsdelivr.net/gh/{GITHUB_REPO}@{PUBLISH_BRANCH}/{rel_path}",
                f"- gh-proxy: https://gh-proxy.org/https://github.com/{GITHUB_REPO}/blob/{PUBLISH_BRANCH}/{rel_path}",
                "",
            ]
        )

    readme_path = output_path(target, bundle, "README.MD")
    readme_path.parent.mkdir(parents=True, exist_ok=True)
    readme_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


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
    mapped: list[dict] = []

    def append_rule(key: str, value: str) -> None:
        if mapped and key in mapped[-1]:
            mapped[-1][key].append(value)
        else:
            mapped.append({key: [value]})

    for rule in rules:
        if rule.kind == "DOMAIN":
            append_rule("domain", rule.value)
        elif rule.kind == "DOMAIN-SUFFIX":
            append_rule("domain_suffix", rule.value)
        elif rule.kind == "DOMAIN-KEYWORD":
            append_rule("domain_keyword", rule.value)
        elif rule.kind in {"IP-CIDR", "IP-CIDR6"}:
            append_rule("ip_cidr", rule.value)
        elif rule.kind == "URL-REGEX":
            append_rule("domain_regex", rule.value)

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


def emit_one(bundle: Bundle, raw_rules: list[Rule], compile_srs: bool, generated_at: str) -> None:
    generated_files: dict[str, list[str]] = {target: [] for target in TARGETS}

    for target in ["surge", "shadowrocket", "loon"]:
        mapped = map_rules_for_target(target, raw_rules)
        groups = split_rules(mapped)

        if write_lines_with_header(
            output_path(target, bundle, "domain.list"),
            domainset_entries_for_target(target, groups.domain),
            generated_at,
        ):
            generated_files[target].append("domain.list")
        if write_lines_with_header(
            output_path(target, bundle, "endpoint.conf"),
            [rule.as_line for rule in groups.endpoint],
            generated_at,
        ):
            generated_files[target].append("endpoint.conf")
        if write_lines_with_header(
            output_path(target, bundle, "ua.conf"),
            [rule.as_line for rule in groups.ua],
            generated_at,
        ):
            generated_files[target].append("ua.conf")

    mihomo_mapped = map_rules_for_target("mihomo", raw_rules)
    mihomo_groups = split_rules(mihomo_mapped)
    if write_lines_with_header(
        output_path("mihomo", bundle, "domain.list"),
        domainset_entries_for_target("mihomo", mihomo_groups.domain),
        generated_at,
    ):
        generated_files["mihomo"].append("domain.list")
    if mihomo_groups.endpoint:
        out = output_path("mihomo", bundle, "endpoint.yaml")
        write_yaml_with_header(out, to_mihomo_payload(mihomo_groups.endpoint), len(mihomo_groups.endpoint), generated_at)
        generated_files["mihomo"].append("endpoint.yaml")

    sing_mapped = map_rules_for_target("sing-box", raw_rules)
    sing_groups = split_rules(sing_mapped)
    sing_rules = [*sing_groups.domain, *sing_groups.endpoint]
    if sing_rules:
        rules_json = output_path("sing-box", bundle, "rules.json")
        rules_json.parent.mkdir(parents=True, exist_ok=True)
        rules_json.write_text(
            json.dumps(to_sing_box_rules(sing_rules), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        generated_files["sing-box"].append("rules.json")
        if compile_srs:
            compile_sing_box(rules_json, output_path("sing-box", bundle, "rules.srs"))
            generated_files["sing-box"].append("rules.srs")

    output_path("mihomo", bundle, "ua.conf").unlink(missing_ok=True)
    output_path("sing-box", bundle, "ua.conf").unlink(missing_ok=True)
    output_path("sing-box", bundle, "ua.unsupported.list").unlink(missing_ok=True)
    output_path("sing-box", bundle, "domain.list").unlink(missing_ok=True)
    output_path("sing-box", bundle, "domain.json").unlink(missing_ok=True)
    output_path("sing-box", bundle, "domain.srs").unlink(missing_ok=True)
    output_path("sing-box", bundle, "endpoint.json").unlink(missing_ok=True)
    output_path("sing-box", bundle, "endpoint.srs").unlink(missing_ok=True)
    output_path("sing-box", bundle, "other.source.json").unlink(missing_ok=True)
    output_path("sing-box", bundle, "other.json").unlink(missing_ok=True)
    output_path("sing-box", bundle, "other.srs").unlink(missing_ok=True)
    output_path("mihomo", bundle, "other.yaml").unlink(missing_ok=True)
    output_path("surge", bundle, "other.conf").unlink(missing_ok=True)
    output_path("shadowrocket", bundle, "other.conf").unlink(missing_ok=True)
    output_path("loon", bundle, "other.conf").unlink(missing_ok=True)

    for target in TARGETS:
        write_bundle_readme(target, bundle, generated_files[target])


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
    generated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    entries = iter_sources()
    for bundle, rules in entries:
        emit_one(bundle, rules, compile_srs=not args.skip_sing_box_compile, generated_at=generated_at)
    write_manifest(entries)
    print(f"Generated {len(entries)} rule bundles.")


if __name__ == "__main__":
    main()

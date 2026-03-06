#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = ROOT / "src"
OUTPUT_ROOT = ROOT / "generated"
RULESET_BASELINE = "mihomo"
GITHUB_REPO = "lapofgod/rulesets"
PUBLISH_BRANCH = "generated"
TARGETS = ["surge", "mihomo", "shadowrocket", "loon", "sing-box"]
GFWLIST_NAME = "gfwlist"
GFWLIST_URL = "https://raw.githubusercontent.com/gfwlist/gfwlist/master/gfwlist.txt"

DOMAINSET_KINDS = {"DOMAIN", "DOMAIN-SUFFIX"}
ORIGIN_KINDS = {"USER-AGENT", "SRC-PORT"}


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
class GenerationFailure:
    name: str
    reason: str


@dataclass(frozen=True)
class RuleGroups:
    domain: list[Rule]
    endpoint: list[Rule]
    origins: list[Rule]


def normalize_kind(kind: str) -> str:
    normalized = kind.strip().upper().replace("_", "-")
    if normalized == "DEST-PORT":
        return "DST-PORT"
    return normalized


def parse_conf_line(raw: str) -> Rule | None:
    line = raw.strip()
    # Support inline comments in .conf, e.g. `RULE,... # note`
    line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
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


def fetch_gfwlist_raw() -> str:
    req = urllib.request.Request(
        GFWLIST_URL,
        headers={"User-Agent": "rulesets-generator/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()

    text = data.decode("utf-8", errors="ignore").strip()
    try:
        decoded = base64.b64decode(text, validate=False).decode("utf-8", errors="ignore")
        if "[AutoProxy" in decoded or "||" in decoded:
            return decoded
    except Exception:
        pass

    return text


def normalize_domain_from_host(host: str) -> str | None:
    host = host.strip().lower().strip(".")
    if not host:
        return None
    if host.startswith("*"):
        host = host.lstrip("*").lstrip(".")
    if host.startswith("[") and host.endswith("]"):
        return None
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", host):
        return None
    if "." not in host:
        return None
    if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for ch in host):
        return None
    return host


def parse_gfwlist_line(line: str) -> Rule | None:
    line = line.strip()
    if not line:
        return None
    if line.startswith("!") or line.startswith("["):
        return None
    if line.startswith("@@"):
        return None

    # Strip adblock options.
    if "$" in line:
        line = line.split("$", 1)[0]

    if line.startswith("||"):
        dom = normalize_domain_from_host(line[2:])
        return Rule("DOMAIN-SUFFIX", dom) if dom else None

    if line.startswith("|"):
        line = line[1:]

    if line.startswith("http://") or line.startswith("https://"):
        try:
            host = urllib.parse.urlparse(line).hostname
            dom = normalize_domain_from_host(host or "")
            return Rule("DOMAIN-SUFFIX", dom) if dom else None
        except Exception:
            return None

    if line.startswith("."):
        dom = normalize_domain_from_host(line[1:])
        return Rule("DOMAIN-SUFFIX", dom) if dom else None

    if line.startswith("*."):
        dom = normalize_domain_from_host(line[2:])
        return Rule("DOMAIN-SUFFIX", dom) if dom else None

    if any(token in line for token in ["*", "^", "/", "?"]):
        return None

    dom = normalize_domain_from_host(line)
    return Rule("DOMAIN-SUFFIX", dom) if dom else None


def fetch_gfwlist_rules() -> list[Rule]:
    raw = fetch_gfwlist_raw()
    rules: list[Rule] = []
    for line in raw.splitlines():
        rule = parse_gfwlist_line(line)
        if rule:
            rules.append(rule)
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
            return Rule("DOMAIN-WILDCARD", value, extras)

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
    origins: list[Rule] = []

    for rule in rules:
        if rule.kind in DOMAINSET_KINDS:
            domain.append(rule)
        elif rule.kind in ORIGIN_KINDS:
            origins.append(rule)
        else:
            endpoint.append(rule)

    return RuleGroups(domain=domain, endpoint=endpoint, origins=origins)


def output_path(target: str, rule_type: str, filename: str) -> Path:
    return OUTPUT_ROOT / target / rule_type / filename


def write_type_readme(target: str, rule_type: str, filenames: list[str]) -> None:
    if not filenames:
        return

    sorted_files = sorted(set(filenames))
    base_path = f"{target}/{rule_type}"
    lines: list[str] = [
        f"# {target}/{rule_type}",
        "",
        "This directory is auto-generated.",
        "",
    ]

    if target == "mihomo":
        lines.extend(["## Mihomo Usage", ""])
        lines.extend(
            [
                "Use `domains` + `endpoints` + `origins` in parallel when available.",
                "",
            ]
        )
        for filename in sorted_files:
            rel_path = f"{base_path}/{filename}"
            raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{PUBLISH_BRANCH}/{rel_path}"
            provider_name = Path(filename).stem

            if rule_type == "domains" and filename.endswith(".list"):
                lines.extend(
                    [
                        f"### {filename}",
                        "- Format: text",
                        "- Behavior: domain",
                        "```yaml",
                        "rule-providers:",
                        f"  {provider_name}_domains:",
                        "    type: http",
                        "    behavior: domain",
                        "    format: text",
                        f"    url: {raw_url}",
                        f"    path: ./ruleset/{provider_name}.list",
                        "    interval: 86400",
                        "```",
                        "",
                    ]
                )
            elif rule_type == "endpoints" and filename.endswith(".yaml"):
                lines.extend(
                    [
                        f"### {filename}",
                        "- Format: yaml",
                        "- Behavior: classical",
                        "```yaml",
                        "rule-providers:",
                        f"  {provider_name}_endpoints:",
                        "    type: http",
                        "    behavior: classical",
                        "    format: yaml",
                        f"    url: {raw_url}",
                        f"    path: ./ruleset/{provider_name}.yaml",
                        "    interval: 86400",
                        "```",
                        "",
                    ]
                )
            elif rule_type == "origins" and filename.endswith(".yaml"):
                lines.extend(
                    [
                        f"### {filename}",
                        "- Format: yaml",
                        "- Behavior: classical",
                        "```yaml",
                        "rule-providers:",
                        f"  {provider_name}_origins:",
                        "    type: http",
                        "    behavior: classical",
                        "    format: yaml",
                        f"    url: {raw_url}",
                        f"    path: ./ruleset/{provider_name}.yaml",
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

    readme_path = output_path(target, rule_type, "README.MD")
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
    return {"payload": [rule.as_line for rule in rules]}


def to_sing_box_rules(rules: list[Rule]) -> dict:
    mapped: list[dict] = []

    def wildcard_to_regex(pattern: str) -> str:
        escaped = re.escape(pattern)
        return "^" + escaped.replace(r"\*", ".*") + "$"

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
        elif rule.kind == "DOMAIN-REGEX":
            append_rule("domain_regex", rule.value)
        elif rule.kind == "DOMAIN-WILDCARD":
            append_rule("domain_regex", wildcard_to_regex(rule.value))
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


def emit_one(bundle: Bundle, raw_rules: list[Rule], compile_srs: bool, generated_at: str) -> dict[str, dict[str, list[str]]]:
    generated_files: dict[str, dict[str, list[str]]] = {target: {} for target in TARGETS}

    def remember(target: str, rule_type: str, filename: str) -> None:
        if rule_type not in generated_files[target]:
            generated_files[target][rule_type] = []
        generated_files[target][rule_type].append(filename)

    for target in ["surge", "shadowrocket", "loon"]:
        mapped = map_rules_for_target(target, raw_rules)
        groups = split_rules(mapped)

        if write_lines_with_header(
            output_path(target, "domains", f"{bundle.name}.list"),
            domainset_entries_for_target(target, groups.domain),
            generated_at,
        ):
            remember(target, "domains", f"{bundle.name}.list")
        if write_lines_with_header(
            output_path(target, "endpoints", f"{bundle.name}.conf"),
            [rule.as_line for rule in groups.endpoint],
            generated_at,
        ):
            remember(target, "endpoints", f"{bundle.name}.conf")
        if write_lines_with_header(
            output_path(target, "origins", f"{bundle.name}.conf"),
            [rule.as_line for rule in groups.origins],
            generated_at,
        ):
            remember(target, "origins", f"{bundle.name}.conf")

    mihomo_mapped = map_rules_for_target("mihomo", raw_rules)
    mihomo_groups = split_rules(mihomo_mapped)
    if write_lines_with_header(
        output_path("mihomo", "domains", f"{bundle.name}.list"),
        domainset_entries_for_target("mihomo", mihomo_groups.domain),
        generated_at,
    ):
        remember("mihomo", "domains", f"{bundle.name}.list")
    if mihomo_groups.endpoint:
        out = output_path("mihomo", "endpoints", f"{bundle.name}.yaml")
        write_yaml_with_header(out, to_mihomo_payload(mihomo_groups.endpoint), len(mihomo_groups.endpoint), generated_at)
        remember("mihomo", "endpoints", f"{bundle.name}.yaml")
    if mihomo_groups.origins:
        out = output_path("mihomo", "origins", f"{bundle.name}.yaml")
        write_yaml_with_header(out, to_mihomo_payload(mihomo_groups.origins), len(mihomo_groups.origins), generated_at)
        remember("mihomo", "origins", f"{bundle.name}.yaml")

    sing_mapped = map_rules_for_target("sing-box", raw_rules)
    sing_groups = split_rules(sing_mapped)
    sing_rules = [*sing_groups.domain, *sing_groups.endpoint, *sing_groups.origins]
    if sing_rules:
        rules_json = output_path("sing-box", "json", f"{bundle.name}.json")
        rules_json.parent.mkdir(parents=True, exist_ok=True)
        rules_json.write_text(
            json.dumps(to_sing_box_rules(sing_rules), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        remember("sing-box", "json", f"{bundle.name}.json")
        if compile_srs:
            compile_sing_box(rules_json, output_path("sing-box", "srs", f"{bundle.name}.srs"))
            remember("sing-box", "srs", f"{bundle.name}.srs")

    return generated_files


def iter_sources() -> list[Bundle]:
    entries: list[Bundle] = []
    for source in sorted(SOURCE_ROOT.glob("*.conf")):
        if source.name.startswith("."):
            continue
        bundle = Bundle(name=source.stem, source=source)
        entries.append(bundle)

    gfw_bundle = Bundle(name=GFWLIST_NAME, source=Path(f"upstream:{GFWLIST_URL}"))
    entries.append(gfw_bundle)
    return entries


def load_rules(bundle: Bundle) -> list[Rule]:
    source_str = str(bundle.source)
    if source_str.startswith("upstream:"):
        return fetch_gfwlist_rules()
    return parse_file(bundle.source)


def write_manifest(entries: list[tuple[Bundle, list[Rule]]], failures: list[GenerationFailure]) -> None:
    def source_ref(source: Path) -> str:
        try:
            return str(source.relative_to(ROOT))
        except ValueError:
            raw = str(source)
            return raw.replace("https:/", "https://", 1).replace("http:/", "http://", 1)

    manifest = {
        "single_source_of_truth": "src/*.conf (non-hidden)",
        "ruleset_baseline": RULESET_BASELINE,
        "sources": [
            {
                "name": bundle.name,
                "source": source_ref(bundle.source),
                "rule_count": len(rules),
                "group_count": {
                    "domain": len(split_rules(rules).domain),
                    "endpoint": len(split_rules(rules).endpoint),
                    "origins": len(split_rules(rules).origins),
                },
            }
            for bundle, rules in entries
        ],
        "targets": TARGETS,
        "failures": [{"name": item.name, "reason": item.reason} for item in failures],
    }
    out = OUTPUT_ROOT / "manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate multi-client rules from src/*.conf")
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
    bundles = iter_sources()
    entries: list[tuple[Bundle, list[Rule]]] = []
    failures: list[GenerationFailure] = []
    readme_index: dict[str, dict[str, list[str]]] = {target: {} for target in TARGETS}
    for bundle in bundles:
        try:
            rules = load_rules(bundle)
            file_map = emit_one(bundle, rules, compile_srs=not args.skip_sing_box_compile, generated_at=generated_at)
            entries.append((bundle, rules))
            for target, types in file_map.items():
                for rule_type, filenames in types.items():
                    if rule_type not in readme_index[target]:
                        readme_index[target][rule_type] = []
                    readme_index[target][rule_type].extend(filenames)
        except Exception as exc:
            failures.append(GenerationFailure(name=bundle.name, reason=str(exc)))
            print(f"[WARN] Failed to generate '{bundle.name}': {exc}. Keep previous published version.")

    for target, types in readme_index.items():
        for rule_type, filenames in types.items():
            write_type_readme(target, rule_type, filenames)

    write_manifest(entries, failures)
    print(f"Generated {len(entries)} rule bundles.")


if __name__ == "__main__":
    main()

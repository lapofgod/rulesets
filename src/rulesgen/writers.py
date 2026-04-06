from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

import yaml

from .models import DOMAINSET_KINDS, Bundle, GenerationFailure, ORIGIN_KINDS, ROOT, Rule


def output_path(output_root: Path, target: str, rule_type: str, filename: str) -> Path:
    return output_root / target / rule_type / filename


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


def write_type_readme(
    output_root: Path,
    target: str,
    rule_type: str,
    filenames: list[str],
    github_repo: str,
    publish_branch: str,
) -> None:
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
            raw_url = f"https://raw.githubusercontent.com/{github_repo}/{publish_branch}/{rel_path}"
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
                f"- raw.githubusercontent.com: https://raw.githubusercontent.com/{github_repo}/{publish_branch}/{rel_path}",
                f"- cdn.jsdelivr.net: https://cdn.jsdelivr.net/gh/{github_repo}@{publish_branch}/{rel_path}",
                f"- fastly.jsdelivr.net: https://fastly.jsdelivr.net/gh/{github_repo}@{publish_branch}/{rel_path}",
                f"- testingcf.jsdelivr.net: https://testingcf.jsdelivr.net/gh/{github_repo}@{publish_branch}/{rel_path}",
                f"- gh-proxy: https://gh-proxy.org/https://github.com/{github_repo}/blob/{publish_branch}/{rel_path}",
                "",
            ]
        )

    readme_path = output_path(output_root, target, rule_type, "README.MD")
    readme_path.parent.mkdir(parents=True, exist_ok=True)
    readme_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_manifest(
    source_root: Path,
    output_root: Path,
    ruleset_baseline: str,
    targets: Sequence[str],
    entries: list[tuple[Bundle, list[Rule]]],
    failures: list[GenerationFailure],
) -> None:
    def group_count(rules: list[Rule]) -> dict[str, int]:
        domain = 0
        origins = 0
        endpoint = 0
        for rule in rules:
            if rule.kind in DOMAINSET_KINDS:
                domain += 1
            elif rule.kind in ORIGIN_KINDS:
                origins += 1
            else:
                endpoint += 1
        return {
            "domain": domain,
            "endpoint": endpoint,
            "origins": origins,
        }

    def source_ref(source: Path) -> str:
        try:
            return str(source.relative_to(ROOT))
        except ValueError:
            raw = str(source)
            return raw.replace("https:/", "https://", 1).replace("http:/", "http://", 1)

    source_glob_root = source_ref(source_root)
    manifest = {
        "single_source_of_truth": f"{source_glob_root}/*.conf + {source_glob_root}/*.py (non-hidden)",
        "ruleset_baseline": ruleset_baseline,
        "sources": [
            {
                "name": bundle.name,
                "source": source_ref(bundle.source),
                "rule_count": len(rules),
                "group_count": group_count(rules),
            }
            for bundle, rules in entries
        ],
        "targets": list(targets),
        "failures": [{"name": item.name, "reason": item.reason} for item in failures],
    }
    out = output_root / "manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

from __future__ import annotations

import json
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, Sequence

from .models import DOMAINSET_KINDS, ORIGIN_KINDS, EmitContext, GenericRuleSet, Rule, RuleGroups
from .writers import output_path, write_lines_with_header, write_yaml_with_header


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


class TargetEmitter(ABC):
    target: str

    @abstractmethod
    def emit_bundle(self, ruleset: GenericRuleSet, context: EmitContext) -> dict[str, list[str]]:
        raise NotImplementedError


class ClassicalTargetEmitter(TargetEmitter):
    def __init__(self, target: str) -> None:
        self.target = target

    def emit_bundle(self, ruleset: GenericRuleSet, context: EmitContext) -> dict[str, list[str]]:
        emitted: dict[str, list[str]] = {}

        mapped = map_rules_for_target(self.target, ruleset.rules)
        groups = split_rules(mapped)

        if write_lines_with_header(
            output_path(context.output_root, self.target, "domains", f"{ruleset.bundle.name}.list"),
            domainset_entries_for_target(self.target, groups.domain),
            context.generated_at,
        ):
            emitted.setdefault("domains", []).append(f"{ruleset.bundle.name}.list")
        if write_lines_with_header(
            output_path(context.output_root, self.target, "endpoints", f"{ruleset.bundle.name}.conf"),
            [rule.as_line for rule in groups.endpoint],
            context.generated_at,
        ):
            emitted.setdefault("endpoints", []).append(f"{ruleset.bundle.name}.conf")
        if write_lines_with_header(
            output_path(context.output_root, self.target, "origins", f"{ruleset.bundle.name}.conf"),
            [rule.as_line for rule in groups.origins],
            context.generated_at,
        ):
            emitted.setdefault("origins", []).append(f"{ruleset.bundle.name}.conf")

        return emitted


class MihomoTargetEmitter(TargetEmitter):
    target = "mihomo"

    def emit_bundle(self, ruleset: GenericRuleSet, context: EmitContext) -> dict[str, list[str]]:
        emitted: dict[str, list[str]] = {}

        mapped = map_rules_for_target(self.target, ruleset.rules)
        groups = split_rules(mapped)

        if write_lines_with_header(
            output_path(context.output_root, self.target, "domains", f"{ruleset.bundle.name}.list"),
            domainset_entries_for_target(self.target, groups.domain),
            context.generated_at,
        ):
            emitted.setdefault("domains", []).append(f"{ruleset.bundle.name}.list")

        if groups.endpoint:
            out = output_path(context.output_root, self.target, "endpoints", f"{ruleset.bundle.name}.yaml")
            write_yaml_with_header(
                out,
                to_mihomo_payload(groups.endpoint),
                len(groups.endpoint),
                context.generated_at,
            )
            emitted.setdefault("endpoints", []).append(f"{ruleset.bundle.name}.yaml")

        if groups.origins:
            out = output_path(context.output_root, self.target, "origins", f"{ruleset.bundle.name}.yaml")
            write_yaml_with_header(
                out,
                to_mihomo_payload(groups.origins),
                len(groups.origins),
                context.generated_at,
            )
            emitted.setdefault("origins", []).append(f"{ruleset.bundle.name}.yaml")

        return emitted


class SingBoxTargetEmitter(TargetEmitter):
    target = "sing-box"

    def emit_bundle(self, ruleset: GenericRuleSet, context: EmitContext) -> dict[str, list[str]]:
        emitted: dict[str, list[str]] = {}

        mapped = map_rules_for_target(self.target, ruleset.rules)
        groups = split_rules(mapped)
        rules = [*groups.domain, *groups.endpoint, *groups.origins]

        if not rules:
            return emitted

        rules_json = output_path(context.output_root, self.target, "json", f"{ruleset.bundle.name}.json")
        rules_json.parent.mkdir(parents=True, exist_ok=True)
        rules_json.write_text(
            json.dumps(to_sing_box_rules(rules), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        emitted.setdefault("json", []).append(f"{ruleset.bundle.name}.json")

        if context.compile_srs:
            compile_sing_box(
                rules_json,
                output_path(context.output_root, self.target, "srs", f"{ruleset.bundle.name}.srs"),
            )
            emitted.setdefault("srs", []).append(f"{ruleset.bundle.name}.srs")

        return emitted


def build_target_emitters(targets: Sequence[str]) -> list[TargetEmitter]:
    emitter_factories = {
        "surge": lambda: ClassicalTargetEmitter("surge"),
        "mihomo": MihomoTargetEmitter,
        "shadowrocket": lambda: ClassicalTargetEmitter("shadowrocket"),
        "loon": lambda: ClassicalTargetEmitter("loon"),
        "sing-box": SingBoxTargetEmitter,
    }
    emitters: list[TargetEmitter] = []
    for target in targets:
        factory = emitter_factories.get(target)
        if not factory:
            supported = ", ".join(sorted(emitter_factories))
            raise RuntimeError(f"Unsupported target '{target}'. Supported targets: {supported}")
        emitters.append(factory())
    return emitters


class GenericToTargetTransformer:
    def __init__(self, targets: Sequence[str]) -> None:
        self.emitters = build_target_emitters(targets)
        self.targets = tuple(targets)

    def emit(self, ruleset: GenericRuleSet, context: EmitContext) -> dict[str, dict[str, list[str]]]:
        generated_files: dict[str, dict[str, list[str]]] = {target: {} for target in self.targets}

        for emitter in self.emitters:
            emitted = emitter.emit_bundle(ruleset, context)
            if emitted:
                generated_files[emitter.target] = emitted

        return generated_files

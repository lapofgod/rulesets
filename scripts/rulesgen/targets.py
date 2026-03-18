from __future__ import annotations

import json
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, Sequence

from .models import DOMAINSET_KINDS, LOGICAL_KINDS, ORIGIN_KINDS, EmitContext, GenericRuleSet, Rule, RuleGroups
from .writers import output_path, write_lines_with_header, write_yaml_with_header


def dedupe_sort_strings(items: Iterable[str]) -> list[str]:
    return sorted(set(items))


def split_rules_default(rules: list[Rule]) -> RuleGroups:
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


def to_domainset_entry_non_mihomo(rule: Rule) -> str | None:
    if rule.kind == "DOMAIN":
        return rule.value

    if rule.kind == "DOMAIN-SUFFIX":
        return f".{rule.value}"

    if rule.kind == "DOMAIN-WILDCARD":
        if rule.value.startswith("*."):
            suffix = rule.value[2:]
            return f".{suffix}"
        return None

    return None


def domainset_entries_non_mihomo(rules: list[Rule]) -> list[str]:
    entries: list[str] = []
    for rule in rules:
        entry = to_domainset_entry_non_mihomo(rule)
        if entry:
            entries.append(entry)
    return dedupe_sort_strings(entries)


def to_domainset_entry_mihomo(rule: Rule) -> str | None:
    if rule.kind == "DOMAIN":
        return rule.value

    if rule.kind == "DOMAIN-SUFFIX":
        return f"+.{rule.value}"

    if rule.kind == "DOMAIN-WILDCARD":
        if rule.value.startswith("*."):
            return f"+.{rule.value[2:]}"
        return None

    return None


def domainset_entries_mihomo(rules: list[Rule]) -> list[str]:
    entries: list[str] = []
    for rule in rules:
        entry = to_domainset_entry_mihomo(rule)
        if entry:
            entries.append(entry)
    return dedupe_sort_strings(entries)


def to_mihomo_payload(rules: list[Rule]) -> dict:
    return {"payload": [rule.as_line for rule in rules]}


def to_sing_box_rule(rule: Rule) -> tuple[dict | None, str | None]:
    def wildcard_to_regex(pattern: str) -> str:
        escaped = re.escape(pattern)
        return "^" + escaped.replace(r"\*", ".*").replace(r"\?", ".") + "$"

    def parse_port_value(raw: str, *, source: bool) -> tuple[dict | None, str | None]:
        value = raw.strip()
        if re.fullmatch(r"\d+", value):
            key = "source_port" if source else "port"
            return {key: [int(value)]}, None

        normalized = value.replace("-", ":")
        if re.fullmatch(r"\d+:\d+|:\d+|\d+:", normalized):
            key = "source_port_range" if source else "port_range"
            return {key: [normalized]}, None

        return None, f"Unsupported port expression for sing-box: '{raw}'"

    if rule.kind == "AND":
        if not rule.logical_children:
            return None, "Invalid AND rule for sing-box: missing parsed children"
        children: list[dict] = []
        for child in rule.logical_children:
            converted, warning = to_sing_box_rule(child)
            if warning:
                return None, warning
            if converted is None:
                return None, "Invalid AND rule for sing-box: empty child"
            children.append(converted)
        return {"type": "logical", "mode": "and", "rules": children}, None

    if rule.kind == "OR":
        if not rule.logical_children:
            return None, "Invalid OR rule for sing-box: missing parsed children"
        children: list[dict] = []
        for child in rule.logical_children:
            converted, warning = to_sing_box_rule(child)
            if warning:
                return None, warning
            if converted is None:
                return None, "Invalid OR rule for sing-box: empty child"
            children.append(converted)
        return {"type": "logical", "mode": "or", "rules": children}, None

    if rule.kind == "NOT":
        if len(rule.logical_children) != 1:
            return None, "Invalid NOT rule for sing-box: exactly one child is required"

        converted, warning = to_sing_box_rule(rule.logical_children[0])
        if warning:
            return None, warning
        if converted is None:
            return None, "Invalid NOT rule for sing-box: empty child"

        toggled = dict(converted)
        toggled["invert"] = not bool(toggled.get("invert", False))
        return toggled, None

    if rule.kind == "DOMAIN":
        return {"domain": [rule.value]}, None
    if rule.kind == "DOMAIN-SUFFIX":
        return {"domain_suffix": [rule.value]}, None
    if rule.kind == "DOMAIN-KEYWORD":
        return {"domain_keyword": [rule.value]}, None
    if rule.kind == "DOMAIN-REGEX":
        return {"domain_regex": [rule.value]}, None
    if rule.kind == "DOMAIN-WILDCARD":
        return {"domain_regex": [wildcard_to_regex(rule.value)]}, None
    if rule.kind in {"IP-CIDR", "IP-CIDR6"}:
        return {"ip_cidr": [rule.value]}, None
    if rule.kind == "GEOIP":
        return {"geoip": [rule.value.lower()]}, None
    if rule.kind == "DST-PORT":
        return parse_port_value(rule.value, source=False)
    if rule.kind == "SRC-PORT":
        return parse_port_value(rule.value, source=True)

    if rule.kind in {"URL-REGEX", "USER-AGENT"}:
        return None, f"Rule kind '{rule.kind}' is not supported by sing-box rule-set source format"

    if rule.kind == "IP-ASN":
        return None, "Rule kind 'IP-ASN' is not supported by sing-box rule-set source format"

    return None, f"Rule kind '{rule.kind}' is not supported by sing-box conversion"


def merge_adjacent_sing_box_rules(rules: list[dict]) -> list[dict]:
    merged: list[dict] = []

    for current in rules:
        if not merged:
            merged.append(current)
            continue

        previous = merged[-1]

        # Keep logical rules independent to preserve exact tree semantics.
        if previous.get("type") == "logical" or current.get("type") == "logical":
            merged.append(current)
            continue

        previous_list_keys = [key for key, value in previous.items() if isinstance(value, list)]
        current_list_keys = [key for key, value in current.items() if isinstance(value, list)]

        if len(previous_list_keys) != 1 or len(current_list_keys) != 1:
            merged.append(current)
            continue

        previous_list_key = previous_list_keys[0]
        current_list_key = current_list_keys[0]
        if previous_list_key != current_list_key:
            merged.append(current)
            continue

        previous_scalars = {
            key: value for key, value in previous.items() if key != previous_list_key and not isinstance(value, list)
        }
        current_scalars = {
            key: value for key, value in current.items() if key != current_list_key and not isinstance(value, list)
        }
        if previous_scalars != current_scalars:
            merged.append(current)
            continue

        previous[previous_list_key].extend(current[current_list_key])

    return merged


def to_sing_box_rules(rules: list[Rule]) -> tuple[dict, list[str]]:
    mapped: list[dict] = []
    warnings: list[str] = []

    for rule in rules:
        converted, warning = to_sing_box_rule(rule)
        if warning:
            warnings.append(warning)
        if converted is not None:
            mapped.append(converted)

    return {"version": 1, "rules": merge_adjacent_sing_box_rules(mapped)}, warnings


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
    target: str

    def map_rule_leaf(self, rule: Rule) -> Rule | None:
        return rule

    def map_rule(self, rule: Rule) -> Rule | None:
        if rule.kind in LOGICAL_KINDS:
            mapped_children: list[Rule] = []
            for child in rule.logical_children:
                mapped_child = self.map_rule(child)
                if mapped_child is None:
                    return None
                mapped_children.append(mapped_child)
            return Rule(
                kind=rule.kind,
                value=rule.value,
                extras=rule.extras,
                logical_children=tuple(mapped_children),
            )
        return self.map_rule_leaf(rule)

    def split_rules(self, rules: list[Rule]) -> RuleGroups:
        return split_rules_default(rules)

    def domain_entries(self, rules: list[Rule]) -> list[str]:
        return domainset_entries_non_mihomo(rules)

    def emit_bundle(self, ruleset: GenericRuleSet, context: EmitContext) -> dict[str, list[str]]:
        emitted: dict[str, list[str]] = {}

        mapped: list[Rule] = []
        for rule in ruleset.rules:
            converted = self.map_rule(rule)
            if converted is not None:
                mapped.append(converted)
        groups = self.split_rules(mapped)

        if write_lines_with_header(
            output_path(context.output_root, self.target, "domains", f"{ruleset.bundle.name}.list"),
            self.domain_entries(groups.domain),
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


class SurgeTargetEmitter(ClassicalTargetEmitter):
    target = "surge"

    def map_rule_leaf(self, rule: Rule) -> Rule | None:
        if rule.kind == "DST-PORT":
            return Rule("DEST-PORT", rule.value, rule.extras)
        return rule


class ShadowrocketTargetEmitter(ClassicalTargetEmitter):
    target = "shadowrocket"


class LoonTargetEmitter(ClassicalTargetEmitter):
    target = "loon"

    def map_rule_leaf(self, rule: Rule) -> Rule | None:
        if rule.kind == "DST-PORT":
            return Rule("DEST-PORT", rule.value, rule.extras)
        if rule.kind != "DOMAIN-WILDCARD":
            return rule
        if rule.value.startswith("*."):
            return Rule("DOMAIN-SUFFIX", rule.value[2:], rule.extras)
        return None


class MihomoTargetEmitter(TargetEmitter):
    target = "mihomo"

    def map_rule_leaf(self, rule: Rule) -> Rule | None:
        if rule.kind in {"USER-AGENT", "URL-REGEX"}:
            return None
        return rule

    def map_rule(self, rule: Rule) -> Rule | None:
        if rule.kind in LOGICAL_KINDS:
            mapped_children: list[Rule] = []
            for child in rule.logical_children:
                mapped_child = self.map_rule(child)
                if mapped_child is None:
                    return None
                mapped_children.append(mapped_child)
            return Rule(
                kind=rule.kind,
                value=rule.value,
                extras=rule.extras,
                logical_children=tuple(mapped_children),
            )
        return self.map_rule_leaf(rule)

    def split_rules(self, rules: list[Rule]) -> RuleGroups:
        return split_rules_default(rules)

    def emit_bundle(self, ruleset: GenericRuleSet, context: EmitContext) -> dict[str, list[str]]:
        emitted: dict[str, list[str]] = {}

        mapped: list[Rule] = []
        for rule in ruleset.rules:
            converted = self.map_rule(rule)
            if converted is not None:
                mapped.append(converted)
        groups = self.split_rules(mapped)

        if write_lines_with_header(
            output_path(context.output_root, self.target, "domains", f"{ruleset.bundle.name}.list"),
            domainset_entries_mihomo(groups.domain),
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

    def map_rule(self, rule: Rule) -> Rule | None:
        return rule

    def emit_bundle(self, ruleset: GenericRuleSet, context: EmitContext) -> dict[str, list[str]]:
        emitted: dict[str, list[str]] = {}

        mapped: list[Rule] = []
        for rule in ruleset.rules:
            converted = self.map_rule(rule)
            if converted is not None:
                mapped.append(converted)

        if not mapped:
            return emitted

        payload, warnings = to_sing_box_rules(mapped)
        for warning in warnings:
            print(f"[WARN] {ruleset.bundle.source.name}: {warning}")

        if not payload.get("rules"):
            return emitted

        rules_json = output_path(context.output_root, self.target, "json", f"{ruleset.bundle.name}.json")
        rules_json.parent.mkdir(parents=True, exist_ok=True)
        rules_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
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
        "surge": SurgeTargetEmitter,
        "mihomo": MihomoTargetEmitter,
        "shadowrocket": ShadowrocketTargetEmitter,
        "loon": LoonTargetEmitter,
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

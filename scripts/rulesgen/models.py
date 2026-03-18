from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOMAINSET_KINDS = {"DOMAIN", "DOMAIN-SUFFIX"}
ORIGIN_KINDS = {"USER-AGENT", "SRC-PORT"}
LOGICAL_KINDS = {"AND", "OR", "NOT"}


@dataclass(frozen=True)
class Rule:
    kind: str
    value: str
    extras: tuple[str, ...] = ()
    logical_children: tuple["Rule", ...] = ()

    @property
    def as_line(self) -> str:
        if self.kind in LOGICAL_KINDS and self.logical_children:
            expression = "(" + ",".join(f"({child.as_line})" for child in self.logical_children) + ")"
            return ",".join([self.kind, expression, *self.extras])
        return ",".join([self.kind, self.value, *self.extras])


@dataclass(frozen=True)
class Bundle:
    name: str
    source: Path
    source_type: str = "conf"


@dataclass(frozen=True)
class GenerationFailure:
    name: str
    reason: str


@dataclass(frozen=True)
class RuleGroups:
    domain: list[Rule]
    endpoint: list[Rule]
    origins: list[Rule]


@dataclass(frozen=True)
class GeneratorConfig:
    source_root: Path
    output_root: Path
    cache_root: Path
    ruleset_baseline: str
    targets: tuple[str, ...]
    github_repo: str | None
    publish_branch: str | None
    compile_srs: bool
    generated_at: str


@dataclass(frozen=True)
class EmitContext:
    output_root: Path
    generated_at: str
    compile_srs: bool


@dataclass(frozen=True)
class GenericRuleSet:
    bundle: Bundle
    rules: list[Rule]

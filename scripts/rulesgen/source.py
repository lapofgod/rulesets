from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from .models import Bundle, LOGICAL_KINDS, Rule
from .plugin_host import activate_context


BASIC_RULE_KINDS = {
    "DOMAIN",
    "DOMAIN-SUFFIX",
    "DOMAIN-KEYWORD",
    "DOMAIN-WILDCARD",
    "DOMAIN-REGEX",
    "IP-CIDR",
    "IP-CIDR6",
    "IP-ASN",
    "GEOIP",
    "AND",
    "OR",
    "NOT",
    "URL-REGEX",
    "USER-AGENT",
    "SRC-PORT",
    "DST-PORT",
}

def _split_top_level_commas(text: str) -> list[str] | None:
    parts: list[str] = []
    depth = 0
    start = 0

    for idx, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return None
        elif ch == "," and depth == 0:
            parts.append(text[start:idx].strip())
            start = idx + 1

    if depth != 0:
        return None

    parts.append(text[start:].strip())
    return parts


def _parse_rule_content(content: str) -> tuple[Rule | None, str | None]:
    kind_raw, separator, remainder = content.partition(",")
    if not separator:
        return None, None

    kind = normalize_kind(kind_raw)

    if kind not in BASIC_RULE_KINDS:
        return None, f"Unknown rule kind '{kind}' ignored"

    if kind in LOGICAL_KINDS:
        expression = remainder.strip()
        if not expression:
            return None, f"Invalid {kind} rule ignored: missing expression"
        if not (expression.startswith("(") and expression.endswith(")")):
            return None, f"Invalid {kind} rule ignored: malformed expression"

        body = expression[1:-1].strip()
        if not body:
            return None, f"Invalid {kind} rule ignored: empty expression"

        items = _split_top_level_commas(body)
        if items is None:
            return None, f"Invalid {kind} rule ignored: unbalanced parentheses"

        children: list[Rule] = []
        for item in items:
            if not (item.startswith("(") and item.endswith(")")):
                return None, f"Invalid {kind} rule ignored: each operand must be wrapped by ()"

            child, warning = _parse_rule_content(item[1:-1].strip())
            if warning:
                return None, f"Invalid {kind} rule ignored: {warning}"
            if child is None:
                return None, f"Invalid {kind} rule ignored: empty operand"
            children.append(child)

        if kind == "NOT" and len(children) != 1:
            return None, "Invalid NOT rule ignored: exactly one operand is required"

        return Rule(kind=kind, value=expression, logical_children=tuple(children)), None

    parts = [part.strip() for part in remainder.split(",")]
    value = parts[0]
    extras = tuple(parts[1:]) if len(parts) > 1 else ()

    if kind == "DOMAIN-SUFFIX" and value.startswith("."):
        value = value[1:]

    return Rule(kind, value, extras), None


def normalize_kind(kind: str) -> str:
    return kind.strip().upper().replace("_", "-")


def parse_conf_line(raw: str) -> tuple[Rule | None, str | None]:
    line = raw.strip()
    line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
    if not line or line.startswith("#"):
        return None, None
    return _parse_rule_content(line)


def parse_file(file_path: Path) -> list[Rule]:
    rules: list[Rule] = []
    for line_no, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        parsed, warning = parse_conf_line(line)
        if warning:
            print(f"[WARN] {file_path.name}:{line_no}: {warning}")
        if parsed:
            rules.append(parsed)
    return rules


def parse_python_file(file_path: Path, *, bundle_name: str, cache_root: Path) -> list[Rule]:
    module_name = f"rulesource_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec: {file_path}")

    module = importlib.util.module_from_spec(spec)
    with activate_context(bundle_name=bundle_name, source_file=file_path, cache_root=cache_root):
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise RuntimeError(f"Failed to execute python source '{file_path.name}': {exc}") from exc

        generator = getattr(module, "generate_conf_lines", None)
        if not callable(generator):
            raise RuntimeError(f"'{file_path.name}' must define callable generate_conf_lines()")

        try:
            generated = generator()
        except Exception as exc:
            raise RuntimeError(f"generate_conf_lines() failed in '{file_path.name}': {exc}") from exc

    if isinstance(generated, str):
        raw_lines = generated.splitlines()
    else:
        try:
            raw_lines = list(generated)
        except TypeError as exc:
            raise RuntimeError(
                f"generate_conf_lines() in '{file_path.name}' must return str or iterable[str]"
            ) from exc

    rules: list[Rule] = []
    for idx, line in enumerate(raw_lines, start=1):
        if not isinstance(line, str):
            raise RuntimeError(f"'{file_path.name}' returned non-string line at index {idx}")
        parsed, warning = parse_conf_line(line)
        if warning:
            print(f"[WARN] {file_path.name}:{idx}: {warning}")
        if parsed:
            rules.append(parsed)

    return rules


def iter_sources(source_root: Path) -> list[Bundle]:
    conf_sources: dict[str, Path] = {}
    py_sources: dict[str, Path] = {}

    for source in sorted(source_root.glob("*.conf")):
        if source.name.startswith("."):
            continue
        conf_sources[source.stem] = source

    for source in sorted(source_root.glob("*.py")):
        if source.name.startswith("."):
            continue
        py_sources[source.stem] = source

    entries: list[Bundle] = []
    all_names = sorted(set(conf_sources) | set(py_sources))
    for name in all_names:
        has_conf = name in conf_sources
        has_py = name in py_sources

        if has_conf and has_py:
            entries.append(Bundle(name=name, source=conf_sources[name], source_type="conflict"))
        elif has_py:
            entries.append(Bundle(name=name, source=py_sources[name], source_type="py"))
        else:
            entries.append(Bundle(name=name, source=conf_sources[name], source_type="conf"))

    return entries


def load_rules(bundle: Bundle, *, cache_root: Path) -> list[Rule]:
    if bundle.source_type == "conflict":
        raise RuntimeError(
            f"Conflicting sources for '{bundle.name}': both {bundle.name}.conf and {bundle.name}.py exist"
        )
    if bundle.source_type == "py":
        return parse_python_file(bundle.source, bundle_name=bundle.name, cache_root=cache_root)
    return parse_file(bundle.source)

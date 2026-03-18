from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from .models import Bundle, Rule


def normalize_kind(kind: str) -> str:
    return kind.strip().upper().replace("_", "-")


def parse_conf_line(raw: str) -> Rule | None:
    line = raw.strip()
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


def parse_python_file(file_path: Path) -> list[Rule]:
    module_name = f"rulesource_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec: {file_path}")

    module = importlib.util.module_from_spec(spec)
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
        parsed = parse_conf_line(line)
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


def load_rules(bundle: Bundle) -> list[Rule]:
    if bundle.source_type == "conflict":
        raise RuntimeError(
            f"Conflicting sources for '{bundle.name}': both {bundle.name}.conf and {bundle.name}.py exist"
        )
    if bundle.source_type == "py":
        return parse_python_file(bundle.source)
    return parse_file(bundle.source)

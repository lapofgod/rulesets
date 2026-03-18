from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class PluginHostContext:
    bundle_name: str
    source_file: Path
    cache_root: Path


_ACTIVE_CONTEXT: ContextVar[PluginHostContext | None] = ContextVar("rulesgen_plugin_host_context", default=None)


@contextmanager
def activate_context(*, bundle_name: str, source_file: Path, cache_root: Path) -> Iterator[None]:
    token = _ACTIVE_CONTEXT.set(
        PluginHostContext(
            bundle_name=bundle_name,
            source_file=source_file,
            cache_root=cache_root,
        )
    )
    try:
        yield
    finally:
        _ACTIVE_CONTEXT.reset(token)


def _require_context() -> PluginHostContext:
    context = _ACTIVE_CONTEXT.get()
    if context is None:
        raise RuntimeError("Plugin host context is not active")
    return context


def bundle_name() -> str:
    return _require_context().bundle_name


def cache_file(name: str) -> Path:
    normalized = name.strip().replace("\\", "/")
    if not normalized:
        raise RuntimeError("Cache file name cannot be empty")
    if "/" in normalized or normalized in {".", ".."}:
        raise RuntimeError(f"Cache file name must be a simple filename: {name}")
    return _require_context().cache_root / normalized


def read_cache_text(name: str) -> str | None:
    path = cache_file(name)
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def write_cache_text(name: str, content: str) -> None:
    path = cache_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

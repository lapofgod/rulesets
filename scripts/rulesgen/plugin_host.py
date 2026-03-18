from __future__ import annotations

import hashlib
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence


@dataclass(frozen=True)
class PluginHostContext:
    bundle_name: str
    source_file: Path
    cache_root: Path


_ACTIVE_CONTEXT: ContextVar[PluginHostContext | None] = ContextVar("rulesgen_plugin_host_context", default=None)
DEFAULT_FETCH_TIMEOUTS: tuple[int, ...] = (8, 12, 20)
DEFAULT_FETCH_RETRY_BACKOFF_SECONDS = 0.8
DEFAULT_FETCH_USER_AGENT = "rulesets-generator/1.0"


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


def fetch_bytes(url: str, *, timeout: int = 30, user_agent: str = DEFAULT_FETCH_USER_AGENT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_bytes_with_retry(
    url: str,
    *,
    timeouts: Sequence[int] = DEFAULT_FETCH_TIMEOUTS,
    backoff_seconds: float = DEFAULT_FETCH_RETRY_BACKOFF_SECONDS,
    user_agent: str = DEFAULT_FETCH_USER_AGENT,
) -> bytes:
    attempts = tuple(int(t) for t in timeouts if int(t) > 0)
    if not attempts:
        raise RuntimeError("fetch timeouts cannot be empty")

    last_error: Exception | None = None
    for idx, timeout in enumerate(attempts, start=1):
        try:
            return fetch_bytes(url, timeout=timeout, user_agent=user_agent)
        except Exception as exc:
            last_error = exc
            if idx < len(attempts):
                time.sleep(max(0.0, backoff_seconds) * idx)

    detail = str(last_error) if last_error else "unknown error"
    raise RuntimeError(f"fetch failed after {len(attempts)} attempts ({url}): {detail}")


def fetch_text_with_retry(
    url: str,
    *,
    timeouts: Sequence[int] = DEFAULT_FETCH_TIMEOUTS,
    backoff_seconds: float = DEFAULT_FETCH_RETRY_BACKOFF_SECONDS,
    user_agent: str = DEFAULT_FETCH_USER_AGENT,
    encoding: str = "utf-8",
    errors: str = "ignore",
) -> str:
    data = fetch_bytes_with_retry(
        url,
        timeouts=timeouts,
        backoff_seconds=backoff_seconds,
        user_agent=user_agent,
    )
    return data.decode(encoding, errors=errors)


def fetch_text_with_retry_cache(
    *,
    url: str,
    cache_name: str | None = None,
    timeouts: Sequence[int] = DEFAULT_FETCH_TIMEOUTS,
    backoff_seconds: float = DEFAULT_FETCH_RETRY_BACKOFF_SECONDS,
    user_agent: str = DEFAULT_FETCH_USER_AGENT,
    encoding: str = "utf-8",
    errors: str = "ignore",
) -> tuple[str, bool]:
    """Fetch text with retry/backoff and fallback to per-plugin cache.

    Returns (content, from_cache).
    """
    if cache_name is None:
        parsed = urllib.parse.urlparse(url)
        stem = Path(parsed.path).name or "payload"
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        cache_name = f"{stem}.{digest}.cache"

    try:
        content = fetch_text_with_retry(
            url,
            timeouts=timeouts,
            backoff_seconds=backoff_seconds,
            user_agent=user_agent,
            encoding=encoding,
            errors=errors,
        )
        write_cache_text(cache_name, content)
        return content, False
    except Exception as exc:
        cached = read_cache_text(cache_name)
        if cached is not None and cached.strip():
            return cached, True
        raise RuntimeError(f"fetch failed and cache missing ({url}, cache={cache_name}): {exc}") from exc

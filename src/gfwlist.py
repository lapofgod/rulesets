from __future__ import annotations

import base64
import time
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from rulesgen.plugin_host import read_cache_text, write_cache_text

GFWLIST_URL = "https://raw.githubusercontent.com/gfwlist/gfwlist/master/gfwlist.txt"
GFWLIST_CACHE_NAME = "gfwlist_raw.txt"
FETCH_TIMEOUTS = [8, 12, 20]
FETCH_RETRY_BACKOFF_SECONDS = 0.8


def decode_gfwlist_payload(data: bytes) -> str:
    text = data.decode("utf-8", errors="ignore").strip()
    try:
        decoded = base64.b64decode(text, validate=False).decode("utf-8", errors="ignore")
        if "[AutoProxy" in decoded or "||" in decoded:
            return decoded
    except Exception:
        pass
    return text


def save_gfwlist_cache(content: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    write_cache_text(GFWLIST_CACHE_NAME, f"! cached_at={stamp}\n{content}\n")


def load_gfwlist_cache() -> str | None:
    content = read_cache_text(GFWLIST_CACHE_NAME)
    if content is None:
        return None

    if not content.strip():
        return None

    # Allow a cache metadata header line while keeping parser behavior unchanged.
    if content.startswith("! cached_at="):
        return "\n".join(content.splitlines()[1:])
    return content


def fetch_gfwlist_raw() -> str:
    last_error: Exception | None = None
    for idx, timeout in enumerate(FETCH_TIMEOUTS, start=1):
        try:
            req = urllib.request.Request(GFWLIST_URL, headers={"User-Agent": "rulesets-generator/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()

            decoded = decode_gfwlist_payload(data)
            save_gfwlist_cache(decoded)
            return decoded
        except Exception as exc:
            last_error = exc
            if idx < len(FETCH_TIMEOUTS):
                # Exponential backoff for transient network/TLS failures.
                time.sleep(FETCH_RETRY_BACKOFF_SECONDS * idx)

    detail = str(last_error) if last_error else "unknown error"
    raise RuntimeError(f"fetch failed after {len(FETCH_TIMEOUTS)} attempts ({GFWLIST_URL}): {detail}")


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


def parse_gfwlist_domain(line: str) -> str | None:
    line = line.strip()
    if not line:
        return None
    if line.startswith("!") or line.startswith("["):
        return None
    if line.startswith("@@"):
        return None

    if "$" in line:
        line = line.split("$", 1)[0]

    if line.startswith("||"):
        return normalize_domain_from_host(line[2:])

    if line.startswith("|"):
        line = line[1:]

    if line.startswith("http://") or line.startswith("https://"):
        try:
            host = urllib.parse.urlparse(line).hostname
            return normalize_domain_from_host(host or "")
        except Exception:
            return None

    if line.startswith("."):
        return normalize_domain_from_host(line[1:])

    if line.startswith("*."):
        return normalize_domain_from_host(line[2:])

    if any(token in line for token in ["*", "^", "/", "?"]):
        return None

    return normalize_domain_from_host(line)


def generate_conf_lines() -> list[str]:
    domains: set[str] = set()
    try:
        raw = fetch_gfwlist_raw()
    except Exception as exc:
        cached = load_gfwlist_cache()
        if cached is None:
            raise
        print(f"[WARN] gfwlist.py fetch failed, using cache: {exc}")
        raw = cached

    for line in raw.splitlines():
        domain = parse_gfwlist_domain(line)
        if domain:
            domains.add(domain)

    return [f"DOMAIN-SUFFIX,{domain}" for domain in sorted(domains)]

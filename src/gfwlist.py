from __future__ import annotations

import base64
import re
import urllib.parse

from rulesgen.plugin_host import fetch_text_with_retry_cache

GFWLIST_URL = "https://raw.githubusercontent.com/gfwlist/gfwlist/master/gfwlist.txt"


def _decode_gfwlist_payload(payload: str) -> str:
    text = payload.strip()

    try:
        decoded = base64.b64decode(text, validate=False).decode("utf-8", errors="ignore")
        if "[AutoProxy" in decoded or "||" in decoded:
            return decoded
    except Exception:
        pass
    return text


def _normalize_domain_from_host(host: str) -> str | None:
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


def _parse_gfwlist_domain(line: str) -> str | None:
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
        return _normalize_domain_from_host(line[2:])

    if line.startswith("|"):
        line = line[1:]

    if line.startswith("http://") or line.startswith("https://"):
        try:
            host = urllib.parse.urlparse(line).hostname
            return _normalize_domain_from_host(host or "")
        except Exception:
            return None

    if line.startswith("."):
        return _normalize_domain_from_host(line[1:])

    if line.startswith("*."):
        return _normalize_domain_from_host(line[2:])

    if any(token in line for token in ["*", "^", "/", "?"]):
        return None

    return _normalize_domain_from_host(line)


def generate_conf_lines() -> list[str]:
    domains: set[str] = set()
    payload, from_cache = fetch_text_with_retry_cache(
        url=GFWLIST_URL,
    )
    if from_cache:
        print("[WARN] gfwlist.py using cached payload")
    raw = _decode_gfwlist_payload(payload)

    for line in raw.splitlines():
        domain = _parse_gfwlist_domain(line)
        if domain:
            domains.add(domain)

    return [f"DOMAIN-SUFFIX,{domain}" for domain in sorted(domains)]

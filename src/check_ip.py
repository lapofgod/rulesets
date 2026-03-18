# Commonly used IP checking services. (foreign only)
from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import datetime, timezone

from rulesgen.plugin_host import read_cache_text, write_cache_text

TEST_IPV6_SITES_JSON_URL = "https://raw.githubusercontent.com/falling-sky/source/master/sites/sites.json"
MIRROR_CACHE_NAME = "check_ip_mirrors.json"
FETCH_TIMEOUTS = [8, 12, 20]
FETCH_RETRY_BACKOFF_SECONDS = 0.8

STATIC_LINES = [
    "DOMAIN-SUFFIX,123169.xyz",
    "DOMAIN-SUFFIX,ip.sb",
    "DOMAIN-SUFFIX,ip.skk.moe",
    "DOMAIN-SUFFIX,ip.api.skk.moe",
    "DOMAIN-SUFFIX,ipinfo.io",
    "DOMAIN-SUFFIX,ifconfig.co",
    "DOMAIN-SUFFIX,ifconfig.me",
    "DOMAIN-SUFFIX,icanhazip.com",
    "DOMAIN-SUFFIX,myip.la",
    "DOMAIN-SUFFIX,ip-api.com",
    "DOMAIN-SUFFIX,api.myip.la",
    "DOMAIN-SUFFIX,ip.gs",
    "DOMAIN-SUFFIX,ippure.com",
    "DOMAIN-SUFFIX,ip125.com",
    "DOMAIN-SUFFIX,ping0.cc",
    "DOMAIN-SUFFIX,whoer.net",
    "DOMAIN-SUFFIX,ipleak.net",
    "DOMAIN-SUFFIX,browserleaks.com",
    "DOMAIN-SUFFIX,dnsleaktest.com",
    "DOMAIN-SUFFIX,checkip.amazonaws.com",
    "DOMAIN-SUFFIX,ipify.org",
    "DOMAIN-SUFFIX,httpbin.org",
    "DOMAIN-SUFFIX,whatismyipaddress.com",
    "DOMAIN-SUFFIX,ident.me",
    "DOMAIN-SUFFIX,test-ipv6.com",
    "DOMAIN-SUFFIX,ip2location.com",
    "DOMAIN-SUFFIX,ip2location.io",
]


def fetch_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "rulesets-generator/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def fetch_text_with_retry(url: str) -> str:
    last_error: Exception | None = None
    for idx, timeout in enumerate(FETCH_TIMEOUTS, start=1):
        try:
            return fetch_text(url, timeout=timeout)
        except Exception as exc:
            last_error = exc
            if idx < len(FETCH_TIMEOUTS):
                # Exponential backoff for transient TLS/network spikes.
                time.sleep(FETCH_RETRY_BACKOFF_SECONDS * idx)

    detail = str(last_error) if last_error else "unknown error"
    raise RuntimeError(f"fetch failed after {len(FETCH_TIMEOUTS)} attempts ({url}): {detail}")


def load_mirror_cache() -> list[str]:
    cache_text = read_cache_text(MIRROR_CACHE_NAME)
    if cache_text is None:
        return []

    try:
        payload = json.loads(cache_text)
    except Exception:
        return []

    domains = payload.get("domains")
    if not isinstance(domains, list):
        return []

    valid_domains = [d for d in domains if isinstance(d, str) and normalize_domain_from_host(d)]
    return sorted(set(valid_domains))


def save_mirror_cache(domains: list[str]) -> None:
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "domains": sorted(set(domains)),
    }
    write_cache_text(MIRROR_CACHE_NAME, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


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


def is_cn_location(loc: str) -> bool:
    upper = loc.upper()
    return bool(re.search(r"\bCN\b", upper) or "CHINA" in upper)


def dynamic_mirror_lines() -> list[str]:
    payload = json.loads(fetch_text_with_retry(TEST_IPV6_SITES_JSON_URL))
    if not isinstance(payload, dict):
        raise RuntimeError("sites.json payload is not a JSON object")

    sites = payload.get("sites")
    if not isinstance(sites, dict):
        raise RuntimeError("sites.json missing 'sites' object")

    domains: set[str] = set()
    for item in sites.values():
        if not isinstance(item, dict):
            continue
        if not bool(item.get("mirror")):
            continue
        if is_cn_location(str(item.get("loc", ""))):
            continue

        domain = normalize_domain_from_host(str(item.get("site", "")))
        if domain:
            domains.add(domain)

    sorted_domains = sorted(domains)
    save_mirror_cache(sorted_domains)
    return [f"DOMAIN-SUFFIX,{domain}" for domain in sorted_domains]


def dedupe_lines_keep_order(lines: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        deduped.append(line)
    return deduped


def generate_conf_lines() -> list[str]:
    lines = list(STATIC_LINES)
    try:
        lines.extend(dynamic_mirror_lines())
    except Exception as exc:
        cached = load_mirror_cache()
        if cached:
            lines.extend(f"DOMAIN-SUFFIX,{domain}" for domain in cached)
            print(f"[WARN] check_ip.py dynamic mirrors failed, using cache ({len(cached)}): {exc}")
        else:
            # Keep static fallback output when dynamic fetch fails.
            print(f"[WARN] check_ip.py dynamic mirrors skipped (no cache): {exc}")

    return dedupe_lines_keep_order(lines)

# Commonly used IP checking services. (foreign only)
from __future__ import annotations

import json
import re

from rulesgen.plugin_host import fetch_text_with_retry_cache

TEST_IPV6_SITES_JSON_URL = "https://raw.githubusercontent.com/falling-sky/source/master/sites/sites.json"

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
    "DOMAIN-SUFFIX,ipwhois.io",
    "DOMAIN-SUFFIX,ipwho.is",
    "DOMAIN-SUFFIX,ipapi.is",
    "DOMAIN-SUFFIX,ipdata.co",
]


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


def _is_cn_location(loc: str) -> bool:
    upper = loc.upper()
    return bool(re.search(r"\bCN\b", upper) or "CHINA" in upper)


def _dynamic_mirror_lines() -> list[str]:
    payload_text, from_cache = fetch_text_with_retry_cache(
        url=TEST_IPV6_SITES_JSON_URL,
    )
    payload = json.loads(payload_text)
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
        if _is_cn_location(str(item.get("loc", ""))):
            continue

        domain = _normalize_domain_from_host(str(item.get("site", "")))
        if domain:
            domains.add(domain)

    sorted_domains = sorted(domains)
    if from_cache:
        print("[WARN] check_ip.py using cached sites payload")
    return [f"DOMAIN-SUFFIX,{domain}" for domain in sorted_domains]


def _dedupe_lines_keep_order(lines: list[str]) -> list[str]:
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
        lines.extend(_dynamic_mirror_lines())
    except Exception as exc:
        # Keep static fallback output when dynamic fetch/cache fails.
        print(f"[WARN] check_ip.py dynamic mirrors skipped: {exc}")
    return _dedupe_lines_keep_order(lines)

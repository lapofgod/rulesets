# Commonly used IP checking services. (foreign only)
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TEST_IPV6_MIRRORS_URL = "https://test-ipv6.com/mirrors.html.en_US"
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
MIRROR_CACHE_FILE = CACHE_DIR / "check_ip_mirrors.json"
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
    if not MIRROR_CACHE_FILE.exists():
        return []

    try:
        payload = json.loads(MIRROR_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

    domains = payload.get("domains")
    if not isinstance(domains, list):
        return []

    valid_domains = [d for d in domains if isinstance(d, str) and normalize_domain_from_host(d)]
    return sorted(set(valid_domains))


def save_mirror_cache(domains: list[str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "domains": sorted(set(domains)),
    }
    MIRROR_CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_js_object(text: str, marker: str) -> str | None:
    assign = re.search(rf"{re.escape(marker)}\s*=\s*", text)
    if not assign:
        return None

    brace_start = text.find("{", assign.end())
    if brace_start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False

    for idx in range(brace_start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start : idx + 1]

    return None


def parse_js_object_as_dict(raw_object: str) -> dict:
    try:
        parsed = json.loads(raw_object)
    except json.JSONDecodeError:
        normalized = re.sub(r",\s*([}\]])", r"\1", raw_object)
        parsed = json.loads(normalized)

    if not isinstance(parsed, dict):
        raise RuntimeError("Parsed payload is not a JSON object")
    return parsed


def candidate_index_js_urls(html: str) -> list[str]:
    urls: list[str] = []
    for src in re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", html, flags=re.IGNORECASE):
        if "index.js" in src:
            urls.append(urllib.parse.urljoin(TEST_IPV6_MIRRORS_URL, src))

    urls.extend(
        [
            urllib.parse.urljoin(TEST_IPV6_MIRRORS_URL, "/index.js.en_US"),
            urllib.parse.urljoin(TEST_IPV6_MIRRORS_URL, "/index.js"),
        ]
    )

    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def parse_sites_payload(script_text: str) -> dict:
    for marker in ["GIGO.sites_parsed", "sites_parsed"]:
        payload = extract_js_object(script_text, marker)
        if payload:
            return parse_js_object_as_dict(payload)
    raise RuntimeError("Could not locate sites_parsed payload")


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
    html = fetch_text_with_retry(TEST_IPV6_MIRRORS_URL)
    candidates = candidate_index_js_urls(html)

    sites: dict | None = None
    last_error: Exception | None = None
    for script_url in candidates:
        try:
            sites = parse_sites_payload(fetch_text_with_retry(script_url))
            break
        except Exception as exc:
            last_error = exc

    if sites is None:
        detail = str(last_error) if last_error else "unknown error"
        raise RuntimeError(f"Failed to parse mirror payload: {detail}")

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

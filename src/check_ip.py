# Commonly used IP checking services. (foreign only)
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

TEST_IPV6_MIRRORS_URL = "https://test-ipv6.com/mirrors.html.en_US"

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
    html = fetch_text(TEST_IPV6_MIRRORS_URL)
    candidates = candidate_index_js_urls(html)

    sites: dict | None = None
    last_error: Exception | None = None
    for script_url in candidates:
        try:
            sites = parse_sites_payload(fetch_text(script_url))
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

    return [f"DOMAIN-SUFFIX,{domain}" for domain in sorted(domains)]


def generate_conf_lines() -> list[str]:
    lines = list(STATIC_LINES)
    try:
        lines.extend(dynamic_mirror_lines())
    except Exception as exc:
        # Keep static fallback output when dynamic fetch fails.
        print(f"[WARN] check_ip.py dynamic mirrors skipped: {exc}")
    return lines

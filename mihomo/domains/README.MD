# mihomo/domains

This directory is auto-generated.

## Mihomo Usage

Use `domains` + `endpoints` + `origins` in parallel when available.

### _personal_reject.list
- Format: text
- Behavior: domain
```yaml
rule-providers:
  _personal_reject_domains:
    type: http
    behavior: domain
    format: text
    url: https://raw.githubusercontent.com/lapofgod/rulesets/generated/mihomo/domains/_personal_reject.list
    path: ./ruleset/_personal_reject.list
    interval: 86400
```

### audited.list
- Format: text
- Behavior: domain
```yaml
rule-providers:
  audited_domains:
    type: http
    behavior: domain
    format: text
    url: https://raw.githubusercontent.com/lapofgod/rulesets/generated/mihomo/domains/audited.list
    path: ./ruleset/audited.list
    interval: 86400
```

### check_ip.list
- Format: text
- Behavior: domain
```yaml
rule-providers:
  check_ip_domains:
    type: http
    behavior: domain
    format: text
    url: https://raw.githubusercontent.com/lapofgod/rulesets/generated/mihomo/domains/check_ip.list
    path: ./ruleset/check_ip.list
    interval: 86400
```

### conn_check.list
- Format: text
- Behavior: domain
```yaml
rule-providers:
  conn_check_domains:
    type: http
    behavior: domain
    format: text
    url: https://raw.githubusercontent.com/lapofgod/rulesets/generated/mihomo/domains/conn_check.list
    path: ./ruleset/conn_check.list
    interval: 86400
```

### gfwlist.list
- Format: text
- Behavior: domain
```yaml
rule-providers:
  gfwlist_domains:
    type: http
    behavior: domain
    format: text
    url: https://raw.githubusercontent.com/lapofgod/rulesets/generated/mihomo/domains/gfwlist.list
    path: ./ruleset/gfwlist.list
    interval: 86400
```

### wikimedia.list
- Format: text
- Behavior: domain
```yaml
rule-providers:
  wikimedia_domains:
    type: http
    behavior: domain
    format: text
    url: https://raw.githubusercontent.com/lapofgod/rulesets/generated/mihomo/domains/wikimedia.list
    path: ./ruleset/wikimedia.list
    interval: 86400
```

## External URLs

### _personal_reject.list

- raw.githubusercontent.com: https://raw.githubusercontent.com/lapofgod/rulesets/generated/mihomo/domains/_personal_reject.list
- cdn.jsdelivr.net: https://cdn.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/_personal_reject.list
- fastly.jsdelivr.net: https://fastly.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/_personal_reject.list
- testingcf.jsdelivr.net: https://testingcf.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/_personal_reject.list
- gh-proxy: https://gh-proxy.org/https://github.com/lapofgod/rulesets/blob/generated/mihomo/domains/_personal_reject.list

### audited.list

- raw.githubusercontent.com: https://raw.githubusercontent.com/lapofgod/rulesets/generated/mihomo/domains/audited.list
- cdn.jsdelivr.net: https://cdn.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/audited.list
- fastly.jsdelivr.net: https://fastly.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/audited.list
- testingcf.jsdelivr.net: https://testingcf.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/audited.list
- gh-proxy: https://gh-proxy.org/https://github.com/lapofgod/rulesets/blob/generated/mihomo/domains/audited.list

### check_ip.list

- raw.githubusercontent.com: https://raw.githubusercontent.com/lapofgod/rulesets/generated/mihomo/domains/check_ip.list
- cdn.jsdelivr.net: https://cdn.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/check_ip.list
- fastly.jsdelivr.net: https://fastly.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/check_ip.list
- testingcf.jsdelivr.net: https://testingcf.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/check_ip.list
- gh-proxy: https://gh-proxy.org/https://github.com/lapofgod/rulesets/blob/generated/mihomo/domains/check_ip.list

### conn_check.list

- raw.githubusercontent.com: https://raw.githubusercontent.com/lapofgod/rulesets/generated/mihomo/domains/conn_check.list
- cdn.jsdelivr.net: https://cdn.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/conn_check.list
- fastly.jsdelivr.net: https://fastly.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/conn_check.list
- testingcf.jsdelivr.net: https://testingcf.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/conn_check.list
- gh-proxy: https://gh-proxy.org/https://github.com/lapofgod/rulesets/blob/generated/mihomo/domains/conn_check.list

### gfwlist.list

- raw.githubusercontent.com: https://raw.githubusercontent.com/lapofgod/rulesets/generated/mihomo/domains/gfwlist.list
- cdn.jsdelivr.net: https://cdn.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/gfwlist.list
- fastly.jsdelivr.net: https://fastly.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/gfwlist.list
- testingcf.jsdelivr.net: https://testingcf.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/gfwlist.list
- gh-proxy: https://gh-proxy.org/https://github.com/lapofgod/rulesets/blob/generated/mihomo/domains/gfwlist.list

### wikimedia.list

- raw.githubusercontent.com: https://raw.githubusercontent.com/lapofgod/rulesets/generated/mihomo/domains/wikimedia.list
- cdn.jsdelivr.net: https://cdn.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/wikimedia.list
- fastly.jsdelivr.net: https://fastly.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/wikimedia.list
- testingcf.jsdelivr.net: https://testingcf.jsdelivr.net/gh/lapofgod/rulesets@generated/mihomo/domains/wikimedia.list
- gh-proxy: https://gh-proxy.org/https://github.com/lapofgod/rulesets/blob/generated/mihomo/domains/wikimedia.list

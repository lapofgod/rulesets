# Project Guidelines

一个基于平台无关规则源自动生成多客户端规则文件的仓库。

Single Source of Truth: `rules/*.conf` + `rules/*.py`（仅非隐藏文件）。

支持目标：

- Surge
- Mihomo (Clash Meta)
- Shadowrocket
- Loon
- sing-box

## Architecture

目录结构：

```text
.
├── rules/
│   ├── *.conf             # 静态规则源（Mihomo 规则 + URL-REGEX + USER-AGENT）
│   └── *.py               # 可插拔规则源，需实现 generate_conf_lines()
├── scripts/
│   └── generate_rules.py  # 生成器
├── pyproject.toml         # 依赖与项目元数据（uv）
├── generated/             # 本地生成产物（发布时会展开到 generated 分支根目录）
│   ├── surge/<规则名>/
│   ├── mihomo/<规则名>/
│   ├── shadowrocket/<规则名>/
│   ├── loon/<规则名>/
│   ├── sing-box/<规则名>/
│   └── manifest.json
└── .github/workflows/
    └── generate-rules.yml
```

`generated` 输出命名规则：

- 第一层：代理软件
- 第二层：规则类型
- 文件名：服务名（例如 `audited.list`、`conn_check.conf`、`audited.json`）
- 本地生成阶段：空产物文件不会新建。
- GitHub Actions 发布阶段：若 `generated` 分支历史文件本次未生成（等价于本次为空），保留同路径文件并写为 0 字节空文件，避免外链 404。

发布到 `generated` 分支后，`generated/` 这一层会被去掉，直接在分支根目录得到：

```text
mihomo/domains/audited.list
sing-box/json/audited.json
sing-box/srs/audited.srs
surge/endpoints/conn_check.conf
surge/endpoints/README.MD
...
```

## Conventions

规则源发现与命名：

- 自动检索 `rules/` 下所有非隐藏 `.conf` 与 `.py` 文件。
- 规则名使用文件名（去掉扩展名）。

规则源格式：

- `.conf`：按基础规则语法逐行解析；以 `#` 开头的行视为注释并忽略。
- source 输入不支持 domain set 简写（如 `.example.com`、`+.example.com`、`*.example.com`），应显式写为 `DOMAIN-SUFFIX,example.com` 或其他标准规则行。
- 遇到不识别的规则类型时：忽略该行并输出 `[WARN]` 警告（包含文件名与行号）。
- `.py`：必须导出 `generate_conf_lines()`，返回 `str` 或 `iterable[str]`；每行内容与 `.conf` 行格式一致。
- `.py`：涉及缓存时应使用宿主提供的 API（`rulesgen.plugin_host`），不要在插件内自行拼接或管理 `cache/` 路径。

冲突处理：

- 若同名 `.conf` 与 `.py` 同时存在（如 `foo.conf` + `foo.py`），仅该项目标记为失败，不影响其他项目。

迁移状态：

- `gfwlist` 与 `check_ip` 已迁移到 `rules/gfwlist.py` 与 `rules/check_ip.py`。

失败容错：

- 某个项目生成失败时，只记录该项目失败，不中断其余项目。
- 发布到 `generated` 分支时，失败项目沿用该项目上一次已存在的文件版本。

基础规则语法（Mihomo 语法 + URL-REGEX + USER-AGENT）：

```text
DOMAIN-SUFFIX,example.com
DOMAIN,api.example.com
DOMAIN-KEYWORD,foo
DOMAIN-WILDCARD,*.example.com
DOMAIN-REGEX,^.*\.example\.com$
IP-CIDR,1.1.1.0/24,no-resolve
IP-CIDR6,2400:3200::/32
IP-ASN,13335
GEOIP,CN
AND,((DOMAIN,example.com),(DST-PORT,443))
OR,((DOMAIN-SUFFIX,example.com),(DOMAIN-KEYWORD,foo))
NOT,((DOMAIN-REGEX,^ads\\.example\\.com$))
URL-REGEX,^https?:\/\/example\.com\/api
USER-AGENT,Curl*
```

支持行尾注释，例如：`DOMAIN-SUFFIX,example.com # note`。
`AND` / `OR` / `NOT` 为特殊语法：首个逗号后的表达式整体解析（允许内部继续包含逗号）。

自动升级规则类型：

- 可表示为 domain set 的规则拆分到 `domains`。
- `USER-AGENT` 与 `SRC-PORT`（请求者来源约束）拆分到 `origins`。
- 其余规则进入 `endpoints`。
- sing-box 不拆分上述类型，统一输出到 `json/<服务>.json`。

高级规则支持：

- 当前 source 仅支持基础规则语法；不在基础语法列表中的类型会被忽略并告警。
- `DOMAIN-WILDCARD`、`DOMAIN-REGEX`、`IP-ASN`、`GEOIP`、`AND`、`OR`、`NOT` 属于基础语法，仍然支持。
- 非 sing-box 平台主要落到 `endpoints`（或保留平台可兼容映射）。
- sing-box 可映射 `domain_keyword` 等字段。

domain set 语义：

- `domains.list` 文件名不变，但内容按平台语义输出。
- mihomo 使用 `+.example.com`。
- surge/shadowrocket/loon 使用 `.example.com`。
- sing-box 统一输出 `rules.json`（可编译为 `rules.srs`）。

稳定性：

- 所有平台的 domain set 输出都会去重并排序，保证产物稳定、diff 更干净。
- 除 sing-box 外，所有生成规则文件都带英文注释头，且包含 `Rule count`。

平台差异映射：

- source 输入不接受域名前缀简写（`.baidu.com`、`+.baidu.com`、`*.baidu.com`）；请使用显式规则语法。
- 端口规则映射：源基准使用 `DST-PORT`，Surge/Shadowrocket 输出为 `DEST-PORT`。
- Loon 兼容：`DOMAIN-WILDCARD` 若值为 `*.example.com` 则降级为 `DOMAIN-SUFFIX,example.com`，否则跳过。
- Origin 兼容：`USER-AGENT` 仅在支持的平台输出；`SRC-PORT` 归类到 `origins`。

使用建议：

- 推荐并列使用 `domains` + `endpoints` + `origins` 组合，以获得更紧凑且语义清晰的策略。

## Build and Test

本地环境与生成命令：

```bash
uv venv .venv
source .venv/bin/activate
uv sync
python scripts/generate_rules.py \
    --source-root rules \
    --output-root generated \
    --ruleset-baseline mihomo \
    --github-repo lapofgod/rulesets \
    --publish-branch generated
```

参数规则：

- `--source-root`、`--output-root`、`--ruleset-baseline`、`--github-repo`、`--publish-branch` 必填。
- `--targets` 可选；不提供时默认生成全部目标（`surge,mihomo,shadowrocket,loon,sing-box`）。

运行后查看 `generated/`。

sing-box 相关：

- 不区分 domain/endpoint/ua，统一按规则顺序输出到 `rules.json`。
- 产物按类型目录输出：`sing-box/json/<服务>.json` 与 `sing-box/srs/<服务>.srs`。
- `USER-AGENT` 在不支持的客户端（mihomo/sing-box）不会输出对应文件。
- 本地未安装 `sing-box` 时，可使用：

```bash
python scripts/generate_rules.py \
    --source-root rules \
    --output-root generated \
    --ruleset-baseline mihomo \
    --github-repo lapofgod/rulesets \
    --publish-branch generated \
    --skip-sing-box-compile
```

仅生成部分目标：

```bash
python scripts/generate_rules.py \
    --source-root rules \
    --output-root generated \
    --ruleset-baseline mihomo \
    --github-repo lapofgod/rulesets \
    --publish-branch generated \
    --targets mihomo,sing-box
```

可选发布参数（用于 README 外链生成）：

```bash
python scripts/generate_rules.py \
    --source-root rules \
    --output-root generated \
    --ruleset-baseline mihomo \
    --github-repo lapofgod/rulesets \
    --publish-branch generated
```

## Automation

工作流：`.github/workflows/generate-rules.yml`

触发方式：

- push（`rules/**`、`scripts/**` 变更）
- schedule（每日 UTC 02:15）
- 手动触发（`workflow_dispatch`）

手动触发输入：

- 无需输入参数，始终提交到 `generated` 分支根目录（不会走 Release）。

额外规则：

- 工作流固定只向 `generated` 分支提交产物，不会写回源码分支（例如 `main`）。
- `main` 分支默认忽略本地产物目录 `generated/`。
- 发布逻辑内联在 `.github/workflows/generate-rules.yml` 中（不再依赖独立发布脚本）。
- 发布前会清理目标分支根目录下历史遗留的 `generated/` 目录，确保产物直接落在分支根目录。
- 目标分支 `.gitignore` 使用白名单模式：默认忽略全部，仅放行 `.gitignore`、`manifest.json` 与各目标产物目录（`surge/`、`mihomo/`、`shadowrocket/`、`loon/`、`sing-box/`）。

## Agent Guidance

以下约束用于 agent 在本仓库执行任务时的默认行为：

- 不新增或修改规则语义时，优先保持输出稳定性（顺序、去重、注释头格式）。
- 修改生成逻辑时，需同时考虑 Surge、Mihomo、Shadowrocket、Loon、sing-box 的等价映射。
- 若同名 `.conf` 与 `.py` 冲突，不应让整个生成流程失败。
- 保持 CLI 严格参数接口：仅 `--targets` 允许默认值；其余关键参数按现有规则必填。

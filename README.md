# ruleset

一个基于**平台无关规则源**自动生成多客户端规则文件的仓库。

> Single Source of Truth: `sources/*.conf`（非隐藏文件）

支持目标：
- Surge
- Mihomo (Clash Meta)
- Shadowrocket
- Loon
- sing-box

## 目录结构

```text
.
├── sources/
│   └── *.conf             # 规则源（Mihomo 规则 + URL-REGEX + USER-AGENT）
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
- 第二层：规则名
- 文件按类型输出：`domain.list` 或 `endpoint.*` + `ua.conf`
- 空产物文件不会新建；若发布分支中历史文件已存在，会保留历史文件

发布到 `generated` 分支后，`generated/` 这一层会被去掉，直接在分支根目录得到：

```text
mihomo/AI/domain.list
mihomo/AI/other.yaml
surge/AI/domain.list
surge/AI/endpoint.conf
surge/AI/ua.conf
...
```

## 规则源格式

`sources/` 下所有不以 `.` 开头的 `.conf` 文件都会被自动检索并生成，规则名取文件名（去掉 `.conf`）。
以 `#` 开头的行会被视为注释并忽略。

每行规则采用：**Mihomo 语法 + URL-REGEX + USER-AGENT**，例如：

```text
DOMAIN-SUFFIX,example.com
DOMAIN,api.example.com
DOMAIN-KEYWORD,foo
IP-CIDR,1.1.1.0/24,no-resolve
URL-REGEX,^https?:\/\/example\.com\/api
USER-AGENT,Curl*
```

## 自动升级规则类型

- 若 `.conf` 中**全部规则**都可表示为 domain set（`DOMAIN`/`DOMAIN-SUFFIX`/`DOMAIN-KEYWORD`/`DOMAIN-WILDCARD`），则输出到 `domain.list`。
- 否则输出为 `endpoint` + `ua`：
  - endpoint 会合并原先的 endpoint/other（包含 domain 类规则）
  - ua 单独输出到 `ua.conf`（仅支持 UA 的客户端）

`domain.list` 文件名保持不变，但内容是平台对应的 domain set 语义：
- mihomo: `+.example.com`
- surge/shadowrocket/loon: `.example.com`
- sing-box: 统一输出 `rules.json`（可编译为 `rules.srs`）

所有平台的 domain set 输出都会做去重和排序，保证产物稳定、diff 更干净。
除 sing-box 外，所有生成规则文件都会带英文注释头，并包含 `Rule count`。

## 平台差异映射

生成器内置了按平台的语义映射，确保同一源规则在不同客户端尽量等价：

- 域名前缀归一化：源里 `.baidu.com`、`+.baidu.com`、`*.baidu.com` 都先归一为 `DOMAIN-SUFFIX,baidu.com`，避免不同平台对点前缀语义差异。
- 端口规则映射：源基准使用 `DST-PORT`，输出到 Surge / Shadowrocket 自动转成 `DEST-PORT`。
- Loon 兼容：`DOMAIN-WILDCARD` 在 Loon 不支持，若值是 `*.example.com` 自动降级为 `DOMAIN-SUFFIX,example.com`，否则跳过。
- UA 兼容：`USER-AGENT` 仅对支持的平台输出（Surge / Shadowrocket / Loon）。

## sing-box 说明

- 不区分 domain/endpoint/ua，统一按规则顺序输出到 `rules.json`
- 默认同时产出：`rules.json` 与可直接使用的 `rules.srs`
- `USER-AGENT` 规则在不支持的客户端（mihomo/sing-box）不会输出对应文件
- 若本地未安装 `sing-box`，可临时使用：

```bash
python scripts/generate_rules.py --skip-sing-box-compile
```

## 自动生成

工作流：`.github/workflows/generate-rules.yml`

触发方式：
- push（`sources/**`、`scripts/**` 变更）
- schedule（每日 UTC 02:15）
- 手动触发（`workflow_dispatch`）

手动触发时支持输入：
- 无需输入参数：始终提交到 `generated` 分支根目录（不会走 Release）

额外规则：
- 工作流固定只向 `generated` 分支提交产物，不会写回源码分支（例如 `main`）
- `main` 分支默认忽略本地产物目录 `generated/`

## 本地运行

```bash
uv venv .venv
source .venv/bin/activate
uv sync
python scripts/generate_rules.py
```

运行后查看 `generated/`。

# PAST 5 简体中文汉化工具链

把 [PAST](https://www.nhm.uio.no/english/research/resources/past/)（PAlaeontological
STatistics）第 5 版的英文界面汉化成简体中文。

> **本仓库不包含 PAST 本体**。请从官网下载原版 `Past5.exe`，再用本工具生成汉化版。
> PAST 版权归 Øyvind Hammer 与 David A. Harper 所有。

支持三种接入方式：**MCP**（供 AI agent 调用）、**CLI**、**HTTP API**。

---

## 快速开始

```bash
# 0) 准备：把官网下载的原版 Past5.exe 放到本目录

# 1) 查看可汉化内容
python -m past5loc verify Past5.exe

# 2) 生成汉化版
python -m past5loc build Past5.exe translations_zh.json \
       -o Past5_zh-CN.exe --allow allow_strings.json

# 3) 确认结果
python -m past5loc verify Past5_zh-CN.exe
```

只需要 Python 3.9+；MCP 模式另需 `pip install mcp`。

---

## 为什么需要一个专门的工具

PAST 5 是 Delphi 12 / FireMonkey 编译的原生程序，**没有 `.dfm` 文本资源**：
全部 201 个窗体的界面文字，都以**二进制组件流**（`TPF0` 开头）嵌在 PE 的
`RCDATA` 段里。通用汉化工具（Resource Hacker、各类 PE 编辑器）看到它只是一坨
二进制，无法解析，因此本仓库实现了：

- **TPF0 组件流解析器**（`past5loc/formstream.py`）——逆向出的语法，含各 tag 的载荷布局
- **PE 资源重建**（`past5loc/pe.py`）——按改动后的载荷重新序列化 `.rsrc` 段
- **三层结构校验**（`past5loc/validate.py`）——决定一个字符串**能不能改**

最后一条是关键，详见下文。

---

## 原理：字符串怎么改，以及为什么需要校验

界面文字在流里的编码是：

```
<属性名> 0x06 <长度:u8> <字节>
```

看起来只要找到 `0x06` 就能替换，但**直接按字节扫会误伤**：某个整数属性的值
恰好等于 `6`（即 `0x06`）时，紧跟其后的**属性名**会被误当成字符串值替换掉。
PAST 启动时报的这个错就是这么来的：

```
Error reading ListBoxItem11.<乱码>: Property <乱码> does not exist
```

因此每个候选串都要过三关：

1. `0x06` 前面必须是一个**长度自洽的 DFM 属性名**；
2. 该属性名要命中**属性名词典**（从 exe 自身统计得出，155 个）；
3. `0x06` 后面必须是**合法结尾或结构自洽的下一个属性**。

只有全过的串才会被替换。词典里那些"只在无法验证的位置出现、且本身不是属性名"
的字符串，需要显式写进 `allow_strings.json` 才放行。

### 两个已踩过的坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 启动崩溃，报 `Property <乱码> does not exist` | `allow` 列表误放了属性名类字符串（`Text`/`Color`/`Value`/`None`），使"整数 6"处的属性名被替换 | `allow` 生成时排除属性名词典内的串 |
| `Plot`/`Numbers`/`Scatter plot` 大批未汉化 | 校验曾要求"下一个属性名也必须在词典里"，而它们后面是低频派生属性 `ExplicitSize.cx`（词典只收了 `ExplicitSize.cy`） | 放宽为"右侧结构自洽即可"；通过率 1712 → 1845 |

---

## 编码：必须用 GBK，不能用 UTF-8

PAST 的窗体字符串按**系统 ANSI 代码页**解码。在简体中文 Windows（CP936）上
写入 UTF-8 会显示成乱码。默认 `--encoding gbk` 已处理；如你的系统代码页不同，
用 `--encoding utf-8` 或相应编码。

---

## 三种接入方式

### MCP（AI agent 推荐）

```bash
python -m past5loc mcp          # stdio 传输
```

配置样例见 `mcp_config.dsh.yaml`（DSH）与 `mcp_config.generic.json`
（Claude Desktop / Cursor 的 `mcpServers` 格式）。工具以
`mcp__past5loc__<tool>` 出现：

| 工具 | 作用 |
|---|---|
| `past5_list_resources` | 列出 PE 资源（默认只看内嵌窗体） |
| `past5_extract_strings` | 提取可翻译字符串 |
| `past5_check_dictionary` | 检查词典覆盖率 |
| `past5_build` | 生成汉化 exe |
| `past5_verify` | 审计汉化情况 |
| `past5_run_command` | 透传任意 CLI 子命令 |

### CLI

```bash
python -m past5loc list    <exe> [--json] [--limit N]
python -m past5loc extract <exe> [-o catalog.json]
python -m past5loc check   <exe> <dictionary.json>
python -m past5loc build   <exe> <dictionary.json> -o <out.exe>
                           [--encoding gbk|utf-8] [--allow allow.json] [--pad]
python -m past5loc verify  <exe>
python -m past5loc serve   [--host 127.0.0.1] [--port 8765]
python -m past5loc mcp
```

`--pad` 为等长模式：译文短于原文时以空格补齐，流内零位移，最保守。

### HTTP API

```bash
python -m past5loc serve --port 8765
curl -s -X POST http://127.0.0.1:8765/verify \
     -H "Content-Type: application/json" \
     -d '{"exe":"Past5_zh-CN.exe"}'
```

端点：`/health`、`/list_resources`、`/extract_strings`、`/check_dictionary`、
`/build`、`/verify`。

---

## 汉化覆盖情况

| 指标 | 数值 |
|---|---|
| 内嵌窗体 | 201 |
| 字符串 token | 6905 |
| 用户可见文本（Text/Caption 等） | 4711 |
| 其中已汉化 | **3609（76%）** |
| 词典条目 | 1867 |
| 词典通过结构校验 | 1845（98.8%） |

剩余约 24% 大多**约定保持拉丁**：相似度/距离指数名（Bray-Curtis、Jaccard、
Euclidean、Morisita、Jukes-Cantor…）、统计符号（`R2:` `p:` `N:` `RMSE:`）、
统计术语（ANOVA、Poisson、EFA PCA）。用 `python audit_zh.py <原版exe> <汉化exe>`
可随时复查。

---

## 目录结构

```
past5loc/                   汉化工具链（Python 包）
├── pe.py                   PE 解析 / 资源树读写 / .rsrc 段重建
├── formstream.py           TPF0 组件流解析器
├── validate.py             三层结构校验（安全核心）
├── props.py                属性名词典自动采集
├── catalog.py              字符串提取
├── builder.py              变长/等长替换与构建
├── cli.py                  CLI 入口
├── mcp_server.py           MCP 服务器
└── http_api.py             HTTP API 服务器

translations_zh.json        术语表（英文 → 中文），可直接编辑
allow_strings.json          允许在未校验位置替换的白名单
mcp_config.dsh.yaml         DSH 的 MCP 接入配置
mcp_config.generic.json     通用 MCP 配置
README_接口.md              接口与工作流详解

make_allow.py               重新生成白名单（改过校验规则后必跑）
audit_zh.py                 汉化完整性审计
test_launch.py              启动稳定性测试（进程存活 + 错误弹窗）
```

### 维护词典

`translations_zh.json` 是一个扁平的 `{"English": "中文"}` 映射，改完重跑
`build` 即可。新增条目若落在无法校验的位置，会被 `check` 列出，按需加入
`allow_strings.json`。

---

## 许可

工具链与词典以 [MIT](LICENSE) 发布。PAST 本体版权归其作者所有，本仓库不包含、
也不重新分发它。

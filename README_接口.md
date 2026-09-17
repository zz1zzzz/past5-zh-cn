# past5loc 接口文档（给 agent 用）

PAST 5 简体中文汉化工具链。三种接入方式：**MCP**（推荐）、**CLI**、**HTTP API**。
核心逻辑在 `past5loc` 包里，三种接口都调用同一套实现。

```
python -m past5loc <子命令>     # CLI
python -m past5loc mcp          # MCP stdio 服务器
python -m past5loc serve        # HTTP/JSON 服务器
```

依赖：Python 3.9+；仅 MCP 模式需要 `mcp` 包（已安装）。

---

## 一、概念：为什么需要"结构校验"

Past5.exe 是 Delphi FireMonkey 程序，界面文字以**二进制 TPF0 组件流**存在
PE 的 `RCDATA` 资源里（201 个窗体）。每个字符串值编码为：

```
<属性名> 0x06 <长度:u8> <UTF-8 或 GBK 字节>
```

直接按 `0x06` 扫描字节会**误伤**：某个整数属性的值恰好等于 `6`（=0x06）时，
后面紧跟的属性名会被误当成字符串值并替换，导致属性名被破坏，程序启动时报
`Error reading <组件>.<乱码>: Property <乱码> does not exist`。

因此本工具用三层校验决定一个字符串**能不能改**：

1. `0x06` 前面必须是一个**真实的 DFM 属性名**（长度字节自洽）；
2. 该属性名必须在**属性名词典**里（从 exe 自身统计得出，155 个）；
3. `0x06` 后面的结构必须是**合法结尾或下一个属性**。

只有通过校验的字符串才会被替换；`past5loc check` 会报告哪些词典条目落在
"仅未验证位置"（这些需要显式写进 allow 列表才允许替换）。

---

## 二、MCP 接口（推荐，agent 首选）

配置见 `mcp_config.dsh.yaml`（DSH）和 `mcp_config.generic.json`（通用）。

### 工具清单

| 工具 | 参数 | 返回 |
|---|---|---|
| `past5_list_resources` | `exe`, `only_forms=true` | 资源清单（类型/名称/语言/大小/是否窗体） |
| `past5_extract_strings` | `exe`, `out_path?`, `min_len=2` | `unique`、`occurrences`、`stats`、前 20 条预览 |
| `past5_check_dictionary` | `exe`, `dictionary` | `certified`、`only_unvalidated[]`、`never_seen[]` |
| `past5_build` | `exe`, `dictionary`, `out_path`, `encoding='gbk'`, `allow_list?` | `resources_changed`、`patched`、`blocked_unvalidated` |
| `past5_verify` | `exe` | `form_resources`、`string_tokens`、`structurally_valid`、`localized_tokens` |
| `past5_run_command` | `args[]` | `exit_code`、`output` |

---

## 三、CLI 接口

所有命令输出 **JSON**（便于 agent 解析）。

```bat
python -m past5loc list    <exe> [--json] [--limit N]
python -m past5loc extract <exe> [-o catalog.json]
python -m past5loc check   <exe> <dictionary.json>
python -m past5loc build   <exe> <dictionary.json> -o <out.exe>
                           [--encoding gbk|utf-8] [--allow allow.json] [--pad]
python -m past5loc verify  <exe>
python -m past5loc serve   [--host 127.0.0.1] [--port 8765]
python -m past5loc mcp
```

`--pad`：等长模式。译文短于原文时用空格补齐，流内**零位移**，最保守。

---

## 四、HTTP API

```bat
python -m past5loc serve --port 8765
```

| 方法 | 路径 | body |
|---|---|---|
| GET | `/health` | — |
| POST | `/list_resources` | `{exe, only_forms?}` |
| POST | `/extract_strings` | `{exe, out_path?, min_len?, include_strings?}` |
| POST | `/check_dictionary` | `{exe, dictionary}` |
| POST | `/build` | `{exe, dictionary, out_path, encoding?, allow_list?}` |
| POST | `/verify` | `{exe}` |

示例：

```bash
curl -s -X POST http://127.0.0.1:8765/verify -H "Content-Type: application/json" \
     -d '{"exe":"D:/out/Past5_zh-CN.exe"}'
```

---

## 五、Python 库

```python
from past5loc.pe import PEFile
from past5loc import catalog, builder

# 1) 提取
pe = PEFile.open(r'D:\in\Past5.exe'); pe.read_resources()
data = catalog.extract(pe)          # {'strings': {...}, 'unique': N, ...}

# 2) 覆盖率检查
print(builder.translation_delta(r'D:\in\Past5.exe', 'translations_zh.json'))

# 3) 构建
info = builder.build(r'D:\in\Past5.exe', {'About': '关于'},
                     r'D:\out\Past5_zh-CN.exe',
                     encoding='gbk', allow_unvalidated={'About'})
```

---

## 六、完整工作流（agent 视角）

```
1. past5_verify(原版)                     -> 确认 201 个窗体、6905 个字符串
2. past5_extract_strings(原版)            -> 得到待翻译清单
3. （翻译）产出 translations_zh.json       -> {英文: 中文}
4. past5_check_dictionary(原版, 词典)      -> 看 certified / only_unvalidated
5. 把 only_unvalidated 里确认是 UI 文本的写进 allow_strings.json
6. past5_build(原版, 词典, out, allow)     -> 生成汉化 exe
7. past5_verify(汉化版)                    -> localized_tokens 应显著上升
8. 启动汉化版人工确认
```

---

## 七、关键注意事项

1. **编码**：Past5 的窗体字符串按**系统 ANSI 代码页**解码。简体中文 Windows
   （CP936）必须用 `--encoding gbk`（默认）。写 UTF-8 会显示成乱码。
2. **不要跳过结构校验**：`--allow` 只放"确认是 UI 文本、但落在无法验证位置"的
   字符串，**绝不能**放属性名类字符串（如 `Text`、`Color`、`Value`、`None`），
   否则会破坏属性名并导致启动崩溃。
3. **`--pad` 最安全**：零位移，不会因长度变化影响任何偏移；代价是短译文有尾随
   空格、且译文长于原文的条目会被跳过（保持英文）。
4. **原版不被修改**：`build` 只读原 exe，写出新文件。
5. **单实例**：测试时确保同一时刻只有一个 Past5 实例在运行，多实例会抢配置
   文件造成假崩溃。
6. **校验规则不能过严**：`next_property_ok` 早期版本要求"下一个属性名也必须在
   词典里"，结果把后面跟着低频派生属性（如 `ExplicitSize.cx`——它的兄弟
   `ExplicitSize.cy` 进了词典而它没有）的整批值否决掉，导致 `Plot`(55 处)、
   `Numbers`(44 处)、`Scatter plot`(17 处) 长期未汉化。现在规则是：**右侧结构
   自洽即可**（长度字节自洽 + 全为名字字符 + 后随合法 tag），这一条已足够强。
   改动后词典通过率 1712 → 1845（98.8%），白名单 151 → 19 条。
7. **改过校验规则必须重跑白名单**：`python make_allow.py`，否则
   `allow_strings.json` 与实际判定不一致。
8. **如何自查汉化完整性**：`python audit_zh.py` 会输出"仍为英文的界面文本"并按
   频次排序。注意其中仍会列出大量**约定保持拉丁**的统计指数名
   （Bray-Curtis / Jaccard / Euclidean …）与统计符号（`R2:` `p:` `N:`），
   这些是刻意保留的，不是遗漏。

---

## 八、文件清单

| 文件 | 作用 |
|---|---|
| `past5loc/pe.py` | PE 解析、资源树读写、`.rsrc` 段重建 |
| `past5loc/formstream.py` | TPF0 组件流解析器 |
| `past5loc/validate.py` | 三层结构校验（核心安全机制） |
| `past5loc/props.py` | 属性名词典自动采集 |
| `past5loc/catalog.py` | 字符串提取 |
| `past5loc/builder.py` | 变长/等长替换与构建 |
| `past5loc/cli.py` | CLI 入口 |
| `past5loc/mcp_server.py` | MCP 服务器 |
| `past5loc/http_api.py` | HTTP API 服务器 |
| `translations_zh.json` | 术语表（英文→中文，可手工维护） |
| `allow_strings.json` | 允许在未验证位置替换的白名单 |
| `mcp_config.dsh.yaml` / `mcp_config.generic.json` | MCP 接入配置 |

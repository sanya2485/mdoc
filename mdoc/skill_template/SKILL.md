---
name: mdoc
description: "修复方案文档管理系统 — 查找/创建/更新/删除修复方案参考文档，支持全文搜索、翻页列表、上下文感知。子命令：/mdoc -f（搜索）, /mdoc -l（列表翻页）, /mdoc -c（创建）, /mdoc -u（更新）, /mdoc -d（删除）"
tools: Bash, Read
---

# /mdoc — 修复方案文档管理系统

管理你在各种修复场景下积累的参考文档。文档库位置由 `mdoc` 配置解析，**本 skill 不硬编码任何路径**。

> ⚠️ **一切确定性操作跑 `mdoc` 命令**：列表/搜索/读取/创建/更新/删除/校验都由 `mdoc` CLI 完成（规则锁在代码里），本 skill **不直接 Read/Write/Edit 文档文件**。

---

## 0. 首次使用（建库）

库目录不存在时先建库：

```
mdoc init <你的文档目录>
```

建库会创建目录 + 索引 + 库本地配置 `.mdoc.toml`，并把本 skill 模板写入 `<目录>/SKILL.md`。之后把这份 SKILL.md 放到 Claude Code 可发现的技能目录（用户级 `skills/` 下建 `mdoc/` 子目录，或参考 Claude Code 文档的本机技能位置），即可用下面的斜杠命令。

**库路径解析优先级**：命令行 `--store <dir>` > 环境变量 `MDOC_DIR` > 库本地配置 `<dir>/.mdoc.toml` > 用户配置 `~/.mdoc.toml`（`$MDOC_CONFIG` 可换）> 当前目录向上探测 `.mdoc.toml`。

- 在库目录内运行命令时，`mdoc` 自动发现该库（无需任何配置）。
- 在其它目录运行时，先 `mdoc config --json` 确认 `store_dir` 非空；为空则提示用户 `mdoc init <dir>` 或设置 `MDOC_DIR`。

---

## 1. 存储规范

### 1.1 文档目录（由配置决定）

```
<文档库目录>/
├── <INDEX>.md                       # 实时索引：一行一个文档指针（默认 INDEX.md）
├── <fix-name>.md                    # /mdoc -c 新增的修复方案文档
└── .mdoc.toml                       # 库本地配置（mdoc init 生成）
```

### 1.2 文档分类规则（mdoc 管理范围）

库中只混入 mdoc 自己的文档；`mdoc list`/`mdoc search` 按 `metadata.type: reference` 过滤（排除 `user / feedback / project` 与配置的排除文件）。**计数与列表一律以 `mdoc list` 输出为准，禁止凭记忆或人工数数。**

### 1.3 文档格式（统一 spec，单一事实来源）

每个修复方案文档必须有 frontmatter：

```markdown
---
name: kebab-case-slug
description: 一句话概述修复内容
metadata:
  type: reference        # mdoc 文档统一为 reference
  tags: [关键词]
  blog_ready: false      # 默认 false
  created: YYYY-MM-DD
  style: partial         # 内容风格（§1.5）：sanitized | partial | free
---

## 问题

{问题描述}

## 根因

{根因分析}

## 修复方案

{方案说明}

## 如何应用

{操作步骤}
```

- **未知字段保留**：frontmatter 里的其它字段（如系统写入的额外字段）原样保留，不要求、也不删除。
- **文件名 kebab-case**（core 强制）：英文小写、`-` 连接，可带日期后缀（如 `-20260715`）；纯中文名无法生成 ASCII 文件名时，`doc.json` 里必须提供 `filename`。
- **YAML 安全由 core 保证**：description 等含 `冒号+空格`（如 `修复 502: 网关超时`）的字段自动加引号，无需手工处理。

### 1.4 索引格式

`<INDEX>.md` 每行 `- [文档标题](文件名.md) — 一句话概述`，由 `mdoc` 命令维护（创建/删除/改描述时自动同步），**本 skill 不手工改索引**。

### 1.5 内容风格（轻度可配置）

| style 值 | 名称 | 规则 |
|----------|------|------|
| `sanitized` | 完全脱敏 | 不含任何 `/xxx` API 路径代码，不使用代码/文件路径，只用自然语言说明技术实现 |
| `partial` | 部分脱敏 | 可含 API 路径代码和文件夹代码；涉及 apikey 等敏感字段时用占位符脱敏描述（如 `<API_KEY>`），不写真实密钥 |
| `free` | 完全自由 | 无限制，由作者自行决定详略与脱敏程度 |

- 默认风格取配置 `[style] default`（未配置默认 `partial`）；可用 `[style] overrides` 覆盖规则文字或新增自定义风格。
- `mdoc validate <refname> --style` 用轻启发式查路径/密钥泄漏；写作仍是 LLM 执行。

---

## 2. 命令协议（核心命令）

> 调用形式：`/mdoc` + 参数子命令（空格分隔，如 `/mdoc -u <参考名>`）；裸 `/mdoc` 默认搜索。
> 命令一律跑 `mdoc ...`，解析输出（`--json` 下 stdout 只有一条 JSON）。列表/搜索/读取**直接采用命令输出**，不得自行枚举文件。

### 2.1 裸 `/mdoc` — 默认搜索 + 上下文感知

**行为 = `/mdoc -f`（搜索模式），但增加上下文感知**：判断当前对话是否含明显"修复场景"（刚改代码/配置、刚解决某个问题、刚做排查、讨论方案细节、明确说"记录一下"）。

- 检测到修复场景 → 执行 `/mdoc -f` 搜索后附加提示：`[c] 新建文档 / [u] 补充到已有 / [s] 跳过`
- 未检测到 → 纯搜索（同 `/mdoc -f`）
- 意图不明确时**仅追问一次**

### 2.2 `/mdoc -f <关键词>` — 搜索文档

```
mdoc search <关键词> --json
```

- 匹配范围与排序由 core 决定（索引行 + frontmatter + 正文，`type: reference` 过滤，相关度 + 创建时间倒序）。
- 单条命中 → 用 `mdoc get <refname>` 展示全文；多条 → 列表展示 + 翻页（`--page N`）；无命中 → 引导 `/mdoc -c` 新建。
- 无参数 → 等同 `/mdoc -l`。

### 2.3 `/mdoc -l [页码]` — 列出所有文档

```
mdoc list --json
```

- 直接采用 `total` 与条目（已过滤 + 按 `created` 倒序）。每页最多 10 条，`[n]`/`[p]` 翻页。
- 空列表 → "还没有修复方案文档，用 /mdoc -c 创建第一篇"。

### 2.4 `/mdoc -c <标题>` — 创建新文档

1. 从当前对话提取内容，组装 `doc.json`：

```json
{
  "name": "kebab-case-slug",
  "description": "一句话概述",
  "metadata": { "tags": ["关键词"], "created": "YYYY-MM-DD", "style": "partial" },
  "sections": [
    { "title": "问题", "content": "..." },
    { "title": "根因", "content": "..." },
    { "title": "修复方案", "content": "..." }
  ]
}
```

   - 缺省值：`created` = 今天、`style` = 配置默认、`blog_ready` = `false`、`type` 固定为 `reference`。
   - 纯中文名必须提供 `filename`（kebab-case 覆盖）。

2. **预览（不落盘）**：`mdoc create --stdin --dry-run` 出全文预览。

3. **用户确认**：展示 `文件名 / 标题 / 描述 / 预览内容`，`[y] 确认创建 / [e] 编辑描述 / [c] 取消`。

4. **落盘**：确认后去掉 `--dry-run`：`mdoc create --stdin`。文件 + 索引同步由 core 完成。

5. **冲突**：文件名已存在 → `mdoc create` 退出 1 提示；询问用户覆盖（`--force`）或改用 `/mdoc -u` 追加。

### 2.5 `/mdoc -u <参考名>` — 更新已有文档

1. 确认文档存在（`mdoc get <refname>`）。
2. 用户选择 `[a] 追加 / [o] 替换章节 / [v] 仅查看`。
3. 从对话提取内容，组装 `patch.json`：

```json
{
  "description": "可选：新描述（同步索引行）",
  "ops": [
    { "op": "append", "title": "验证", "content": "..." },
    { "op": "replace", "title": "根因", "content": "新根因" },
    { "op": "delete", "title": "废弃章节" }
  ]
}
```

4. **预览（不落盘）**：`mdoc update <refname> --stdin --dry-run` 出 unified diff。
5. **用户确认** `[y] / [e] / [c]` → 去掉 `--dry-run` 落盘。

> ⚠️ `update` 不改变 `blog_ready`；replace/delete 目标章节不存在会报错退出 1（会提示，不会静默）。`node_type` 等未知 frontmatter 字段保留。

### 2.6 `/mdoc -d <参考名>` — 删除文档/方案

- **删整篇**：`mdoc get <refname>` 展示概要 → 用户输参考名二次确认 → `mdoc delete <refname> --yes`。
- **删章节**：用 `mdoc update <refname> --stdin --dry-run`（`{"ops":[{"op":"delete","title":"章节"}]}`）预览 → 确认后落盘。

---

## 3. 安全与边界规则

| 规则 | 说明 |
|------|------|
| **所有写操作二次确认** | 创建/更新/删除都必须经用户确认后才执行；`--dry-run` 由 CLI 保证预览不落盘 |
| **删除需输名确认** | 删除整篇要求用户输入参考名，防止误删 |
| **只经 `mdoc` 写数据** | 不直接 Write/Edit 文档文件或索引；所有写操作走 `mdoc create/update/delete` |
| **只操作 mdoc 文档** | 默认不操作库目录外的文件（除非用户明确指定） |

**错误恢复**：文件写入失败/索引异常 → 提示错误并建议重试；搜索无结果 → 建议 `/mdoc -c` 新建；命令缺参 → 展示用法。

---

## 4. 命令速查

| 命令 | 用途 | 示例 |
|------|------|------|
| `/mdoc <词>` | 搜索文档（默认行为 + 上下文感知） | `/mdoc nginx` |
| `/mdoc -f <词>` | 搜索文档 | `/mdoc -f 死锁` |
| `/mdoc -l [页码]` | 列表翻页 | `/mdoc -l 2` |
| `/mdoc -c <标题>` | 创建新文档 | `/mdoc -c MySQL 死锁修复` |
| `/mdoc -u <参考名>` | 更新已有文档 | `/mdoc -u mysql-deadlock-fix` |
| `/mdoc -d <参考名>` | 删除文档/方案 | `/mdoc -d mysql-deadlock-fix` |

底层 `mdoc` 命令：`init / config / list / search / get / create / update / delete / slugify / validate`。详情 `mdoc --help`。

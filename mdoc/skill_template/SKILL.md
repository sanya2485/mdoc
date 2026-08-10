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

建库会创建目录 + 索引 + 库本地配置 `.mdoc.toml`，并把本 skill 模板写入 `<目录>/SKILL.md`。之后跑 `mdoc install-skill` 把 skill 装到 Claude Code 技能目录，重启（或 `/reload`）即可用下面的斜杠命令。

**不想手动操作？把下面这段复制给 AI，让它帮你完成建库与技能安装：**

```text
请帮我安装并配置 /mdoc（修复方案文档管理系统）：
1. 执行 `git clone https://github.com/sanya2485/mdoc.git && cd mdoc && pip install -e .` 安装 mdoc 命令；
2. 执行 `mdoc init <我的文档目录>` 建库——自动创建目录、索引、库本地配置 .mdoc.toml，并写入 skill 模板 SKILL.md；
3. 执行 `mdoc install-skill` 把 skill 安装到 Claude Code 技能目录，并告诉我重启 Claude Code（或 /reload）让技能生效。
完成后运行 `mdoc --help` 验证，把命令输出和文档库目录告诉我。
```

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
> ⚠️ **命令输出只有你能看到，用户看不到**：`mdoc` 的 list / search / get 结果**必须把内容（或按模板格式化后的内容）写进你的回复**呈现给用户，不能只停在命令输出就结束回合。
> **`/mdoc --help`（或 `-h`）** → 展示 §4 命令速查表；CLI 细节跑 `mdoc --help` / `mdoc <子命令> --help`。**`/mdoc --version`** → 跑 `mdoc --version`。

### 2.1 裸 `/mdoc` — 默认搜索 + 上下文感知

**行为 = `/mdoc -f`（搜索模式），但增加上下文感知**：判断当前对话是否含明显"修复场景"（刚改代码/配置、刚解决某个问题、刚做排查、讨论方案细节、明确说"记录一下"）。

- 检测到修复场景 → 执行 `/mdoc -f` 搜索后附加提示：`[c] 新建文档 / [u] 补充到已有 / [s] 跳过`
- 未检测到 → 纯搜索（同 `/mdoc -f`）
- 意图不明确时**仅追问一次**（格式：「你的意思是要…？」），追问后按用户回答执行

### 2.2 `/mdoc -f <关键词>` — 搜索文档

```
mdoc search <关键词> --json
```

- 匹配范围与排序由 core 决定（索引行 + frontmatter + 正文，`type: reference` 过滤，相关度 + 创建时间倒序）。
- **自然语言查询**：用户输入口语（如「上次微信是怎么修的」）→ 提取关键词（取名词/专有名词，去停用词，如「微信 修复」）再搜。
- **多关键词**：合并为一个搜索词（引号包裹，如 `mdoc search "MySQL 死锁"`）；`mdoc` 按空白分词做 AND 匹配——每词至少命中一处才返回。
- 单条命中 → 用 `mdoc get <refname>` 拿全文，**并把全文写进回复**呈现给用户（用下面的模板，`{全文}` 处放 `mdoc get` 输出的完整内容）：
  ```
  📋 找到 1 个匹配文档：

  {全文}
  ```
- 多条 → 列表展示 + 翻页（`--page N`），**把命中列表写进回复**：
  ```
  📋 找到 N 个匹配文档（关键词：{关键词}）：

  [1] {参考名}  {创建日期}
      {描述}
      命中: {name/desc/title/body}  {摘要}
  ...
  --- 第 {页}/{总页数} 页 ---
  输入 [n] 翻页 / 输入参考名查看全文 / [q] 退出
  ```
- 无命中 → 引导 `/mdoc -c` 新建：
  ```
  📋 没有找到匹配「{关键词}」的文档。

  💡 要用 /mdoc -c 新建一个修复方案文档吗？
  ```
- 无参数 → 等同 `/mdoc -l`。

### 2.3 `/mdoc -l [页码]` — 列出所有文档

```
mdoc list --json
```

- 直接采用 `total` 与条目（已过滤 + 按 `created` 倒序）。每页最多 10 条，**把列表写进回复**：
  ```
  📚 修复方案文档目录（第 {页}/{总页数} 页，共 {total} 篇）

    {n}  {参考名}  {描述}  {创建日期}  {修改日期}
  ...
  --- 第 {页}/{总页数} 页 ---
  [n] 下一页  [p] 上一页  [q] 退出  输入编号查看详情
  ```
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

> **内容提取质量**：上下文信息不足时，生成已有部分并在预览标注「【信息不足，建议补充】」，由用户决定是否创建后再手动编辑。

### 2.5 `/mdoc -u <参考名>` — 更新已有文档

1. 确认文档存在（`mdoc get <refname>`）。未找到 → 提示，并 `mdoc search <关键词>` 列出相近文档名，建议用 `/mdoc -c` 新建。
2. 用户选择 `[a] 追加 / [o] 替换章节 / [v] 仅查看`（[v] 时用 `mdoc get` 取全文并**写进回复**展示给用户）。
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
> **追加格式**：追加的新方案用独立章节，标题如 `## 方案三：{新方案名称}`（含问题/根因/修复方案等小节）。

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

底层 `mdoc` 命令：`init / install-skill / config / list / search / get / create / update / delete / slugify / validate`。详情 `mdoc --help`。

# mdoc —— 修复方案文档管理系统（core + CLI）

把"修复方案文档"的确定性操作（分类、kebab-case、frontmatter、索引同步、搜索、校验）锁进代码，供 Claude Code skill 驱动。

- **core**（`mdoc/core.py`）：纯逻辑，单一事实来源，零依赖，可单测。
- **CLI**（`mdoc/cli.py`）：core 的薄壳，确定性操作 + `--json` 结构化输出。
- **skill**：LLM 前端，模型驱动 `mdoc` 命令，不直接碰文件。

## 快速开始

```bash
pip install -e .          # 或 python -m mdoc.cli ...
mdoc init ~/my-docs       # 建库：目录 + 索引 + 库本地配置
MDOC_DIR=~/my-docs mdoc list
MDOC_DIR=~/my-docs mdoc search nginx
MDOC_DIR=~/my-docs mdoc validate <refname> --style
```

## 命令

| 命令 | 说明 |
|------|------|
| `mdoc init <dir> [--index INDEX.md]` | 建库 |
| `mdoc config [--json]` | 打印当前配置 |
| `mdoc list [--json] [--names]` | 列出全部 mdoc 文档 |
| `mdoc search <关键词> [--page N] [--json]` | 索引+frontmatter+正文匹配，含过滤与排序 |
| `mdoc get <refname> [--json]` | 查看单篇全文 |
| `mdoc create <doc.json>|--stdin [--dry-run] [--force] [--json]` | 从 doc.json 创建（校验 → 落盘 → 索引同步） |
| `mdoc update <refname> <patch.json>|--stdin [--dry-run] [--json]` | 追加/替换/删除章节 + 描述更新 |
| `mdoc delete <refname> --yes [--json]` | 删文件 + 同步索引（必须显式 `--yes`） |
| `mdoc slugify <标题>` | 标题 → kebab-case |
| `mdoc validate <refname> [--style] [--json]` | frontmatter / `[[wikilink]]` / 内容风格校验 |

`search` / `list` / `get` / `create` / `update` / `delete` / `config` / `validate` 支持 `--store <dir>` 覆盖库路径（优先级：命令行 > `MDOC_DIR` > 配置；`init` 的库目录由位置参数指定，`slugify` 无需库）。

## JSON 中间格式（skill 层组装，CLI 校验落盘）

`mdoc create` / `mdoc update` 走 JSON 中间格式：LLM 从对话提取内容，组装成 doc.json / patch.json，`--dry-run` 出预览（不落盘），用户确认后去掉 `--dry-run` 落盘。**写操作二次确认在 skill 交互层**。

**doc.json（create）**——`sections` 的每个元素渲染为一个 `## 标题` 章节：

```json
{
  "name": "nginx-502-fix",
  "description": "Nginx 502 修复: 网关超时",
  "metadata": {
    "tags": ["nginx", "修复"],
    "blog_ready": false,
    "created": "2026-08-10",
    "style": "partial"
  },
  "sections": [
    { "title": "问题", "content": "502 Bad Gateway" },
    { "title": "根因", "content": "上游超时" },
    { "title": "修复方案", "content": "调大 proxy_read_timeout" }
  ],
  "filename": "optional-kebab-override"
}
```

- 缺省值：`created` = 今天、`style` = 配置默认、`blog_ready` = `false`、`type` 固定为 `reference`
- 文件名：`filename` 覆盖优先（会做 kebab-case 净化），否则 `slugify(name)`；纯中文 name 无法生成文件名时**必须提供 filename**
- schema 不合法 → 列出问题并退出 1，不落盘；文件名冲突 → 退出 1 提示改用 `update` 或 `--force` 覆盖

**patch.json（update）**——`op`：`append`（末尾追加章节）/ `replace`（按标题替换全部同名章节）/ `delete`（按标题删除章节）：

```json
{
  "description": "新描述（更新索引行）",
  "ops": [
    { "op": "append", "title": "验证", "content": "curl 无 502" },
    { "op": "replace", "title": "根因", "content": "新根因" },
    { "op": "delete", "title": "废弃章节" }
  ]
}
```

- `update` 不改变 `blog_ready`（§2.5）；未提供的字段原样保留（含 `node_type` 等未知字段）
- `replace`/`delete` 目标章节不存在 → 报错退出 1（不静默）；描述与现网相同 → 视为无变更，不重写文件/索引
- `--dry-run` 用 unified diff 输出变更预览，绝不落盘

**退出码**：`validate` 0=通过，1=发现问题或文档不存在；其余命令 0=成功，1=错误。`--json` 下 stdout 只有一条 JSON。

## 配置解析优先级

内置默认 < 用户配置（`~/.mdoc.toml`，可用 `$MDOC_CONFIG` 指定）< 库本地配置（`<store>/.mdoc.toml`，`mdoc init` 生成）< `MDOC_DIR` / `--store`。

## 开发

```bash
python -m unittest discover -s tests -v
```

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
| `mdoc delete <refname> --yes [--json]` | 删文件 + 同步索引（必须显式 `--yes`） |
| `mdoc slugify <标题>` | 标题 → kebab-case |
| `mdoc validate <refname> [--style] [--json]` | frontmatter / `[[wikilink]]` / 内容风格校验 |

`search` / `list` / `get` / `delete` / `config` / `validate` 支持 `--store <dir>` 覆盖库路径（优先级：命令行 > `MDOC_DIR` > 配置；`init` 的库目录由位置参数指定，`slugify` 无需库）。

**退出码**：`validate` 0=通过，1=发现问题或文档不存在；其余命令 0=成功，1=错误。`--json` 下 stdout 只有一条 JSON。

## 配置解析优先级

内置默认 < 用户配置（`~/.mdoc.toml`，可用 `$MDOC_CONFIG` 指定）< 库本地配置（`<store>/.mdoc.toml`，`mdoc init` 生成）< `MDOC_DIR` / `--store`。

## 开发

```bash
python -m unittest discover -s tests -v
```

# mdoc —— 修复方案文档管理系统

每次修好一个问题，用 `/mdoc` 记一篇「问题 / 根因 / 方案」，下次遇到同样的坑，一搜就找回来。格式、分类、索引全部自动整理，你不用管。

## 它做什么

- **记**：跟 Claude 说「记一下这次修复」，它自动从对话里整理成文档。
- **找**：`/mdoc nginx` 一搜，以前的修复全出来。
- **存**：文档是普通 Markdown，存在你自己的目录，随时能打开看。

> 📖 想 10 分钟上手，看 [快速入门（docs/quickstart.md）](docs/quickstart.md)。

## 快速开始（约 5 分钟）

需要：Python 3.10+、Claude Code。

**① 安装命令**

```bash
git clone https://github.com/sanya2485/mdoc.git
cd mdoc
pip install -e .
```

**② 建库**

```bash
mdoc init ~/mdoc-docs
```

这一步自动建好文档目录、索引和配置，并生成 skill 模板 `~/mdoc-docs/SKILL.md`。

**③ 启用斜杠命令**

```bash
mdoc install-skill
```

这一步把 skill 模板安装到 Claude Code 的技能目录 `~/.claude/skills/mdoc/`。重启 Claude Code（或 `/reload`）后就能用 `/mdoc` 了。以后想更新到最新模板，`mdoc install-skill --force` 即可。

> 只想用终端命令、不想装斜杠命令？跳过第 ③ 步，`cd ~/mdoc-docs` 后直接 `mdoc list` / `mdoc search xxx`。

### 不想手动敲？把这段复制给 AI

```text
请帮我安装并配置 /mdoc（修复方案文档管理系统）：
1. 执行 `git clone https://github.com/sanya2485/mdoc.git && cd mdoc && pip install -e .` 安装 mdoc 命令；
2. 执行 `mdoc init <我的文档目录>` 建库——自动创建文档目录、索引、配置 .mdoc.toml，并写入 skill 模板 SKILL.md；
3. 执行 `mdoc install-skill` 把 skill 安装到 Claude Code 技能目录（~/.claude/skills/mdoc/），并告诉我重启 Claude Code（或 /reload）让技能生效。
完成后运行 `mdoc --help` 验证，把命令输出和文档库目录告诉我。
```

> 提示词里的 `<我的文档目录>` 换成你自己的路径，例如 `~/mdoc-docs`。

## 常用命令

| 你打 | 它做 |
|------|------|
| `/mdoc <词>` | 搜索文档（刚修完问题会自动提醒你记录） |
| `/mdoc -f <词>` | 搜索文档 |
| `/mdoc -l` | 列出全部文档 |
| `/mdoc -c <标题>` | 新建文档 |
| `/mdoc -u <参考名>` | 更新文档（追加 / 替换 / 删章节） |
| `/mdoc -d <参考名>` | 删除文档 |
| `/mdoc --help` | 命令速查 |

不装斜杠命令也能用，底层 `mdoc` 命令：`init`（建库）、`install-skill`（装斜杠命令到 Claude Code）、`list`（列表）、`search`（搜索）、`get`（看全文）、`create` / `update` / `delete`（增删改）、`validate`（校验）、`config`（看配置）。

> 写操作都是「先预览、你确认、再落盘」；删整篇还要你输入文档名二次确认，不会误删。

## 文档长什么样

每篇修复文档就是一个 Markdown 文件，开头一段 frontmatter 记录元信息（标题、日期、标签等），正文是「问题 / 根因 / 方案」等小节。格式规则都锁在代码里，`mdoc` 自动管理——你不会记乱，多台机器行为也一致。

## 给维护者 / 开发者

- **作者分发渠道（私有 PyPI，非公开）**：仅维护者多机分发用（认证防陌生访问、减流量），不对外注册。一般用户忽略本节：

  ```bash
  # 有账密时安装：<USER>/<PASSWORD> 换成实际账密
  pip install --index-url "https://<USER>:<PASSWORD>@www.sanyablog.cn/pypi/simple/" mdoc

  # 发布新版本
  twine upload --repository-url https://www.sanyablog.cn/pypi/ dist/*.whl
  ```

  真实账密由管理员线下分发（本仓库 `secrets/` 存一份，`.gitignore` 排除，**不入 git**）；文档里一律用 `<PASSWORD>` 占位。

- **JSON 中间格式**：`create` / `update` 通过 JSON 交互（skill 组装、CLI 校验），`--dry-run` 先预览不落盘。完整说明见 [快速入门](docs/quickstart.md) 与设计文档 `mdoc-mcp-refactor-plan.md`。

- **配置解析优先级**：内置默认 < 用户配置 `~/.mdoc.toml` < 库本地配置 `<store>/.mdoc.toml` < `MDOC_DIR` / `--store`。

- **跑测试**：

  ```bash
  python -m unittest discover -s tests -v
  ```

## License

MIT

# 快速入门 /mdoc —— 修复方案文档管理系统

面向第一次用 `/mdoc` 的 Claude Code 用户。10 分钟跑通：装好 → 建库 → 用斜杠命令记录一条修复方案 → 下次搜得到。

---

## 1. 它是什么

`/mdoc` 帮你把零散的修复过程沉淀成**可检索的参考文档**：

- 记录「问题 / 根因 / 修复方案」——下次遇到同样问题，`/mdoc -f` 一搜就有。
- 文档格式、索引、分类、搜索的**规则锁在代码里**（`mdoc` CLI + core），skill 只负责听你说、组内容、跑命令。不会记乱，也不会漏。

一套工具 = 一个 pip 包（`mdoc` 命令）+ 一个 skill（`/mdoc` 斜杠命令）。**各人用各人的文档库**，互不干扰。

## 2. 三步装上

```bash
# ① 安装命令（拿到 wheel 后）
pip install dist/mdoc-0.1.0-py3-none-any.whl

# ② 建库：目录 + 索引 + 配置 + skill 模板 SKILL.md 一次到位
mdoc init ~/mdoc-docs

# ③ 把 SKILL.md 放到 Claude Code 能发现的技能目录
#    用户级 skills/ 下建 mdoc/ 子目录，把 ~/mdoc-docs/SKILL.md 复制进去
#    然后重启 Claude Code（或 /reload），/mdoc 就能用了
```

> 不想要斜杠命令，只想在终端用 `mdoc` 命令也一样，见 §5。

## 3. 一条命令一次搜索

在库目录内（`cd ~/mdoc-docs`）运行，`mdoc` 自动发现该库，**不用配任何环境变量**。

| 你打 | 它做 |
|------|------|
| `/mdoc 关键词` | 搜索（默认行为，带上下文感知） |
| `/mdoc -f 关键词` | 搜索文档 |
| `/mdoc -l` | 列出全部文档（翻页） |
| `/mdoc -c 标题` | 创建新文档 |
| `/mdoc -u 参考名` | 更新已有文档 |
| `/mdoc -d 参考名` | 删除文档 |
| `/mdoc --help` | 命令速查（`-h` 同） |

> 注意：参数子命令是**空格分隔**的（`/mdoc -u`），不是 `/mdoc-u`。

## 4. 记一条修复方案（示例）

刚修好一个 Nginx 502，想记下来：

1. 打 `/mdoc -c Nginx 502 修复`。
2. Claude 会从当前对话提取内容，先给你**预览**（`--dry-run`，不落盘）：

   ```
   [dry-run] 将创建：nginx-502-fix.md（参考名 nginx-502-fix，风格 partial）
   --- 预览 ---
   ## 问题
   502 Bad Gateway
   ## 根因
   上游超时
   ## 修复方案
   调大 proxy_read_timeout
   --- 预览结束（--dry-run 未落盘）---
   ```

3. 确认没问题，回 `[y]` → 落盘 + 索引同步。
4. 下次遇到类似问题，`/mdoc -f 502` → 命中，`mdoc get nginx-502-fix` 看全文。

**写操作都有二次确认**：预览 → 你确认 → 才落盘。删除整篇还要你输参考名确认，不会误删。

## 5. 纯命令方式（可选）

不想装 skill，直接在终端管理库：

```bash
mdoc init ~/mdoc-docs
cd ~/mdoc-docs                      # 库目录内，自动发现
mdoc list                           # TOTAL=11 之类
mdoc search nginx
mdoc get nginx-502-fix
```

不在库目录里时，指定库：`mdoc --store ~/mdoc-docs list`，或设一次环境变量 `MDOC_DIR=~/mdoc-docs`。

## 6. 配置（可选）

- 库本地配置 `~/mdoc-docs/.mdoc.toml`（`mdoc init` 生成）：改索引文件名、排除项、默认风格等。
- 用户配置 `~/.mdoc.toml`：设置你自己的默认库，所有目录都生效（`$MDOC_CONFIG` 可换路径）。
- **库路径解析优先级**：`--store <dir>` > `MDOC_DIR` > 当前目录向上发现 `.mdoc.toml` > 用户配置 > 未配置。

## 7. 文档风格（记之前心里有数）

frontmatter 里 `metadata.style` 决定脱敏程度，默认 `partial`：

| style | 规则 |
|-------|------|
| `sanitized` | 完全脱敏：不用代码/文件路径，只用自然语言 |
| `partial` | 部分脱敏：可含路径，敏感字段用 `<API_KEY>` 占位 |
| `free` | 自由，自己定 |

`mdoc validate <参考名> --style` 能查有没有把密钥/路径泄进去。

## 8. 调用流程（一条命令怎么跑起来）

```
你输入 /mdoc -f 502
   │
   ▼
① Claude Code 命中 mdoc 技能（SKILL.md）
   技能是 LLM 指令层：解析意图（-f 搜索 / -l 列表 / -c 创建 / -u 更新 / -d 删除）；
   裸 /mdoc = 搜索 + 上下文感知（检测到修复场景 → 提示归档）
   │
   ▼
② 技能决定跑哪些确定性命令（Bash，必要时 --json）：
   mdoc search / list / get / create / update / delete ...
   │
   ▼
③ mdoc CLI（薄壳）：解析参数 → 调 core → 输出（--json 下 stdout 只有一条 JSON）
   │
   ▼
④ core（规则唯一写入方）：
   解析库路径（--store > MDOC_DIR > 当前目录向上发现 > 用户配置）
   → 读写库文件：frontmatter / kebab-case / 索引同步 / 搜索排序 / 校验
   │
   ▼
⑤ 库文件：<store>/*.md + <store>/<INDEX>.md + <store>/.mdoc.toml
   │
   ▼
⑥ 结果回传 → 技能格式化呈现给你
```

**写操作（create / update / delete）固定双段式**：`--dry-run` 预览（不落盘）→ 你确认 → 去掉 `--dry-run` 落盘。

**一句话**：skill 只负责「听懂你 + 组内容 + 跑命令」，规则和写文件全在 mdoc 代码里——格式永远不会乱，多台机器行为一致，这也是它能打包分发给陌生人的原因。

## 9. 更多

- `mdoc --help`：全部命令。
- 文档格式规范：库里的 `SKILL.md` §1（frontmatter 字段、kebab-case 文件名、YAML 安全由 core 保证）。
- 底层：确定性操作全在 `mdoc` CLI，skill 不直接改文件——所以规则永远一致。

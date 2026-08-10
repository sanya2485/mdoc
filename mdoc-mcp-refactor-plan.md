# /mdoc 脚本化改造方案（定稿：单 core + CLI）

> 目标：把 /mdoc 的确定性操作下沉为 **core + CLI**，打包分发，供他人（Claude Code 用户）安装到各自机器、管理各自的修复方案文档。
> 状态：**方案已定稿**（2026-08-10）· 改造进行中（阶段 1 配置层 ✅；阶段 2 CLI 骨架 ✅，已 code-review）
> 关键取舍：CLI+skills vs MCP 的讨论结论是「**单 core + CLI，MCP 后置**」

---

## 0. 结论摘要

- **形态**：分发他人，**各用各的库**。公共的是"工具 + 文档规范"，数据永远各自私有。
- **受众**：Claude Code 用户，第一动作是 `/mdoc-f xxx` → **skill 是产品前门**，不是附赠品。
- **架构**：`core`（规则单一事实来源）→ `CLI`（确定性操作）→ `skill`（LLM 前端，驱动 CLI）。
- **不做 MCP**：各用各的库 = 本地数据，用不上远程/HTTP。MCP 在这个受众下只剩"工具调用体验"这一个锦上添花，现阶段收益有限，**后置**。若将来真出现"多机共享一份库"或"多客户端"，在同一个 core 上再套一层 MCP 适配壳即可。
- **规则必须进代码**：分类、kebab-case、schema、索引同步锁进 core。提示词是软约束、每份安装是死副本——靠陌生人的模型自觉会漂移，且无法批量更新/验证。

---

## 1. 决策记录（2026-08-10 讨论收敛）

| 维度 | 结论 |
|------|------|
| 使用场景 | 分发他人，各用各的库（形态 B） |
| 受众 | Claude Code 用户（`/mdoc-f` slash command） |
| 架构 | 单 core + CLI，MCP 后置 |
| 数据归属 | 本地私有，每机一个库 |
| 分发形态 | pip 包（core + CLI）+ 通用 skill 模板 |
| 公共边界 | 文档管理内核进包；auto-memory 绑定 / blog-pipeline / 个人 subagent 是外挂 |

---

## 2. 现状基线（功能确认 2026-08-10）

改造前确认现有功能可用，建立基线。

### 2.1 正常工作的项 ✅

| 项 | 验证结果 |
|----|---------|
| `list.py` 列表 + 计数 | `TOTAL=10`，按 created 倒序 ✅ |
| `list.py --names` | 脚本消费格式（每行一个参考名）✅ |
| 分类规则 §1.2 | `mdoc-skill-redesign`（type: project）正确排除；`windows-environment.md`（排除项）正确排除 ✅ |
| MEMORY.md 索引 vs 计数 | 12 行索引 vs 10 篇 mdoc 文档，差值 = 2 个非 mdoc 文档 ✅ |
| 搜索路径 | 索引行 + 正文均可命中（"nginx" 命中 7 篇）✅ |
| YAML 安全 §3.4 | 描述含 `:` 已被引号包裹，list.py 解析正确 ✅ |

### 2.2 发现的问题 ⚠️

1. **`coze-chat-theme-zindex.md` 缺 `created` 字段** → 列表显示 `0000-00-00` 排最后，不符合 spec，建议补 `created: 2026-08-06`。
2. **搜索是否过滤非 mdoc 文档，规范未写明**：SKILL.md §2.2 搜索实现没引用 §1.2 的排除规则。实测搜"微信"会命中 project 型/环境文档。**脚本化时把过滤逻辑写死**——这正是代码层存在的意义。

---

## 3. 目标架构

```
┌───────────────────────────────────────┐
│  skill（/mdoc，LLM 前端）               │
│  上下文感知 / 内容提取 / 确认流程        │
│  —— 模型驱动 `mdoc` 命令，不直接碰文件  │
└───────────────────┬───────────────────┘
                    │ 命令行调用（--json 结构化）
┌───────────────────▼───────────────────┐
│  CLI（mdoc 命令）                      │
│  search / list / get / create /       │
│  update / delete / slugify / validate │
│  / init / config                       │
│  —— 确定性操作，规则锁在代码里          │
└───────────────────┬───────────────────┘
                    │ 唯一数据写入方
┌───────────────────▼───────────────────┐
│  core（mdoclib）                       │
│  分类规则 / kebab-case / frontmatter   │
│  schema / 索引同步                     │
│  —— 单一事实来源，可单测               │
└───────────────────┬───────────────────┘
                    ▼
         每机本地文档库（各自私有）
```

**分层原则**：
- **core**：纯逻辑，无 I/O 调用方式假设，可单测。
- **CLI**：core 的薄壳 + 人类/脚本界面，`--json` 输出供 skill 消费。
- **skill**：只做模型判断性工作，所有落盘/读取走 `mdoc` 命令，不 Read/Write/Edit 文档文件。
- **路径零硬编码**：库路径由 `mdoc init` 写入配置（config 文件或 `MDOC_DIR` 环境变量），skill 模板不出现任何机器路径。

---

## 4. CLI 命令面设计

| 命令 | 对应 | 说明 |
|------|------|------|
| `mdoc init <dir>` | — | 建库：创建目录 + 索引 + 写配置 |
| `mdoc search <关键词> [--page N] [--json]` | `/mdoc-f` | 索引+frontmatter+正文匹配 → 排序 → **含过滤** |
| `mdoc list [--json]` | `/mdoc-l` | 复用现有 list.py 逻辑 |
| `mdoc get <refname>` | 查看单篇 | 输出全文 |
| `mdoc create <doc.json> [--dry-run]` | `/mdoc-c` 落盘 | 校验 schema → 生成 kebab-case 文件名 → 写盘 → 同步索引 → 出预览 |
| `mdoc update <refname> <patch.json> [--dry-run]` | `/mdoc-u` 落盘 | 追加/替换章节 + 索引同步 |
| `mdoc delete <refname> --yes` | `/mdoc-d` 落盘 | 删文件 + 清理索引 |
| `mdoc slugify <标题>` | — | kebab-case 转换 |
| `mdoc validate <refname>` | doc-validator 确定性项 | 路径/`[[wikilink]]`/命令存在性 |
| `mdoc config` | — | 打印当前库路径与配置 |

**skill 侧的 create/update 流程**：LLM 从对话提取 → 组装 `doc.json`（sections + metadata）→ `mdoc create --stdin --dry-run` 出预览 → 用户确认 → 去掉 `--dry-run` 落盘。**所有写操作二次确认在 skill 交互层**，CLI 的 `--dry-run` 保证预览不落盘。

**validate 确定性边界**（阶段 2 定稿）：frontmatter 完整性 + `[[wikilink]]` 可达性 + `--style` 风格校验进 CLI；"路径/命令存在性"依赖读者机器的真实环境、无法在任意库上确定性判定，归 doc-validator LLM 语义审查（Tier 2），不进 CLI。

**配置解析优先级**：命令行 flag > 环境变量 `MDOC_DIR` > 配置文件（`mdoc init` 生成）。

---

## 5. 脚本化切分（三档）

### Tier 1 — 纯确定性 ✅（全部进 CLI）
搜索、列表/计数、读取、删除、kebab-case、索引同步、validator 的确定性项。

### Tier 2 — 混合 🟡（LLM 提取 + CLI 落盘）
- `/mdoc-c` / `/mdoc-u`：LLM 从对话提取 → `doc.json` → CLI 校验 + 落盘 + 索引同步 + 出 diff 预览。
- validator 语义项（"代码与实际文件一致"）留给 LLM 判断。

### Tier 3 — 纯 LLM ❌（不进 CLI）
上下文感知、从对话提取内容、`blog_ready` 判定、博客改写/去敏。

---

## 6. 公共边界（进包 vs 外挂）

**进公共包（通用能力）**：文档格式规范 + 校验、search/list/get/create/update/delete/索引同步、`mdoc init`、通用 skill 模板。

**不进包（个人胶水）**：Claude **auto-memory 目录**绑定（陌生人用 `mdoc init` 指向任意目录）、**blog-pipeline / blog_ready / myFireflyBlog**、三个个人 subagent（mdoc-archiver / doc-validator / blog-publisher）。

---

## 7. 改造步骤（分阶段，每步可独立验收）

### 阶段 1 — 抽共享核心 `mdoc_core.py`
- 分类规则、kebab-case、frontmatter 读写、索引同步写成模块；`list.py` 改用它。
- **验收**：`list.py` 输出与改造前逐字一致（TOTAL=10 不变）。

### 阶段 2 — 建 CLI 骨架 + 确定性命令
- `mdoc init/config/search/get/delete/slugify/validate`，`--json` 输出。
- SKILL.md 命令协议改为"先跑 `mdoc` 命令、再展示"。
- **验收**：`mdoc search nginx` 与预期一致；删除流程走 `mdoc delete` 后索引同步正确。

**✅ 已完成**（2026-08-10，含 code-review 修复）：包落在 `Desktop/mdoc/`（`pyproject.toml` + `mdoc/{core,cli}.py` + `tests/`，53 单测零依赖全绿）。命令全带 `--json`；搜索含 §1.2 过滤与确定性排序；`delete` 走 `core.delete_doc`（删文件 + 索引同步，满足 §3"core 唯一数据写入方"）；`validate --style` 调 `check_style_violations`；配置解析支持库本地 `.mdoc.toml`。SKILL.md 命令协议切换与 skill 迁移到阶段 4（打包安装后，避免改坏现网技能）。

### 阶段 3 — create/update 走 JSON 中间格式
- `mdoc create/update --stdin --dry-run`，LLM 提取 → JSON → 落盘。
- **验收**：文档结构 100% 符合 spec，索引与文件同步无误。

### 阶段 4 — 打包 + 通用 skill 模板
- `pyproject.toml` 打包，`mdoc init` 引导；skill 模板参数化（零硬编码路径）。
- **验收**：在一台"陌生"机器（临时目录）走通 init → 建库 → 搜索 → 删除全流程。

### 阶段 5 —（后置，不阻塞）MCP 适配层
- 真出现多机共享/多客户端需求时，在 core 上套一层 MCP stdio adapter，skill 加"有 tools 用 tools、没有退 CLI"。

---

## 8. 待决策点（剩余）

| # | 决策 | 现状 |
|---|------|------|
| 1 | 分发形态 | 已定：pip 包 + skill 模板 |
| 2 | 索引文件名 | ✅ 已解决（阶段 2）：core 支持可配置 `index_file`；`mdoc init` 公共默认 `INDEX.md`，个人配置保留 `MEMORY.md` |
| 3 | 是否发布到 PyPI | 待定：先本地打包，验证后再决定 |
| 4 | skill 模板的 skill 命名/命令协议 | 待定：阶段 4 时细化 |

---

## 9. 风险

| 风险 | 缓解 |
|------|------|
| 规则下沉为代码后行为漂移 | 阶段 1-2 每步回归验证 list.py / search 输出一致 |
| 分发后各机器格式漂移 | 规则锁进 core，create/validate 在落盘时强制 |
| 路径硬编码泄漏进包 | core 全用配置解析，skill 模板零路径 |
| 现网文档（coze-chat-theme-zindex 缺 created） | 改造前顺手补字段 |

---

## 10. 内容风格系统（2026-08-10 新增需求）

用户可轻度定义文档内容风格，内置三种默认风格：

| style 值 | 名称 | 规则 |
|----------|------|------|
| `sanitized` | 完全脱敏 | 不含任何 `/xxx` API 路径代码，不使用代码/文件路径，只用自然语言说明技术实现 |
| `partial` | 部分脱敏 | 可含 API 路径代码和文件夹代码；涉及 apikey 等敏感文件/字段时脱敏描述 |
| `free` | 完全自由 | 无限制，作者自行决定 |

**设计原则**：判定/校验是确定性逻辑（进 core），写作应用是 LLM 指令（skill §1.5）。

- 配置：`~/.mdoc.toml` `[style] default`（`sanitized`/`partial`/`free`，未配置默认 `partial`）+ `[style] overrides`（覆盖规则文字或新增自定义风格）
- 每篇文档 frontmatter 记录 `metadata.style`；缺省按配置默认
- 确定性校验：`mdoc_core.check_style_violations()` —— `sanitized` 查路径泄漏（`/a/b` 形态）、`sanitized`/`partial` 查密钥疑似泄漏（`api_key=真实值`），供 `mdoc validate --style` 调用
- 现有文档缺 `style` 字段 → 按配置默认 `partial` 处理（贴合现状）

**已实现**（2026-08-10）：core 的 `STYLE_PRESETS` / `load_style` / `resolve_style` / `style_rule` / `check_style_violations`；config 解析 `[style]` 段；SKILL.md §1.3/§1.5/§2.4；`~/.mdoc.toml` 已配置默认 `partial`。

---

## 附：功能确认操作记录

- 运行 `list.py` → `TOTAL=10` ✅；`list.py --names` → 10 个参考名 ✅
- 核对 `mdoc-skill-redesign.md`（project）与 `windows-environment.md` → 正确排除 ✅
- 模拟搜索 "nginx" → 索引+正文双路径命中 ✅；搜 "微信" → 命中非 mdoc 文档（暴露 §2.2 过滤缺口）⚠️
- 检查 `coze-chat-theme-zindex.md` frontmatter → 缺 `created` ⚠️（已补 `created: 2026-08-06`）

### 阶段 2 验证记录（2026-08-10）

- 53/53 单测全绿（`unittest`，零依赖；覆盖 config/search/索引同步/slugify/style/validate/init + CLI 端到端）
- 真实库回归：`mdoc list` TOTAL=10 不变；`mdoc search nginx` 命中 7 篇（含 §1.2 过滤，非 mdoc 不再混入）；desc 引号已剥离
- 临时库端到端：init → search → `validate --style`（sanitized 路径 + 密钥泄漏检出）→ `delete --yes` 索引同步 ✅
- code-review（两轴并行）：Standards 1 硬违反（delete 在 CLI 直接 unlink，绕过 core 唯一数据写入方）→ 已下沉 `core.delete_doc`；Spec 3 处缺口 → 已修（`init --json` / `init_store` 幂等不覆盖 / README 越界 `create` 与 `--store` 声明不符）；若干判断项（`_known_docs` 消解别名重复、索引改写助手、单版本源）已顺手落实

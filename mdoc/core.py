#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mdoc 核心模块 —— 确定性规则的单一事实来源。

分层：core（本模块，纯逻辑）→ CLI（mdoc.cli，薄壳）→ skill（LLM 前端）。
规则锁进代码、不依赖提示词（对应 /mdoc SKILL.md §1.2 / §1.3 / §1.5）。
零机器路径硬编码：库路径一律来自配置或环境变量。

配置解析优先级（后者覆盖前者）：
  内置默认 < 用户配置（~/.mdoc.toml，可用 $MDOC_CONFIG 指定）
  < 当前目录向上探测 .mdoc.toml（陌生机 fallback，未配置时免设 MDOC_DIR）
  < 库本地配置（<store_dir>/.mdoc.toml，mdoc init 生成）
  < 环境变量 MDOC_DIR / 命令行 --store
"""

import json
import os
import re
import time
import tomllib
from pathlib import Path

# --- 内置默认 ---
DEFAULT_INDEX_FILE = "MEMORY.md"        # 兼容个人现状；mdoc init 默认 INDEX.md
DEFAULT_REFERENCE_TYPE = "reference"
DEFAULT_EXCLUDED_TYPES = ["user", "feedback", "project"]
DEFAULT_EXCLUDED_FILES = []
DEFAULT_STYLE_DEFAULT = "partial"
DEFAULT_STORE_DIR = ""                  # 公共包不硬编码个人库路径

_CONFIG_KEYS = ("store_dir", "index_file")
_CLASS_KEYS = ("reference_type", "excluded_types", "excluded_files")
_STYLE_KEYS = ("default", "overrides")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def user_config_path() -> Path:
    """用户配置位置：$MDOC_CONFIG 优先，否则用户主目录 ~/.mdoc.toml。"""
    env = os.environ.get("MDOC_CONFIG")
    return Path(env) if env else Path(os.path.expanduser("~")) / ".mdoc.toml"


def store_config_path(store_dir) -> Path:
    """库本地配置位置：<store_dir>/.mdoc.toml（mdoc init 生成）。"""
    return Path(store_dir) / ".mdoc.toml"


def _merge_toml(cfg, path):
    """把一份配置文件合并进 cfg；文件缺失或损坏则忽略。"""
    p = Path(path)
    if not p.is_file():
        return
    try:
        with open(p, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return
    for k in _CONFIG_KEYS:
        if k in data:
            cfg[k] = data[k]
    cls = data.get("classification") or {}
    for k in _CLASS_KEYS:
        if k in cls:
            cfg[k] = cls[k]
    style = data.get("style") or {}
    for k in _STYLE_KEYS:
        if k in style:
            cfg["style_" + k] = style[k]


def _find_cwd_store() -> str:
    """当前工作目录向上探测 `.mdoc.toml`（最多 5 层，到用户主目录即停）。命中返回其所在目录，否则空串。

    陌生机 fallback：用户配置 / MDOC_DIR / --store 均未给出 store_dir 时，
    在库目录内运行命令即可免配置（SKILL.md §0）。
    到 home 即停：`~/.mdoc.toml` 是用户配置（含 store_dir 指向别处），不是库标记，
    不设防会把 home 误当库。"""
    d = Path.cwd().resolve()
    home = Path(os.path.expanduser("~")).resolve()
    for _ in range(5):
        if d == home:
            break
        if (d / ".mdoc.toml").is_file():
            return str(d)
        if d.parent == d:
            break
        d = d.parent
    return ""


def load_config(store_override=None) -> dict:
    """合并配置：默认 < 用户配置 < cwd 发现（库本地） < env/CLI。

    store_dir 解析：--store > MDOC_DIR > 当前目录向上发现的库（.mdoc.toml）
    > 用户配置 ~/.mdoc.toml > 未配置。库目录内的调用优先于用户默认库——
    否则陌生库目录里跑命令会被 ~/.mdoc.toml 的默认库劫持。"""
    cfg = {
        "store_dir": DEFAULT_STORE_DIR,
        "index_file": DEFAULT_INDEX_FILE,
        "reference_type": DEFAULT_REFERENCE_TYPE,
        "excluded_types": list(DEFAULT_EXCLUDED_TYPES),
        "excluded_files": list(DEFAULT_EXCLUDED_FILES),
        "style_default": DEFAULT_STYLE_DEFAULT,
        "style_overrides": {},
    }
    _merge_toml(cfg, user_config_path())
    store_dir = (
        store_override
        or os.environ.get("MDOC_DIR")
        or _find_cwd_store()
        or cfg.get("store_dir")
        or ""
    )
    cfg["store_dir"] = store_dir
    if store_dir:
        _merge_toml(cfg, store_config_path(store_dir))
        cfg["store_dir"] = store_dir  # 库本地配置里即使写了 store_dir 也以解析结果为准
    return cfg


# ---------------------------------------------------------------------------
# frontmatter 与分类（§1.2 / §1.3）
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A\s*---\s*\n(.*?)\n---", re.DOTALL)
_SCALAR_KEYS = ("type", "name", "description", "created", "blog_ready", "style")


def _strip_yaml_quotes(v):
    """剥掉标量值首尾成对的引号（YAML 里含 `:` 的描述会被引号包裹）。"""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_frontmatter(text) -> dict:
    """提取 frontmatter 标量字段（容忍 YAML 缩进 / 内联 / 嵌套 metadata 块）。"""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fields = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^\s*([A-Za-z0-9_]+):\s*(.*?)\s*$", line)
        if mm:
            key, val = mm.group(1), mm.group(2)
            if key in _SCALAR_KEYS:
                fields[key] = _strip_yaml_quotes(val)
    return fields


def is_mdoc_doc(fm, cfg) -> bool:
    """§1.2 判定：非排除类型 + 必须为 reference 类型。"""
    if not fm:
        return False
    if fm.get("type") in set(cfg["excluded_types"]):
        return False
    return fm.get("type") == cfg["reference_type"]


def load_docs(cfg) -> list:
    """枚举 store_dir 下所有 mdoc 文档（§1.2 判定），按 created 倒序。"""
    store_dir = Path(cfg["store_dir"])
    excluded_files = set(cfg["excluded_files"])
    docs = []
    if not store_dir.is_dir():
        return docs
    for fn in sorted(os.listdir(store_dir)):
        if not fn.endswith(".md") or fn in excluded_files:
            continue
        path = store_dir / fn
        with open(path, encoding="utf-8") as f:
            fm = parse_frontmatter(f.read())
        if not is_mdoc_doc(fm, cfg):
            continue
        docs.append(
            {
                "name": _display_name(fm, fn),
                "desc": fm.get("description") or "",
                "created": fm.get("created") or "0000-00-00",
                "mtime": time.strftime(
                    "%Y-%m-%d", time.localtime(os.path.getmtime(path))
                ),
                "file": fn,
            }
        )
    docs.sort(key=lambda d: d["created"], reverse=True)
    return docs


def _display_name(fm, file):
    """文档显示名：frontmatter name 优先，缺省用文件名（去 .md）。"""
    return fm.get("name") or file[:-3]


def _known_docs(cfg) -> dict:
    """参考名 / 文件名 / 去后缀名 三类别名 → 文件名的映射（resolve_ref 与 wikilink 校验共用）。"""
    known = {}
    for d in load_docs(cfg):
        known[d["name"].lower()] = d["file"]
        known[d["file"].lower()] = d["file"]
        known[d["file"][:-3].lower()] = d["file"]
    return known


def resolve_ref(cfg, refname):
    """refname → 文件名：文件名 / 参考名（均不区分大小写）。未找到返回 None。"""
    return _known_docs(cfg).get(refname.strip().lower())


def read_doc(cfg, refname) -> dict:
    """读取单篇全文。返回 {file, name, fm, text, path}；未找到抛 FileNotFoundError。"""
    file = resolve_ref(cfg, refname)
    if not file:
        raise FileNotFoundError(f"未找到文档：{refname}")
    path = Path(cfg["store_dir"]) / file
    text = path.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    return {"file": file, "name": _display_name(fm, file), "fm": fm, "text": text, "path": str(path)}


def delete_doc(cfg, refname) -> dict:
    """删除单篇并同步索引（core 内完成，保持一致性）。返回 {deleted, name}；未找到抛 FileNotFoundError。"""
    doc = read_doc(cfg, refname)
    Path(doc["path"]).unlink()
    remove_index_entry(cfg, doc["file"])
    return {"deleted": doc["file"], "name": doc["name"]}


# ---------------------------------------------------------------------------
# 索引同步（MEMORY.md / INDEX.md）
# ---------------------------------------------------------------------------

_INDEX_LINE_RE = re.compile(r"^\s*-\s*\[([^\]]+)\]\(([^)]+\.md)\)(?:\s*[—-]\s*(.*))?\s*$")


def _read_index_lines(cfg) -> list:
    idx = Path(cfg["store_dir"]) / cfg["index_file"]
    if not idx.is_file():
        return []
    return idx.read_text(encoding="utf-8").splitlines()


def read_index(cfg) -> list:
    """解析索引文件，返回 [{'title','file','desc'}, ...]（保留非索引行为原始数据，不回写）。"""
    entries = []
    for line in _read_index_lines(cfg):
        m = _INDEX_LINE_RE.match(line)
        if m:
            entries.append(
                {"title": m.group(1), "file": m.group(2), "desc": (m.group(3) or "").strip()}
            )
    return entries


def _index_line(title, file, desc=""):
    line = f"- [{title}]({file})"
    if desc:
        line += f" — {desc}"
    return line


def _rewrite_index(cfg, rewrite):
    """读取索引全部行；对每个索引行调用 rewrite(line, match) -> 新行 或 None(删除)。
    非索引行原样保留。返回 (改写后的行列表, 是否改动)。"""
    idx = Path(cfg["store_dir"]) / cfg["index_file"]
    raw = idx.read_text(encoding="utf-8").splitlines() if idx.is_file() else []
    out, changed = [], False
    for ln in raw:
        m = _INDEX_LINE_RE.match(ln)
        if m is None:
            out.append(ln)
            continue
        r = rewrite(ln, m)
        if r is None:
            changed = True
        elif r != ln:
            out.append(r)
            changed = True
        else:
            out.append(ln)
    return out, changed


def _write_index(idx, out, changed):
    if changed or not idx.is_file():
        idx.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")


def add_index_entry(cfg, title, file, desc=""):
    """追加/替换一条索引行（按 file 去重），保留其它行。"""
    idx = Path(cfg["store_dir"]) / cfg["index_file"]
    out, changed = _rewrite_index(
        cfg, lambda ln, m: _index_line(title, file, desc) if m.group(2) == file else ln
    )
    if not any(
        _INDEX_LINE_RE.match(ln) and _INDEX_LINE_RE.match(ln).group(2) == file
        for ln in out
    ):
        out.append(_index_line(title, file, desc))
        changed = True
    _write_index(idx, out, changed)


def remove_index_entry(cfg, file):
    """删除指向该文件的索引行，保留其它行。"""
    if not Path(cfg["store_dir"]).is_dir():
        return
    idx = Path(cfg["store_dir"]) / cfg["index_file"]
    if not idx.is_file():
        return
    out, changed = _rewrite_index(cfg, lambda ln, m: None if m.group(2) == file else ln)
    _write_index(idx, out, changed)


# ---------------------------------------------------------------------------
# 搜索（§2.2：索引 + frontmatter + 正文，含 §1.2 过滤）
# ---------------------------------------------------------------------------

def _match(d, index_title, kw, text):
    """确定性匹配得分：name 精确 > name 包含 > desc > 索引标题 > 正文。返回 (score, 命中位置)。"""
    name = d["name"].lower()
    desc = d["desc"].lower()
    index_title = index_title.lower()
    if kw in name:
        return (201 if kw == name else 200), "name"
    if kw in desc:
        return 160, "desc"
    if kw in index_title:
        return 120, "title"
    if kw in text.lower():
        return 80, "body"
    return None, None


def _snippet(text, kw, width=40):
    idx = text.lower().find(kw)
    if idx < 0:
        return ""
    start = max(0, idx - width // 2)
    end = min(len(text), idx + len(kw) + width // 2)
    snippet = text[start:end].replace("\n", " ")
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet += "…"
    return snippet


def search_docs(cfg, keyword) -> list:
    """搜索全部 mdoc 文档，按相关度（score desc, created desc）排序。"""
    kw = keyword.strip().lower()
    if not kw:
        return []
    store_dir = Path(cfg["store_dir"])
    titles = {e["file"]: e["title"] for e in read_index(cfg)}
    ranked = []
    for d in load_docs(cfg):
        path = store_dir / d["file"]
        with open(path, encoding="utf-8") as f:
            text = f.read()
        score, where = _match(d, titles.get(d["file"], ""), kw, text)
        if score is None:
            continue
        ranked.append({**d, "score": score, "match": where, "snippet": _snippet(text, kw)})
    ranked.sort(key=lambda r: (r["score"], r["created"]), reverse=True)
    return ranked


# ---------------------------------------------------------------------------
# kebab-case（§1.3）
# ---------------------------------------------------------------------------

def slugify(title) -> str:
    """标题 → kebab-case：小写、非 [a-z0-9] 归并为 `-`、去首尾连字符。

    中文标题无法确定性转拼音，非 ASCII 会被剔除（如 "Coze 浮窗 UI" → "coze-ui"）；
    需拼音/翻译时由 skill/作者提供文件名建议（SKILL.md §1.3 优先采用用户建议）。
    """
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")


# ---------------------------------------------------------------------------
# 内容风格系统（§1.5）
# ---------------------------------------------------------------------------

STYLE_PRESETS = {
    "sanitized": (
        "完全脱敏：不含任何 /xxx API 路径代码，不使用代码或文件路径，"
        "只用自然语言说明技术实现。"
    ),
    "partial": (
        "部分脱敏：可含 API 路径代码和文件夹代码；"
        "涉及 apikey 等敏感文件或字段时用占位符脱敏描述（如 <API_KEY>），不写真实密钥。"
    ),
    "free": "完全自由：无限制，由作者自行决定详略与脱敏程度。",
}

_PATH_PATTERN = re.compile(r"(?<![\w])(?:/[a-zA-Z0-9_\-\.]+){2,}")
_SECRET_PATTERN = re.compile(
    r"(api[_-]?key|secret|token|password|passwd)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}",
    re.IGNORECASE,
)


def load_style(cfg=None) -> dict:
    """返回 {name: rule_text} 风格表：内置三种 + 配置覆盖/自定义。"""
    cfg = cfg or load_config()
    styles = dict(STYLE_PRESETS)
    styles.update(cfg.get("style_overrides", {}))
    return styles


def resolve_style(metadata_style=None, cfg=None) -> str:
    """文档实际风格：metadata.style（合法则用）> 配置默认 > 内置默认 partial。"""
    cfg = cfg or load_config()
    styles = load_style(cfg)
    if metadata_style in styles:
        return metadata_style
    default = cfg.get("style_default", DEFAULT_STYLE_DEFAULT)
    return default if default in styles else DEFAULT_STYLE_DEFAULT


def style_rule(metadata_style=None, cfg=None):
    """返回某文档应遵循的风格规则文字（写作指令，供 skill 展示/执行）。"""
    cfg = cfg or load_config()
    name = resolve_style(metadata_style, cfg)
    return name, load_style(cfg).get(name, "")


def check_style_violations(text, style) -> list:
    """确定性风格校验（轻启发式）。返回 [(问题类型, 命中的片段), ...]。

    - sanitized: 查路径泄漏（/a/b 形态）
    - sanitized / partial: 查密钥疑似泄漏（api_key 等赋值真实值）
    """
    issues = []
    if style == "sanitized":
        for m in _PATH_PATTERN.finditer(text):
            issues.append(("路径泄漏", m.group(0)))
    if style in ("sanitized", "partial"):
        for m in _SECRET_PATTERN.finditer(text):
            issues.append(("密钥疑似泄漏", m.group(0)))
    return issues


# ---------------------------------------------------------------------------
# 确定性校验（doc-validator 的确定性项）
# ---------------------------------------------------------------------------

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def validate_doc(cfg, refname, check_style=True) -> dict:
    """校验单篇：frontmatter 完整性 + [[wikilink]] 可达性 + （可选）内容风格。

    返回 {file, name, style, issues:[{'type','msg'}, ...]}。
    """
    doc = read_doc(cfg, refname)
    issues = []
    fm = doc["fm"]
    if not _FRONTMATTER_RE.match(doc["text"]):
        issues.append({"type": "frontmatter", "msg": "frontmatter 缺失或格式错误"})
    if not fm.get("name"):
        issues.append({"type": "frontmatter", "msg": "缺 name 字段"})
    if fm.get("type") != cfg["reference_type"]:
        issues.append({"type": "frontmatter", "msg": f"type 应为 {cfg['reference_type']}"})
    if not fm.get("created"):
        issues.append({"type": "frontmatter", "msg": "缺 created 字段"})
    known = _known_docs(cfg)  # 参考名 / 文件名均可作为 [[wikilink]] 目标
    for link in _WIKILINK_RE.findall(doc["text"]):
        if link.lower() not in known:
            issues.append({"type": "wikilink", "msg": f"[[{link}]] 未指向现有文档"})
    style = resolve_style(fm.get("style"), cfg)
    if check_style:
        for kind, frag in check_style_violations(doc["text"], style):
            issues.append({"type": "style", "msg": f"[{kind}] {frag}"})
    return {"file": doc["file"], "name": doc["name"], "style": style, "issues": issues}


# ---------------------------------------------------------------------------
# create / update —— doc.json / patch.json 中间格式（阶段 3）
#
# skill 流程：LLM 从对话提取 → 组装 doc.json（sections + metadata）
#   → `mdoc create --stdin --dry-run` 出预览 → 用户确认 → 去掉 --dry-run 落盘。
# 所有写操作二次确认在 skill 交互层；CLI 的 --dry-run 保证预览不落盘。
# 校验 / 渲染 / 文件名 / 索引同步全部在此确定性完成（core 唯一数据写入方）。
#
# doc.json 结构（create 输入）：
#   { name, description, metadata{tags, blog_ready, created, style},
#     sections:[{title, content}], filename? }
# patch.json 结构（update 输入）：
#   { ops:[{op: append|replace|delete, title, content?}], description? }
#   —— op=delete 不需要 content；description 更新会同步索引行。
#   update 不改变 blog_ready（SKILL.md §2.5）。
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YAML_SPECIAL_RE = re.compile(r'[:#\[\]{},&\*!|>%@`"\'\\]|\s$|^\s')
_H2_RE = re.compile(r"^##\s+(.*?)\s*$")


def _yaml_quote(v):
    """标量值的 YAML 安全表示：含特殊字符时用 JSON 双引号转义（合法 YAML 标量）。"""
    v = str(v)
    if v and not _YAML_SPECIAL_RE.search(v):
        return v
    return json.dumps(v, ensure_ascii=False)


def _render_frontmatter(name, description, meta, cfg):
    """按 §1.3 渲染 frontmatter：name / description + metadata(type, tags, blog_ready, created, style)。"""
    tags = meta.get("tags", [])
    lines = [
        "---",
        f"name: {_yaml_quote(name)}",
        f"description: {_yaml_quote(description)}",
        "metadata:",
        f"  type: {cfg['reference_type']}",
        "  tags: [" + ", ".join(tags) + "]" if tags else "  tags: []",
        f"  blog_ready: {'true' if meta.get('blog_ready') else 'false'}",
        f"  created: {meta.get('created')}",
        f"  style: {meta.get('style')}",
        "---",
    ]
    return "\n".join(lines)


def normalize_doc(doc, cfg):
    """校验并规范化 doc.json。返回 (normalized, issues)；issues 为空才可用于落盘。

    normalized = {name, description, metadata{type,tags,blog_ready,created,style},
                  sections, filename}。缺省值：created=今天、style=配置默认、blog_ready=False。
    文件名：filename 覆盖优先（slugify 净化），否则 slugify(name)；slug 为空则要求 filename。
    """
    issues = []
    if not isinstance(doc, dict):
        return None, ["doc 必须是 JSON 对象"]
    name = doc.get("name")
    if not isinstance(name, str) or not name.strip():
        issues.append("缺 name（参考名）")
        name = ""
    else:
        name = name.strip()
    description = doc.get("description")
    if not isinstance(description, str) or not description.strip():
        issues.append("缺 description（一句话概述）")
        description = ""
    else:
        description = description.strip()
    meta = doc.get("metadata") or {}
    if not isinstance(meta, dict):
        issues.append("metadata 必须是对象")
        meta = {}
    tags = meta.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        issues.append("metadata.tags 必须是字符串数组")
        tags = []
    blog_ready = meta.get("blog_ready", False)
    if not isinstance(blog_ready, bool):
        issues.append("metadata.blog_ready 必须是布尔值")
        blog_ready = False
    created = meta.get("created")
    if created is None or created == "":
        created = time.strftime("%Y-%m-%d")
    created = str(created)
    if not _DATE_RE.match(created):
        issues.append(f"metadata.created 应为 YYYY-MM-DD，当前：{created}")
    style = meta.get("style")
    if style is None:
        style = resolve_style(None, cfg)
    else:
        style = str(style)
        if style not in load_style(cfg):
            issues.append(f"metadata.style 应为 {sorted(load_style(cfg))} 之一")
    sections = doc.get("sections")
    if not isinstance(sections, list) or not sections:
        issues.append("sections 至少需要一个章节")
        sections = []
    else:
        cleaned = []
        for i, s in enumerate(sections):
            if not isinstance(s, dict):
                issues.append(f"sections[{i}] 必须是对象")
                continue
            title = s.get("title")
            content = s.get("content", "")
            if not isinstance(title, str) or not title.strip():
                issues.append(f"sections[{i}] 缺 title")
                continue
            if not isinstance(content, str):
                issues.append(f"sections[{i}] 缺 content（字符串）")
                content = ""
            cleaned.append({"title": title.strip(), "content": content.strip("\n")})
        sections = cleaned
    filename = None
    raw = doc.get("filename")
    if raw is not None:
        if not isinstance(raw, str) or not raw.strip():
            issues.append("filename 必须是字符串")
        else:
            stem = slugify(raw.rsplit(".", 1)[0] if "." in raw else raw)
            filename = (stem + ".md") if stem else None
            if not filename:
                issues.append(f"filename 无法转成合法文件名：{raw}")
    if not filename:
        stem = slugify(name)
        filename = (stem + ".md") if stem else None
        if not filename:
            issues.append("name 无法生成 ASCII 文件名，请提供 filename（kebab-case，如 nginx-502-fix）")
    return {
        "name": name,
        "description": description,
        "metadata": {
            "type": cfg["reference_type"],
            "tags": [str(t).strip() for t in tags if str(t).strip()],
            "blog_ready": blog_ready,
            "created": created,
            "style": style,
        },
        "sections": sections,
        "filename": filename,
    }, issues


def render_sections(sections):
    """章节列表 → 正文 markdown（每个章节 `## 标题` + 空行 + 内容，块间空行分隔）。"""
    blocks = []
    for s in sections:
        title = s["title"].strip()
        content = s.get("content", "").strip("\n")
        block = f"## {title}"
        if content:
            block += "\n\n" + content
        blocks.append(block)
    return "\n\n".join(blocks)


def split_sections(text):
    """按 H2 章节切分文档正文（跳过围栏代码块内的 `##` 行）。

    返回 (preamble, [{'title','content'}, ...])；preamble = frontmatter 及第一个
    H2 之前的所有内容，原样保留（含未知字段，如 node_type: memory）。
    """
    h2s = _h2_matches(text)
    if not h2s:
        return text.rstrip("\n") + "\n", []
    preamble = text[:h2s[0][0]]
    sections = []
    for i, (start, title) in enumerate(h2s):
        end = h2s[i + 1][0] if i + 1 < len(h2s) else len(text)
        block = text[start:end]
        content = block.split("\n", 1)[1].strip("\n") if "\n" in block else ""
        sections.append({"title": title, "content": content})
    return preamble, sections


def _h2_matches(text):
    """定位 H2 章节标题行（```` ``` ````/`~~~` 围栏代码块内的 ## 不算标题）。返回 [(offset, title), ...]。"""
    matches = []
    in_fence = False
    offset = 0
    for ln in text.split("\n"):
        stripped = ln.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
        elif not in_fence:
            m = _H2_RE.match(ln)
            if m and m.group(1):
                matches.append((offset, m.group(1)))
        offset += len(ln) + 1
    return matches


def render_doc(doc, cfg):
    """doc.json → 落盘文本（不写盘）。返回 (rendered, issues)：
    合法 → (rendered, [])，rendered = {file, name, description, style, exists, text}；
    schema 不合法 → (None, issues 字符串列表)。文件名冲突与否由 `exists` 字段给出（不进 CLI 逻辑）。"""
    norm, issues = normalize_doc(doc, cfg)
    if issues:
        return None, issues
    fm = _render_frontmatter(norm["name"], norm["description"], norm["metadata"], cfg)
    body = render_sections(norm["sections"])
    text = fm + "\n\n" + body + "\n"
    target = Path(cfg["store_dir"]) / norm["filename"]
    return {
        "file": norm["filename"],
        "name": norm["name"],
        "description": norm["description"],
        "style": norm["metadata"]["style"],
        "exists": target.exists(),
        "text": text,
    }, []


def create_doc(cfg, rendered, force=False):
    """把 render_doc 的结果写盘 + 索引同步（core 内完成，唯一数据写入方）。
    文件名已存在且未 --force 抛 FileExistsError；force=True 覆盖（§2.4 覆盖分支）。"""
    target = Path(cfg["store_dir"]) / rendered["file"]
    if target.exists() and not force:
        raise FileExistsError(
            f"文件名已存在：{rendered['file']}。如需修改请用 `mdoc update {rendered['name']}`，"
            f"换 name/filename，或用 --force 覆盖。"
        )
    target.write_text(rendered["text"], encoding="utf-8")
    add_index_entry(cfg, rendered["name"], rendered["file"], rendered["description"])
    return {"file": rendered["file"], "name": rendered["name"], "path": str(target), "index_synced": True}


def _set_description_line(text, new_desc):
    """在 frontmatter 块内更新 description 行（找不到则在 name 行后插入），保留其它行原样。
    只改写第一个 frontmatter 块内的行，避免误命中正文里列顶格的 `description:` 段落。"""
    fm = _FRONTMATTER_RE.match(text)
    if not fm:
        raise ValueError("文档缺少 frontmatter，无法更新描述")
    new_line = f"description: {_yaml_quote(new_desc)}"
    lines = fm.group(0).splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if re.match(r"^description:", ln):
            lines[i] = new_line + ("\n" if ln.endswith("\n") else "")
            return text[:fm.start()] + "".join(lines) + text[fm.end():]
    for i, ln in enumerate(lines):
        if re.match(r"^name:", ln):
            lines.insert(i + 1, new_line + "\n")
            return text[:fm.start()] + "".join(lines) + text[fm.end():]
    raise ValueError("frontmatter 中找不到 name 或 description 行，无法更新描述")


_OPS = ("append", "replace", "delete")


def apply_patch_text(cfg, refname, patch):
    """计算 update 后的文档文本（不写盘）。返回 {file,name,path,old_text,new_text,changed,description}。
    replace/delete 目标章节不存在 → ValueError（不静默）；语义无变化（章节序列与描述都没变）
    → changed=False 且 new_text 原样，避免把非规范空白重排成规范格式（spurious 变更）。"""
    doc = read_doc(cfg, refname)
    if not isinstance(patch, dict):
        raise ValueError("patch 必须是 JSON 对象")
    ops = patch.get("ops")
    if ops is None:
        ops = []
    if not isinstance(ops, list):
        raise ValueError("patch.ops 必须是数组")
    for op in ops:
        if not isinstance(op, dict) or op.get("op") not in _OPS:
            raise ValueError("patch.ops[] 需含 op: append|replace|delete")
        title = op.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"op {op.get('op')} 缺 title")
        if op["op"] != "delete" and not isinstance(op.get("content"), str):
            raise ValueError(f"op {op['op']} 缺 content（字符串）")
    new_desc = patch.get("description")
    if new_desc is not None and not isinstance(new_desc, str):
        raise ValueError("patch.description 必须是字符串")
    preamble, sections = split_sections(doc["text"])
    orig_sections = list(sections)
    missing = []
    for op in ops:
        op_name = op["op"]
        title = op["title"].strip()
        if op_name in ("replace", "delete") and title not in {s["title"] for s in sections}:
            missing.append(title)
        if op_name == "append":
            sections.append({"title": title, "content": op.get("content", "").strip("\n")})
        elif op_name == "replace":
            sections = [
                {"title": title, "content": op.get("content", "").strip("\n")} if s["title"] == title else s
                for s in sections
            ]
        else:  # delete
            sections = [s for s in sections if s["title"] != title]
    if missing:
        raise ValueError(f"未找到章节：{'、'.join(sorted(set(missing)))}（update 的 replace/delete 目标必须已存在）")
    old_desc = doc["fm"].get("description")
    desc_changed = new_desc is not None and new_desc != old_desc
    if sections == orig_sections and not desc_changed:
        # 语义无变化：不重渲染、不落盘，避免把非规范空白重排成规范格式（spurious 变更）
        return {
            "file": doc["file"], "name": doc["name"], "path": doc["path"],
            "old_text": doc["text"], "new_text": doc["text"],
            "changed": False, "description": None,
        }
    body = render_sections(sections)
    new_text = (preamble.rstrip() + "\n\n" + body + "\n") if body else (preamble.rstrip() + "\n")
    if desc_changed:
        new_text = _set_description_line(new_text, new_desc)
    return {
        "file": doc["file"],
        "name": doc["name"],
        "path": doc["path"],
        "old_text": doc["text"],
        "new_text": new_text,
        "changed": new_text != doc["text"],
        "description": new_desc if desc_changed else None,
    }


def update_doc(cfg, refname, patch):
    """apply_patch_text → 写盘 + 描述变更时同步索引。返回 {file,name,description,changed,index_synced}。"""
    r = apply_patch_text(cfg, refname, patch)
    index_synced = False
    if r["changed"]:
        Path(r["path"]).write_text(r["new_text"], encoding="utf-8")
    if r["description"] is not None:
        add_index_entry(cfg, r["name"], r["file"], r["description"].strip())
        index_synced = True
    return {
        "file": r["file"],
        "name": r["name"],
        "description": r["description"],
        "changed": r["changed"],
        "index_synced": index_synced,
    }


# ---------------------------------------------------------------------------
# mdoc init：建库
# ---------------------------------------------------------------------------

INIT_CONFIG_TEMPLATE = """# mdoc 库本地配置 —— 由 `mdoc init` 生成
# 优先级：内置默认 < 本文件 < 环境变量 MDOC_DIR / 命令行 --store

index_file = "{index_file}"

[classification]
reference_type = "reference"
excluded_types = ["user", "feedback", "project"]
excluded_files = []

[style]
default = "partial"
# 轻度自定义内容风格（SKILL.md §1.5）：
# overrides = {{ sanitized = "额外：不出现服务器 IP", free = "..." }}
"""


def write_skill_template(store_dir) -> str:
    """把包内 skill_template/SKILL.md 写入 <store_dir>/SKILL.md（仅当不存在）。

    返回 written | exists | absent。模板随 wheel 分发（package-data），
    源码树与安装态均可通过 __file__ 定位。幂等：不覆盖用户改动。"""
    src = Path(__file__).parent / "skill_template" / "SKILL.md"
    if not src.is_file():
        return "absent"
    dst = Path(store_dir) / "SKILL.md"
    if dst.exists():
        return "exists"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return "written"


def init_store(store_dir, index_file="INDEX.md") -> dict:
    """建库：创建目录 + 索引 + 库本地配置 + skill 模板。幂等（已存在则跳过，不覆盖用户改动）。"""
    d = Path(store_dir)
    d.mkdir(parents=True, exist_ok=True)
    idx = d / index_file
    index_created = False
    if not idx.exists():
        idx.write_text("", encoding="utf-8")
        index_created = True
    cfg_path = d / ".mdoc.toml"
    config_written = False
    if not cfg_path.exists():
        cfg_path.write_text(INIT_CONFIG_TEMPLATE.format(index_file=index_file), encoding="utf-8")
        config_written = True
    return {
        "store_dir": str(d),
        "index_file": index_file,
        "index_created": index_created,
        "config_written": config_written,
        "config": str(cfg_path),
        "skill_template": write_skill_template(d),
    }

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mdoc 核心模块 —— 确定性规则的单一事实来源。

分层：core（本模块，纯逻辑）→ CLI（mdoc.cli，薄壳）→ skill（LLM 前端）。
规则锁进代码、不依赖提示词（对应 /mdoc SKILL.md §1.2 / §1.3 / §1.5）。
零机器路径硬编码：库路径一律来自配置或环境变量。

配置解析优先级（后者覆盖前者）：
  内置默认 < 用户配置（~/.mdoc.toml，可用 $MDOC_CONFIG 指定）
  < 库本地配置（<store_dir>/.mdoc.toml，mdoc init 生成）
  < 环境变量 MDOC_DIR / 命令行 --store
"""

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


def load_config(store_override=None) -> dict:
    """合并配置：默认 < 用户配置 < 库本地配置 < env/CLI。"""
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
        store_override or os.environ.get("MDOC_DIR") or cfg.get("store_dir") or ""
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


def init_store(store_dir, index_file="INDEX.md") -> dict:
    """建库：创建目录 + 索引 + 库本地配置。幂等（已存在则跳过，不覆盖用户改动）。"""
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
    }

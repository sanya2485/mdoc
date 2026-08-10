#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mdoc CLI —— core 的薄壳。确定性操作全在 core，本模块只做参数解析 + 输出。
`--json` 输出结构化结果供 skill / 脚本消费（--json 下 stdout 只有一条 JSON）。

用法:
  mdoc init <dir> [--index INDEX.md]     建库
  mdoc config [--json]                   打印当前配置
  mdoc list [--json] [--names]           列出全部 mdoc 文档
  mdoc search <关键词> [--page N] [--json]  搜索
  mdoc get <refname> [--json]            查看单篇全文
  mdoc create <doc.json>|--stdin [--dry-run] [--force] [--json]  从 doc.json 创建（校验→落盘→索引）
  mdoc update <refname> <patch.json>|--stdin [--dry-run] [--json]  追加/替换/删除章节
  mdoc delete <refname> --yes [--json]   删文件 + 同步索引
  mdoc slugify <标题>                     kebab-case
  mdoc validate <refname> [--style] [--json]  确定性校验
"""

import argparse
import difflib
import json
import sys
from pathlib import Path

from . import __version__, core


def _need_store(cfg):
    if not cfg["store_dir"]:
        print("错误：未配置文档库。先 `mdoc init <dir>`，或设置环境变量 MDOC_DIR。", file=sys.stderr)
        sys.exit(1)


def _human_list(obj):
    print(f"TOTAL={obj['total']}")
    if not obj["docs"]:
        print("（还没有修复方案文档，用 /mdoc-c 创建第一篇）")
        return
    print(f"📋 修复方案文档目录（共 {obj['total']} 篇，按创建时间倒序）")
    print(f"📂 根目录: {obj['store_dir']}\\")
    for i, d in enumerate(obj["docs"], 1):
        print("  %-3d %-20s %-30s %s  %s" % (i, d["name"][:20], d["desc"][:30], d["created"][:10], d["mtime"]))


def _human_search(obj):
    print(f"🔍 搜索 “{obj['keyword']}”（命中 {obj['total']} 篇，按相关度排序）")
    for i, r in enumerate(obj["results"], 1):
        where = {"name": "参考名", "desc": "描述", "title": "索引标题", "body": "正文"}.get(r["match"], r["match"])
        print(f"  {i:>2}. {r['name']}  [命中:{where}]  {r['created']}")
        if r.get("snippet"):
            print(f"      …{r['snippet']}…")
        if r.get("desc"):
            print(f"      {r['desc'][:60]}")
    if obj["total"] > obj["per_page"]:
        print(f"  （共 {obj['total']} 条，仅显示前 {obj['per_page']} 条，用 --page N 继续翻页）")


# --- 各命令实现 ---

def cmd_init(args):
    res = core.init_store(args.dir, index_file=args.index)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    print(f"已初始化文档库：{res['store_dir']}")
    print(f"索引文件：{res['store_dir']}/{res['index_file']}（{'新建' if res['index_created'] else '已存在'}）")
    print(f"库本地配置：{res['config']}（{'写入' if res['config_written'] else '已存在，未覆盖'}）")
    if res["skill_template"] == "absent":
        print("skill 模板：未随包提供（跳过）")
    else:
        print(f"skill 模板：{res['store_dir']}/SKILL.md（"
              + ("写入，可复制到 Claude Code 技能目录" if res["skill_template"] == "written" else "已存在，未覆盖") + "）")
    return 0


def cmd_config(args):
    cfg = core.load_config(args.store)
    if args.json:
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        return 0
    print("mdoc 配置")
    print(f"  文档库目录  store_dir        = {cfg['store_dir'] or '（未配置）'}")
    print(f"  索引文件    index_file       = {cfg['index_file']}")
    print(f"  参考类型    reference_type   = {cfg['reference_type']}")
    print(f"  排除类型    excluded_types   = {cfg['excluded_types']}")
    print(f"  排除文件    excluded_files   = {cfg['excluded_files']}")
    print(f"  默认风格    style_default    = {cfg['style_default']}")
    return 0


def cmd_list(args):
    cfg = core.load_config(args.store)
    _need_store(cfg)
    docs = core.load_docs(cfg)
    if args.names:
        for d in docs:
            print(d["name"])
        return 0
    obj = {"total": len(docs), "store_dir": cfg["store_dir"], "docs": docs}
    if args.json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        return 0
    _human_list(obj)
    return 0


def cmd_search(args):
    cfg = core.load_config(args.store)
    _need_store(cfg)
    ranked = core.search_docs(cfg, args.keyword)
    total = len(ranked)
    per = args.per_page or 20
    start = (args.page - 1) * per
    obj = {"keyword": args.keyword, "total": total, "page": args.page, "per_page": per,
           "results": ranked[start:start + per]}
    if args.json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        return 0
    _human_search(obj)
    return 0


def cmd_get(args):
    cfg = core.load_config(args.store)
    _need_store(cfg)
    try:
        doc = core.read_doc(cfg, args.refname)
    except FileNotFoundError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"file": doc["file"], "name": doc["name"],
                          "frontmatter": doc["fm"], "text": doc["text"]},
                         ensure_ascii=False, indent=2))
        return 0
    print(doc["text"])
    return 0


def cmd_delete(args):
    cfg = core.load_config(args.store)
    _need_store(cfg)
    doc = None
    try:
        doc = core.read_doc(cfg, args.refname)
    except FileNotFoundError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    if not args.yes:
        print(f"即将删除：{doc['file']}（{doc['name']}）。确认请加 --yes。", file=sys.stderr)
        return 1
    obj = core.delete_doc(cfg, args.refname)  # core 内完成删文件 + 索引同步
    if args.json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        return 0
    print(f"已删除：{obj['name']}（{obj['deleted']}），索引已同步。")
    return 0


def cmd_slugify(args):
    s = core.slugify(args.title)
    if args.json:
        print(json.dumps({"slug": s}, ensure_ascii=False, indent=2))
        return 0
    print(s or "（无可用的 ASCII 字符，建议由作者提供文件名）")
    return 0


def cmd_validate(args):
    cfg = core.load_config(args.store)
    _need_store(cfg)
    try:
        res = core.validate_doc(cfg, args.refname, check_style=args.style)
    except FileNotFoundError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    ok = not res["issues"]
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"{res['name']}（{res['file']}，风格 {res['style']}）：{'✅ 通过' if ok else '❌ 发现 ' + str(len(res['issues'])) + ' 个问题'}")
        for it in res["issues"]:
            print(f"  - [{it['type']}] {it['msg']}")
    return 0 if ok else 1


def _require_single_input(args, what):
    """<file> 与 --stdin 只能二选一。返回 None（通过）或退出码。"""
    if args.stdin and args.file:
        print(f"错误：{what} 的 <file> 与 --stdin 只能二选一", file=sys.stderr)
        return 1
    if not args.stdin and not args.file:
        print(f"错误：需要 {what} JSON 文件路径，或 --stdin 从标准输入读取", file=sys.stderr)
        return 1
    return None


def _load_json_input(args):
    """读取并解析 JSON：--stdin 或文件路径。JSON 非法抛 ValueError。"""
    if args.stdin:
        data = sys.stdin.read()
    else:
        data = Path(args.file).read_text(encoding="utf-8")
    try:
        return json.loads(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败：{e}") from e


def cmd_create(args):
    cfg = core.load_config(args.store)
    _need_store(cfg)
    err = _require_single_input(args, "doc.json")
    if err:
        return err
    try:
        doc = _load_json_input(args)
    except (ValueError, OSError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    rendered, issues = core.render_doc(doc, cfg)  # 校验 + 渲染一次完成（含 exists）
    if issues:
        print("错误：doc.json 不符合规范：", file=sys.stderr)
        for it in issues:
            print(f"  - {it}", file=sys.stderr)
        return 1
    if args.dry_run:
        if args.json:
            print(json.dumps({"dry_run": True, "file": rendered["file"], "name": rendered["name"],
                              "exists": rendered["exists"], "style": rendered["style"],
                              "text": rendered["text"]},
                             ensure_ascii=False, indent=2))
        else:
            print(f"[dry-run] 将创建：{rendered['file']}（参考名 {rendered['name']}，风格 {rendered['style']}）"
                  + ("　⚠️ 文件已存在，落盘将失败" if rendered["exists"] else ""))
            print("--- 预览 ---")
            print(rendered["text"])
            print("--- 预览结束（--dry-run 未落盘）---")
        return 0
    try:
        res = core.create_doc(cfg, rendered, force=args.force)
    except FileExistsError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"✅ 文档已创建：{res['file']}（参考名 {res['name']}）")
        print(f"   索引已同步：{cfg['index_file']}")
        print(f"   查看: mdoc get {res['name']}    更新: mdoc update {res['name']}")
    return 0


def cmd_update(args):
    cfg = core.load_config(args.store)
    _need_store(cfg)
    err = _require_single_input(args, "patch.json")
    if err:
        return err
    try:
        patch = _load_json_input(args)
        if args.dry_run:
            r = core.apply_patch_text(cfg, args.refname, patch)
        else:
            r = core.update_doc(cfg, args.refname, patch)
    except (FileNotFoundError, ValueError, OSError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    if args.dry_run:
        diff = list(difflib.unified_diff(
            r["old_text"].splitlines(keepends=True),
            r["new_text"].splitlines(keepends=True),
            fromfile="当前", tofile="修改后"))
        if args.json:
            print(json.dumps({"dry_run": True, "file": r["file"], "name": r["name"],
                              "changed": r["changed"], "ops": patch.get("ops", []),
                              "description": r["description"], "diff": diff},
                             ensure_ascii=False, indent=2))
        else:
            print(f"[dry-run] 将更新：{r['file']}（参考名 {r['name']}）")
            if r["changed"]:
                print("".join(diff))
            else:
                print("   无实际变更（当前文档已是该状态）。")
        return 0
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"✅ 已更新：{r['file']}（参考名 {r['name']}）")
        if r["changed"]:
            print(f"   文件已写入；描述变更 → 索引已同步：{cfg['index_file']}" if r["index_synced"]
                  else "   文件已写入。")
        else:
            print("   无实际变更。")
    return 0


# --- 参数解析 ---

def build_parser():
    p = argparse.ArgumentParser(prog="mdoc", description="修复方案文档管理系统 CLI")
    p.add_argument("--version", action="version", version=f"mdoc {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def add_store(sp):
        sp.add_argument("--store", help="覆盖文档库目录（优先于 MDOC_DIR）")

    def add_json(sp):
        sp.add_argument("--json", action="store_true", help="JSON 结构化输出（供 skill 消费）")

    sp = sub.add_parser("init", help="建库：创建目录 + 索引 + 库本地配置")
    add_json(sp)
    sp.add_argument("dir")
    sp.add_argument("--index", default="INDEX.md", help="索引文件名（默认 INDEX.md）")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("config", help="打印当前配置")
    add_store(sp)
    add_json(sp)
    sp.set_defaults(func=cmd_config)

    sp = sub.add_parser("list", help="列出全部 mdoc 文档")
    add_store(sp)
    add_json(sp)
    sp.add_argument("--names", action="store_true", help="仅输出参考名（每行一个，供脚本消费）")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("search", help="搜索（索引+frontmatter+正文，含过滤与排序）")
    add_store(sp)
    add_json(sp)
    sp.add_argument("keyword")
    sp.add_argument("--page", type=int, default=1)
    sp.add_argument("--per-page", type=int, default=20)
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("get", help="查看单篇全文")
    add_store(sp)
    add_json(sp)
    sp.add_argument("refname")
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("delete", help="删除文档并同步索引")
    add_store(sp)
    add_json(sp)
    sp.add_argument("refname")
    sp.add_argument("--yes", action="store_true", help="确认删除（必须显式提供）")
    sp.set_defaults(func=cmd_delete)

    sp = sub.add_parser("slugify", help="标题转 kebab-case 文件名")
    add_json(sp)
    sp.add_argument("title")
    sp.set_defaults(func=cmd_slugify)

    sp = sub.add_parser("validate", help="确定性校验（frontmatter / [[wikilink]] / 风格）")
    add_store(sp)
    add_json(sp)
    sp.add_argument("refname")
    sp.add_argument("--style", action="store_true", help="附加内容风格校验（§1.5）")
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("create", help="从 doc.json 创建文档（校验 → 落盘 → 索引同步）")
    add_store(sp)
    add_json(sp)
    sp.add_argument("file", nargs="?", help="doc.json 文件路径")
    sp.add_argument("--stdin", action="store_true", help="从标准输入读取 doc.json")
    sp.add_argument("--dry-run", action="store_true", help="仅渲染预览，不落盘（skill 确认流程用）")
    sp.add_argument("--force", action="store_true", help="文件名已存在时覆盖（§2.4 覆盖分支）")
    sp.set_defaults(func=cmd_create)

    sp = sub.add_parser("update", help="按 patch.json 更新文档（追加/替换/删除章节 + 描述）")
    add_store(sp)
    add_json(sp)
    sp.add_argument("refname")
    sp.add_argument("file", nargs="?", help="patch.json 文件路径")
    sp.add_argument("--stdin", action="store_true", help="从标准输入读取 patch.json")
    sp.add_argument("--dry-run", action="store_true", help="仅出 diff 预览，不落盘")
    sp.set_defaults(func=cmd_update)

    return p


def main(argv=None):
    # 统一 UTF-8：stdin 若不重配，Windows 非 UTF-8 locale 下 `--stdin` 读中文会按 GBK 解码成
    # 孤立代理对，再写回 UTF-8 时报 UnicodeEncodeError（surrogates not allowed）。
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except FileNotFoundError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

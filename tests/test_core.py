# -*- coding: utf-8 -*-
"""mdoc core 单元测试（stdlib unittest，零依赖）。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mdoc import core


class MdocTestCase(unittest.TestCase):
    """隔离用户配置（指向不存在的 MDOC_CONFIG），提供临时库。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Path(self._tmp.name) / "store"
        self.store.mkdir()
        # 显式声明索引文件名（等价于 mdoc init 生成的库本地配置），避免依赖内置默认 MEMORY.md
        (self.store / ".mdoc.toml").write_text(
            "index_file = \"INDEX.md\"\n", encoding="utf-8")
        self._saved_cfg = os.environ.get("MDOC_CONFIG")
        self._saved_dir = os.environ.get("MDOC_DIR")
        os.environ["MDOC_CONFIG"] = str(Path(self._tmp.name) / "nonexistent.toml")
        os.environ.pop("MDOC_DIR", None)

    def tearDown(self):
        if self._saved_cfg is None:
            os.environ.pop("MDOC_CONFIG", None)
        else:
            os.environ["MDOC_CONFIG"] = self._saved_cfg
        if self._saved_dir is None:
            os.environ.pop("MDOC_DIR", None)
        else:
            os.environ["MDOC_DIR"] = self._saved_dir
        self._tmp.cleanup()

    def cfg(self, store=None):
        return core.load_config(store_override=str(store or self.store))

    def write_doc(self, name, type="reference", created="2026-08-01", desc="",
                  body="", style=None, index=False):
        fm = ["---",
              f"name: {name}",
              f"type: {type}",
              f"description: \"{desc}\"",
              f"created: {created}"]
        if style:
            fm.append(f"style: {style}")
        content = "\n".join(fm + ["---", "", body]) + "\n"
        fn = f"{name}.md"
        (self.store / fn).write_text(content, encoding="utf-8")
        if index:
            core.add_index_entry(self.cfg(), name, fn, desc)
        return fn

    def write_index(self, text):
        (self.store / "INDEX.md").write_text(text, encoding="utf-8")


class TestSlugify(MdocTestCase):
    def test_basic(self):
        self.assertEqual(core.slugify("MyFireflyBlog Nginx Config"), "myfireflyblog-nginx-config")

    def test_underscores_and_multi_space(self):
        self.assertEqual(core.slugify("my_file  name"), "my-file-name")

    def test_chinese_dropped(self):
        self.assertEqual(core.slugify("Coze 浮窗 UI 定制"), "coze-ui")

    def test_date_kept(self):
        self.assertEqual(core.slugify("2026-08-10"), "2026-08-10")

    def test_chinese_only_empty(self):
        self.assertEqual(core.slugify("浮窗修复"), "")

    def test_strip_edges(self):
        self.assertEqual(core.slugify("  nginx  "), "nginx")


class TestFrontmatter(MdocTestCase):
    def test_parse_nested_metadata(self):
        text = "---\nname: x\nmetadata:\n  type: reference\n  created: 2026-08-06\n  blog_ready: true\n---\nbody"
        fm = core.parse_frontmatter(text)
        self.assertEqual(fm["type"], "reference")
        self.assertEqual(fm["created"], "2026-08-06")
        self.assertEqual(fm["blog_ready"], "true")
        self.assertEqual(fm["name"], "x")

    def test_missing(self):
        self.assertEqual(core.parse_frontmatter("no frontmatter"), {})

    def test_scalar_fields(self):
        text = "---\ntype: reference\nname: abc\ndescription: \"x: y\"\n---\n"
        fm = core.parse_frontmatter(text)
        self.assertEqual(fm["description"], "x: y")  # 剥掉 YAML 引号

    def test_strip_quotes(self):
        text = "---\ndescription: '单引号包裹'\ncreated: \"2026-08-06\"\n---\n"
        fm = core.parse_frontmatter(text)
        self.assertEqual(fm["description"], "单引号包裹")
        self.assertEqual(fm["created"], "2026-08-06")


class TestConfig(MdocTestCase):
    def test_defaults_without_config(self):
        cfg = self.cfg()
        self.assertEqual(cfg["reference_type"], "reference")
        self.assertEqual(cfg["style_default"], "partial")
        self.assertEqual(cfg["excluded_types"], ["user", "feedback", "project"])

    def test_env_mdoc_dir(self):
        os.environ["MDOC_DIR"] = str(self.store)
        cfg = core.load_config()
        self.assertEqual(cfg["store_dir"], str(self.store))

    def test_store_local_overrides_user(self):
        (self.store / ".mdoc.toml").write_text(
            "index_file = \"LOCAL.md\"\n[style]\ndefault = \"sanitized\"\n",
            encoding="utf-8",
        )
        cfg = self.cfg()
        self.assertEqual(cfg["index_file"], "LOCAL.md")
        self.assertEqual(cfg["style_default"], "sanitized")


class TestDocs(MdocTestCase):
    def test_load_docs_filters(self):
        self.write_doc("a", type="reference", created="2026-08-02")
        self.write_doc("b", type="project", created="2026-08-03")   # 排除
        self.write_doc("c", type="user", created="2026-08-04")      # 排除
        self.write_doc("d", type="feedback", created="2026-08-05")  # 排除
        (self.store / "e.md").write_text("no frontmatter", encoding="utf-8")
        (self.store / "f.txt").write_text("x", encoding="utf-8")
        docs = core.load_docs(self.cfg())
        self.assertEqual([d["name"] for d in docs], ["a"])

    def test_load_docs_excluded_files(self):
        self.write_doc("keep")
        cfg = self.cfg()
        cfg["excluded_files"] = ["keep.md"]
        self.assertEqual(core.load_docs(cfg), [])

    def test_created_desc_order(self):
        self.write_doc("old", created="2026-08-01")
        self.write_doc("new", created="2026-08-09")
        docs = core.load_docs(self.cfg())
        self.assertEqual([d["name"] for d in docs], ["new", "old"])

    def test_missing_created_fallback(self):
        self.write_doc("no-date", created="")
        docs = core.load_docs(self.cfg())
        self.assertEqual(docs[0]["created"], "0000-00-00")

    def test_resolve_ref_by_name_and_file(self):
        self.write_doc("nginx 502 修复", created="2026-08-02")
        self.assertEqual(core.resolve_ref(self.cfg(), "Nginx 502 修复"), "nginx 502 修复.md")
        self.assertEqual(core.resolve_ref(self.cfg(), "nginx 502 修复.md"), "nginx 502 修复.md")
        self.assertIsNone(core.resolve_ref(self.cfg(), "不存在"))


class TestDeleteDoc(MdocTestCase):
    def test_delete_doc_removes_file_and_index(self):
        self.write_doc("a", created="2026-08-01", desc="待删")
        core.add_index_entry(self.cfg(), "a", "a.md", "待删")
        res = core.delete_doc(self.cfg(), "a")
        self.assertEqual(res["deleted"], "a.md")
        self.assertFalse((self.store / "a.md").exists())
        self.assertEqual(core.read_index(self.cfg()), [])
        self.assertEqual(core.load_docs(self.cfg()), [])

    def test_delete_doc_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            core.delete_doc(self.cfg(), "不存在")


class TestIndex(MdocTestCase):
    def test_add_remove_preserves_other_lines(self):
        self.write_index("# 索引\n\n- [A](a.md) — descA\n")
        core.add_index_entry(self.cfg(), "B", "b.md", "descB")
        core.remove_index_entry(self.cfg(), "a.md")
        lines = (self.store / "INDEX.md").read_text(encoding="utf-8").splitlines()
        self.assertIn("# 索引", lines)
        self.assertIn("", lines)
        self.assertIn("- [B](b.md) — descB", lines)
        self.assertFalse(any("a.md" in ln for ln in lines))

    def test_add_dedup_by_file(self):
        core.add_index_entry(self.cfg(), "B", "b.md", "v1")
        core.add_index_entry(self.cfg(), "B", "b.md", "v2")
        entries = core.read_index(self.cfg())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["desc"], "v2")

    def test_read_index_missing_file(self):
        self.assertEqual(core.read_index(self.cfg()), [])

    def test_add_creates_index(self):
        core.add_index_entry(self.cfg(), "B", "b.md", "descB")
        self.assertEqual(core.read_index(self.cfg())[0]["title"], "B")


class TestSearch(MdocTestCase):
    def test_ranking_and_filter(self):
        # a: 参考名命中；b: 正文命中；c: project 型含关键词 → 必须被过滤
        self.write_doc("nginx 502 修复", created="2026-08-02", desc="nginx 网关 502")
        self.write_doc("mysql deadlock", created="2026-08-01", body="与 nginx 反代相关")
        self.write_doc("其它", type="project", created="2026-08-03", body="nginx 秘密方案")
        results = core.search_docs(self.cfg(), "nginx")
        names = [r["name"] for r in results]
        self.assertEqual(names, ["nginx 502 修复", "mysql deadlock"])  # name 命中在前，project 已过滤
        self.assertEqual(results[0]["match"], "name")
        self.assertEqual(results[1]["match"], "body")

    def test_index_title_match(self):
        self.write_doc("微信登录", created="2026-08-01", body="正文不含关键词")
        self.write_index("- [微信登录 nginx 方案](微信登录.md) — x\n")
        results = core.search_docs(self.cfg(), "nginx")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["match"], "title")

    def test_empty_keyword(self):
        self.write_doc("a")
        self.assertEqual(core.search_docs(self.cfg(), "  "), [])

    def test_exact_name_ranks_first(self):
        self.write_doc("nginx", created="2026-08-05", body="nginx 反复出现")
        self.write_doc("nginx 502 修复", created="2026-08-09", desc="nginx")
        results = core.search_docs(self.cfg(), "nginx")
        self.assertEqual(results[0]["name"], "nginx")  # 精确名 201 > 包含名 200


class TestStyle(MdocTestCase):
    def test_resolve_style_defaults(self):
        self.assertEqual(core.resolve_style(None), "partial")
        self.assertEqual(core.resolve_style("sanitized"), "sanitized")
        self.assertEqual(core.resolve_style("不存在"), "partial")

    def test_sanitized_path_and_secret(self):
        issues = core.check_style_violations("调用 /api/v1/chat 接口；密钥 api_key = 'sk-abcdefgh123'", "sanitized")
        kinds = [k for k, _ in issues]
        self.assertIn("路径泄漏", kinds)
        self.assertIn("密钥疑似泄漏", kinds)

    def test_partial_only_secret(self):
        issues = core.check_style_violations("调用 /api/v1/chat 接口；密钥 token=abcdefgh12345", "partial")
        kinds = [k for k, _ in issues]
        self.assertIn("密钥疑似泄漏", kinds)
        self.assertNotIn("路径泄漏", kinds)

    def test_free_no_check(self):
        self.assertEqual(core.check_style_violations("api_key=abcdefgh12345 /a/b/c", "free"), [])

    def test_short_secret_ok(self):
        # 8 位以下的占位符/示例值不算泄漏
        self.assertEqual(core.check_style_violations("api_key=abc", "partial"), [])

    def test_override_new_style(self):
        (self.store / ".mdoc.toml").write_text(
            "[style]\noverrides = { custom = \"自定义规则\" }\n", encoding="utf-8")
        self.assertEqual(core.resolve_style("custom", self.cfg()), "custom")


class TestValidate(MdocTestCase):
    def test_valid_doc(self):
        self.write_doc("good", created="2026-08-01")
        res = core.validate_doc(self.cfg(), "good", check_style=False)
        self.assertEqual(res["issues"], [])
        self.assertEqual(res["style"], "partial")

    def test_missing_created(self):
        self.write_doc("bad", created="")
        res = core.validate_doc(self.cfg(), "bad", check_style=False)
        self.assertTrue(any(i["type"] == "frontmatter" for i in res["issues"]))

    def test_broken_wikilink(self):
        self.write_doc("w", created="2026-08-01", body="见 [[不存在的文档]] 和 [[w]]")
        res = core.validate_doc(self.cfg(), "w", check_style=False)
        wikis = [i for i in res["issues"] if i["type"] == "wikilink"]
        self.assertEqual(len(wikis), 1)
        self.assertIn("不存在的文档", wikis[0]["msg"])

    def test_style_flag(self):
        self.write_doc("s", created="2026-08-01", style="sanitized", body="调用 /api/v1/x")
        res = core.validate_doc(self.cfg(), "s", check_style=True)
        self.assertTrue(any(i["type"] == "style" for i in res["issues"]))
        self.assertEqual(res["style"], "sanitized")


class TestInitStore(MdocTestCase):
    def test_init_creates_dir_index_config(self):
        target = Path(self._tmp.name) / "newstore"
        res = core.init_store(str(target), index_file="INDEX.md")
        self.assertTrue(target.is_dir())
        self.assertTrue((target / "INDEX.md").is_file())
        self.assertTrue((target / ".mdoc.toml").is_file())
        self.assertTrue(res["index_created"])
        self.assertTrue(res["config_written"])

    def test_init_idempotent(self):
        target = Path(self._tmp.name) / "newstore"
        core.init_store(str(target))
        cfg_path = target / ".mdoc.toml"
        original = cfg_path.read_text(encoding="utf-8")
        res = core.init_store(str(target))
        self.assertFalse(res["index_created"])
        self.assertFalse(res["config_written"])  # 重跑不覆盖用户配置
        self.assertEqual(cfg_path.read_text(encoding="utf-8"), original)

    def test_init_generated_config_roundtrip(self):
        target = Path(self._tmp.name) / "newstore"
        core.init_store(str(target))
        cfg = core.load_config(store_override=str(target))
        self.assertEqual(cfg["index_file"], "INDEX.md")
        self.assertEqual(cfg["style_default"], "partial")


if __name__ == "__main__":
    unittest.main()

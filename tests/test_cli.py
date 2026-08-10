# -*- coding: utf-8 -*-
"""mdoc CLI 端到端测试（subprocess，零依赖）。"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Path(self._tmp.name) / "store"
        self.store.mkdir()
        env = os.environ.copy()
        env["MDOC_CONFIG"] = str(Path(self._tmp.name) / "nonexistent.toml")
        env["MDOC_DIR"] = str(self.store)
        self.env = env

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "mdoc.cli", *args],
            cwd=REPO,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def write_doc(self, name, created="2026-08-01", desc="", body="", type="reference"):
        content = "---\n" \
            f"name: {name}\n" \
            f"type: {type}\n" \
            f"description: \"{desc}\"\n" \
            f"created: {created}\n" \
            "---\n\n" + body + "\n"
        (self.store / f"{name}.md").write_text(content, encoding="utf-8")


class TestCliCommands(CliTestCase):
    def test_init(self):
        target = Path(self._tmp.name) / "newstore"
        r = self.run_cli("init", str(target))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("已初始化", r.stdout)

    def test_list_json(self):
        self.write_doc("a", created="2026-08-02")
        self.write_doc("b", type="project", created="2026-08-03")
        r = self.run_cli("list", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        obj = json.loads(r.stdout)
        self.assertEqual(obj["total"], 1)
        self.assertEqual(obj["docs"][0]["name"], "a")

    def test_list_names(self):
        self.write_doc("a")
        self.write_doc("b")
        r = self.run_cli("list", "--names")
        self.assertEqual(sorted(r.stdout.splitlines()), ["a", "b"])

    def test_search_json(self):
        self.write_doc("nginx 502", created="2026-08-02")
        self.write_doc("mysql", body="nginx 相关", created="2026-08-01")
        self.write_doc("其它", type="project", body="nginx")
        r = self.run_cli("search", "nginx", "--json")
        obj = json.loads(r.stdout)
        self.assertEqual(obj["total"], 2)
        self.assertEqual(obj["results"][0]["name"], "nginx 502")

    def test_get(self):
        self.write_doc("a", body="正文内容测试")
        r = self.run_cli("get", "a")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("正文内容测试", r.stdout)

    def test_get_missing(self):
        r = self.run_cli("get", "不存在")
        self.assertEqual(r.returncode, 1)
        self.assertIn("未找到", r.stderr)

    def test_delete_requires_yes(self):
        self.write_doc("a")
        r = self.run_cli("delete", "a")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--yes", r.stderr)
        self.assertTrue((self.store / "a.md").is_file())

    def test_delete_syncs_index(self):
        self.write_doc("a")
        # 先写入索引行，验证 delete 会清理它
        (self.store / "MEMORY.md").write_text(
            "- [a](a.md) — 保留测试\n\n- [b](b.md) — 另一条\n", encoding="utf-8")
        r = self.run_cli("delete", "a", "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.store / "a.md").exists())
        self.assertIn("索引已同步", r.stdout)
        remaining = (self.store / "MEMORY.md").read_text(encoding="utf-8")
        self.assertNotIn("a.md", remaining)
        self.assertIn("b.md", remaining)  # 其它行保留

    def test_slugify(self):
        r = self.run_cli("slugify", "MyFireflyBlog Nginx Config")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "myfireflyblog-nginx-config")

    def test_validate_json_and_exit(self):
        self.write_doc("bad", created="", body="见 [[不存在的文档]]")
        r = self.run_cli("validate", "bad", "--json")
        self.assertEqual(r.returncode, 1)
        obj = json.loads(r.stdout)
        self.assertTrue(any(i["type"] == "wikilink" for i in obj["issues"]))
        self.assertTrue(any(i["type"] == "frontmatter" for i in obj["issues"]))

    def test_config(self):
        r = self.run_cli("config", "--json")
        obj = json.loads(r.stdout)
        self.assertEqual(obj["store_dir"], str(self.store))


if __name__ == "__main__":
    unittest.main()

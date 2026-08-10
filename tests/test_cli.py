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

    def run_cli(self, *args, input=None):
        return subprocess.run(
            [sys.executable, "-m", "mdoc.cli", *args],
            cwd=REPO,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            input=input,
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

    def test_init_json(self):
        target = Path(self._tmp.name) / "newstore"
        r = self.run_cli("init", str(target), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        obj = json.loads(r.stdout)
        self.assertEqual(obj["store_dir"], str(target))
        self.assertTrue(obj["index_created"])
        self.assertTrue(obj["config_written"])

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


class TestCliCreateUpdate(CliTestCase):
    def create_json(self, **over):
        d = {
            "name": "nginx-502-fix",
            "description": "修复 502",
            "metadata": {"tags": ["nginx"], "created": "2026-08-10"},
            "sections": [{"title": "问题", "content": "出现 502。"}],
        }
        d.update(over)
        return json.dumps(d, ensure_ascii=False)

    def test_create_dry_run_no_write(self):
        r = self.run_cli("create", "--stdin", "--dry-run", input=self.create_json())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry-run", r.stdout)
        self.assertIn("## 问题", r.stdout)
        self.assertFalse((self.store / "nginx-502-fix.md").exists())

    def test_create_stdin_real_and_index_sync(self):
        r = self.run_cli("create", "--stdin", input=self.create_json())
        self.assertEqual(r.returncode, 0, r.stderr)
        f = self.store / "nginx-502-fix.md"
        self.assertTrue(f.is_file())
        content = f.read_text(encoding="utf-8")
        self.assertIn("name: nginx-502-fix", content)
        self.assertIn("## 问题", content)
        # 索引同步 + 可见于 list / search
        self.assertIn("nginx-502-fix.md", (self.store / "MEMORY.md").read_text(encoding="utf-8"))
        self.assertIn("nginx-502-fix", self.run_cli("list").stdout)
        self.assertIn("nginx-502-fix", self.run_cli("search", "502").stdout)

    def test_create_from_file(self):
        p = Path(self._tmp.name) / "doc.json"
        p.write_text(self.create_json(), encoding="utf-8")
        r = self.run_cli("create", str(p))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.store / "nginx-502-fix.md").is_file())

    def test_create_invalid_schema(self):
        r = self.run_cli("create", "--stdin", input=self.create_json(sections=[]))
        self.assertEqual(r.returncode, 1)
        self.assertIn("sections", r.stderr)

    def test_create_requires_input(self):
        r = self.run_cli("create")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--stdin", r.stderr)

    def test_create_conflict(self):
        self.run_cli("create", "--stdin", input=self.create_json())
        r = self.run_cli("create", "--stdin", input=self.create_json())
        self.assertEqual(r.returncode, 1)
        self.assertIn("已存在", r.stderr)

    def test_create_json_dry_run_output(self):
        r = self.run_cli("create", "--stdin", "--dry-run", "--json", input=self.create_json())
        obj = json.loads(r.stdout)
        self.assertTrue(obj["dry_run"])
        self.assertEqual(obj["file"], "nginx-502-fix.md")
        self.assertFalse(obj["exists"])

    def test_update_stdin_append(self):
        self.run_cli("create", "--stdin", input=self.create_json())
        patch = json.dumps({"ops": [{"op": "append", "title": "方案", "content": "重启 nginx"}]},
                           ensure_ascii=False)
        r = self.run_cli("update", "nginx-502-fix", "--stdin", input=patch)
        self.assertEqual(r.returncode, 0, r.stderr)
        content = (self.store / "nginx-502-fix.md").read_text(encoding="utf-8")
        self.assertIn("## 方案\n\n重启 nginx", content)
        self.assertIn("## 问题\n\n出现 502。", content)

    def test_update_dry_run_no_write(self):
        self.run_cli("create", "--stdin", input=self.create_json())
        patch = json.dumps({"ops": [{"op": "append", "title": "方案", "content": "x"}]}, ensure_ascii=False)
        r = self.run_cli("update", "nginx-502-fix", "--stdin", "--dry-run", input=patch)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("## 方案", (self.store / "nginx-502-fix.md").read_text(encoding="utf-8"))

    def test_update_description_syncs_index(self):
        self.run_cli("create", "--stdin", input=self.create_json())
        patch = json.dumps({"description": "新描述 502"}, ensure_ascii=False)
        r = self.run_cli("update", "nginx-502-fix", "--stdin", input=patch)
        self.assertEqual(r.returncode, 0, r.stderr)
        idx = (self.store / "MEMORY.md").read_text(encoding="utf-8")
        self.assertIn("新描述 502", idx)
        self.assertNotIn("修复 502", idx)

    def test_update_missing_doc(self):
        r = self.run_cli("update", "不存在", "--stdin", input="{}")
        self.assertEqual(r.returncode, 1)
        self.assertIn("未找到", r.stderr)

    def test_update_invalid_patch(self):
        self.run_cli("create", "--stdin", input=self.create_json())
        r = self.run_cli("update", "nginx-502-fix", "--stdin", input='{"ops": [{"op": "nope"}]}')
        self.assertEqual(r.returncode, 1)
        self.assertIn("op", r.stderr)

    def test_create_force_overwrites(self):
        self.run_cli("create", "--stdin", input=self.create_json())
        r = self.run_cli("create", "--stdin", "--force", input=self.create_json(description="覆盖版描述"))
        self.assertEqual(r.returncode, 0, r.stderr)
        content = (self.store / "nginx-502-fix.md").read_text(encoding="utf-8")
        self.assertIn("覆盖版描述", content)
        # 描述已覆盖，索引行同步为新描述
        idx = (self.store / "MEMORY.md").read_text(encoding="utf-8")
        self.assertIn("覆盖版描述", idx)

    def test_update_replace_missing_title_exits_1(self):
        self.run_cli("create", "--stdin", input=self.create_json())
        patch = json.dumps({"ops": [{"op": "replace", "title": "不存在的章节", "content": "x"}]},
                           ensure_ascii=False)
        r = self.run_cli("update", "nginx-502-fix", "--stdin", input=patch)
        self.assertEqual(r.returncode, 1)
        self.assertIn("未找到章节", r.stderr)
        # 不落盘
        content = (self.store / "nginx-502-fix.md").read_text(encoding="utf-8")
        self.assertIn("## 问题", content)
        self.assertNotIn("## 不存在的章节", content)

    def test_update_same_description_noop(self):
        self.run_cli("create", "--stdin", input=self.create_json())
        before = (self.store / "MEMORY.md").read_text(encoding="utf-8")
        patch = json.dumps({"description": "修复 502"}, ensure_ascii=False)  # 与 create 时相同
        r = self.run_cli("update", "nginx-502-fix", "--stdin", input=patch)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("无实际变更", r.stdout)
        self.assertEqual((self.store / "MEMORY.md").read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()

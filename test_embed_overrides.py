import json
import tempfile
import unittest
from pathlib import Path

from scripts import apply_embed_overrides as ao

BOOKS = [
    {"id": "9784000000001", "title": "作品A 1", "series_key": "作品A", "series_title": "作品A"},
    {"id": "9784000000002", "title": "作品B 1", "series_key": "作品B", "series_title": "作品B"},
]


def body(ops, extra=""):
    return "- 除外: 作品A\n\n```json\n" + json.dumps(ops, ensure_ascii=False) + "\n```\n" + extra


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "data").mkdir()
        (d / "data" / "books.json").write_text(json.dumps(BOOKS), encoding="utf-8")
        self.cfg = d / "ov.json"
        self.cfg.write_text(json.dumps({"exclude": [], "exclude_series": [], "include": []}), encoding="utf-8")
        self.d = d

    def tearDown(self):
        self.tmp.cleanup()

    def run_issue(self, text, title="[embed-overrides] 除外 1件"):
        ev = self.d / "event.json"
        ev.write_text(json.dumps({"issue": {"title": title, "body": text, "number": 5}}), encoding="utf-8")
        res = self.d / "res.txt"
        ok, msg = ao.run(ev, self.cfg, self.d / "data", "2026-11-22", res)
        self.assertEqual(res.read_text(encoding="utf-8"), msg)
        return ok, msg

    def ov(self):
        return json.loads(self.cfg.read_text(encoding="utf-8"))

    def test_exclude_and_include_added_with_date(self):
        ok, msg = self.run_issue(body({"exclude": [{"id": "9784000000001", "title": "x"}],
                                       "include": [{"id": "9784000000002", "title": "y"}],
                                       "exclude_series": [{"series_key": "作品B", "title": "z"}]}))
        self.assertTrue(ok, msg)
        o = self.ov()
        self.assertEqual(o["exclude"], [{"id": "9784000000001", "title": "作品A 1", "added": "2026-11-22"}])  # 題名は data 側の値
        self.assertEqual(o["include"][0]["id"], "9784000000002")
        self.assertEqual(o["exclude_series"][0]["series_key"], "作品B")

    def test_duplicates_not_added(self):
        ops = {"exclude": [{"id": "9784000000001"}]}
        self.run_issue(body(ops))
        ok, msg = self.run_issue(body(ops))
        self.assertTrue(ok)
        self.assertEqual(len(self.ov()["exclude"]), 1)
        self.assertIn("反映済み", msg)

    def test_remove_exclude(self):
        self.run_issue(body({"exclude": [{"id": "9784000000001"}], "exclude_series": [{"series_key": "作品B"}]}))
        ok, _ = self.run_issue(body({"remove_exclude": [{"id": "9784000000001"}], "remove_exclude_series": [{"series_key": "作品B"}]}))
        self.assertTrue(ok)
        o = self.ov()
        self.assertEqual((o["exclude"], o["exclude_series"]), ([], []))

    def test_invalid_leaves_config_untouched(self):
        before = self.cfg.read_text(encoding="utf-8")
        cases = [
            body({"exclude": [{"id": "9780000000000"}]}),                       # 存在しない id
            body({"exclude_series": [{"series_key": "無い作品"}]}),             # 存在しない series_key
            "JSON ブロックのない本文",
            body({"exclude": [{"id": "9784000000001", "title": "あ" * 300}]}),  # 長すぎる
            body({"exclude": [{"id": "9784000000001"}] * 101}),                 # 件数超過
            body({"unknown": []}),
            body({}),                                                          # 0件
            "```json\n{broken\n```",
        ]
        for c in cases:
            ok, msg = self.run_issue(c)
            self.assertFalse(ok, c[:40])
            self.assertTrue(msg)
            self.assertEqual(self.cfg.read_text(encoding="utf-8"), before)

    def test_limit_100_ok(self):
        ok, _ = self.run_issue(body({"exclude": [{"id": "9784000000001"}] * 100}))
        self.assertTrue(ok)

    def test_title_prefix_required(self):
        ok, _ = self.run_issue(body({"exclude": [{"id": "9784000000001"}]}), title="別のIssue")
        self.assertFalse(ok)


class WorkflowTest(unittest.TestCase):
    def test_workflow_guards(self):
        t = (Path(__file__).parent / ".github/workflows/embed-overrides.yml").read_text(encoding="utf-8")
        self.assertIn("github.event.issue.user.login == 'netafull'", t)
        self.assertIn("startsWith(github.event.issue.title, '[embed-overrides]')", t)
        self.assertIn("group: update", t)
        self.assertNotIn("event.issue.body", t)  # 本文をシェル・式に展開しない


if __name__ == "__main__":
    unittest.main()

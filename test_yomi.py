import datetime
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import build
import yomi

D = datetime.date


def bk(key, date, isbn):
    return {"series_key": key, "release_date": date, "isbn13": isbn}


def item(key):
    """openBD の応答の形を写した小さなJSON。"""
    return {"onix": {"DescriptiveDetail": {"TitleDetail": {"TitleType": "01", "TitleElement": {
        "TitleElementLevel": "01", "TitleText": {"content": "x", "collationkey": key}}}}}}


class NormalizeTest(unittest.TestCase):
    def test_volume_and_parens(self):
        self.assertEqual(yomi.normalize_yomi("アオノミブロ シンセングミヘン(013)"), "アオノミブロシンセングミヘン")
        self.assertEqual(yomi.normalize_yomi("ヒャクダイヘイキフ（001）"), "ヒャクダイヘイキフ")
        self.assertEqual(yomi.normalize_yomi("セイジョサマノカイネコ01"), "セイジョサマノカイネコ")
        self.assertEqual(yomi.normalize_yomi("セイジョサマノカイネコ０１"), "セイジョサマノカイネコ")

    def test_note(self):
        self.assertEqual(yomi.normalize_yomi("ヨアケヲコウケモノタチ006デンシゲンテイオマケツキ"), "ヨアケヲコウケモノタチ")

    def test_trailing_edition_note(self):
        self.assertEqual(yomi.normalize_yomi("ハルノアラシショウサッシツキトクソウバン"), "ハルノアラシ")
        self.assertEqual(yomi.normalize_yomi("アイウトクソウバン"), "アイウ")

    def test_hiragana_and_spaces(self):
        self.assertEqual(yomi.normalize_yomi("さる もの わ ひび に うとし"), "サルモノワヒビニウトシ")

    def test_rejects_non_kana_start(self):
        self.assertIsNone(yomi.normalize_yomi("1ポンドノフクイン"))
        self.assertIsNone(yomi.normalize_yomi("Dr.STONE"))
        self.assertIsNone(yomi.normalize_yomi("(013)"))
        self.assertIsNone(yomi.normalize_yomi(None))

    def test_digit_inside_kept(self):
        self.assertEqual(yomi.normalize_yomi("ナンバー3ノオトコ12"), "ナンバー3ノオトコ")

    def test_extract_prefers_product_title(self):
        it = {"onix": {"DescriptiveDetail": {"TitleDetail": {"TitleElement": [
            {"TitleElementLevel": "02", "TitleText": {"collationkey": "シリーズ"}},
            {"TitleElementLevel": "01", "TitleText": {"collationkey": "ホンタイ"}}]}}}}
        self.assertEqual(yomi.extract_collationkey(it), "ホンタイ")
        self.assertIsNone(yomi.extract_collationkey({"onix": {}}))


class RunTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.p = Path(self._t.name) / "yomi.json"
        self.calls = []

    def tearDown(self):
        self._t.cleanup()

    def fetcher(self, table, fail_at=None):
        def f(isbns):
            self.calls.append(list(isbns))
            if fail_at is not None and len(self.calls) >= fail_at:
                raise yomi.Stop("HTTP 429")
            return {i: table.get(i) for i in isbns}
        return f

    def run_(self, books, table, today, **kw):
        with redirect_stdout(io.StringIO()):
            return yomi.run(books, self.p, today, manual=kw.pop("manual", {}), fetch=self.fetcher(table, kw.pop("fail_at", None)), **kw)

    def test_got_and_not_requeried(self):
        books = [bk("A", "2026-11-10", "111")]
        st = self.run_(books, {"111": "アイウ(001)"}, D(2026, 11, 21))
        self.assertEqual((st["queries"], st["got"]), (1, 1))
        e = json.loads(self.p.read_text())["A"]
        self.assertEqual(e, {"yomi": "アイウ", "source": "openbd", "isbn": "111", "checked": "2026-11-21"})
        self.run_(books, {"111": "ゼンゼンチガウ"}, D(2026, 11, 22))
        self.assertEqual(len(self.calls), 1)  # 取得済みは再問い合わせしない
        self.assertEqual(json.loads(self.p.read_text())["A"]["yomi"], "アイウ")

    def test_batches_and_oldest_first(self):
        books = [bk("A", "2026-11-10", "new"), bk("A", "2026-05-10", "old")]
        self.run_(books, {"old": "アイ"}, D(2026, 11, 21))
        self.assertEqual(self.calls, [["old"]])
        books2 = [bk("K%d" % i, "2026-11-10", "i%d" % i) for i in range(150)]
        self.run_(books2, {}, D(2026, 11, 21))
        self.assertEqual([len(c) for c in self.calls[1:]], [100, 50])

    def test_falls_back_to_next_book(self):
        books = [bk("A", "2026-05-10", "old"), bk("A", "2026-11-10", "new")]
        st = self.run_(books, {"new": "カキ"}, D(2026, 11, 21))
        self.assertEqual(self.calls, [["old"], ["new"]])
        self.assertEqual(st["got"], 1)

    def test_retry_before_release(self):
        books = [bk("A", "2026-12-04", "111")]
        self.run_(books, {}, D(2026, 11, 21))
        e = json.loads(self.p.read_text())["A"]
        self.assertEqual((e["yomi"], e["retry_after"]), (None, "2026-12-05"))
        n = len(self.calls)
        self.run_(books, {}, D(2026, 12, 4))       # まだ日が来ていない
        self.assertEqual(len(self.calls), n)
        self.run_(books, {"111": "ハヒ"}, D(2026, 12, 5))
        self.assertEqual(json.loads(self.p.read_text())["A"]["yomi"], "ハヒ")

    def test_retry_after_release_is_7_days(self):
        books = [bk("A", "2026-11-10", "111")]
        self.run_(books, {}, D(2026, 11, 21))
        self.assertEqual(json.loads(self.p.read_text())["A"]["retry_after"], "2026-11-28")

    def test_gives_up_after_60_days(self):
        books = [bk("A", "2026-09-01", "111")]
        self.p.write_text(json.dumps({"A": {"yomi": None, "checked": "2026-10-01", "retry_after": "2026-10-08"}}))
        self.run_(books, {"111": "アイ"}, D(2026, 11, 1))          # 発売から61日 → 問い合わせない
        self.assertEqual(self.calls, [])
        self.run_(books, {"111": "アイ"}, D(2026, 10, 30))         # 59日 → 問い合わせる
        self.assertEqual(len(self.calls), 1)

    def test_manual_skips_query(self):
        self.run_([bk("A", "2026-11-10", "111")], {}, D(2026, 11, 21), manual={"A": "アイ"})
        self.assertEqual(self.calls, [])

    def test_error_stops_and_keeps_state(self):
        books = [bk("K%d" % i, "2026-11-10", "i%03d" % i) for i in range(250)]
        table = {"i%03d" % i: "カナ" for i in range(250)}
        st = self.run_(books, table, D(2026, 11, 21), fail_at=2)
        self.assertEqual(len(self.calls), 2)                        # 2回目で失敗、3回目は呼ばない
        self.assertEqual(st["stopped"], "HTTP 429")
        saved = json.loads(self.p.read_text())
        self.assertEqual(len(saved), 100)                           # 1回目の分は残る
        self.assertTrue(all(v["yomi"] == "カナ" for v in saved.values()))

    def test_no_net(self):
        st = self.run_([bk("A", "2026-11-10", "111")], {}, D(2026, 11, 21), net=False)
        self.assertEqual(self.calls, [])
        self.assertTrue(st["stopped"])


class KanaRowTest(unittest.TestCase):
    def test_yomi_decides_row(self):
        self.assertEqual(build.kana_row("薬屋のひとりごと"), build.KANJI)
        self.assertEqual(build.kana_row("薬屋のひとりごと", "クスリヤノヒトリゴト"), "か")
        self.assertEqual(build.kana_row("ブルーロック", "ヴ"), "あ")
        self.assertEqual(build.kana_row("薬屋", None), build.KANJI)

    def test_manual_beats_state(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / "yomi.json").write_text(json.dumps({"S": {"yomi": "アイウ"}, "T": {"yomi": "サシス"}, "U": {"yomi": None}}))
            works = {n: {"series_key": n, "title": "漢字", "yomi": None} for n in "STUV"}
            orig = yomi.load_manual
            yomi.load_manual = lambda path=None: {"S": "ナニヌ"}
            try:
                build.apply_yomi(works, d)
            finally:
                yomi.load_manual = orig
            self.assertEqual([works[n]["yomi"] for n in "STUV"], ["ナニヌ", "サシス", None, None])


class CleanTailTest(unittest.TestCase):
    def test_slash_and_marks(self):
        self.assertEqual(yomi.normalize_yomi("ネガイアイ/ハジメテドウシノハジライユウギ"), "ネガイアイ")
        self.assertEqual(yomi.normalize_yomi("ヒカリノニワ~チョウコウシ~"), "ヒカリノニワ~チョウコウシ")
        self.assertEqual(yomi.normalize_yomi("リュウカリノナト-ドラゴン-"), "リュウカリノナト-ドラゴン")
        self.assertEqual(yomi.normalize_yomi("セット1-"), "セット")

    def test_volume_readings(self):
        self.assertIn("ヨン", yomi.volume_readings(4))
        self.assertIn("シ", yomi.volume_readings(4))
        self.assertIn("ニジュウサン", yomi.volume_readings(23))
        self.assertIn("ヒャクヨンジュウ", yomi.volume_readings(140))
        self.assertEqual(yomi.volume_readings(0), [])
        self.assertEqual(yomi.volume_readings(None), [])

    def test_strip_volume_kana(self):
        self.assertEqual(yomi.clean_tail("バカニコクハクサン", "バカに告白", 3), "バカニコクハク")
        self.assertEqual(yomi.clean_tail("ヒトリミデスイチ", "ひとりみです", 1), "ヒトリミデス")
        self.assertEqual(yomi.clean_tail("アクヤクレイジョウテンセイオジサンジュウイチ", "悪役令嬢転生おじさん", 11), "アクヤクレイジョウテンセイオジサン")
        self.assertEqual(yomi.clean_tail("オロカナテンシハアクマトオドルニジュウヨン", "愚かな天使は悪魔と踊る", 24), "オロカナテンシハアクマトオドル")
        self.assertEqual(yomi.clean_tail("ハルタヴォリュームヒャクヨンジュウ", "ハルタ", 140), "ハルタヴォリューム")
        self.assertEqual(yomi.clean_tail("スーパーラヴァーズダイ22カン", "SUPER LOVERS", 22), "スーパーラヴァーズ")

    def test_title_ending_in_same_sound_is_kept(self):
        self.assertEqual(yomi.clean_tail("タカミノタカミサン", "高みの鷹見さん", 3), "タカミノタカミサン")
        self.assertEqual(yomi.clean_tail("タカミノタカミサンサン", "高みの鷹見さん", 3), "タカミノタカミサン")
        self.assertEqual(yomi.clean_tail("コンヅクシ", "こんづくし", 4), "コンヅクシ")
        self.assertEqual(yomi.clean_tail("ジョリク", "じょりく!", 9), "ジョリク")
        # 1音の読み（シ）で題名が漢字終わり（〜話→ハナシ）は削らない
        self.assertEqual(yomi.clean_tail("ダレカノハナシ", "誰かの話", 4), "ダレカノハナシ")
        # 別の巻の読みで終わっていても削らない
        self.assertEqual(yomi.clean_tail("ウェイバーズニ", "ウェイバーズ", 5), "ウェイバーズニ")

    def test_digits_not_in_title(self):
        self.assertEqual(yomi.clean_tail("マセキグルメ14マモノノチカラヲ", "魔石グルメ", 14), "マセキグルメ")
        self.assertEqual(yomi.clean_tail("ヒャクオクコン", "100億婚", 1), "ヒャクオクコン")
        self.assertEqual(yomi.clean_tail("ナンバー3ノオトコ", "ナンバー3の男", 2), "ナンバー3ノオトコ")   # 題名自体の数字は残す
        self.assertEqual(yomi.clean_tail("クスリヤ23ポストカードブック", "薬屋", 23), "クスリヤ")
        self.assertEqual(yomi.clean_tail("ツウカクタンテイVOLUME2TWO", "痛覚探偵", 2), "ツウカクタンテイ")

    def test_idempotent(self):
        once = yomi.clean_tail("バカニコクハクサン", "バカに告白", 3)
        self.assertEqual(yomi.clean_tail(once, "バカに告白", 3), once)

    def test_run_applies_clean_tail(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "yomi.json"
            books = [{"series_key": "A", "series_title": "バカに告白", "volume": 3, "release_date": "2026-11-10", "isbn13": "111"}]
            with redirect_stdout(io.StringIO()):
                yomi.run(books, p, D(2026, 11, 21), manual={}, fetch=lambda isbns: {i: "バカニコクハクサン" for i in isbns})
            self.assertEqual(json.loads(p.read_text())["A"]["yomi"], "バカニコクハク")


class RenormalizeScriptTest(unittest.TestCase):
    def test_renormalize(self):
        import importlib
        sc = importlib.import_module("scripts.renormalize_yomi_20261122")
        books = [
            {"series_key": "A", "series_title": "バカに告白", "volume": 3, "isbn13": "111"},
            {"series_key": "B", "series_title": "ネガイアイ", "volume": None, "isbn13": "222"},
        ]
        state = {
            "A": {"yomi": "バカニコクハクサン", "source": "openbd", "isbn": "111", "checked": "x"},
            "B": {"yomi": "ネガイアイ/ハジメテ", "source": "openbd", "isbn": "222", "checked": "x"},
            "C": {"yomi": "ムカシノキー", "source": "openbd", "isbn": "333", "checked": "x"},
            "A2": {"yomi": None, "checked": "x"},
        }
        new, changes, dead = sc.renormalize(state, books)
        self.assertEqual(new["A"]["yomi"], "バカニコクハク")
        self.assertEqual(new["A"]["isbn"], "111")
        self.assertEqual(new["B"]["yomi"], "ネガイアイ")
        self.assertEqual(sorted(dead), ["A2", "C"])
        self.assertEqual(len(changes), 2)
        again, ch2, _ = sc.renormalize(new, books)
        self.assertEqual((again, ch2), (new, []))
        self.assertEqual(state["A"]["yomi"], "バカニコクハクサン")  # 元は書き換えない


class ManualTest(unittest.TestCase):
    def test_manual_file_wins_and_keys_exist(self):
        man = yomi.load_manual()
        self.assertEqual(man.get("MAMBA"), "マンバ")
        self.assertTrue(all(v and v[0] >= "ァ" for v in man.values()))
        works = {"M": {"series_key": "MAMBA", "title": "MAMBA", "yomi": None}}
        build.apply_yomi(works, Path(tempfile.mkdtemp()))
        self.assertEqual(works["M"]["yomi"], "マンバ")


if __name__ == "__main__":
    unittest.main()

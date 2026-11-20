"""日次パイプライン（update.py）の安全装置のテスト。ネットワークには出ない（すべてモック）。"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "scripts"))
import datetime

import amazon
import build_backbone
import common
import enrich
import parse_pub as pp
import pubfetch
import update
import scan_kodansha

TODAY = datetime.date(2026, 11, 20)
FAKE_ENV = {"CREATORSAPI_CREDENTIAL_ID": "dummy-id-for-test", "CREATORSAPI_CREDENTIAL_SECRET": "dummy-secret-for-test",
            "CREATORSAPI_PARTNER_TAG": "dummy-22"}


class AmazonBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        t = Path(self._tmp.name)
        self._saved = (amazon.USAGE, amazon.LOG, amazon.CACHE, amazon.GAP, amazon._http_post, amazon._token,
                       {k: os.environ.get(k) for k in FAKE_ENV}, os.environ.get("SHINKAN_TODAY"))
        amazon.USAGE, amazon.LOG, amazon.CACHE = t / "api_usage.json", t / "log.jsonl", t / "cache"
        amazon.GAP = 0
        amazon._token = lambda: "tok"
        os.environ.update(FAKE_ENV)
        os.environ["SHINKAN_TODAY"] = TODAY.isoformat()
        amazon.reset_run()
        self.sent = []

    def tearDown(self):
        (amazon.USAGE, amazon.LOG, amazon.CACHE, amazon.GAP, amazon._http_post, amazon._token, env, td) = self._saved
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if td is None:
            os.environ.pop("SHINKAN_TODAY", None)
        else:
            os.environ["SHINKAN_TODAY"] = td
        amazon.reset_run()
        self._tmp.cleanup()

    def mock_http(self, status=200, payload=None):
        def f(url, body):
            self.sent.append(body)
            return status, payload if payload is not None else {"itemsResult": {"items": []}}
        amazon._http_post = f


class CapTest(AmazonBase):
    def test_default_cap_is_260(self):
        self.assertEqual(amazon.DAILY_CAP, 260)  # 共有枠。2026-11-21 にオーナーが200→260を承認。確認なしに上げない

    def test_cap_checked_before_every_call(self):
        self.mock_http()
        amazon.USAGE.write_text(json.dumps({TODAY.isoformat(): amazon.DAILY_CAP - 1}))
        amazon.get_items(["4098736225"])               # 199 -> 200 回目は通る
        self.assertEqual(len(self.sent), 1)
        with self.assertRaises(amazon.Stop):
            amazon.get_items(["4098736226"])           # 200 到達済み
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(amazon.calls_today(), amazon.DAILY_CAP)
        with self.assertRaises(amazon.Stop):           # 停止後は以後ずっと呼ばない
            amazon.get_items(["4098736227"])
        self.assertEqual(len(self.sent), 1)

    def test_429_stops_rest_of_run(self):
        self.mock_http(429, {})
        with self.assertRaises(amazon.Stop):
            amazon.get_items(["4098736225"])
        self.mock_http(200)
        with self.assertRaises(amazon.Stop):
            amazon.get_items(["4098736226"])
        self.assertEqual(len(self.sent), 1)            # 2回目は送っていない（1回目の429のみ）
        self.assertEqual(amazon.stopped_reason(), "HTTP 429")
        self.assertEqual(amazon.calls_today(), 1)

    def test_usage_is_per_day_and_trimmed(self):
        self.mock_http()
        amazon.USAGE.write_text(json.dumps({f"2026-10-{d:02d}": 5 for d in range(1, 31)}))
        amazon.get_items(["4098736225"])
        u = json.loads(amazon.USAGE.read_text())
        self.assertEqual(u[TODAY.isoformat()], 1)
        self.assertLessEqual(len(u), amazon.KEEP_DAYS)

    def test_search_never_sends_min_saving_percent(self):
        self.mock_http()
        amazon.search_items(keywords="講談社", browse_node_id="466280", sort_by="NewestArrivals")
        self.assertNotIn("minSavingPercent", json.dumps(self.sent))


def book(i, pub="小学館", date="2026-11-25", **kw):
    isbn13 = "97840987362" + str(20 + i)[-2:]
    return dict({"id": f"id{i}", "isbn13": None, "isbn10": None, "title": f"作品{i} {i}", "volume": i,
                 "series_key": f"作品{i}", "series_title": f"作品{i}", "author": "著者", "publisher": pub,
                 "label": "", "release_date": date, "source_url": "https://example.com/", "editions": []}, **kw)


class UpdateRunTest(AmazonBase):
    def setUp(self):
        super().setUp()
        self.data = Path(self._tmp.name) / "data"
        self.data.mkdir()
        # 窓内に発売で、Amazon未取得のISBN-10を持つ本
        b = book(1, isbn13="9784098736225", isbn10="4098736225")
        common.dump_records(self.data / "books.json", [b])
        self._run = build_backbone.run
        # 出版社の段はそのまま前回データを返す（ネットワークに出ない）
        build_backbone.run = lambda today, prev, net=True, use_cache=False, log=print: (prev, {"publishers": {}, "warnings": []})
        self.built = []

    def tearDown(self):
        build_backbone.run = self._run
        super().tearDown()

    def go(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            r = update.run(data_dir=self.data, today=TODAY, build_fn=lambda: self.built.append(1))
        return r, buf.getvalue()

    def test_429_still_builds_from_existing_data(self):
        self.mock_http(429, {})
        r, out = self.go()
        self.assertEqual(r["stopped"], "HTTP 429")
        self.assertEqual(r["run_calls"], 1)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.built, [1])
        self.assertEqual(len(json.loads((self.data / "books.json").read_text())), 1)
        self.assertIn("[update]", out)
        self.assertIn("amazon_calls=1", out)
        self.assertIn("stopped=HTTP 429", out)

    def test_no_credentials_skips_amazon(self):
        for k in FAKE_ENV:
            os.environ.pop(k, None)
        self.mock_http()
        r, out = self.go()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.built, [1])
        self.assertIn("WARNING", out)

    def test_credentials_never_printed_or_stored(self):
        self.mock_http()
        r, out = self.go()
        blob = out + "".join(p.read_text(encoding="utf-8") for p in self.data.iterdir())
        for v in FAKE_ENV.values():
            self.assertNotIn(v, blob)

    def test_cap_reached_before_run(self):
        self.mock_http()
        amazon.USAGE = self.data / "api_usage.json"
        (self.data / "api_usage.json").write_text(json.dumps({TODAY.isoformat(): amazon.DAILY_CAP}))
        r, out = self.go()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.built, [1])
        self.assertIn("上限", r["stopped"])

    def test_kodansha_scan_empty_keeps_previous(self):
        prev = [{"id": "9784065000001", "isbn13": "9784065000001", "isbn10": "4065000009", "title": "講談社の本 1",
                 "volume": 1, "series_key": "講談社の本", "series_title": "講談社の本", "author": "", "publisher": "講談社",
                 "label": "", "release_date": "2026-11-27", "source_url": None, "editions": []}]
        common.dump_records(self.data / "books_kodansha.json", prev)
        self.mock_http(200, {"itemsResult": {"items": []}, "searchResult": {"items": []}})
        r, out = self.go()
        kept = json.loads((self.data / "books_kodansha.json").read_text(encoding="utf-8"))
        self.assertEqual([b["isbn13"] for b in kept], ["9784065000001"])
        self.assertIn("0件", out)
        self.assertEqual(self.built, [1])


class PublisherFailureTest(unittest.TestCase):
    def setUp(self):
        self._fetch = pubfetch.fetch
        self._sho = pp.parse_shogakukan

    def tearDown(self):
        pubfetch.fetch = self._fetch
        pp.parse_shogakukan = self._sho

    def prev(self):
        return [book(1, "小学館", "2026-11-25", id="s-nov"), book(2, "小学館", "2026-12-10", id="s-dec"),
                book(3, "秋田書店", "2026-12-08", id="a-dec"), book(4, "白泉社", "2026-12-05", id="h-dec"),
                book(5, "小学館", "2026-11-05", id="s-past")]

    def test_all_sites_fail_keeps_everything(self):
        pubfetch.fetch = lambda url, net=True, use_cache=True: "<html></html>"   # レイアウト変更（0件/例外）
        prev = self.prev()
        out, rep = build_backbone.run(TODAY, prev, log=lambda m: None)
        self.assertEqual({b["id"] for b in out}, {b["id"] for b in prev})
        self.assertTrue(rep["warnings"])
        self.assertFalse(any(v["ok"] for v in rep["publishers"].values()))

    def test_fetch_returns_none_keeps_everything(self):
        pubfetch.fetch = lambda url, net=True, use_cache=True: None
        prev = self.prev()
        out, rep = build_backbone.run(TODAY, prev, log=lambda m: None)
        self.assertEqual(len(out), len(prev))

    def test_one_site_down_others_update(self):
        def fetch(url, net=True, use_cache=True):
            return "OK-SHO" if url == pp.SHOGAKUKAN_URLS[1] else "<html></html>"
        new = {"isbn13": "9784098736225", "title_raw": "新作 1", "author": "新", "publisher": "小学館", "label": "",
               "release_date": "2026-12-20", "source_url": pp.SHOGAKUKAN_BASE}
        pubfetch.fetch = fetch
        pp.parse_shogakukan = lambda h: [dict(new)] if h == "OK-SHO" else (_ for _ in ()).throw(ValueError("x"))
        out, rep = build_backbone.run(TODAY, self.prev(), log=lambda m: None)
        ids = {b["id"] for b in out}
        self.assertIn("9784098736225", ids)       # 成功したページの月(12月)は置き換わる
        self.assertNotIn("s-dec", ids)
        self.assertIn("s-nov", ids)               # 失敗した月(11月)は前回を保持
        self.assertIn("s-past", ids)              # 過去日付は残る
        self.assertIn("a-dec", ids)               # 他の出版社は前回を保持
        self.assertIn("h-dec", ids)
        self.assertTrue(rep["publishers"]["小学館"]["ok"])
        self.assertFalse(rep["publishers"]["秋田書店"]["ok"])

    def test_kodansha_host_refused(self):
        with self.assertRaises(RuntimeError):
            pubfetch.fetch("https://kodansha.co.jp/x")


class TodayTest(unittest.TestCase):
    def test_today_is_jst(self):
        os.environ.pop("SHINKAN_TODAY", None)
        self.assertEqual(common.JST.utcoffset(None), datetime.timedelta(hours=9))


if __name__ == "__main__":
    unittest.main()


def raw_item(asin, title, manufacturer, pub, ean=None):
    """searchItems 応答の商品1件（slim が読む形）。"""
    return {"asin": asin, "detailPageURL": "https://example.com/" + asin,
            "itemInfo": {"title": {"displayValue": title},
                         "byLineInfo": {"manufacturer": {"displayValue": manufacturer}, "contributors": [{"name": "著者"}]},
                         "contentInfo": {"publicationDate": {"displayValue": pub}},
                         "externalIds": {"eans": {"displayValues": [ean]}} if ean else {}}}


class ShueishaScanTest(AmazonBase):
    def scan(self, items, max_calls=60):
        # 1ページ目に固定の商品を返し、以後は空。呼び出しごとに本文を記録する
        def f(url, body):
            self.sent.append(body)
            page = body.get("itemPage", 1)
            return 200, {"searchResult": {"items": items if page == 1 else []}}
        amazon._http_post = f
        store, found = {"items": {}, "invalid": []}, {}
        n = scan_kodansha.scan_shueisha(store, TODAY, max_calls, found, log=lambda *_: None)
        return n, store, found

    def test_manufacturer_and_date_window(self):
        items = [raw_item("4088800001", "集英作品 1 (ジャンプコミックス)", "集英社", "2026-11-25", "9784088800004"),
                 raw_item("4065000009", "講談作品 1", "講談社", "2026-11-25", "9784065000001"),
                 raw_item("4088800002", "範囲外(未来)", "集英社", "2027-03-01", "9784088800028"),
                 raw_item("4088800003", "範囲外(過去)", "集英社", "2026-11-01", "9784088800035"),
                 raw_item("4088800004", "窓の端(今日-7)", "集英社", "2026-11-13", "9784088800042")]
        n, store, found = self.scan(items)
        self.assertEqual(sorted(found), ["4088800001", "4088800004"])
        self.assertEqual(sorted(store["items"]), ["4088800001", "4088800004"])  # 他社・範囲外は保存しない
        self.assertEqual(n, len(self.sent))

    def test_stops_paging_when_older_than_window_and_respects_budget(self):
        old = [raw_item("4088800009", "古い", "集英社", "2026-10-01", "9784088800097")]
        n, _, found = self.scan(old)
        self.assertEqual(found, {})
        self.assertEqual(n, len(scan_kodansha.SHUEISHA_IMPRINTS))  # キーワードごとに1ページで打ち切り
        import shutil
        shutil.rmtree(amazon.CACHE, ignore_errors=True)  # 応答キャッシュ命中は呼び出しに数えないため消す
        amazon.reset_run()
        n2, _, _ = self.scan(old, max_calls=3)
        self.assertEqual(n2, 3)

    def test_shueisha_book_record(self):
        s = amazon.slim(raw_item("4088800001", "集英作品(3) (ジャンプコミックス)", "集英社", "2026-11-25", "9784088800004"), "2026-11-20")
        b = enrich.kodansha_book(s, "集英社")
        self.assertEqual((b["publisher"], b["volume"], b["label"]), ("集英社", 3, "ジャンプコミックス"))
        self.assertEqual(b["source_note"], "Amazon の商品情報より")
        self.assertIsNone(enrich.kodansha_book(amazon.slim(raw_item("B0XXXXXXXX", "電子のみ 1", "集英社", "2026-11-25")), "集英社"))


class BudgetSplitTest(unittest.TestCase):
    def test_step_budgets_fit_daily_cap(self):
        total = (update.SCAN_MAX_CALLS + update.SCAN_SHUEISHA_MAX_CALLS + update.ENRICH_MAX_CALLS
                 + update.REFRESH_MAX_CALLS)
        self.assertEqual(update.SCAN_SHUEISHA_MAX_CALLS, 60)
        self.assertLessEqual(total, amazon.DAILY_CAP)


class ShueishaUpdateTest(UpdateRunTest):
    def test_shueisha_scan_runs_separately_and_is_logged(self):
        self.mock_http(200, {"itemsResult": {"items": []}, "searchResult": {"items": [
            raw_item("4088800001", "集英作品 1 (ジャンプコミックス)", "集英社", "2026-11-25", "9784088800004")]}})
        r, out = self.go()
        saved = json.loads((self.data / "books_shueisha.json").read_text(encoding="utf-8"))
        self.assertEqual([b["publisher"] for b in saved], ["集英社"])
        self.assertEqual(r["shueisha"], 1)
        self.assertGreater(r["calls"]["shueisha"], 0)
        self.assertLessEqual(r["calls"]["shueisha"], update.SCAN_SHUEISHA_MAX_CALLS)
        self.assertIn("shueisha=", out)

    def test_shueisha_empty_keeps_previous(self):
        prev = [{"id": "9784088800004", "isbn13": "9784088800004", "isbn10": "4088800001", "title": "集英作品 1",
                 "volume": 1, "series_key": "集英作品", "series_title": "集英作品", "author": "", "publisher": "集英社",
                 "label": "", "release_date": "2026-11-27", "source_url": None, "editions": []}]
        common.dump_records(self.data / "books_shueisha.json", prev)
        self.mock_http(200, {"itemsResult": {"items": []}, "searchResult": {"items": []}})
        r, out = self.go()
        kept = json.loads((self.data / "books_shueisha.json").read_text(encoding="utf-8"))
        self.assertEqual([b["isbn13"] for b in kept], ["9784088800004"])
        self.assertIn("集英社の新着が0件", out)

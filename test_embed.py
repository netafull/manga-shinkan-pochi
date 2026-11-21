import datetime
import re
import tempfile
import unittest
from pathlib import Path

import amazon
import embed_pages
import embed_safety as es

RULES = es.load_rules()
NO_OV = {"exclude": [], "exclude_series": [], "include": []}


def book(**kw):
    b = {"id": "9784000000001", "isbn10": "4000000001", "title": "テスト作品 1", "volume": 1,
         "series_key": "テスト作品", "series_title": "テスト作品", "publisher": "小学館", "label": "",
         "release_date": "2026-11-25", "author": "作者"}
    b.update(kw)
    return b


def item(**kw):
    i = {"asin": "4000000001", "url": "https://www.amazon.co.jp/dp/4000000001?tag=t-22", "title": "テスト作品(1) (ビッグコミックス)",
         "image": "https://m.media-amazon.com/images/I/x.jpg", "adult": False}
    i.update(kw)
    return i


def ov(**kw):
    o = dict(NO_OV)
    o.update(kw)
    return o


class JudgeTest(unittest.TestCase):
    def test_plain_ok_with_cover(self):
        self.assertEqual(es.judge(book(), item(), RULES, NO_OV)[:2], (True, True))

    def test_adult_true_excluded(self):
        s, c, r = es.judge(book(), item(adult=True), RULES, NO_OV)
        self.assertFalse(s)
        self.assertIn("成人向け", r)

    def test_adult_missing_text_only(self):
        i = item()
        del i["adult"]
        self.assertEqual(es.judge(book(), i, RULES, NO_OV)[:2], (True, False))
        self.assertEqual(es.judge(book(), None, RULES, NO_OV)[:2], (True, False))

    def test_ng_label_on_book(self):
        s, _c, r = es.judge(book(label="花丸コミックス"), item(), RULES, NO_OV)
        self.assertFalse(s)
        self.assertIn("レーベル", r)

    def test_ng_label_from_title_parens(self):
        i = item(title="何か(3) (蜜猫コミックス)")
        self.assertFalse(es.judge(book(), i, RULES, NO_OV)[0])
        self.assertEqual(es.label_of(book(), item(title="作品(3) (ヤングマガジンKC)")), "ヤングマガジンKC")
        self.assertEqual(es.label_of(book(), item(title="作品 (12)")), "")  # 巻数の括弧はレーベルでない

    def test_keywords(self):
        for t in ("人気のR-18作品 1", "TL作品 2", "ふたりエッチ 96"):
            self.assertFalse(es.judge(book(title=t), item(), RULES, NO_OV)[0], t)

    def test_short_keyword_word_boundary(self):
        # TL / BL は英字の一部では当たらない
        self.assertTrue(es.judge(book(title="BLUE LOCK 1"), item(title="BLUE LOCK"), RULES, NO_OV)[0])
        self.assertTrue(es.judge(book(title="CATLOVE 1"), item(title="CATLOVE"), RULES, NO_OV)[0])

    def test_exclude_beats_everything(self):
        o = ov(exclude=[{"id": "9784000000001"}], include=[{"id": "9784000000001"}])
        s, _c, r = es.judge(book(), item(), RULES, o)
        self.assertFalse(s)
        self.assertIn("手動除外", r)

    def test_exclude_series(self):
        s, _c, r = es.judge(book(), item(), RULES, ov(exclude_series=[{"series_key": "テスト作品"}]))
        self.assertFalse(s)
        self.assertIn("作品ごと", r)

    def test_include_restores_auto_exclusion(self):
        b = book(label="花丸コミックス")
        self.assertFalse(es.judge(b, item(), RULES, NO_OV)[0])
        self.assertEqual(es.judge(b, item(), RULES, ov(include=[{"id": b["id"]}]))[:2], (True, True))

    def test_include_does_not_restore_adult(self):
        o = ov(include=[{"id": "9784000000001"}])
        self.assertFalse(es.judge(book(), item(adult=True), RULES, o)[0])


class SlimTest(unittest.TestCase):
    def raw(self, pi):
        r = {"asin": "4000000001", "detailPageURL": "u", "itemInfo": {"title": {"displayValue": "t"}}}
        if pi is not None:
            r["itemInfo"]["productInfo"] = pi
        return r

    def test_resource_requested(self):
        self.assertIn("itemInfo.productInfo", amazon.ITEM_RESOURCES)

    def test_adult_flag_saved(self):
        self.assertIs(amazon.slim(self.raw({"isAdultProduct": {"displayValue": True}}), "2026-11-21")["adult"], True)
        self.assertIs(amazon.slim(self.raw({"isAdultProduct": {"displayValue": False}}), "2026-11-21")["adult"], False)

    def test_adult_flag_absent(self):
        self.assertNotIn("adult", amazon.slim(self.raw(None), "2026-11-21"))
        self.assertNotIn("adult", amazon.slim(self.raw({}), "2026-11-21"))


class PagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.docs = Path(self.tmp.name)
        self.today = datetime.date(2026, 11, 21)
        a_ok = item()
        a_bl = item(title="X (花丸コミックス)", url="https://www.amazon.co.jp/dp/4000000002?tag=t-22")
        a_unk = item(url="https://www.amazon.co.jp/dp/4000000003?tag=t-22", title="Y(1) (ビッグコミックス)")
        del a_unk["adult"]
        self.books = [
            book(amazon=a_ok),
            book(id="9784000000002", title="除外される本 1", series_title="除外される本", series_key="除外される本", amazon=a_bl),
            book(id="9784000000003", title="文字だけの本 1", series_title="文字だけの本", series_key="文字だけの本",
                 publisher="秋田書店", amazon=a_unk),
            book(id="9784000000004", title="遠い未来 1", release_date="2027-06-01", amazon=a_ok),
        ]
        self.stats = embed_pages.write_all(self.docs, self.books, self.today, RULES, NO_OV)
        self.e = self.docs / "embed"

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, rel):
        return (self.e / rel).read_text(encoding="utf-8")

    def snippet(self, rel):
        h = self.read(rel)
        m = re.search(r'<h2>プレビュー</h2>\n(.*?)\n<h2>貼り付け用HTML', h, re.S)
        return m.group(1)

    def test_pages_exist_noindex_and_outside_range(self):
        for rel in ("2026-11-25/index.html", "2026-11-25/shogakukan/index.html", "2026-11-25/akitashoten/index.html",
                    "index.html", "review/index.html"):
            self.assertIn('<meta name="robots" content="noindex">', self.read(rel), rel)
        self.assertFalse((self.e / "2027-06-01").exists())
        self.assertFalse((self.e / "2026-11-25" / "kadokawa").exists())  # 本がない組み合わせは作らない

    def test_snippet_clean(self):
        for rel in ("2026-11-25/index.html", "2026-11-25/shogakukan/index.html"):
            s = self.snippet(rel)
            self.assertNotIn("<script", s)
            self.assertNotIn("class=", s)
            self.assertNotIn("<style", s)
            self.assertIn('rel="nofollow sponsored noopener"', s)
            self.assertIn("適格販売により収入を得ています", s)
            self.assertIn("https://shinkan.netaful.jp/date/2026-11-25/", s)
            for img in re.findall(r"<img[^>]*>", s):
                for attr in ("width=", "height=", "alt=", 'loading="lazy"'):
                    self.assertIn(attr, img)
        self.assertIn("11月25日（水）発売のマンガ（小学館）", self.snippet("2026-11-25/shogakukan/index.html"))

    def test_excluded_book_absent_and_cover_rule(self):
        h = self.read("2026-11-25/index.html")
        self.assertNotIn("除外される本", h)
        self.assertIn("テスト作品", h)
        s = self.snippet("2026-11-25/index.html")
        self.assertEqual(s.count("<img"), 1)  # adult 未取得の本は表紙なし
        self.assertIn("文字だけの本", s)

    def test_copy_page_notes_and_button(self):
        h = self.read("2026-11-25/index.html")
        self.assertIn("HTMLをコピー", h)
        self.assertIn("自動では更新されません", h)
        self.assertIn("<textarea", h)

    def test_json(self):
        import json
        d = json.loads(self.read("2026-11-25.json"))
        self.assertEqual(sorted(d["publishers"]), ["小学館", "秋田書店"])
        books = [b for v in d["publishers"].values() for b in v]
        self.assertEqual(len(books), 2)
        self.assertTrue(all(b["image"] is None for b in books if "文字だけ" in b["title"]))
        self.assertTrue(any(b["image"] for b in books))

    def test_review_shows_reasons(self):
        h = self.read("review/index.html")
        self.assertIn("自動除外：NGレーベル", h)
        self.assertIn("表紙なしで表示", h)
        self.assertIn("除外される本", h)

    def test_index_links(self):
        h = self.read("index.html")
        self.assertIn("/embed/2026-11-25/", h)
        self.assertIn("/embed/2026-11-25/shogakukan/", h)

    def test_not_in_sitemap(self):
        import build
        self.assertFalse(any(p.startswith("embed/") for p in build._pages))


if __name__ == "__main__":
    unittest.main()

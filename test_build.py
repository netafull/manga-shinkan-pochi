import datetime
import os
import tempfile
import unittest
from pathlib import Path

import build
import isbnlib
import parse_pub as pp

ROOT = Path(__file__).parent


class IsbnTest(unittest.TestCase):
    def test_wikipedia_example(self):
        # 978-0-306-40615-7 <-> 0-306-40615-2（Wikipediaの例）
        self.assertEqual(isbnlib.isbn13_to_isbn10("9780306406157"), "0306406152")
        self.assertEqual(isbnlib.isbn10_to_isbn13("0306406152"), "9780306406157")

    def test_x_check_digit(self):
        self.assertEqual(isbnlib.isbn10_to_isbn13("080442957X"), "9780804429573")
        self.assertEqual(isbnlib.isbn13_to_isbn10("9780804429573"), "080442957X")

    def test_shogakukan_isbn8(self):
        # Amazon getItemsで実在確認した 4098736225 (されど、ふたりはくされ恋 1)
        self.assertEqual(isbnlib.isbn13_from_isbn8("09873622"), "9784098736225")
        self.assertEqual(isbnlib.isbn13_to_isbn10("9784098736225"), "4098736225")

    def test_valid(self):
        self.assertTrue(isbnlib.valid_isbn13("9784098736225"))
        self.assertFalse(isbnlib.valid_isbn13("9784098736226"))


class TitleTest(unittest.TestCase):
    def test_plain_volume(self):
        self.assertEqual(pp.parse_title("青のオーケストラ　１６")[:2], ("青のオーケストラ", 16))

    def test_dai_kan(self):
        key, vol, _d, _f = pp.parse_title("氷結系こそ最強です！ 〜小さくて可愛い師匠〜 第5巻")
        self.assertEqual(vol, 5)
        self.assertTrue(key.startswith("氷結系こそ最強です!"))

    def test_edition(self):
        key, vol, _d, flags = pp.parse_title("薬屋のひとりごと～猫猫の後宮謎解き手帳～　２３　ポストカードブック付特装版")
        self.assertEqual(vol, 23)
        self.assertIn("特装版", flags)
        self.assertNotIn("特装版", key)
        self.assertNotIn("付", key)

    def test_leading_number_kept(self):
        key, vol, _d, _f = pp.parse_title("１００年の恋もさめなくて 2")
        self.assertEqual(vol, 2)
        self.assertTrue(key.startswith("100年"))

    def test_no_volume(self):
        self.assertIsNone(pp.parse_title("あくまでてんしです")[1])


class CacheParseTest(unittest.TestCase):
    """キャッシュ済みの実ページに対するパーサ検証（キャッシュが無ければスキップ）。"""

    def _page(self, url):
        import pubfetch
        h = pubfetch.fetch(url, allow_network=False)
        if h is None:
            self.skipTest("cache missing")
        return h

    def test_shogakukan(self):
        r = pp.parse_shogakukan(self._page(pp.SHOGAKUKAN_URLS[1]))
        self.assertGreater(len(r), 50)
        self.assertTrue(all(isbnlib.valid_isbn13(b["isbn13"]) for b in r))
        self.assertTrue(all(b["release_date"].startswith("2026-12") for b in r))

    def test_akita(self):
        r = pp.parse_akita(self._page(pp.AKITA_URL), today=datetime.date(2026, 11, 20))
        self.assertGreater(len(r), 30)
        self.assertTrue(all(isbnlib.valid_isbn13(b["isbn13"]) for b in r))

    def test_hakusensha(self):
        r = pp.parse_haku_month(self._page(pp.haku_url(2026, 12)))
        self.assertGreater(len(r), 10)
        self.assertNotIn("電子版のみ", {b["label"] for b in r})


class BuildSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["SHINKAN_TODAY"] = "2026-11-20"
        os.environ.pop("GA4_ID", None)
        cls._tmp = tempfile.TemporaryDirectory()
        cls.docs = Path(cls._tmp.name) / "docs"
        old = build.DOCS
        cls.books, cls.works = build.build(docs=cls.docs, write_lastmod=False)
        build.DOCS = old

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_pages_exist(self):
        for p in ["index.html", "404.html", "month/2026-12/index.html", "publisher/shogakukan/index.html",
                  "publisher/kodansha/index.html", "static/style.css"]:
            self.assertTrue((self.docs / p).exists(), p)
        d = self.books[0]["release_date"]
        self.assertTrue((self.docs / "date" / d / "index.html").exists())

    def test_top_has_affiliate_notice_and_sections(self):
        h = (self.docs / "index.html").read_text(encoding="utf-8")
        self.assertIn("アソシエイト", h)
        for s in ["今日発売", "今週", "来週"]:
            self.assertIn(s, h)

    def test_kodansha_source_wording(self):
        h = (self.docs / "publisher/kodansha/index.html").read_text(encoding="utf-8")
        self.assertIn("Amazon の商品情報より", h)
        self.assertNotIn("kodansha.co.jp", h)

    def test_work_page(self):
        w = next(iter(self.works.values()))
        h = (self.docs / "work" / w["slug"] / "index.html").read_text(encoding="utf-8")
        self.assertIn("<h1>", h)

    def test_nav_groups_and_h1(self):
        h = (self.docs / "index.html").read_text(encoding="utf-8")
        self.assertIn("発売日で探す", h)
        self.assertIn("出版社で探す", h)
        for a in ['href="/#today"', 'href="/#week"', 'href="/#nextweek"', 'href="/work/"']:
            self.assertIn(a, h)
        for i in ['id="today"', 'id="week"', 'id="nextweek"']:
            self.assertIn(i, h)
        self.assertEqual(h.count("<h1"), 1)
        self.assertIn("<h1>マンガ・コミック新刊の発売日一覧</h1>", h)
        self.assertIn("<title>マンガ新刊ポチ｜コミック新刊の発売日一覧（今日・今週・来週）</title>", h)

    def test_work_index_counts(self):
        h = (self.docs / "work/index.html").read_text(encoding="utf-8")
        self.assertEqual(h.count('<li><a href="/work/'), len(self.works))
        self.assertIn("作品一覧（%d作品）" % len(self.works), h)
        self.assertIn("漢字ではじまる作品", h)
        w = next(iter(self.works.values()))
        wp = (self.docs / "work" / w["slug"] / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="/work/">作品一覧', wp)

    def test_kana_row(self):
        self.assertEqual(build.kana_row("ブルーロック"), "は")
        self.assertEqual(build.kana_row("ゴッドマザー"), "か")
        self.assertEqual(build.kana_row("ぁ"), "あ")
        self.assertEqual(build.kana_row("100年の恋"), build.ALNUM)
        self.assertEqual(build.kana_row("ONE PIECE"), build.ALNUM)
        self.assertEqual(build.kana_row("薬屋のひとりごと"), build.KANJI)
        self.assertEqual(build.kana_row("『薬屋』"), build.KANJI)
        self.assertEqual(build.kana_row("★☆"), build.OTHER)

    def test_search_index(self):
        import json
        idx = json.loads((self.docs / "static/search.json").read_text(encoding="utf-8"))
        self.assertEqual(len(idx), len(self.works))
        self.assertEqual({x["s"] for x in idx}, set(self.works))
        for k in ("t", "a", "p", "s", "v", "d"):
            self.assertIn(k, idx[0])
        self.assertTrue((self.docs / "static/search.js").exists())
        h = (self.docs / "index.html").read_text(encoding="utf-8")
        self.assertIn('/static/search.js', h)
        self.assertIn('action="/work/"', h)

    def test_sitemap_robots_cname_404(self):
        sm = (self.docs / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("<loc>https://shinkan.netaful.jp/</loc>", sm)
        self.assertIn("<loc>https://shinkan.netaful.jp/month/2026-12/</loc>", sm)
        w = next(iter(self.works.values()))
        self.assertIn(f"<loc>https://shinkan.netaful.jp/work/{w['slug']}/</loc>", sm)
        self.assertIn("<lastmod>", sm)
        self.assertNotIn("404.html", sm)
        n_pages = len([p for p in self.docs.rglob("index.html")])
        self.assertEqual(sm.count("<url>"), n_pages)
        rb = (self.docs / "robots.txt").read_text(encoding="utf-8")
        self.assertIn("Sitemap: https://shinkan.netaful.jp/sitemap.xml", rb)
        self.assertEqual((self.docs / "CNAME").read_text(encoding="utf-8").strip(), "shinkan.netaful.jp")
        h404 = (self.docs / "404.html").read_text(encoding="utf-8")
        self.assertIn("ページが見つかりません", h404)

    def test_canonical_and_no_noindex(self):
        for p in self.docs.rglob("*.html"):
            h = p.read_text(encoding="utf-8")
            self.assertNotIn("noindex", h, p)
            if p.name == "404.html":
                continue
            rel = str(p.relative_to(self.docs))
            self.assertIn('<link rel="canonical" href="%s">' % build.canonical_of(rel), h, rel)
            self.assertIn('property="og:image"', h)
            self.assertIn('name="twitter:card"', h)

    def test_titles(self):
        h = (self.docs / "month/2026-12/index.html").read_text(encoding="utf-8")
        self.assertIn("<title>2026年12月発売のコミック新刊（マンガ）一覧｜マンガ新刊ポチ</title>", h)
        h = (self.docs / "date/2026-11-20/index.html").read_text(encoding="utf-8")
        self.assertIn("<title>11月20日発売のマンガ・コミック新刊｜マンガ新刊ポチ</title>", h)
        h = (self.docs / "publisher/kodansha/index.html").read_text(encoding="utf-8")
        self.assertIn("<title>講談社のコミック新刊 発売日一覧｜マンガ新刊ポチ</title>", h)
        w = next(w for w in self.works.values() if build.latest_book(w).get("volume"))
        h = (self.docs / "work" / w["slug"] / "index.html").read_text(encoding="utf-8")
        self.assertIn("最新刊%d巻の発売日" % build.latest_book(w)["volume"], h)
        self.assertIn('"@type":"ItemList"', h)
        self.assertIn('"@type":"Book"', h)

    def test_website_jsonld_on_top(self):
        h = (self.docs / "index.html").read_text(encoding="utf-8")
        self.assertIn('"@type":"WebSite"', h)

    def test_footer_series_and_notes(self):
        h = (self.docs / "index.html").read_text(encoding="utf-8")
        self.assertIn("関連サイト", h)
        self.assertIn("https://manga.netaful.jp/", h)
        self.assertIn("https://shinhatsubai.netaful.jp/", h)
        self.assertIn("ポチシリーズ一覧：", h)
        self.assertIn('href="https://pochi.netaful.jp/"', h)
        self.assertIn("非公式サイト", h)
        self.assertNotIn("試作", h)
        self.assertIn('/static/assets/logo.png', h)

    def test_assets(self):
        for n in ("logo.png", "favicon.png", "favicon.ico", "apple-touch-icon.png", "ogp.jpg"):
            self.assertTrue((self.docs / "static/assets" / n).exists(), n)

    def test_ga4_only_with_env(self):
        h = (self.docs / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("googletagmanager", h)
        os.environ["GA4_ID"] = "G-TEST123456"
        try:
            with tempfile.TemporaryDirectory() as t:
                old = build.DOCS
                try:
                    build.build(docs=Path(t) / "d", write_lastmod=False)
                    h2 = (Path(t) / "d/index.html").read_text(encoding="utf-8")
                finally:
                    build.DOCS = old
        finally:
            os.environ.pop("GA4_ID", None)
        self.assertIn("googletagmanager.com/gtag/js?id=G-TEST123456", h2)
        self.assertIn("gtag('config', 'G-TEST123456')", h2)

    def test_no_credentials_in_docs(self):
        for var in ("CREATORSAPI_CREDENTIAL_SECRET", "CREATORSAPI_CREDENTIAL_ID"):
            v = os.environ.get(var)
            if v:
                for p in self.docs.rglob("*.html"):
                    self.assertNotIn(v, p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

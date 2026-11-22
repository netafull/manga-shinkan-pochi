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


class CrumbsHelperTest(unittest.TestCase):
    def test_crumbs(self):
        html, ld = build.crumbs([("トップ", "/"), ("A&B", "/x/"), ("現在", None)])
        self.assertEqual(html, '<p class="crumbs"><a href="/">トップ</a> › <a href="/x/">A&amp;B</a> › 現在</p>')
        els = ld["itemListElement"]
        self.assertEqual(ld["@type"], "BreadcrumbList")
        self.assertEqual(els[0]["item"], build.SITE_URL + "/")
        self.assertEqual(els[1]["item"], build.SITE_URL + "/x/")
        self.assertEqual(els[2], {"@type": "ListItem", "position": 3, "name": "現在"})


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

    def test_feed_file_built(self):
        import json
        f = json.loads((self.docs / "feed.json").read_text(encoding="utf-8"))
        self.assertEqual(f["version"], 1)
        self.assertEqual(f["site"], "shinkan")
        self.assertLessEqual(len(f["items"]), 20)

    def test_pochi_latest_file_compact(self):
        import json
        h = (self.docs / "api" / "pochi-latest.json").read_text(encoding="utf-8")
        self.assertNotIn("\n", h)
        self.assertEqual(json.loads(h)["generated"], "2026-11-20")

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
        n_pages = len([p for p in self.docs.rglob("index.html") if "embed" not in p.relative_to(self.docs).parts])  # embed/ は noindex で sitemap 外
        self.assertEqual(sm.count("<url>"), n_pages)
        rb = (self.docs / "robots.txt").read_text(encoding="utf-8")
        self.assertIn("Sitemap: https://shinkan.netaful.jp/sitemap.xml", rb)
        self.assertEqual((self.docs / "CNAME").read_text(encoding="utf-8").strip(), "shinkan.netaful.jp")
        h404 = (self.docs / "404.html").read_text(encoding="utf-8")
        self.assertIn("ページが見つかりません", h404)

    def test_canonical_and_no_noindex(self):
        for p in self.docs.rglob("*.html"):
            if "embed" in p.relative_to(self.docs).parts:  # embed/ は noindex が正
                continue
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

    def _breadcrumb_ld(self, rel):
        import json
        import re
        h = (self.docs / rel).read_text(encoding="utf-8")
        for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', h):
            o = json.loads(m.group(1))
            if o.get("@type") == "BreadcrumbList":
                return h, o
        self.fail("BreadcrumbList がない: " + rel)

    def test_date_page_breadcrumb_has_month(self):
        d = self.books[0]["release_date"]
        h, o = self._breadcrumb_ld(f"date/{d}/index.html")
        self.assertIn(f'<a href="/month/{d[:7]}/">', h)
        self.assertIn('<p class="crumbs"><a href="/">トップ</a> › <a href="/month/', h)
        els = o["itemListElement"]
        self.assertEqual([e["position"] for e in els], [1, 2, 3])
        self.assertEqual(els[1]["item"], f"{build.SITE_URL}/month/{d[:7]}/")
        self.assertNotIn("item", els[2])

    def test_work_page_keeps_itemlist_and_breadcrumb(self):
        w = next(iter(self.works.values()))
        h, o = self._breadcrumb_ld(f"work/{w['slug']}/index.html")
        self.assertIn('"@type":"ItemList"', h)
        self.assertEqual([e["name"] for e in o["itemListElement"]][:3], ["トップ", "作品一覧", w["publisher"]])
        self.assertEqual(len(o["itemListElement"]), 4)

    def test_other_pages_have_breadcrumb_and_top_does_not(self):
        for rel in ("work/index.html", "publisher/shogakukan/index.html", "month/2026-12/index.html"):
            self._breadcrumb_ld(rel)
        self.assertNotIn("BreadcrumbList", (self.docs / "index.html").read_text(encoding="utf-8"))

    def test_no_credentials_in_docs(self):
        for var in ("CREATORSAPI_CREDENTIAL_SECRET", "CREATORSAPI_CREDENTIAL_ID"):
            v = os.environ.get(var)
            if v:
                for p in self.docs.rglob("*.html"):
                    self.assertNotIn(v, p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class PochiVerifyTest(unittest.TestCase):
    def c(self, author, pub, pa, site):
        import pochi_verify as pv
        return pv.classify(author, pub, pa, site)[0]

    def test_same_title_different_author_is_mismatch(self):
        self.assertEqual(self.c("甲野 乙男", "講談社", ["丙川丁子"], "マガポケ"), "mismatch")

    def test_author_overlap_confirmed(self):
        self.assertEqual(self.c("原作:山田 太郎 作画:鈴木 花子", "小学館", ["鈴木花子"], "サンデーうぇぶり"), "confirmed")
        self.assertEqual(self.c("ツジトモ / 綱本 将也", "講談社", ["綱本将也"], "マガポケ"), "confirmed")

    def test_publisher_only(self):
        self.assertEqual(self.c("誰か", "講談社", [], "コミックDAYS"), "publisher_consistent")

    def test_publisher_contradiction_is_mismatch(self):
        self.assertEqual(self.c("誰か", "白泉社", [], "マガポケ"), "mismatch")

    def test_unknown_site_without_authors(self):
        self.assertEqual(self.c("誰か", "講談社", [], "くらげバンチ"), "unknown")

    def test_authors_confirm_even_on_other_publisher_site(self):
        self.assertEqual(self.c("江口夏実", "講談社", ["江口夏実"], "くらげバンチ"), "confirmed")

    def test_build_links_unseen_work_by_candidates(self):
        def bk(pub, author):
            return {"series_key": "新作", "series_title": "新作", "publisher": pub, "author": author,
                    "title": "新作 1", "release_date": "2026-12-01"}
        cands = {"新作": [{"catalogId": "9", "site": "マガポケ", "authors": ["山田太郎"]}]}
        ok = build.group_works([bk("講談社", "山田 太郎")], cands)
        self.assertEqual([w["pochi"] for w in ok.values()], ["9"])
        other_author = build.group_works([bk("講談社", "鈴木 花子")], cands)
        self.assertEqual([w["pochi"] for w in other_author.values()], [None])
        other_pub = build.group_works([bk("小学館", "鈴木 花子")], cands)
        self.assertEqual([w["pochi"] for w in other_pub.values()], [None])

    def test_pick_prefers_confirmed_then_wikidata(self):
        import pochi_verify as pv
        cs = [{"catalogId": "5", "site": "コミックDAYS", "authors": []},
              {"catalogId": "7", "site": "マガポケ", "authors": [], "wikidata": True},
              {"catalogId": "9", "site": "マガポケ", "authors": ["山田太郎"]}]
        self.assertEqual(pv.pick_candidate("山田太郎", "講談社", cs)[0]["catalogId"], "9")
        self.assertEqual(pv.pick_candidate("誰か", "講談社", cs[:2])[0]["catalogId"], "7")

    def test_fuzzy_key(self):
        import pochi_verify as pv
        self.assertEqual(pv.fuzzy_key("土竜(モグラ)の唄"), pv.fuzzy_key("土竜の唄"))
        self.assertEqual(pv.fuzzy_key("作品~副題"), pv.fuzzy_key("作品〜副題〜"))
        self.assertEqual(pv.fuzzy_key("作品 新装版"), pv.fuzzy_key("作品"))
        self.assertNotEqual(pv.fuzzy_key("作品+"), pv.fuzzy_key("作品"))  # 続編は別作品
        self.assertNotEqual(pv.fuzzy_key("作品"), pv.fuzzy_key("作品外伝"))

    def test_latin_accent_folded_in_author(self):
        self.assertEqual(self.c("OYSTER", "双葉社", ["ÖYSTER"], "webアクション"), "confirmed")
        self.assertEqual(self.c("かき", "双葉社", ["かぎ"], "webアクション"), "mismatch")  # 濁点は外さない

    def test_fuzzy_title_uses_same_rule_as_exact(self):
        def bk(author, title="作品~副題", pub="小学館"):
            return {"series_key": title, "series_title": title, "publisher": pub, "author": author,
                    "title": title + " 1", "release_date": "2026-12-01"}
        cands = {"作品~副題~": [{"catalogId": "9", "site": "サンデーうぇぶり", "authors": ["山田太郎"]}]}
        self.assertEqual([w["pochi"] for w in build.group_works([bk("山田 太郎")], cands).values()], ["9"])
        self.assertEqual([w["pochi"] for w in build.group_works([bk("鈴木 花子")], cands).values()], [None])
        # 著者データが無くても出版社が整合すれば付ける（一段目と同じ基準。オーナー決定 2026-11-22）
        nauth = {"作品~副題~": [{"catalogId": "9", "site": "サンデーうぇぶり", "authors": []}]}
        self.assertEqual([w["pochi"] for w in build.group_works([bk("山田 太郎")], nauth).values()], ["9"])
        # 出版社が食い違う（講談社のサイトに小学館の本）なら付けない
        other = {"作品~副題~": [{"catalogId": "9", "site": "マガポケ", "authors": []}]}
        self.assertEqual([w["pochi"] for w in build.group_works([bk("山田 太郎")], other).values()], [None])
        # 続編(+)・外伝は本編に寄せない
        seq = {"作品": [{"catalogId": "9", "site": "サンデーうぇぶり", "authors": ["山田太郎"]}]}
        self.assertEqual([w["pochi"] for w in build.group_works([bk("山田 太郎", "作品+")], seq).values()], [None])
        self.assertEqual([w["pochi"] for w in build.group_works([bk("山田 太郎", "作品外伝")], seq).values()], [None])

    def test_exact_match_unchanged_by_fuzzy_stage(self):
        # 完全一致で付くものは二段目の影響を受けない
        cands = {"作品": [{"catalogId": "1", "site": "マガポケ", "authors": []}],
                 "作品~副題~": [{"catalogId": "2", "site": "マガポケ", "authors": ["山田太郎"]}]}
        b = {"series_key": "作品", "series_title": "作品", "publisher": "講談社", "author": "山田太郎",
             "title": "作品 1", "release_date": "2026-12-01"}
        self.assertEqual([w["pochi"] for w in build.group_works([b], cands).values()], ["1"])


class CardCoverTest(unittest.TestCase):
    B = {"id": "9784000000001", "title": "テスト 1", "volume": 1, "series_title": "テスト", "publisher": "小学館",
         "release_date": "2026-11-25", "author": "作者", "work_slug": "x", "source_url": "https://example.com/", "editions": []}

    def test_no_image_uses_placeholder(self):
        h = build.card(dict(self.B))
        self.assertIn('src="/static/noimage.png" alt="書影なし"', h)
        self.assertNotIn("Amazonで見る", h)  # Amazon のリンクは付けない

    def test_amazon_image_unchanged(self):
        h = build.card(dict(self.B, amazon={"image": "https://m.media-amazon.com/x.jpg", "url": "https://www.amazon.co.jp/dp/1"}))
        self.assertIn("m.media-amazon.com/x.jpg", h)
        self.assertNotIn("noimage", h)


class FeedTest(unittest.TestCase):
    def test_feed_file_and_window(self):
        t = datetime.date(2026, 11, 20)
        bk = lambda d, v=1, **k: dict({"release_date": d, "series_title": "作品", "title": "作品", "volume": v,
                                       "publisher": "小学館", "work_slug": "abc", "isbn13": "978" + d.replace("-", "") + str(v),
                                       "amazon": None}, **k)
        books = [bk("2026-11-16"), bk("2026-11-17"), bk("2026-11-20"), bk("2026-11-21"), bk("2026-11-22")]
        books[2]["amazon"] = {"image": "https://m.media-amazon.com/images/I/x.jpg", "url": "https://www.amazon.co.jp/dp/x?tag=t"}
        items = build.feed_items(books, t)
        self.assertEqual([i["date"] for i in items], ["2026-11-21", "2026-11-20", "2026-11-17"])
        self.assertEqual([i["note"] for i in items], ["明日発売", "今日発売", "11月17日発売"])
        self.assertEqual(items[0]["title"], "作品 1巻")
        self.assertEqual(items[0]["url"], "https://shinkan.netaful.jp/work/abc/")
        self.assertNotIn("image", items[0])
        self.assertEqual(items[1]["image_link"], "https://www.amazon.co.jp/dp/x?tag=t")
        self.assertEqual(items[0]["source"], "shinkan")

    def test_max_20(self):
        t = datetime.date(2026, 11, 20)
        books = [dict({"release_date": "2026-11-20", "series_title": f"s{i}", "title": "t", "volume": 1,
                       "publisher": "小学館", "work_slug": "w", "isbn13": str(i), "amazon": None}) for i in range(30)]
        self.assertEqual(len(build.feed_items(books, t)), 20)


class PochiLatestTest(unittest.TestCase):
    def work(self, pochi, books):
        return {"slug": "abc", "title": "作品", "publisher": "小学館", "author": "著者", "pochi": pochi, "books": books}

    def bk(self, vol, date):
        return {"volume": vol, "release_date": date, "title": f"作品 {vol}" if vol else "作品"}

    def test_split_around_today(self):
        w = self.work("42", [self.bk(1, "2026-10-01"), self.bk(2, "2026-11-20"), self.bk(3, "2026-12-01"), self.bk(4, "2027-01-01")])
        r = build.pochi_latest({"abc": w}, datetime.date(2026, 11, 20))
        e = r["works"]["42"]
        self.assertEqual(r["generated"], "2026-11-20")
        self.assertEqual(e["latest"]["volume"], 2)          # 今日発売は latest 側
        self.assertEqual(e["next"]["volume"], 3)
        self.assertEqual(e["work_url"], "https://shinkan.netaful.jp/work/abc/")

    def test_only_linked_works_and_null_cases(self):
        w1 = self.work(None, [self.bk(1, "2026-10-01")])
        w2 = self.work("7", [self.bk(None, "2026-12-01")])
        w3 = dict(self.work("8", [self.bk(5, "2026-10-01")]), slug="zzz")
        r = build.pochi_latest({"a": w1, "b": w2, "c": w3}, datetime.date(2026, 11, 20))
        self.assertEqual(set(r["works"]), {"7", "8"})
        self.assertIsNone(r["works"]["7"]["latest"])
        self.assertIsNone(r["works"]["7"]["next"]["volume"])   # 巻数なしは null のまま
        self.assertIsNone(r["works"]["8"]["next"])

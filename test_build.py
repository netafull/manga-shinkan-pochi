import os
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
        r = pp.parse_akita(self._page(pp.AKITA_URL))
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
        cls.books, cls.works = build.build()
        cls.docs = ROOT / "docs"

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
        self.assertNotIn("今日・今週", h)
        self.assertEqual(h.count("<h1"), 1)
        self.assertIn("<h1>マンガ新刊の発売日一覧</h1>", h)

    def test_work_index_counts(self):
        h = (self.docs / "work/index.html").read_text(encoding="utf-8")
        self.assertEqual(h.count('<li><a href="/work/'), len(self.works))
        self.assertIn("作品一覧（%d作品）" % len(self.works), h)
        w = next(iter(self.works.values()))
        wp = (self.docs / "work" / w["slug"] / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="/work/">作品一覧', wp)

    def test_kana_row(self):
        self.assertEqual(build.kana_row("ブルーロック"), "は")
        self.assertEqual(build.kana_row("ゴッドマザー"), "か")
        self.assertEqual(build.kana_row("ぁ"), "あ")
        self.assertEqual(build.kana_row("100年の恋"), "その他")
        self.assertEqual(build.kana_row("薬屋"), "その他")

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

    def test_no_credentials_in_docs(self):
        for var in ("CREATORSAPI_CREDENTIAL_SECRET", "CREATORSAPI_CREDENTIAL_ID"):
            v = os.environ.get(var)
            if v:
                for p in self.docs.rglob("*.html"):
                    self.assertNotIn(v, p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

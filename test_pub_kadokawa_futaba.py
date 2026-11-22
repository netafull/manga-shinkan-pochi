"""KADOKAWA・双葉社パーサと、取得失敗時の前回データ保持のテスト。ネットワークには出ない。手書きの小さな断片だけを使う。"""
import datetime
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_backbone
import parse_pub as pp
import pubfetch

TODAY = datetime.date(2026, 11, 20)

IMG = "https://media-cdn.kadokawa.co.jp/x/y/%s.jpg"


def kbook(pid, title, img, authors="<li>漫画&nbsp;山田　太郎</li><li>原作&nbsp;鈴木　一郎</li>", label="レーベル：ヒューコミックス"):
    return f'''<div class="calendar-result-list large-genre-filter-21"><div class="calendar-book-details">
<div class="calendar-book-face"><a href="/product/{pid}/"><img src="noimage.png" data-original="https://cdn.kdkw.jp/c/{pid}.webp" unique="{img}" alt="x"></a></div>
<div class="calendar-book-detail"><h2 class="book-title">{title}</h2><ul class="book-auther">{authors}</ul>
<span class="book-info-price">定価&nbsp;<span class="money">1,023</span>円</span>
<span class="book-info-label">{label}</span></div></div></div>'''


KADOKAWA_HTML = ("<html><head><title>コミック 新刊カレンダー 2026年12月発売の新刊 | KADOKAWAオフィシャルサイト</title></head><body>"
                 '<div id="date-1" class="calendar-main"><div class="calendar-date-wrapper"></div></div>'
                 '<div id="date-4" class="calendar-main"><div class="calendar-date-wrapper">'
                 + kbook("322607000470", "破門　３", IMG % "9784046607119")
                 + kbook("302608000001", "俺の召喚魔法がおかしい。 vol.02", IMG % "9784049211931")
                 + kbook("322607000999", "夜な夜な　（１２）", IMG % "9784041180136", label="")
                 + kbook("302609002834", "純情ギャル【分冊版】", IMG % "302609002834")          # 電子のみ: ISBN無し
                 + kbook("322603001322", "【単話】噛むよりキスして", "https://x/322603001322.jpg")  # 電子のみ
                 + kbook("322607000555", "チェックディジット不正", IMG % "9784046607118")           # ISBNとして不正
                 + '</div></div><div id="date-18" class="calendar-main"><div class="calendar-date-wrapper">'
                 + kbook("322607000777", "別の日　１", IMG % "9784049722628", authors="<li>山田　花子</li>")
                 + "</div></div></body></html>")


def fbook(name, form="コミック", release="2026-12-10", start="2026-12-10", isbn="9784575425406", label="モンスターコミックス", authors=("甲", "乙")):
    return {"isbn_code": isbn, "book_name": name, "publication_form_value": form, "release_dt": release, "start_dt": start,
            "label_name": label, "book_authors": [{"author_name": a, "author_type_name": "画"} for a in authors],
            "book_images": [{"filename330": "https://example.invalid/x.jpg"}]}


FUTABA_JSON = json.dumps({"books": {"book_informations": [
    fbook("厳つい公爵様 9 【コミック】"),
    fbook("復讐の未亡人 ： 13", isbn="9784575862942", label=""),
    fbook("石神戦記 8 完", isbn="9784575862935", release="2026-12-12"),
    fbook("電子先行 ： 2", release=None, start="2026-12-01", isbn=None),
    fbook("小説の本", form="文庫", isbn="9784575510010"),
    fbook("雑誌", form="雑誌", isbn="9784575800001"),
    fbook("来月分", isbn="9784575862928", release="2027-01-05"),
]}}, ensure_ascii=False)


class KadokawaParserTest(unittest.TestCase):
    def test_isbn_from_image_and_electronic_excluded(self):
        r = pp.parse_kadokawa(KADOKAWA_HTML)
        self.assertEqual([b["isbn13"] for b in r], ["9784046607119", "9784049211931", "9784041180136", "9784049722628"])
        self.assertEqual(r[0]["release_date"], "2026-12-04")
        self.assertEqual(r[3]["release_date"], "2026-12-18")
        self.assertEqual(r[0]["publisher"], "KADOKAWA")
        self.assertEqual(r[0]["label"], "ヒューコミックス")
        self.assertEqual(r[2]["label"], "")
        self.assertEqual(r[0]["source_url"], "https://www.kadokawa.co.jp/product/322607000470/")
        self.assertEqual(r[0]["author"], "山田　太郎 / 鈴木　一郎")   # 役割(漫画/原作)は落とす
        self.assertEqual(r[3]["author"], "山田　花子")
        for b in r:  # 画像URL・価格は持たない
            self.assertFalse(any("jpg" in str(v) or "1,023" in str(v) for v in b.values()))

    def test_no_isbn_gets_unique_kadokawa_id_when_kept(self):
        r = pp.parse_kadokawa(KADOKAWA_HTML, paper_only=False)
        ids = [build_backbone._process(b)["id"] for b in r]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("kadokawa:302609002834", ids)
        self.assertIn("9784046607119", ids)

    def test_volume_split(self):
        v = {b["isbn13"]: build_backbone._process(b) for b in pp.parse_kadokawa(KADOKAWA_HTML)}
        self.assertEqual((v["9784046607119"]["series_title"], v["9784046607119"]["volume"]), ("破門", 3))
        self.assertEqual((v["9784049211931"]["series_title"], v["9784049211931"]["volume"]), ("俺の召喚魔法がおかしい。", 2))
        self.assertEqual(v["9784041180136"]["volume"], 12)
        self.assertEqual(v["9784046607119"]["title"], "破門　３")   # 表示用の原題は崩さない

    def test_volume_hint_variants(self):
        def h(t):
            return pp.parse_title(pp.volume_hint(t, "KADOKAWA"))[:2]
        self.assertEqual(h("悪女の珈琲物語２"), ("悪女の珈琲物語", 2))
        self.assertEqual(h("ハイスクール　[VOLUME]２"), ("ハイスクール", 2))
        self.assertEqual(h("話の話"), ("話の話", None))

    def test_layout_change_raises(self):
        with self.assertRaises(ValueError):
            pp.parse_kadokawa("<html></html>")

    def test_volume_hint_vol_applies_to_all_publishers(self):
        # 2026-11-22: volume_hint は KADOKAWA 限定をやめた。「vol.N」は全出版社で「N」にそろえる
        self.assertEqual(pp.volume_hint("X vol.02", "小学館"), "X 2")
        # 空白なしで付く数字（「物語2」）だけは KADOKAWA 限定（「ペルソナ5」型の題名を巻数と誤認しないため）
        self.assertEqual(pp.volume_hint("悪女の珈琲物語2", "小学館"), "悪女の珈琲物語2")
        self.assertEqual(pp.volume_hint("悪女の珈琲物語2", "KADOKAWA"), "悪女の珈琲物語 2")

    def test_months(self):
        self.assertEqual(pp.kadokawa_months(datetime.date(2026, 12, 3)), [(0, 2026, 12), (2, 2027, 1)])
        self.assertEqual(pp.futaba_months(datetime.date(2026, 12, 3)), ["202612", "202701"])


class FutabaParserTest(unittest.TestCase):
    def test_comics_with_release_date_only(self):
        r = pp.parse_futabasha(FUTABA_JSON, ym="202612")
        self.assertEqual([b["isbn13"] for b in r], ["9784575425406", "9784575862942", "9784575862935"])
        self.assertEqual(r[0]["release_date"], "2026-12-10")
        self.assertEqual(r[0]["author"], "甲 / 乙")
        self.assertEqual(r[0]["publisher"], "双葉社")
        self.assertIsNone(r[1]["label"])
        self.assertEqual(r[0]["source_url"], "https://www.futabasha.co.jp/book/9784575425406")

    def test_other_month_dropped_only_with_ym(self):
        self.assertEqual(len(pp.parse_futabasha(FUTABA_JSON)), 4)

    def test_volume_split(self):
        v = [build_backbone._process(b) for b in pp.parse_futabasha(FUTABA_JSON, ym="202612")]
        self.assertEqual([(x["series_title"], x["volume"]) for x in v],
                         [("厳つい公爵様", 9), ("復讐の未亡人", 13), ("石神戦記", 8)])
        self.assertEqual(v[0]["label"], "モンスターコミックス")
        self.assertIsNone(v[1]["label"])

    def test_other_publishers_title_parsing_unchanged(self):
        self.assertEqual(pp.parse_title("ワンピース 109")[:2], ("ワンピース", 109))


def old(i, pub, date, **kw):
    return {"id": i, "isbn13": None, "isbn10": None, "title": "t" + i, "volume": 1, "series_key": "k" + i, "series_title": "t" + i,
            "author": "", "publisher": pub, "label": "", "release_date": date, "source_url": "u", "editions": [], **kw}


class NewPublisherFailureTest(unittest.TestCase):
    def setUp(self):
        self._fetch = pubfetch.fetch

    def tearDown(self):
        pubfetch.fetch = self._fetch

    def prev(self):
        return [old("k-dec", "KADOKAWA", "2026-12-08"), old("k-nov", "KADOKAWA", "2026-11-25"), old("k-past", "KADOKAWA", "2026-11-02"),
                old("f-dec", "双葉社", "2026-12-08"), old("f-nov", "双葉社", "2026-11-25"), old("s-dec", "小学館", "2026-12-10")]

    def test_new_sites_fail_previous_kept(self):
        pubfetch.fetch = lambda url, net=True, use_cache=True: "<html></html>"
        out, rep = build_backbone.run(TODAY, self.prev(), log=lambda m: None)
        self.assertEqual({b["id"] for b in out}, {b["id"] for b in self.prev()})
        self.assertFalse(rep["publishers"]["KADOKAWA"]["ok"])
        self.assertFalse(rep["publishers"]["双葉社"]["ok"])
        self.assertTrue(any("KADOKAWA" in w for w in rep["warnings"]))

    def test_fetch_none_previous_kept(self):
        pubfetch.fetch = lambda url, net=True, use_cache=True: None
        out, _ = build_backbone.run(TODAY, self.prev(), log=lambda m: None)
        self.assertEqual(len(out), len(self.prev()))

    def test_one_page_ok_other_month_kept_and_existing_untouched(self):
        def fetch(url, net=True, use_cache=True):
            if url == pp.kadokawa_url(2):
                return KADOKAWA_HTML           # 2026年12月分だけ成功
            if url == pp.futaba_url("202612"):
                return FUTABA_JSON
            return "<html></html>"
        pubfetch.fetch = fetch
        out, rep = build_backbone.run(TODAY, self.prev(), log=lambda m: None)
        ids = {b["id"] for b in out}
        self.assertNotIn("k-dec", ids)            # 成功した12月は置き換わる
        self.assertIn("9784046607119", ids)
        self.assertIn("k-nov", ids)               # 失敗した11月(今月)は前回保持
        self.assertIn("k-past", ids)
        self.assertNotIn("f-dec", ids)
        self.assertIn("9784575425406", ids)
        self.assertIn("f-nov", ids)
        self.assertIn("s-dec", ids)               # 既存の出版社は変わらない(取得失敗で前回保持)
        r = next(b for b in out if b["id"] == "9784046607119")
        self.assertEqual(r["publisher"], "KADOKAWA")
        self.assertEqual(r["kadokawa_id"], "322607000470")

    def test_kadokawa_gap_is_20s(self):
        self.assertEqual(pubfetch.HOST_GAP["www.kadokawa.co.jp"], 20.0)


if __name__ == "__main__":
    unittest.main()

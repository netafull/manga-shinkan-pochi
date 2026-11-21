"""竹書房・少年画報社のパーサ、ISBN再利用と詳細取得の上限、取得失敗時の前回データ保持のテスト。ネットワークには出ない。手書きの小さな断片だけを使う。"""
import datetime
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_backbone
import isbnlib
import parse_pub as pp
import pubfetch

TODAY = datetime.date(2026, 11, 20)


def make_isbn(n):
    body = "978400" + "%06d" % n
    return body + isbnlib.isbn13_check(body)


def titem(bid, title, date, authors='<a href="/author/a1.html">甲</a> 著', tags=("バンブーコミックス", "竹コミ！")):
    tg = "".join(f'<div class="tag"><a href="/search/g1.html"><span>{t}</span></a></div>' for t in tags)
    return f'''<div class="item"><div class="image"><a href="/book/b{bid}.html"><img src="/images/org/ph_dummy-book.png" alt="x" /></a></div>
<div class="cont"><div class="tags">{tg}</div><div class="ttl">
<a href="/book/b{bid}.html">
  {title}
</a></div><div class="author">{authors}</div><div class="date">[ {date} 発売 ]</div></div></div>'''


def tpage(*items):
    return ('<html><body><div class="side"><div class="item">サイドバー<a href="/search/?search_genre=1">x</a></div></div>'
            '<div class="booklist">' + "".join(items) + "</div></body></html>")


TAKE_HTML = tpage(
    titem("10204019", "本気になるには遅すぎる", "2026/12/25", tags=("バンブーコミックス", "バンブーコミックスmoment")),
    titem("10204021", "今日もカレーですか？  11", "2026/12/16",
          authors='<a href="/author/a2.html">藤川よつ葉</a> 原作 <a href="/author/a3.html">あづま笙子</a> 作画'),
    titem("10211035", "八月九日 僕は君に喰われる。  7                         （電子書籍）", "2026/12/16"),
    titem("10194913", "新装版 pop one&#039;s cherry  1                         （コミック）", "2026/11/25", tags=("バンブーコミックス", "Qpaコレクション")),
    titem("10204035", "旧フリテンくん  5", "2026/11/22", tags=("B6廉価コミックス",)),
    titem("10171546", "めんつゆひとり飯  10                         （コミック）", "2026/11/02", tags=("バンブーコミックス",)),
    titem("10171547", "先月の本  1", "2026/10/16"),
)


OLD = titem("1", "先月の本  1", "2026/10/16")   # 月初より前の本(ページ送りの打ち止め)


def tdetail(isbn):
    return f"<table><tr><th>出版年月日</th><td>2026/12/16</td></tr><tr><th>ISBN</th><td>{isbn}</td></tr></table>"


class TakeParserTest(unittest.TestCase):
    def test_basic(self):
        r = pp.parse_takeshobo(TAKE_HTML)
        self.assertEqual([b["take_id"] for b in r], ["10204019", "10204021", "10194913", "10204035", "10171546", "10171547"])  # 電子書籍は除く
        a = r[0]
        self.assertEqual((a["publisher"], a["release_date"], a["author"]), ("竹書房", "2026-12-25", "甲"))
        self.assertIsNone(a["isbn13"])
        self.assertEqual(a["source_url"], "https://www.takeshobo.co.jp/book/b10204019.html")
        self.assertEqual(a["label"], "バンブーコミックスmoment")     # 総称「バンブーコミックス」より細かいレーベルを優先
        self.assertEqual(r[1]["author"], "藤川よつ葉 / あづま笙子")     # 役割(原作/作画)は落とす
        self.assertEqual(r[1]["title_raw"], "今日もカレーですか？ 11")
        self.assertEqual(r[2]["title_raw"], "新装版 pop one's cherry 1")  # 「（コミック）」を外し、実体参照を戻す
        self.assertEqual(r[3]["label"], "B6廉価コミックス")
        self.assertEqual(r[4]["label"], "バンブーコミックス")
        for b in r:
            self.assertFalse(any("png" in str(v) for v in b.values()))

    def test_min_date(self):
        r = pp.parse_takeshobo(TAKE_HTML, min_date="2026-11-01")
        self.assertEqual([b["take_id"] for b in r], ["10204019", "10204021", "10194913", "10204035", "10171546"])
        self.assertEqual(min(pp.take_dates(TAKE_HTML)), "2026-10-16")   # ページ送り判定は除外前の全件で見る

    def test_volume(self):
        v = {b["take_id"]: build_backbone._process(b) for b in pp.parse_takeshobo(TAKE_HTML)}
        self.assertEqual((v["10204021"]["series_title"], v["10204021"]["volume"]), ("今日もカレーですか?", 11))  # parse_title は NFKC で正規化する(既存仕様)
        self.assertEqual((v["10194913"]["series_title"], v["10194913"]["volume"]), ("新装版 pop one's cherry", 1))
        self.assertIsNone(v["10204019"]["volume"])
        self.assertEqual(v["10204019"]["id"], "take:10204019")

    def test_layout_change_raises(self):
        with self.assertRaises(ValueError):
            pp.parse_takeshobo("<html></html>")

    def test_detail_isbn(self):
        self.assertEqual(pp.parse_take_detail_isbn(tdetail("9784801991446")), "9784801991446")
        self.assertIsNone(pp.parse_take_detail_isbn(tdetail("9784801991447")))   # チェックディジット不正
        self.assertIsNone(pp.parse_take_detail_isbn("<th>ISBN</th><td></td>"))
        self.assertIsNone(pp.parse_take_detail_isbn('<th>ISBN</th><td><input type="text" name="search_isbn" value="" /></td>'))  # 検索フォーム

    def test_url(self):
        self.assertEqual(pp.take_url(1), "https://www.takeshobo.co.jp/search/g106010.html?amount=100&order=book_date_desc")
        self.assertIn("page=2&", pp.take_url(2))


def srow(day, kind, title, authors="　/　甲/乙", cls="comi"):
    return f'''<tr class="border1"><th>{day}（月）</th><td><div style="display:flex;"><span class="ico-{cls}">{kind}</span></div>
<b>{title}</b>{authors}<br>あらすじは保存しない<p><a href="https://7net.omni7.jp/detail/1.html"><img src="images/7net.png"></a></p></td></tr>'''


def spage(y, m, *rows):
    return f"<html><body><h2>{y}年 {m}月</h2><table>" + "".join(rows) + "</table></body></html>"


SGH_NOV = spage(2026, 11,
                srow("02", "雑誌", "ヤングキング 2026年23号", authors=""),
                srow("09", "コミックス", "悪役令嬢転生おじさん 第11巻", authors="　/　上山道郎"),
                srow("09", "コンビニコミックス", "ときめきごはん No.59", authors="", cls="coco"),
                srow("24", "コミックス", "刀匠火車　全１巻", authors="　/　貘九三口造"),
                srow("24", "コミックス", "朝ごはん亭　第10巻", authors="　/　青菜ぱせり／大羽隆廣"),
                srow("24", "コミックス", "クライマックスネクロマンス\t第５巻", authors="　/　水上悟志 /瀬戸一里"))
SGH_DEC = spage(2026, 12, srow("14", "コミックス", "やんちゃギャルの安城さん 第18巻", authors="　/　加藤雄一"))
SGH_LIST = '''<ul class="itemList">
<li><a href="book_Info.php?id=11542" class="hover"><span class="itemThumb"><img src="/images/Book/thumb/a.png"></span><span class="itemText">悪役令嬢転生おじさん 第11巻</span></a></li>
<li><a href="book_Info.php?id=11550" class="hover"><span class="itemThumb"><img src="/images/Book/thumb/b.png"></span><span class="itemText">朝ごはん亭　第10巻</span></a></li></ul>'''


def sdetail(isbn, date):
    return f"<html><div>[ISBN] {isbn} [発売日] {date} <br /></div></html>"


class SghParserTest(unittest.TestCase):
    def test_comics_only(self):
        r = pp.parse_shonengahosha(SGH_NOV)
        self.assertEqual([b["title_raw"] for b in r],
                         ["悪役令嬢転生おじさん 第11巻", "刀匠火車 全１巻", "朝ごはん亭 第10巻", "クライマックスネクロマンス 第５巻"])  # 雑誌・コンビニコミックスを除く
        a = r[0]
        self.assertEqual((a["publisher"], a["release_date"], a["author"]), ("少年画報社", "2026-11-09", "上山道郎"))
        self.assertIsNone(a["isbn13"])
        self.assertIsNone(a["label"])
        self.assertEqual(a["source_url"], "https://www.shonengahosha.co.jp/cal.php?release=2026-11")
        self.assertEqual(r[2]["author"], "青菜ぱせり / 大羽隆廣")
        self.assertEqual(r[3]["author"], "水上悟志 / 瀬戸一里")
        for b in r:  # あらすじ・電子書店リンクは持たない
            self.assertFalse(any("あらすじ" in str(v) or "omni7" in str(v) for v in b.values()))

    def test_volume_split(self):
        v = [build_backbone._process(b) for b in pp.parse_shonengahosha(SGH_NOV)]
        self.assertEqual([(x["series_title"], x["volume"]) for x in v],
                         [("悪役令嬢転生おじさん", 11), ("刀匠火車", 1), ("朝ごはん亭", 10), ("クライマックスネクロマンス", 5)])
        self.assertEqual(v[1]["title"], "刀匠火車 全１巻")

    def test_unique_ids_without_isbn(self):
        nov = pp.parse_shonengahosha(SGH_NOV)
        ids = [build_backbone._process(b)["id"] for b in nov + pp.parse_shonengahosha(SGH_DEC)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i.startswith("sgh:2026") for i in ids))
        again = [build_backbone._process(b)["id"] for b in pp.parse_shonengahosha(SGH_NOV)]   # 再実行で同じID
        self.assertEqual(ids[:len(nov)], again)

    def test_layout_and_month_checks(self):
        with self.assertRaises(ValueError):
            pp.parse_shonengahosha("<html></html>")
        with self.assertRaises(ValueError):
            pp.parse_shonengahosha(SGH_DEC, ym="2026-11")

    def test_list_and_detail(self):
        self.assertEqual(pp.parse_sgh_comics_list(SGH_LIST), [("11542", "悪役令嬢転生おじさん 第11巻"), ("11550", "朝ごはん亭 第10巻")])
        self.assertEqual(pp.parse_sgh_detail(sdetail("9784785983253", "2026-11-09")), ("9784785983253", "2026-11-09"))
        self.assertEqual(pp.parse_sgh_detail(sdetail("9784785983254", "2026-11-09")), (None, "2026-11-09"))
        self.assertEqual(pp.parse_sgh_detail("<html></html>"), (None, None))

    def test_volume_hint_only_touches_sgh(self):
        self.assertEqual(pp.volume_hint("X 全１巻", "小学館"), "X 全１巻")
        self.assertEqual(pp.volume_hint("X vol.02", "KADOKAWA"), "X 2")

    def test_months(self):
        self.assertEqual(pp.sgh_months(datetime.date(2026, 12, 3)), ["2026-12", "2027-01"])


def old(i, pub, date, **kw):
    return {"id": i, "isbn13": None, "isbn10": None, "title": "t" + i, "volume": 1, "series_key": "k" + i, "series_title": "t" + i,
            "author": "", "publisher": pub, "label": "", "release_date": date, "source_url": "u", "editions": [], **kw}


class FetchMock:
    """URLごとの応答を差し替える。None=取得失敗。値が関数なら URL を渡して呼ぶ。"""

    def __init__(self, pages=None, default="<html></html>"):
        self.pages, self.default, self.calls = pages or {}, default, []

    def __call__(self, url, net=True, use_cache=True):
        self.calls.append(url)
        v = self.pages.get(url, self.default)
        return v(url) if callable(v) else v


class TakeBuildTest(unittest.TestCase):
    def setUp(self):
        self._fetch = pubfetch.fetch

    def tearDown(self):
        pubfetch.fetch = self._fetch

    def take(self, out):
        return [b for b in out if b["publisher"] == "竹書房"]

    def test_detail_cap_and_nearest_first(self):
        items = [titem(str(500 + i), f"作品{i}  1", f"2026/12/{10 + (i % 15):02d}") for i in range(40)]
        items += [titem("900", "遠い先  1", "2027/03/01"), titem("901", "もう過ぎた  1", "2026/11/19"), titem("902", "先月  1", "2026/10/01")]
        counter = {"n": 0}

        def detail(url):
            if "/book/b" in url:
                counter["n"] += 1
                return "<th>ISBN</th><td>" + make_isbn(counter["n"]) + "</td>"
            return "<html></html>"
        m = FetchMock({pp.take_url(1): tpage(*items)}, default=detail)
        pubfetch.fetch = m
        out, rep = build_backbone.run(TODAY, [], log=lambda s: None)
        details = [u for u in m.calls if "/book/b" in u]
        self.assertEqual(len(details), build_backbone.MAX_TAKE_DETAILS)
        self.assertEqual(rep["take_details"], build_backbone.MAX_TAKE_DETAILS)
        self.assertNotIn("https://www.takeshobo.co.jp/book/b900.html", details)   # 30日より先は取りに行かない
        self.assertNotIn("https://www.takeshobo.co.jp/book/b901.html", details)   # 発売済みは取らない
        t = self.take(out)
        self.assertEqual(len(t), 42)                                  # 11/19 の本は今月の範囲なので載る
        self.assertEqual(len({b["id"] for b in t}), 42)               # ISBN無しでも一意のID
        self.assertEqual(sum(1 for b in t if b["isbn13"]), build_backbone.MAX_TAKE_DETAILS)
        self.assertTrue(all(b["isbn13"] or b["id"].startswith("take:") for b in t))
        # 近い順: 12/10 発売の本(i % 15 == 0 の3冊)は必ず取られる
        for i in (0, 15, 30):
            self.assertIn(f"https://www.takeshobo.co.jp/book/b{500 + i}.html", details)

    def test_isbn_reuse_and_no_refetch(self):
        prev = [old("9784801991446", "竹書房", "2026-12-10", isbn13="9784801991446", take_id="100", isbn10="480199144X")]
        m = FetchMock({pp.take_url(1): tpage(titem("100", "既知  1", "2026/12/10"), titem("101", "未知  1", "2026/12/10"), OLD)})
        pubfetch.fetch = m
        out, _ = build_backbone.run(TODAY, prev, log=lambda s: None)
        r = self.take(out)
        by = {b["take_id"]: b for b in r}
        self.assertEqual(by["100"]["isbn13"], "9784801991446")
        self.assertEqual(by["100"]["id"], "9784801991446")
        self.assertEqual(len(r), 2)                      # 旧レコードと二重にならない
        self.assertIsNone(by["101"]["isbn13"])
        self.assertEqual(by["101"]["id"], "take:101")
        self.assertEqual([u for u in m.calls if "/book/b" in u], ["https://www.takeshobo.co.jp/book/b101.html"])  # 既知は詳細を取らない

    def test_isbn_found_replaces_provisional_record(self):
        prev = [old("take:101", "竹書房", "2026-12-10", take_id="101")]
        pubfetch.fetch = FetchMock({pp.take_url(1): tpage(titem("101", "未知  1", "2026/12/10"), OLD),
                                    "https://www.takeshobo.co.jp/book/b101.html": "<th>ISBN</th><td>9784801991446</td>"})
        out, _ = build_backbone.run(TODAY, prev, log=lambda s: None)
        self.assertEqual([(b["id"], b["isbn13"]) for b in self.take(out)], [("9784801991446", "9784801991446")])

    def test_pagination_stops_at_month_start(self):
        m = FetchMock({pp.take_url(1): tpage(titem("1", "A  1", "2026/12/10"), titem("2", "B  1", "2026/10/30"))})
        pubfetch.fetch = m
        build_backbone.run(TODAY, [], log=lambda s: None)
        self.assertEqual([u for u in m.calls if "takeshobo.co.jp/search" in u], [pp.take_url(1)])

    def test_pagination_continues_until_older_month(self):
        pages = {pp.take_url(1): tpage(titem("1", "A  1", "2026/12/10"), titem("2", "B  1", "2026/11/30")),
                 pp.take_url(2): tpage(titem("3", "C  1", "2026/11/05"), titem("4", "D  1", "2026/10/30"))}
        m = FetchMock(pages)
        pubfetch.fetch = m
        out, _ = build_backbone.run(TODAY, [], log=lambda s: None)
        self.assertEqual([u for u in m.calls if "takeshobo.co.jp/search" in u], [pp.take_url(1), pp.take_url(2)])
        self.assertEqual({b["take_id"] for b in self.take(out)}, {"1", "2", "3"})

    def test_page_limit_drops_partial_oldest_month(self):
        pages = {pp.take_url(p): tpage(titem(str(p * 10), f"X{p}  1", "2026/12/10"), titem(str(p * 10 + 1), f"Y{p}  1", "2026/11/30"))
                 for p in (1, 2, 3)}
        pubfetch.fetch = FetchMock(pages)
        out, rep = build_backbone.run(TODAY, [], log=lambda s: None)
        self.assertEqual({b["release_date"][:7] for b in self.take(out)}, {"2026-12"})
        self.assertTrue(any("最大ページ数" in w for w in rep["warnings"]))

    def test_second_page_failure_keeps_previous(self):
        pages = {pp.take_url(1): tpage(titem("1", "A  1", "2026/12/10"), titem("2", "B  1", "2026/11/30")), pp.take_url(2): None}
        pubfetch.fetch = FetchMock(pages)
        prev = [old("t-dec", "竹書房", "2026-12-08", take_id="77"), old("t-nov", "竹書房", "2026-11-25", take_id="78")]
        out, rep = build_backbone.run(TODAY, prev, log=lambda s: None)
        self.assertFalse(rep["publishers"]["竹書房"]["ok"])
        self.assertEqual({b["id"] for b in self.take(out)}, {"t-dec", "t-nov"})

    def test_layout_change_keeps_previous(self):
        pubfetch.fetch = FetchMock({pp.take_url(1): "<html></html>"})
        prev = [old("t-dec", "竹書房", "2026-12-08", take_id="77")]
        out, rep = build_backbone.run(TODAY, prev, log=lambda s: None)
        self.assertEqual({b["id"] for b in self.take(out)}, {"t-dec"})
        self.assertTrue(any("竹書房" in w for w in rep["warnings"]))


class SghBuildTest(unittest.TestCase):
    def setUp(self):
        self._fetch = pubfetch.fetch

    def tearDown(self):
        pubfetch.fetch = self._fetch

    def pages(self, **extra):
        p = {pp.sgh_url("2026-11"): SGH_NOV, pp.sgh_url("2026-12"): SGH_DEC, pp.SGH_COMICS_LIST_URL: SGH_LIST}
        for k, v in extra.items():
            p[k.replace("DETAIL", pp.SGH_BASE + "/book_Info.php?id=")] = v
        return p

    def sgh(self, out):
        return [b for b in out if b["publisher"] == "少年画報社"]

    def test_isbn_from_detail_when_title_and_date_match(self):
        pubfetch.fetch = FetchMock({
            **self.pages(),
            pp.SGH_BASE + "/book_Info.php?id=11542": sdetail("9784785983253", "2026-11-09"),
            pp.SGH_BASE + "/book_Info.php?id=11550": sdetail("9784785983260", "2026-11-10"),   # 発売日が違う→採らない
        })
        out, rep = build_backbone.run(TODAY, [], log=lambda s: None)
        s = {b["title"]: b for b in self.sgh(out)}
        self.assertEqual(len(s), 5)
        a = s["悪役令嬢転生おじさん 第11巻"]
        self.assertEqual((a["id"], a["isbn13"]), ("9784785983253", "9784785983253"))
        self.assertEqual(a["isbn10"], "4785983256")
        self.assertEqual(a["source_url"], pp.SGH_BASE + "/book_Info.php?id=11542")
        self.assertTrue(a["sgh_id"])
        b = s["朝ごはん亭 第10巻"]
        self.assertIsNone(b["isbn13"])
        self.assertTrue(b["id"].startswith("sgh:"))
        self.assertEqual(rep["sgh_details"], 2)
        self.assertEqual(len({x["id"] for x in s.values()}), 5)

    def test_unreleased_book_has_no_detail_fetch(self):
        m = FetchMock(self.pages())
        pubfetch.fetch = m
        build_backbone.run(TODAY, [], log=lambda s: None)
        self.assertEqual(len([u for u in m.calls if "book_Info" in u]), 2)   # 一覧に載っている(発売済み)2冊だけ

    def test_reuse_isbn_from_previous(self):
        sid = build_backbone._process(pp.parse_shonengahosha(SGH_NOV)[0])["sgh_id"]
        prev = [old("9784785983253", "少年画報社", "2026-11-09", isbn13="9784785983253", sgh_id=sid, source_url="detail-url")]
        m = FetchMock(self.pages())
        pubfetch.fetch = m
        out, _ = build_backbone.run(TODAY, prev, log=lambda s: None)
        a = [b for b in self.sgh(out) if b.get("sgh_id") == sid]
        self.assertEqual(len(a), 1)
        self.assertEqual((a[0]["isbn13"], a[0]["source_url"]), ("9784785983253", "detail-url"))
        self.assertNotIn(pp.SGH_BASE + "/book_Info.php?id=11542", m.calls)   # 既知のISBNは取り直さない

    def test_detail_cap(self):
        listing = "".join(f'<li><a href="book_Info.php?id={i}" class="hover"><span class="itemText">本{i} 第1巻</span></a></li>' for i in range(30))
        rows = [srow("%02d" % (1 + i % 20), "コミックス", f"本{i} 第1巻") for i in range(30)]
        pubfetch.fetch = FetchMock({**self.pages(), pp.sgh_url("2026-11"): spage(2026, 11, *rows), pp.SGH_COMICS_LIST_URL: listing})
        _, rep = build_backbone.run(TODAY, [], log=lambda s: None)
        self.assertEqual(rep["sgh_details"], build_backbone.MAX_SGH_DETAILS)

    def test_comics_list_failure_still_builds(self):
        pubfetch.fetch = FetchMock({**self.pages(), pp.SGH_COMICS_LIST_URL: None})
        out, rep = build_backbone.run(TODAY, [], log=lambda s: None)
        self.assertEqual(len(self.sgh(out)), 5)
        self.assertEqual(rep["sgh_details"], 0)

    def test_failure_keeps_previous(self):
        prev = [old("s-dec", "少年画報社", "2026-12-08", sgh_id="a"), old("s-nov", "少年画報社", "2026-11-25", sgh_id="b"),
                old("s-past", "少年画報社", "2026-11-02", sgh_id="c")]
        pubfetch.fetch = FetchMock({**self.pages(), pp.sgh_url("2026-12"): None})     # 12月分だけ失敗
        out, rep = build_backbone.run(TODAY, prev, log=lambda s: None)
        ids = {b["id"] for b in self.sgh(out)}
        self.assertIn("s-dec", ids)              # 失敗した月は前回保持
        self.assertNotIn("s-nov", ids)           # 成功した今月は置き換わる
        self.assertIn("s-past", ids)             # 過去日付は残る
        self.assertTrue(rep["publishers"]["少年画報社"]["ok"])

    def test_all_fail_keeps_previous(self):
        prev = [old("s-dec", "少年画報社", "2026-12-08", sgh_id="a"), old("t-dec", "竹書房", "2026-12-08", take_id="9")]
        pubfetch.fetch = FetchMock(default=None)
        out, rep = build_backbone.run(TODAY, prev, log=lambda s: None)
        self.assertEqual({b["id"] for b in out if b["publisher"] in ("少年画報社", "竹書房")}, {"s-dec", "t-dec"})
        self.assertFalse(rep["publishers"]["少年画報社"]["ok"])
        self.assertFalse(rep["publishers"]["竹書房"]["ok"])

    def test_other_publisher_untouched(self):
        pubfetch.fetch = FetchMock(self.pages())
        out, _ = build_backbone.run(TODAY, [old("x", "小学館", "2026-12-10")], log=lambda s: None)
        self.assertIn("x", {b["id"] for b in out})


if __name__ == "__main__":
    unittest.main()

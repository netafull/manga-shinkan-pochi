import json
import tempfile
import unittest
from pathlib import Path

import build
import noncomic
import parse_pub as pp

NO = {"exclude": [], "include": []}


def bk(title, label="", pub="KADOKAWA", **kw):
    return {"id": kw.pop("id", "x" + title), "title": title, "label": label, "publisher": pub, "volume": kw.pop("volume", 1), **kw}


def bad(b, ov=NO):
    return noncomic.judge(b, ov)[0]


class TitleRules(unittest.TestCase):
    def test_noncomic_titles(self):
        for t in ["貞本義行画集 EVANGELION【限定版】", "SILENT HILL f 公式設定資料集", "スプラトゥーン レイダース ザ・コンプリートガイド",
                  "Livly Island 公式ガイドブック5", "しぐれういファンブック", "The Art of PRAGMATA 公式設定画集",
                  "ジ・アート・オブ トイ・ストーリー5", "継母の連れ子が元カノだった Art Works たかやKi画集",
                  "イタリアンブレインロット 生態図鑑", "シマエナガちゃんずかん", "瀬戸みるか1st写真集 TOYBOX",
                  "ブルーロック エゴイストシールブック", "スペリオールμ(ミュー) BIBLE", "DVD) TVシリーズ クレヨンしんちゃん",
                  "小説 機動戦士ガンダム 水星の魔女(6)", "グラビアチャンピオンVOL.15", "青騎士 第35号", "ドラえもんライフ2027冬号 ~上田誠セレクション~",
                  "ブルーピリオド公式アートワーク"]:
            self.assertTrue(bad(bk(t, volume=None)), t)

    def test_false_positive_examples_stay(self):
        for t, lab, pub in [("理想郷女子図鑑 5 ~私の結婚生活、とっても幸せです~ (ヤングジャンプコミックス)", "ヤングジャンプコミックス", "集英社"),
                            ("私が大好きな小説家を殺すまで(4) (ヤンマガKCスペシャル)", "ヤンマガKCスペシャル", "講談社"),
                            ("オークの樹の下 6 ペアアクリルキーホルダー&ミニカレンダー付き特装版", "FLOS COMIC", "KADOKAWA"),
                            ("薬屋のひとりごと 23 ポストカードブック付特装版", "", "小学館"),
                            ("Unanswered//butterfly -SWORD ART ONLINE- 1", "電撃コミックスNEXT", "KADOKAWA"),
                            ("ゴールデンファントム(2) (アフタヌーンKC)", "アフタヌーンKC", "講談社")]:
            self.assertFalse(bad(bk(t, lab, pub)), t)

    def test_special_editions_and_drama_cd_stay(self):
        self.assertFalse(bad(bk("腐男子召喚 14 【ドラマCD付き特装版】", "マージナルコミックス", "双葉社")))
        self.assertFalse(bad(bk("ある漫画 3 DVD付き特装版")))
        self.assertTrue(bad(bk("ドラマCD) ある作品", volume=None)))

    def test_zukan_ending_only_without_volume(self):
        self.assertTrue(bad(bk("恐竜図鑑", volume=None)))
        self.assertFalse(bad(bk("人外図鑑", volume=3)))

    def test_boundary_cases_stay(self):
        # ハルタの月号は2026-11-22のオーナー決定で外す側に移した（HarutaTest）
        for t in ["劇場版アニメコミック 名探偵コナン 上", "本宮ひろ志漫画大全集030", "こち亀 超50周年 お宝!チョイス"]:
            self.assertFalse(bad(bk(t)), t)


class Labels(unittest.TestCase):
    def test_light_novel_label(self):
        self.assertTrue(bad(bk("異世界ラクラク無人島ライフ 5", "ダッシュエックス文庫", "集英社")))
        self.assertTrue(bad(bk("何か", "電撃文庫")))

    def test_kodansha_bunko_manga_stays(self):
        self.assertFalse(bad(bk("文庫版 賭博黙示録カイジ 3 (講談社文庫 ふ 96-3)", "講談社文庫 ふ 96-3", "講談社")))


class Roles(unittest.TestCase):
    def test_no_comic_role_and_no_label(self):
        self.assertTrue(bad(bk("何かの本", "", author_roles=["編集"])))
        self.assertTrue(bad(bk("何かの本", "", author_roles=["監修", "イラスト"])))

    def test_comic_role_or_label_stays(self):
        self.assertFalse(bad(bk("漫画", "", author_roles=["原作", "漫画"])))
        self.assertFalse(bad(bk("漫画", "", author_roles=["著者"])))
        self.assertFalse(bad(bk("漫画", "", author_roles=["原作・キャラクター原案"])))
        self.assertFalse(bad(bk("漫画", "角川コミックス・エース", author_roles=["編集"])))

    def test_missing_roles_key_is_fine(self):
        self.assertFalse(bad(bk("漫画", "")))

    def test_parse_kadokawa_keeps_roles(self):
        html = ('<title>x 2026年11月発売</title><div id="date-5"><div class="calendar-result-list a"><a href="/product/1/"></a>'
                '<h2 class="book-title">T</h2><ul class="book-auther"><li><a>漫画 山田</a></li><li><a>原作 佐藤</a></li></ul>'
                '<img unique="/x/9784041178874.jpg"></div></div></html>')
        r = pp.parse_kadokawa(html)
        self.assertEqual(r[0].get("roles"), ["漫画", "原作"])


class Overrides(unittest.TestCase):
    def test_exclude_and_include_priority(self):
        b = bk("普通の漫画 1", id="A")
        self.assertTrue(bad(b, {"exclude": [{"id": "A"}], "include": []}))
        c = bk("X画集", id="B")
        self.assertFalse(bad(c, {"exclude": [{"id": "B"}], "include": [{"id": "B"}]}))
        self.assertFalse(bad(c, {"exclude": [], "include": [{"id": "B"}]}))

    def test_load_overrides_missing_file(self):
        self.assertEqual(noncomic.load_overrides(Path("/nonexistent.json")), NO)

    def test_real_config_loads(self):
        ov = noncomic.load_overrides()
        self.assertTrue(all("id" in r for r in ov["exclude"] + ov["include"]))


class LoadAll(unittest.TestCase):
    def test_load_all_drops_noncomic(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            rows = [dict(id="1", isbn13="9784041178874", isbn10=None, title="普通の漫画 1", volume=1, series_key="a", series_title="a",
                         author="a", publisher="KADOKAWA", label="x", release_date="2026-11-01"),
                    dict(id="2", isbn13="9784041178881", isbn10=None, title="何か画集", volume=None, series_key="b", series_title="b",
                         author="a", publisher="KADOKAWA", label="", release_date="2026-11-01")]
            (d / "books.json").write_text(json.dumps(rows), encoding="utf-8")
            books, _ = build.load_all(d)
            self.assertEqual([b["id"] for b in books], ["1"])


if __name__ == "__main__":
    unittest.main()


class HarutaTest(unittest.TestCase):
    def test_haruta_monthly_is_magazine(self):
        self.assertTrue(bad(bk("ハルタ 2026-NOVEMBER volume 139")))
        self.assertFalse(bad(bk("ハルタの日常 3")))

"""巻数・series_key の取り方（2026-11-22 修正）のテスト。python3 test_volume_fix.py"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import parse_pub as pp  # noqa: E402
import migrate_volume_fix_20261122 as mig  # noqa: E402
import migrate_series_split_20261122 as mig2  # noqa: E402


def book(t, pub):
    key, vol, _d, flags, _l = pp.parse_book(t, pub)
    return key, vol, flags


class VolumeFixTest(unittest.TestCase):
    def test_label_paren_amazon(self):
        self.assertEqual(book("ヤンキー君と科学ごはん 10 (ヤングジャンプコミックス)", "集英社")[:2], ("ヤンキー君と科学ごはん", 10))
        self.assertEqual(book("ハボウの轍 7 ~公安調査庁調査官・土師空也~ (ヤングジャンプコミックス)", "集英社")[:2], ("ハボウの轍", 7))
        self.assertEqual(book("ジャックジャンヌ FOLIAGE [2] ~ロードナイト・クォーツ~ (ヤングジャンプコミックス)", "集英社")[:2], ("ジャックジャンヌFOLIAGE", 2))
        self.assertEqual(book("TOUGH 第二章 3 (ヤングジャンプコミックス)", "集英社")[:2], ("TOUGH第二章", 3))
        self.assertEqual(book("文庫版 賭博黙示録カイジ 3 (講談社文庫 ふ 96-3)", "講談社")[:2], ("文庫版賭博黙示録カイジ", 3))
        self.assertEqual(book("ON THE CORNER Vоl.1 (KCデラックス)", "講談社")[:2], ("ONTHECORNER", 1))   # キリル文字の о
        # 続巻が同じ作品になる
        a = book("ハボウの轍 7 ~x~ (ヤングジャンプコミックス)", "集英社")[0]
        b = book("ハボウの轍 8 ~y~ (ヤングジャンプコミックス)", "集英社")[0]
        self.assertEqual(a, b)

    def test_collection_number_is_not_volume(self):
        self.assertEqual(book("武蔵 本宮ひろ志漫画大全集009", "集英社")[:2], ("武蔵", None))
        self.assertEqual(book("俺の空 3 本宮ひろ志漫画大全集030", "集英社")[:2], ("俺の空", 3))

    def test_mid_volume(self):
        self.assertEqual(book("天空の異世界ビストロ店 5 ～看板娘ソラノが美味しい幸せ届けます～", "KADOKAWA")[:2], ("天空の異世界ビストロ店", 5))
        self.assertEqual(book("魔石グルメ 　14 魔物の力を食べたオレは最強！", "KADOKAWA")[:2], ("魔石グルメ", 14))
        self.assertEqual(book("異世界転移したけど、王立学院で事務員やってます（3） 平穏な日常", "KADOKAWA")[:2], ("異世界転移したけど、王立学院で事務員やってます", 3))
        self.assertEqual(book("地味令嬢、しごでき皇妃になる！１ 契約婚のはずなのに", "KADOKAWA")[:2], ("地味令嬢、しごでき皇妃になる!", 1))
        self.assertEqual(book("ハウリング・ブレイズ1 葬焔の剣士と不死の魔女", "KADOKAWA")[:2], ("ハウリング・ブレイズ", 1))
        self.assertEqual(book("諸星大二郎短編集成　７　塔に飛ぶ鳥", "小学館")[:2], ("諸星大二郎短編集成", 7))
        self.assertEqual(book("読心探偵 大葉香夏子は頭がわるい 1 ～a～", "KADOKAWA")[0], book("読心探偵 大葉香夏子は頭がわるい 2 ～a～", "KADOKAWA")[0])

    def test_kanji_roman_jouge_volume_word(self):
        self.assertEqual(book("宮中は噂のたえない職場にて 二", "KADOKAWA")[:2], ("宮中は噂のたえない職場にて", 2))
        self.assertEqual(book("香港ネクロポリス 参", "KADOKAWA")[1], 3)
        self.assertEqual(book("拝啓見知らぬ旦那様、離婚していただきます VII", "KADOKAWA")[1], 7)
        self.assertEqual(book("きみと光さす食卓で 上", "KADOKAWA")[1:2], (1,))
        self.assertEqual(book("きみと光さす食卓で 下", "KADOKAWA")[1], 2)
        self.assertEqual(book("スピリットサークル新装版 上巻", "少年画報社")[:2], ("スピリットサークル新装版", 1))
        self.assertEqual(book("スピリットサークル新装版 下巻", "少年画報社")[:2], ("スピリットサークル新装版", 2))
        self.assertEqual(book("劇場版アニメコミック名探偵コナン　ハイウェイの堕天使　上", "小学館")[0],
                         book("劇場版アニメコミック名探偵コナン　ハイウェイの堕天使　下", "小学館")[0])
        self.assertEqual(book("痛覚探偵 通天寺ナツメ ［超感覚者たち］　VOLUME 2 TWO", "KADOKAWA")[1], 2)
        self.assertEqual(pp.volume_hint("X vol.02", "小学館"), "X 2")   # 他社にも効く

    def test_roman_single_letter_not_volume(self):
        self.assertIsNone(book("Project X", "小学館")[1])
        self.assertIsNone(book("Mr. X", "集英社")[1])

    def test_edition_suffix(self):
        k, v, f = book("悪役のエンディングは死のみ　12　シャカシャカアクキー付き特装版", "KADOKAWA")
        self.assertEqual((k, v, f), ("悪役のエンディングは死のみ", 12, ["特装版"]))
        self.assertEqual(book("悪役のエンディングは死のみ 12", "KADOKAWA")[:2], (k, 12))
        self.assertEqual(book("逆転バリバリバース　２　金のバリバコイン２枚つき特装版", "小学館")[:2], ("逆転バリバリバース", 2))
        self.assertEqual(book("オークの樹の下　６　ペアアクリルキーホルダー＆ミニカレンダー付き特装版", "KADOKAWA")[:2], ("オークの樹の下", 6))
        self.assertEqual(book("ましろくん 第2巻 特装版", "秋田書店"), ("ましろくん", 2, ["特装版"]))
        self.assertEqual(book("ゴジラ ギャラクシーオデッセイ 第4巻 特装版", "秋田書店")[1], 4)

    def test_non_volume_numbers_kept(self):
        # 題名中の数字は巻数にしない
        self.assertIsNone(book("宇宙戦艦ヤマト 黎明篇　第３部　ツァラトゥストラ・ゾーン", "KADOKAWA")[1])
        self.assertIsNone(book("ちろぴの 2人のハチャメチャ!? ゆるっとライフ！", "KADOKAWA")[1])
        self.assertIsNone(book("てれびげーむマガジン ゲーム大図かん 桃太郎電鉄2 あなたの町も きっとある", "KADOKAWA")[1])
        self.assertEqual(book("君のことが大大大大大好きな100人の彼女 28 (ヤングジャンプコミックス)", "集英社")[:2], ("君のことが大大大大大好きな100人の彼女", 28))
        self.assertIsNone(book("こち亀 超50周年!! お宝!チョイス 1月 (集英社リミックス)", "集英社")[1])

    def test_novel_label_stays_separate_work(self):
        manga = book("高校時代に傲慢だった女王様との同棲生活は意外と居心地が悪くない 5 (ヤングジャンプコミックス)", "集英社")
        ln = book("高校時代に傲慢だった女王様との同棲生活は意外と居心地が悪くない 6 (ダッシュエックス文庫)", "集英社")
        self.assertNotEqual(manga[0], ln[0])
        self.assertEqual((manga[1], ln[1]), (5, 6))
        # 講談社文庫の「文庫版」は漫画なので別扱いにしない
        self.assertNotIn("文庫)", book("文庫版 賭博黙示録カイジ 3 (講談社文庫 ふ 96-3)", "講談社")[0])

    def test_existing_results_unchanged(self):
        for t, exp in [("ワンピース 109", ("ワンピース", 109)), ("青のオーケストラ　１６", ("青のオーケストラ", 16)),
                       ("氷結系こそ最強です！ 〜小さくて可愛い師匠〜 第5巻", None), ("あくまでてんしです", ("あくまでてんしです", None))]:
            if exp:
                self.assertEqual(pp.parse_title(pp.volume_hint(t, "小学館"))[:2], exp)
        self.assertEqual(pp.parse_title(pp.volume_hint("悪女の珈琲物語２", "KADOKAWA"))[:2], ("悪女の珈琲物語", 2))

    def test_migration(self):
        shu = {"id": "1", "isbn13": "1", "isbn10": "x", "title": "ヤンキー君と科学ごはん 10 (ヤングジャンプコミックス)", "volume": None,
               "series_key": "ヤンキー君と科学ごはん10(ヤングジャンプコミックス)", "series_title": "ヤンキー君と科学ごはん 10",
               "author": "A", "publisher": "集英社", "label": "ヤングジャンプコミックス", "release_date": "2026-11-19",
               "source_url": None, "editions": [], "source_note": "Amazon の商品情報より"}
        shu2 = dict(shu, id="2", isbn13="2", title="ヤンキー君と科学ごはん 11 (ヤングジャンプコミックス)",
                    series_key="ヤンキー君と科学ごはん11(ヤングジャンプコミックス)", series_title="ヤンキー君と科学ごはん 11")
        keep = dict(shu, id="3", isbn13="3", title="ワンピース 109", volume=109, series_key="ワンピース", series_title="ワンピース")
        kad = {"id": "4", "isbn13": "4", "isbn10": None, "title": "きみと光さす食卓で 上", "volume": None, "series_key": "きみと光さす食卓で上",
               "series_title": "きみと光さす食卓で 上", "author": "A", "publisher": "KADOKAWA", "label": "", "release_date": "2026-11-20",
               "source_url": None, "editions": []}
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "books.json").write_text(json.dumps([kad], ensure_ascii=False), encoding="utf-8")
            (d / "books_kodansha.json").write_text("[]", encoding="utf-8")
            (d / "books_shueisha.json").write_text(json.dumps([shu, shu2, keep], ensure_ascii=False), encoding="utf-8")
            (d / "yomi.json").write_text(json.dumps({
                shu["series_key"]: {"yomi": "ヤンキークントカガクゴハン", "source": "openbd", "isbn": "1"},
                shu2["series_key"]: {"yomi": None, "checked": "2026-11-21"},
                "ワンピース": {"yomi": "ワンピース"}}, ensure_ascii=False), encoding="utf-8")
            mig.run(d, log=lambda *_: None)
            s = json.loads((d / "books_shueisha.json").read_text(encoding="utf-8"))
            self.assertEqual([(b["series_key"], b["volume"]) for b in s], [("ヤンキー君と科学ごはん", 10), ("ヤンキー君と科学ごはん", 11), ("ワンピース", 109)])
            self.assertEqual(s[0]["author"], "A")                       # 他の項目は触らない
            self.assertEqual(s[2], keep)                                 # 巻数ありは完全に不変
            k = json.loads((d / "books.json").read_text(encoding="utf-8"))
            self.assertEqual((k[0]["series_key"], k[0]["volume"]), ("きみと光さす食卓で", 1))
            y = json.loads((d / "yomi.json").read_text(encoding="utf-8"))
            self.assertEqual(y["ヤンキー君と科学ごはん"]["yomi"], "ヤンキークントカガクゴハン")   # 読みの値は変えない
            self.assertNotIn(shu["series_key"], y)
            self.assertIn("ワンピース", y)
            before = (d / "books_shueisha.json").read_text(encoding="utf-8")
            mig.run(d, log=lambda *_: None)                              # 再実行しても変わらない
            self.assertEqual((d / "books_shueisha.json").read_text(encoding="utf-8"), before)

    def test_split_series_fix(self):
        # 「(N) ＋特典付き特装版／限定版」: 括弧の巻数を取り、通常版と同じ作品にする
        self.assertEqual(book("しゅごキャラ! ジュエルジョーカー(5) キラキラスリーブケース&イラストカード付き特装版 (プレミアムKC)", "講談社"),
                         ("しゅごキャラ!ジュエルジョーカー", 5, ["特装版"]))
        self.assertEqual(book("しゅごキャラ! ジュエルジョーカー(5) (KCデラックス)", "講談社")[:2], ("しゅごキャラ!ジュエルジョーカー", 5))
        self.assertEqual(book("肩のりイケブクロさんエコバッグ付き 出禁のモグラ(14)限定版 (講談社キャラクターズA)", "講談社"),
                         ("出禁のモグラ", 14, ["限定版"]))
        self.assertEqual(book("とことんクズな渡良瀬なのに(5)特装版 (講談社キャラクターズA)", "講談社"),
                         ("とことんクズな渡良瀬なのに", 5, ["特装版"]))
        # フルカラー版・カラー版は同じ作品の版表記
        self.assertEqual(book("生徒会にも穴はある! 公式フルカラー版『生穴せれくしょん!』(2) (KCデラックス)", "講談社"),
                         ("生徒会にも穴はある!", 2, ["フルカラー版"]))
        self.assertEqual(book("X 3 カラー版", "小学館"), ("X", 3, ["カラー版"]))
        self.assertEqual(book("X カラー版 3", "小学館"), ("X", 3, ["カラー版"]))
        # 題名の先頭の「カラー版」や、版表記のない括弧巻数は変えない
        self.assertEqual(book("カラー版 ゴルゴ 3", "小学館")[:2], ("カラー版ゴルゴ", 3))
        self.assertEqual(book("月曜日のたわわ(16)青版 (プレミアムKC)", "講談社")[1], None)

    def test_split_migration(self):
        rec = lambda i, t, k, v: {"id": i, "isbn13": i, "isbn10": None, "title": t, "volume": v, "series_key": k, "series_title": k,
                                  "author": "A", "publisher": "講談社", "label": "", "release_date": "2026-11-20", "source_url": None, "editions": []}
        bad = rec("1", "生徒会にも穴はある! 公式フルカラー版『生穴せれくしょん!』(2) (KCデラックス)", "生徒会にも穴はある!公式フルカラー版『生穴せれくしょん!』", 2)
        good = rec("2", "生徒会にも穴はある!(14) (KCデラックス)", "生徒会にも穴はある!", 14)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "data").mkdir(); (d / "config").mkdir()
            (d / "data" / "books_kodansha.json").write_text(json.dumps([bad, good], ensure_ascii=False), encoding="utf-8")
            (d / "data" / "yomi.json").write_text(json.dumps({bad["series_key"]: {"yomi": "A"}, good["series_key"]: {"yomi": "B"}}, ensure_ascii=False), encoding="utf-8")
            (d / "config" / "yomi_manual.json").write_text(json.dumps({bad["series_key"]: "C"}, ensure_ascii=False), encoding="utf-8")
            mig2.run(d / "data", d / "config", log=lambda *_: None)
            k = json.loads((d / "data" / "books_kodansha.json").read_text(encoding="utf-8"))
            self.assertEqual([(b["series_key"], b["volume"], b["editions"]) for b in k], [("生徒会にも穴はある!", 2, ["フルカラー版"]), ("生徒会にも穴はある!", 14, [])])
            self.assertEqual(k[1], good)                                   # 変わらない本は不変
            y = json.loads((d / "data" / "yomi.json").read_text(encoding="utf-8"))
            self.assertEqual(y, {"生徒会にも穴はある!": {"yomi": "B"}})      # 新キーの既存の読みを優先
            self.assertEqual(json.loads((d / "config" / "yomi_manual.json").read_text(encoding="utf-8")), {"生徒会にも穴はある!": "C"})


if __name__ == "__main__":
    unittest.main()

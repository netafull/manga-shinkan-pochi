"""コミックの新刊ではない本（画集・設定資料集・公式ガイド・ファンブック・DVD・小説・写真集など）の判定。

build.load_all が読み込み時に使う。data/ のファイルは書き換えない（読み込み時に除くだけ）。
判定の優先順位:
 1. config/noncomic_overrides.json の include … 誤判定を戻す（最優先）
 2. config/noncomic_overrides.json の exclude … 判定で拾えないものを外す
 3. 題名キーワード・文庫レーベル・KADOKAWA の著者の役割で自動判定
「ドラマCD付き」「特装版」「文庫版（講談社文庫の漫画）」は漫画本体なので外さない。
境界例（ハルタ月号・劇場版アニメコミック・よみきり集など）は外さない（オーナーが後で判断）。
"""
import json
import re
import unicodedata

import common

CONFIG = common.ROOT / "config"

# 題名キーワード（NFKC・大文字小文字無視で照合。理由を添える）
TITLE_RULES = [
    (r"画集", "画集"),
    (r"設定(?:画|資料)集|原画集|資料集|設定集", "設定資料集"),
    (r"イラスト集|イラストbook", "イラスト集"),
    (r"アートブック|art ?works?|artbook|アートワークス|公式アートワーク", "アートブック"),
    (r"(?<![a-z])the art of(?![a-z])|ジ・?アート・?オブ|アート・オブ", "アートブック"),
    (r"公式ガイド|ガイドブック|コンプリートガイド|コレクターズ ?ガイド|公式全書|公式ビジュアル", "ガイド"),
    (r"ファンブック|fan ?book|style ?book|anniversary ?book", "ファンブック"),
    (r"(?:生態|大|公式)図鑑|ずかん|図かん", "図鑑"),
    (r"写真集", "写真集"),
    (r"シールブック|ポスターコレクション", "グッズ本"),
    (r"(?<![a-z])bible(?![a-z])", "BIBLE"),
    (r"^dvd[\)\s]|^blu-?ray[\)\s]|^ドラマcd[\)\s]", "映像・音声"),
    (r"^小説", "小説"),
    (r"^グラビア", "グラビア誌"),
    (r"第\d+号$|[春夏秋冬]号(?:\s|$)", "雑誌号"),
    (r"(?:卓上|壁掛け|\d{4}年)?カレンダー$", "カレンダー"),
]
# 末尾が「図鑑」で巻数なしのもの（「理想郷女子図鑑 5」のような漫画は巻数が付くので当たらない）
ENDS_ZUKAN = re.compile(r"図鑑$")

# 漫画ではない文庫（ラノベ・小説）のレーベル。講談社文庫など漫画の文庫版は入れない。
NG_LABELS = [
    "ダッシュエックス文庫", "電撃文庫", "角川文庫", "mf文庫", "ファミ通文庫", "富士見ファンタジア文庫", "富士見l文庫",
    "角川スニーカー文庫", "スニーカー文庫", "ガガガ文庫", "ga文庫", "オーバーラップ文庫", "hj文庫", "ビーンズ文庫",
    "講談社ラノベ文庫", "集英社オレンジ文庫", "コバルト文庫", "メディアワークス文庫", "ファン文庫", "ノベルス",
]

# KADOKAWA: 著者欄の役割にこれらが無い（編集・監修・イラストだけ等）かつレーベル空 → 非作品の強い手がかり
COMIC_ROLE = re.compile(r"漫画|作画|原作|^画$|^著者?$")


def _norm(s):
    return unicodedata.normalize("NFKC", s or "").casefold()


def load_overrides(path=None):
    p = path or CONFIG / "noncomic_overrides.json"
    o = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return {"exclude": o.get("exclude") or [], "include": o.get("include") or []}


def _ids(rows):
    return {r["id"] for r in rows if r.get("id")}


def judge(book, overrides=None):
    """(非作品か, 理由)。理由は除外のときだけ入る。"""
    ov = overrides if overrides is not None else load_overrides()
    bid = book.get("id")
    if bid in _ids(ov["include"]):
        return False, ""
    if bid in _ids(ov["exclude"]):
        return True, "手動除外"
    title = _norm(book.get("title"))
    for pat, why in TITLE_RULES:
        if re.search(pat, title):
            return True, "題名: " + why
    if ENDS_ZUKAN.search(title) and book.get("volume") is None:
        return True, "題名: 図鑑"
    label = _norm(book.get("label"))
    if label:
        for ng in NG_LABELS:
            if _norm(ng) in label:
                return True, "レーベル: " + (book.get("label") or "")
    roles = book.get("author_roles")
    if roles and not label and not any(COMIC_ROLE.search(_norm(r)) for r in roles):
        return True, "著者の役割に漫画・作画・著者・原作が無い（" + "・".join(roles) + "）"
    return False, ""


def split(books, overrides=None):
    """(残す本, [(除いた本, 理由)])"""
    ov = overrides if overrides is not None else load_overrides()
    keep, dropped = [], []
    for b in books:
        bad, why = judge(b, ov)
        if bad:
            dropped.append((b, why))
        else:
            keep.append(b)
    return keep, dropped

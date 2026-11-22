"""漫画ポチへのリンクの裏取り（純関数。ネットワーク・ファイルには触れない）。

題名の一致だけでは同名別作品を取り違えるため、著者の重なりと出版社の整合で確認できたものだけリンクする。
"""
import re
import unicodedata

# 漫画ポチ側のサイト名 → 出版社（新刊ポチ側の publisher 表記）。ここに無いサイトは出版社の証拠なし。
SITE_PUBLISHER = {
    "マガポケ": "講談社",
    "コミックDAYS": "講談社",
    "サンデーうぇぶり": "小学館",
    "マンガワン": "小学館",
    "BigComics": "小学館",
    "チャンピオンクロス": "秋田書店",
    "ヤンチャンWeb": "秋田書店",
    "花とゆめ＋": "白泉社",
    "マンガPark": "白泉社",
    "ヤングアニマル": "白泉社",
}

CONFIRMED = "confirmed"
PUBLISHER_ONLY = "publisher_consistent"
MISMATCH = "mismatch"
UNKNOWN = "unknown"
ALLOWED = (CONFIRMED, PUBLISHER_ONLY)

_ROLE = re.compile(r"(原作|原案|作画|漫画|マンガ|キャラクター原案|キャラクターデザイン|構成|脚本|イラスト|企画|監修|協力|作|著|画)\s*[:：]")
_SEP = re.compile(r"[/／|｜、,，;；]")
_DROP = re.compile(r"[\s　・･·.．。\-－ー_＿()（）\[\]【】「」『』!！?？&＆]")


def norm_title(s):
    return "".join(unicodedata.normalize("NFKC", s).lower().split())


def work_key(title, publisher):
    return norm_title(title) + "|" + publisher


def _fold_latin(s):
    """ÖYSTER → OYSTER。ラテン文字のアクセントだけ外す（かな・漢字の濁点は触らない）。"""
    out = []
    for ch in s:
        if ord(ch) > 127:
            d = unicodedata.normalize("NFD", ch)
            if d[0].isascii() and d[0].isalpha():
                ch = d[0]
        out.append(ch)
    return "".join(out)


def norm_name(s):
    return _DROP.sub("", _fold_latin(unicodedata.normalize("NFKC", s))).lower()


def split_names(s):
    """「原作:X 作画:Y」「X / Y」「X|Y」を名前の集合にする（正規化済み）。"""
    if not s:
        return set()
    s = unicodedata.normalize("NFKC", s)
    s = _ROLE.sub("/", s)
    out = set()
    for part in _SEP.split(s):
        n = norm_name(part)
        if n:
            out.add(n)
    return out


def names_overlap(a, b):
    """どちらかの名前が一致、または3文字以上の名前が他方に含まれる。"""
    for x in a:
        for y in b:
            if x == y:
                return True
            short, long_ = (x, y) if len(x) <= len(y) else (y, x)
            if len(short) >= 3 and short in long_:
                return True
    return False


def classify(work_author, work_publisher, pochi_authors, pochi_site):
    """戻り値 (status, reason)。pochi_authors は漫画ポチ側の著者名の文字列リスト。"""
    mine = split_names(work_author)
    theirs = set()
    for a in pochi_authors:
        theirs |= split_names(a)
    site_pub = SITE_PUBLISHER.get(pochi_site)
    if theirs and mine:
        if names_overlap(mine, theirs):
            return CONFIRMED, "著者が一致"
        return MISMATCH, "著者が重ならない" + (
            "（出版社は整合）" if site_pub == work_publisher else "")
    if site_pub:
        if site_pub == work_publisher:
            return PUBLISHER_ONLY, f"著者の証拠なし・{pochi_site}は{site_pub}"
        return MISMATCH, f"出版社が矛盾（{pochi_site}={site_pub}）"
    return UNKNOWN, "証拠なし"


def pick_candidate(work_author, work_publisher, cands):
    """cands: [{catalogId, site, authors(list), wikidata(bool)}]。
    戻り値 (採用した候補 or None, 代表status, reason, 各候補の判定 [(status, why, cand)])。
    confirmed > publisher_consistent。同順位は wikidata 照合済み→catalogId の小さい順。"""
    judged = []
    for c in cands:
        st, why = classify(work_author, work_publisher, c.get("authors") or [], c.get("site"))
        judged.append((st, why, c))
    for want in ALLOWED:
        hit = [j for j in judged if j[0] == want]
        if hit:
            hit.sort(key=lambda j: (not j[2].get("wikidata"), int(j[2]["catalogId"])))
            why = hit[0][1]
            n = len({j[2]["catalogId"] for j in hit})
            if n > 1:
                why += f"（同順位{n}件から選択）"
            return hit[0][2], want, why, judged
    if not judged:
        return None, UNKNOWN, "候補なし", judged
    final = MISMATCH if any(j[0] == MISMATCH for j in judged) else UNKNOWN
    return None, final, next(j[1] for j in judged if j[0] == final), judged


# --- 表記ゆれで拾う二段目（著者が一致したものだけ採用する） ---
_BRACKETED = re.compile(r"[（(【\[][^）)】\]]*[）)】\]]")
_EDITION = re.compile(r"(新装版|完全版|愛蔵版|カラー版|デジタル版|新版|文庫版)")
_FUZZY_DROP = re.compile(r"[^\w+]|_")


def fuzzy_key(title):
    """記号・空白・括弧書き・版の付記を落とした照合キー。
    「+」は残す（「もやしもん+」は続編で「もやしもん」とは別作品）。副題の切り落としはしない。"""
    t = unicodedata.normalize("NFKC", title).lower()
    t = _EDITION.sub("", _BRACKETED.sub("", t))
    return _FUZZY_DROP.sub("", t)


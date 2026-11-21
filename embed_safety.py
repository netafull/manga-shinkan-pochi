"""埋め込み(docs/embed/)に出してよい本かの判定。方針は「迷ったら外す」。

判定の優先順位:
 1. config/embed_overrides.json の exclude / exclude_series … 必ず除外（最優先）
 2. Amazon の成人向けフラグ adult が True … 除外（include でも戻さない）
 3. include … 自動除外の誤判定を戻す
 4. NG レーベル・NG キーワード … 除外
表紙は Amazon の adult が False と分かっている本だけ出す（キー無し＝未取得は文字だけ）。
ルールは config/embed_rules.json。コードに直書きしない。
"""
import json
import re
import unicodedata

import common

CONFIG = common.ROOT / "config"


def _norm(s):
    return unicodedata.normalize("NFKC", s or "").casefold()


def load_rules(path=None):
    p = path or CONFIG / "embed_rules.json"
    r = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return {"ng_labels": r.get("ng_labels") or [], "ng_keywords": r.get("ng_keywords") or []}


def load_overrides(path=None):
    p = path or CONFIG / "embed_overrides.json"
    o = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return {"exclude": o.get("exclude") or [], "exclude_series": o.get("exclude_series") or [],
            "include": o.get("include") or []}


def label_of(book, item):
    """book の label、無ければ Amazon の商品名末尾の括弧内（「(3) (ヤングマガジンKC)」→ヤングマガジンKC）。
    括弧の中身が数字だけ（巻数）のものはレーベルとみなさない。"""
    if book.get("label"):
        return book["label"]
    m = re.search(r"[(（]([^()（）]*)[)）]\s*$", (item or {}).get("title") or "")
    if m and not re.fullmatch(r"[\d０-９\s上中下]*", m.group(1)):
        return m.group(1).strip()
    return ""


def _kw_hit(text, kw):
    t, k = _norm(text), _norm(kw)
    if not k:
        return False
    if k.isascii() and k[0].isalnum() and k[-1].isalnum():
        return re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", t) is not None
    return k in t


def _ids(rows, key):
    return {r[key] for r in rows if r.get(key)}


def judge(book, item, rules, overrides):
    """(show, show_cover, reason)。reason は表示可でも空とは限らない（表紙なしの理由など）。"""
    item = item or {}
    if book.get("id") in _ids(overrides["exclude"], "id"):
        return False, False, "手動除外"
    if book.get("series_key") in _ids(overrides["exclude_series"], "series_key"):
        return False, False, "手動除外（作品ごと）"
    adult = item.get("adult")
    if adult is True:
        return False, False, "Amazon成人向けフラグ"
    included = book.get("id") in _ids(overrides["include"], "id")
    if not included:
        label = label_of(book, item)
        nl = _norm(label)
        for ng in rules["ng_labels"]:
            if _norm(ng) and _norm(ng) in nl:
                return False, False, f"NGレーベル: {label}"
        for kw in rules["ng_keywords"]:
            if _kw_hit(book.get("title") or "", kw) or _kw_hit(label, kw) or _kw_hit(item.get("title") or "", kw):
                return False, False, f"NGキーワード: {kw}"
    if adult is False:
        return True, True, ""
    return True, False, "成人向けフラグ未取得のため表紙なし"

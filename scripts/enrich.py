#!/usr/bin/env python3
"""Amazon の応答を data/amazon_items.json（ホワイトリスト項目のみ）に集約する。

- 新規ISBN: books.json のうち 今日-7日〜今日+30日 に発売で、まだ store にない isbn10 を getItems で補う。
- 価格の更新: 同じ期間の本を、最後に取得した日(updated)が古い順に getItems で取り直す。
- 無効ASIN（"The ItemIds X provided in the request is invalid"）は invalid に記録し二度と引かない。
- 呼び出しは amazon.py の日次上限・429停止に従う。Stop が出たら残りは呼ばず、ここまでのデータを保存する。
- 生の応答はコミットしない（保存するのは slim() の項目だけ）。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import amazon  # noqa: E402
import common  # noqa: E402
import isbnlib  # noqa: E402
import parse_pub as pp  # noqa: E402

STORE = ROOT / "data" / "amazon_items.json"
KODANSHA = ROOT / "data" / "books_kodansha.json"
SHUEISHA = ROOT / "data" / "books_shueisha.json"
WINDOW_BEFORE, WINDOW_AFTER = 7, 30


def load_store(path=None):
    import json
    path = path or STORE
    if path.exists():
        s = json.loads(path.read_text(encoding="utf-8"))
        s.setdefault("invalid", [])
        return s
    return {"items": {}, "invalid": []}


def ingest(store, resp, today_iso):
    """応答(getItems/searchItems)の商品を store に取り込む。取り込んだ slim のリストを返す。"""
    items = (resp.get("itemsResult") or {}).get("items") or (resp.get("searchResult") or {}).get("items") or []
    out = []
    for i in items:
        s = amazon.slim(i, today_iso)
        store["items"][s["asin"]] = s
        out.append(s)
    for e in resp.get("errors") or []:
        m = re.search(r"ItemIds (\w+) provided", e.get("message", ""))
        if m and m.group(1) not in store["invalid"]:
            store["invalid"].append(m.group(1))
    return out


def kodansha_book(s, publisher="講談社"):
    """slim の1件 → books_kodansha.json / books_shueisha.json のレコード。ISBNが取れないものは None。
    ISBN（ean）が無い電子書籍だけの版はここで落ちる。"""
    if not s["ean"] or not isbnlib.valid_isbn13(s["ean"]) or not s["published"]:
        return None
    # レーベル括弧・巻数表記の整形は parse_pub.parse_book に集約（集英社「題名 10 (ヤングジャンプコミックス)」型・全集の番号・上下・漢数字など）
    key, vol, display, flags, label = pp.parse_book(s["title"] or "", publisher)
    return {
        "id": s["ean"], "isbn13": s["ean"],
        "isbn10": s["asin"] if len(s["asin"]) == 10 else isbnlib.isbn13_to_isbn10(s["ean"]),
        "title": s["title"], "volume": vol, "series_key": key, "series_title": display,
        "author": " / ".join(dict.fromkeys(a for a in s["authors"] if a and a != publisher)),
        "publisher": publisher, "label": label,
        "release_date": s["published"], "source_url": None, "editions": flags,
        "source_note": "Amazon の商品情報より",
    }


def merge_kodansha(prev, found_slims, publisher="講談社"):
    """前回分に今回見つかった分を足す（ISBNで上書き）。スキャンが空でも前回分は消さない。"""
    by = {b["isbn13"]: b for b in prev}
    for s in found_slims:
        b = kodansha_book(s, publisher)
        if b:
            by[b["isbn13"]] = b
    return sorted(by.values(), key=lambda b: (b["release_date"], b["title"]))


def window(today):
    d = today.toordinal()
    return (today.fromordinal(d - WINDOW_BEFORE).isoformat(), today.fromordinal(d + WINDOW_AFTER).isoformat())


def enrich_new(store, books, today, max_calls, log=print):
    """未取得のISBN-10を getItems で補う。使った呼び出し数を返す。Stop は呼び出し側へ。"""
    lo, hi = window(today)
    todo = [b["isbn10"] for b in books if b.get("isbn10") and lo <= b["release_date"] <= hi
            and b["isbn10"] not in store["items"] and b["isbn10"] not in store["invalid"]]
    todo = list(dict.fromkeys(todo))
    n = 0
    for k in range(0, len(todo), 10):
        if n >= max_calls:
            log(f"enrich: 新規分の呼び出し枠 {max_calls} に到達（残り {len(todo) - k} 件は次回）")
            break
        r, hit = amazon.get_items(todo[k:k + 10], label="enrich new")
        n += 0 if hit else 1
        ingest(store, r, today.isoformat())
    return n


def refresh_prices(store, books, today, max_calls):
    """期間内の本を、取得日が古い順に取り直す。使った呼び出し数を返す。"""
    lo, hi = window(today)
    cands = {}
    for b in books:
        a = b.get("isbn10")
        if a and lo <= b["release_date"] <= hi and a in store["items"]:
            cands[a] = store["items"][a].get("updated") or "0000-00-00"
    # 今日より前に取得したものだけ。同じ日に何度回しても同じ商品を引き直さない
    order = [a for a, u in sorted(cands.items(), key=lambda kv: (kv[1], kv[0])) if u < today.isoformat()]
    n = 0
    for k in range(0, len(order), 10):
        if n >= max_calls:
            break
        r, hit = amazon.get_items(order[k:k + 10], label="refresh")
        n += 0 if hit else 1
        ingest(store, r, today.isoformat())
    return n

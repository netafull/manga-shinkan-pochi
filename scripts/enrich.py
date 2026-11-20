#!/usr/bin/env python3
"""Amazon応答を data/amazon_items.json に集約し、足りない分だけ getItems(ISBN-10)で補う。

  source ~/.secrets/env && python3 scripts/enrich.py [--max-calls N]

- cache/api/ の getItems / searchItems 応答を全部取り込む（APIは叩かない）。
- 対象: books.json のうち 今日-7日〜今日+30日 に発売で、まだ store にない isbn10。
- 無効ASIN（"The ItemIds X provided in the request is invalid"）は invalid として記録し二度と引かない。
- 講談社は kodansha_found.json（Amazon検索結果）から data/books_kodansha.json を作る。
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import amazon  # noqa: E402
import isbnlib  # noqa: E402
import parse_pub as pp  # noqa: E402

STORE = ROOT / "data" / "amazon_items.json"
TODAY = datetime.date.today()


def slim(i):
    ii = i.get("itemInfo", {})
    by = ii.get("byLineInfo", {})
    listing = ((i.get("offersV2") or {}).get("listings") or [{}])[0]
    money = (listing.get("price") or {}).get("money") or {}
    img = (((i.get("images") or {}).get("primary") or {}).get("large") or {})
    eans = ((ii.get("externalIds") or {}).get("eans") or {}).get("displayValues") or []
    return {
        "asin": i["asin"], "url": i.get("detailPageURL"),
        "title": (ii.get("title") or {}).get("displayValue"),
        "manufacturer": (by.get("manufacturer") or {}).get("displayValue"),
        "brand": (by.get("brand") or {}).get("displayValue"),
        "authors": [c.get("name") for c in by.get("contributors") or []],
        "published": ((ii.get("contentInfo") or {}).get("publicationDate") or {}).get("displayValue", "")[:10],
        "ean": eans[0] if eans else None,
        "price": money.get("amount"),
        # 幅100px未満の画像は「画像なし」のプレースホルダー
        "image": img.get("url") if (img.get("width") or 0) >= 100 else None,
        "binding": ((ii.get("classifications") or {}).get("binding") or {}).get("displayValue"),
    }


def load_store():
    return json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else {"items": {}, "invalid": []}


def ingest_cache(store):
    for p in sorted(amazon.CACHE.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        items = (d.get("itemsResult") or {}).get("items") or (d.get("searchResult") or {}).get("items") or []
        for i in items:
            store["items"][i["asin"]] = slim(i)
        for e in d.get("errors") or []:
            m = re.search(r"ItemIds (\w+) provided", e.get("message", ""))
            if m and m.group(1) not in store["invalid"]:
                store["invalid"].append(m.group(1))


def kodansha_books(store):
    found = ROOT / "data" / "kodansha_found.json"
    if not found.exists():
        return []
    out = []
    for i in json.loads(found.read_text(encoding="utf-8")):
        s = slim(i)
        store["items"][s["asin"]] = s
        if not s["ean"] or not isbnlib.valid_isbn13(s["ean"]):
            continue
        key, vol, display, flags = pp.parse_title(s["title"] or "")
        label = ""
        m = re.search(r"[(（]([^()（）]*(?:KC|コミックス|文庫|デラックス)[^()（）]*)[)）]\s*$", s["title"] or "")
        if m:
            label = m.group(1)
            display = display.replace(m.group(0), "").strip()
        # 「タイトル(3) (レーベル)」型: 括弧の巻数を取る
        mv = re.search(r"^(.*?)[(（](\d{1,4})[)）]", s["title"] or "")
        if mv:
            vol = int(mv.group(2))
            display = re.sub(r"\s+", " ", mv.group(1)).strip()
            key = re.sub(r"\s+", "", display)
        out.append({
            "id": s["ean"], "isbn13": s["ean"], "isbn10": s["asin"] if len(s["asin"]) == 10 else isbnlib.isbn13_to_isbn10(s["ean"]),
            "title": s["title"], "volume": vol, "series_key": key, "series_title": display,
            "author": " / ".join(dict.fromkeys(a for a in s["authors"] if a and a != "講談社")), "publisher": "講談社", "label": label,
            "release_date": s["published"], "source_url": None, "editions": flags,
            "source_note": "Amazon の商品情報より",
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=60)
    args = ap.parse_args()
    store = load_store()
    ingest_cache(store)
    kb = kodansha_books(store)
    (ROOT / "data" / "books_kodansha.json").write_text(json.dumps(kb, ensure_ascii=False, indent=1), encoding="utf-8")

    lo = (TODAY - datetime.timedelta(days=7)).isoformat()
    hi = (TODAY + datetime.timedelta(days=30)).isoformat()
    books = json.loads((ROOT / "data" / "books.json").read_text(encoding="utf-8"))
    todo = [b["isbn10"] for b in books if b["isbn10"] and lo <= b["release_date"] <= hi
            and b["isbn10"] not in store["items"] and b["isbn10"] not in store["invalid"]]
    print("todo", len(todo), "calls so far", amazon.calls_used())
    n = 0
    for k in range(0, len(todo), 10):
        if n >= args.max_calls:
            print("max-calls reached"); break
        batch = todo[k:k + 10]
        r, hit = amazon.get_items(batch, label="step4 enrich")
        n += 0 if hit else 1
        ingest_cache(store)
        STORE.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
        print("batch", k // 10, "ok" if "itemsResult" in r else r, "calls", amazon.calls_used(), flush=True)
    STORE.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    print("store items", len(store["items"]), "invalid", len(store["invalid"]), "calls", amazon.calls_used())


if __name__ == "__main__":
    main()

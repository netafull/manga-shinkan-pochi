#!/usr/bin/env python3
"""出版社3社(小学館・秋田書店・白泉社)から data/books.json を作る。

  python3 scripts/build_backbone.py            # キャッシュのみ使う(既定)
  python3 scripts/build_backbone.py --fetch    # 未キャッシュのページを礼儀正しく取得

取得するのは次のページだけ（各URL1回、キャッシュ優先）。
  小学館 3 / 秋田書店 1 / 白泉社 月別3 + 詳細(今日〜30日先、最大40件)
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import isbnlib  # noqa: E402
import parse_pub as pp  # noqa: E402
import pubfetch  # noqa: E402

TODAY = datetime.date.today()
MAX_HAKU_DETAILS = 40


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    args = ap.parse_args()
    net = args.fetch
    books = []

    for u in pp.SHOGAKUKAN_URLS:
        h = pubfetch.fetch(u, net)
        if h:
            books += pp.parse_shogakukan(h)
    h = pubfetch.fetch(pp.AKITA_URL, net)
    if h:
        books += pp.parse_akita(h)
    haku = []
    for y, m in pp.HAKU_MONTHS:
        h = pubfetch.fetch(pp.haku_url(y, m), net)
        if h:
            haku += pp.parse_haku_month(h)

    # 白泉社: 今日〜30日先のものだけ詳細ページでISBNを取る
    horizon = TODAY + datetime.timedelta(days=30)
    near = [b for b in haku if TODAY.isoformat() <= b["release_date"] <= horizon.isoformat()]
    near.sort(key=lambda b: b["release_date"])
    n_detail = 0
    for b in near[:MAX_HAKU_DETAILS]:
        h = pubfetch.fetch(b["source_url"], net)
        if h:
            b["isbn13"] = pp.parse_haku_detail_isbn(h)
            n_detail += 1
    haku_no_isbn = [b for b in haku if not b["isbn13"]]
    books += haku

    out, seen = [], set()
    for b in books:
        uid = b["isbn13"] or "haku:" + b["haku_id"]
        if uid in seen:
            continue
        seen.add(uid)
        key, vol, display, flags = pp.parse_title(b["title_raw"])
        out.append({
            "id": uid, "isbn13": b["isbn13"], "isbn10": isbnlib.isbn13_to_isbn10(b["isbn13"]) if b["isbn13"] else None,
            "title": b["title_raw"], "volume": vol, "series_key": key, "series_title": display,
            "author": b["author"], "publisher": b["publisher"], "label": b["label"],
            "release_date": b["release_date"], "source_url": b["source_url"], "editions": flags,
        })
    out.sort(key=lambda x: (x["release_date"], x["publisher"], x["title"]))
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "books.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    # ISBN未取得の白泉社(30日より先)は別ファイルに保持（将来ISBNが取れたら統合）
    (ROOT / "data" / "haku_pending.json").write_text(
        json.dumps(haku_no_isbn, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"books={len(out)} haku_total={len(haku)} haku_details={n_detail} haku_no_isbn={len(haku_no_isbn)}")


if __name__ == "__main__":
    main()

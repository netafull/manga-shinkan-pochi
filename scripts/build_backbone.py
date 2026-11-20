#!/usr/bin/env python3
"""出版社3社(小学館・秋田書店・白泉社)の発売予定から data/books.json を更新する。

  python3 scripts/build_backbone.py            # キャッシュのみ使う（ネットワークなし）
  python3 scripts/build_backbone.py --fetch    # 一覧ページを各1回取得して更新

毎日の実行は scripts/update.py から run() を呼ぶ。
取得するページ: 小学館 3 / 秋田書店 1 / 白泉社 月別3 + 詳細(今日〜30日先でISBN未取得のものだけ、最大40件)。

失敗に強くする:
- ページ単位（出版社×ページ）で成功・失敗を判定する。取得失敗・パース例外・0件は「失敗」。
- 失敗したページが担当する月は、前回のデータをそのまま残す（警告を出す）。
- 成功したページが扱う月は、その月の前回データを新しい内容で置き換える（過去日付の分は常に残す）。
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import common  # noqa: E402
import isbnlib  # noqa: E402
import parse_pub as pp  # noqa: E402
import pubfetch  # noqa: E402

MAX_HAKU_DETAILS = 40
BOOKS = ROOT / "data" / "books.json"


def _process(b):
    key, vol, display, flags = pp.parse_title(b["title_raw"])
    uid = b["isbn13"] or "haku:" + b["haku_id"]
    return {
        "id": uid, "isbn13": b["isbn13"], "isbn10": isbnlib.isbn13_to_isbn10(b["isbn13"]) if b["isbn13"] else None,
        "title": b["title_raw"], "volume": vol, "series_key": key, "series_title": display,
        "author": b["author"], "publisher": b["publisher"], "label": b["label"],
        "release_date": b["release_date"], "source_url": b["source_url"], "editions": flags,
        **({"haku_id": b["haku_id"]} if b.get("haku_id") else {}),
    }


def _haku_id(rec):
    if rec.get("haku_id"):
        return rec["haku_id"]
    m = re.search(r"/comicslist/(\d+)/", rec.get("source_url") or "")
    return m.group(1) if m else None


def merge_publisher(old, new, today_iso):
    """old/new は同一出版社の処理済みレコード。new は成功したページ由来の全件。"""
    months = {b["release_date"][:7] for b in new}
    new_ids = {b["id"] for b in new}
    new_haku = {h for h in (_haku_id(b) for b in new) if h}
    keep = []
    for o in old:
        if o["id"] in new_ids:
            continue
        if _haku_id(o) and _haku_id(o) in new_haku:
            continue
        if o["release_date"] < today_iso or o["release_date"][:7] not in months:
            keep.append(o)
    return keep + new


def run(today, prev_books, net=True, use_cache=False, log=print):
    """戻り値: (books, report)。report は {出版社: {"ok":bool,"new":n,"kept":n}} と warnings のリスト。"""
    today_iso = today.isoformat()
    warnings = []
    units = {"小学館": [], "秋田書店": [], "白泉社": []}  # 出版社 -> ページ結果のリスト(None=失敗)

    def page(pub, url, parser, **kw):
        try:
            h = pubfetch.fetch(url, net, use_cache=use_cache)
            items = parser(h, **kw) if h else None
        except Exception as e:  # レイアウト変更などのパース例外
            warnings.append(f"{pub}: {url} の解析に失敗 ({type(e).__name__})")
            return None
        if not items:
            warnings.append(f"{pub}: {url} が0件または取得失敗")
            return None
        return items

    for u in pp.SHOGAKUKAN_URLS:
        units["小学館"].append(page("小学館", u, pp.parse_shogakukan))
    units["秋田書店"].append(page("秋田書店", pp.AKITA_URL, pp.parse_akita, today=today))
    haku = []
    for y, m in pp.haku_months(today):
        r = page("白泉社", pp.haku_url(y, m), pp.parse_haku_month)
        units["白泉社"].append(r)
        haku += r or []

    # 白泉社: ISBNは詳細ページにしかない。前回までに分かったものは再利用し、今日〜30日先の未取得分だけ取りに行く
    prev_isbn = {}
    for o in prev_books:
        hid = _haku_id(o)
        if hid and o.get("isbn13"):
            prev_isbn[hid] = o["isbn13"]
    horizon = (today.fromordinal(today.toordinal() + 30)).isoformat()
    for b in haku:
        if b["haku_id"] in prev_isbn:
            b["isbn13"] = prev_isbn[b["haku_id"]]
    near = sorted((b for b in haku if not b["isbn13"] and today_iso <= b["release_date"] <= horizon),
                  key=lambda b: b["release_date"])
    n_detail = 0
    for b in near[:MAX_HAKU_DETAILS]:
        try:
            h = pubfetch.fetch(b["source_url"], net)
        except Exception:
            h = None
        if h:
            b["isbn13"] = pp.parse_haku_detail_isbn(h)
            n_detail += 1

    out, report = [], {}
    for pub, results in units.items():
        ok = [r for r in results if r]
        prev = [o for o in prev_books if o["publisher"] == pub]
        if not ok:
            warnings.append(f"{pub}: 取得できたページがありません。前回のデータ {len(prev)} 件を保持します")
            out += prev
            report[pub] = {"ok": False, "new": 0, "kept": len(prev)}
            continue
        if any(r is None for r in results):
            warnings.append(f"{pub}: 一部のページが失敗。その月は前回のデータを保持します")
        new, seen = [], set()
        for items in ok:
            for b in items:
                rec = _process(b)
                if rec["id"] not in seen:
                    seen.add(rec["id"])
                    new.append(rec)
        merged = merge_publisher(prev, new, today_iso)
        out += merged
        report[pub] = {"ok": True, "new": len(new), "kept": len(merged) - len(new)}
    out.sort(key=lambda x: (x["release_date"], x["publisher"], x["title"]))
    for w in warnings:
        log("WARNING: " + w)
    return out, {"publishers": report, "warnings": warnings, "haku_details": n_detail}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    args = ap.parse_args()
    import json
    prev = json.loads(BOOKS.read_text(encoding="utf-8")) if BOOKS.exists() else []
    books, rep = run(common.today(), prev, net=args.fetch, use_cache=not args.fetch)
    common.dump_records(BOOKS, books)
    print(f"books={len(books)}", rep["publishers"], f"haku_details={rep['haku_details']}")


if __name__ == "__main__":
    main()

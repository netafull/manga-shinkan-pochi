#!/usr/bin/env python3
"""出版社7社(小学館・秋田書店・白泉社・KADOKAWA・双葉社・竹書房・少年画報社)の発売予定から data/books.json を更新する。

  python3 scripts/build_backbone.py            # キャッシュのみ使う（ネットワークなし）
  python3 scripts/build_backbone.py --fetch    # 一覧ページを各1回取得して更新

毎日の実行は scripts/update.py から run() を呼ぶ。
取得するページ: 小学館 3 / 秋田書店 1 / 白泉社 月別3 + 詳細(今日〜30日先でISBN未取得のものだけ、最大40件)
/ KADOKAWA 今月・来月の2(Crawl-delay 20秒、ISBNは表紙画像URLのファイル名から) / 双葉社 公開JSON 今月・来月の2
/ 竹書房 コミック一覧(発売日の新しい順・100件/ページ。今月の月初より前が出るまで、最大3ページ)
  + 詳細(今日〜30日先でISBN未取得のものだけ、最大30件。ISBNは詳細ページにだけある)
/ 少年画報社 カレンダー今月・来月の2(区分「コミックス」だけ) + コミックス新着一覧1
  + 詳細(一覧の新着に載っていて書名が一致し、ISBN未取得のものだけ、最大20件。発売日が一致したときだけISBNを採る)。
  ※少年画報社のカレンダーには詳細へのリンクもISBNも無く、未発売の本は詳細ページ自体がまだ無い。そのぶんは ISBN 無し(仮ID sgh:…)で載せる。

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
MAX_TAKE_DETAILS = 30
MAX_SGH_DETAILS = 20
MAX_TAKE_PAGES = 3
BOOKS = ROOT / "data" / "books.json"


def _process(b):
    key, vol, display, flags = pp.parse_title(pp.volume_hint(b["title_raw"], b["publisher"]))
    uid = b["isbn13"]
    if not uid:
        for k, pre in (("haku_id", "haku:"), ("take_id", "take:"), ("sgh_id", "sgh:"), ("kadokawa_id", "kadokawa:")):
            if b.get(k):
                uid = pre + b[k]
                break
    return {
        "id": uid, "isbn13": b["isbn13"],
        "isbn10": isbnlib.isbn13_to_isbn10(b["isbn13"]) if b["isbn13"] and b["isbn13"].startswith("978") else None,
        "title": b["title_raw"], "volume": vol, "series_key": key, "series_title": display,
        "author": b["author"], "publisher": b["publisher"], "label": b["label"],
        "release_date": b["release_date"], "source_url": b["source_url"], "editions": flags,
        **({"haku_id": b["haku_id"]} if b.get("haku_id") else {}),
        **({"kadokawa_id": b["kadokawa_id"]} if b.get("kadokawa_id") else {}),
        **({"author_roles": b["roles"]} if b.get("roles") else {}),  # 著者欄の役割（noncomic.py が非作品の判定に使う）
        **({"take_id": b["take_id"]} if b.get("take_id") else {}),
        **({"sgh_id": b["sgh_id"]} if b.get("sgh_id") else {}),
    }


def _haku_id(rec):
    if rec.get("haku_id"):
        return rec["haku_id"]
    m = re.search(r"/comicslist/(\d+)/", rec.get("source_url") or "")
    return m.group(1) if m else None


def _alt_ids(rec):
    """ISBNが分かる前後で id が変わる本を同じ本とみなすための、出版社内の別キー。"""
    s = set()
    for k in ("take_id", "sgh_id", "kadokawa_id"):
        if rec.get(k):
            s.add((k, rec[k]))
    return s


def merge_publisher(old, new, today_iso):
    """old/new は同一出版社の処理済みレコード。new は成功したページ由来の全件。"""
    months = {b["release_date"][:7] for b in new}
    new_ids = {b["id"] for b in new}
    new_haku = {h for h in (_haku_id(b) for b in new) if h}
    new_alt = set().union(*(_alt_ids(b) for b in new)) if new else set()
    keep = []
    for o in old:
        if o["id"] in new_ids:
            continue
        if _haku_id(o) and _haku_id(o) in new_haku:
            continue
        if _alt_ids(o) & new_alt:
            continue
        if o["release_date"] < today_iso or o["release_date"][:7] not in months:
            keep.append(o)
    return keep + new


def run(today, prev_books, net=True, use_cache=False, log=print):
    """戻り値: (books, report)。report は {出版社: {"ok":bool,"new":n,"kept":n}} と warnings のリスト。"""
    today_iso = today.isoformat()
    warnings = []
    units = {"小学館": [], "秋田書店": [], "白泉社": [], "KADOKAWA": [], "双葉社": [], "竹書房": [], "少年画報社": []}  # 出版社 -> ページ結果のリスト(None=失敗)

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

    for target, _y, _m in pp.kadokawa_months(today):
        units["KADOKAWA"].append(page("KADOKAWA", pp.kadokawa_url(target), pp.parse_kadokawa))
    for ym in pp.futaba_months(today):
        units["双葉社"].append(page("双葉社", pp.futaba_url(ym), pp.parse_futabasha, ym=ym))

    # 竹書房: 発売日の新しい順の一覧を、今月の月初より前が出るまで(最大3ページ)読む。1ページでも失敗したら全体を失敗扱い(前回データを保持)
    take, take_ok = [], True
    month_start = today.replace(day=1).isoformat()
    for pg in range(1, MAX_TAKE_PAGES + 1):
        url = pp.take_url(pg)
        try:
            h = pubfetch.fetch(url, net, use_cache=use_cache)
            dates = pp.take_dates(h) if h else []
            items = pp.parse_takeshobo(h, min_date=month_start) if h else []
        except Exception as e:
            warnings.append(f"竹書房: {url} の解析に失敗 ({type(e).__name__})")
            take_ok = False
            break
        if not dates:
            warnings.append(f"竹書房: {url} が0件または取得失敗")
            take_ok = False
            break
        take += items
        if min(dates) < month_start:
            break
        if pg == MAX_TAKE_PAGES:   # 月初まで届かなかった: いちばん古い月は途中までかもしれないので使わない
            oldest = min(b["release_date"][:7] for b in take) if take else None
            take = [b for b in take if b["release_date"][:7] != oldest]
            warnings.append("竹書房: 月初まで届かないまま最大ページ数に達しました。最も古い月は反映しません")
    units["竹書房"].append(take if take_ok and take else None)
    if take_ok and not take:
        warnings.append("竹書房: 今月以降の本が0件")

    sgh = []
    for ym in pp.sgh_months(today):
        r = page("少年画報社", pp.sgh_url(ym), pp.parse_shonengahosha, ym=ym)
        units["少年画報社"].append(r)
        sgh += r or []

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

    # 竹書房: 白泉社と同じ。前回までに分かったISBNは再利用し、今日〜30日先の未取得分だけ詳細を取りに行く(近い順)
    take_isbn = {o["take_id"]: o["isbn13"] for o in prev_books if o.get("take_id") and o.get("isbn13")}
    for b in take:
        if b["take_id"] in take_isbn:
            b["isbn13"] = take_isbn[b["take_id"]]
    near = sorted((b for b in take if not b["isbn13"] and today_iso <= b["release_date"] <= horizon),
                  key=lambda b: b["release_date"])
    n_take = 0
    for b in near[:MAX_TAKE_DETAILS]:
        try:
            h = pubfetch.fetch(b["source_url"], net)
        except Exception:
            h = None
        if h:
            b["isbn13"] = pp.parse_take_detail_isbn(h)
            n_take += 1

    # 少年画報社: カレンダーに詳細リンクもISBNも無い。コミックス新着一覧に載っている本(発売済み)だけ、書名が一致し
    # 詳細ページの発売日も一致したときにISBNを採る。前回までに分かったISBNは再利用する
    sgh_prev = {o["sgh_id"]: o for o in prev_books if o.get("sgh_id") and o.get("isbn13")}
    for b in sgh:
        if b["sgh_id"] in sgh_prev:
            b["isbn13"] = sgh_prev[b["sgh_id"]]["isbn13"]
            b["source_url"] = sgh_prev[b["sgh_id"]]["source_url"]
    n_sgh = 0
    todo = [b for b in sgh if not b["isbn13"]]
    if todo:
        try:
            lh = pubfetch.fetch(pp.SGH_COMICS_LIST_URL, net)
            listing = pp.parse_sgh_comics_list(lh) if lh else []
        except Exception:
            listing = []
        by_title = {}
        for i, t in listing:
            by_title.setdefault(pp.sgh_norm_title(t), i)
        match = sorted((b for b in todo if pp.sgh_norm_title(b["title_raw"]) in by_title),
                       key=lambda b: b["release_date"], reverse=True)
        for b in match[:MAX_SGH_DETAILS]:
            url = f"{pp.SGH_BASE}/book_Info.php?id={by_title[pp.sgh_norm_title(b['title_raw'])]}"
            try:
                h = pubfetch.fetch(url, net)
            except Exception:
                h = None
            if h:
                n_sgh += 1
                isbn, rd = pp.parse_sgh_detail(h)
                if isbn and rd == b["release_date"]:
                    b["isbn13"] = isbn
                    b["source_url"] = url

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
    return out, {"publishers": report, "warnings": warnings, "haku_details": n_detail, "take_details": n_take, "sgh_details": n_sgh}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    args = ap.parse_args()
    import json
    prev = json.loads(BOOKS.read_text(encoding="utf-8")) if BOOKS.exists() else []
    books, rep = run(common.today(), prev, net=args.fetch, use_cache=not args.fetch)
    common.dump_records(BOOKS, books)
    print(f"books={len(books)}", rep["publishers"], f"haku_details={rep['haku_details']} take_details={rep['take_details']} sgh_details={rep['sgh_details']}")


if __name__ == "__main__":
    main()

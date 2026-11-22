#!/usr/bin/env python3
"""【1回限りの移行】data/yomi.json の読みに、追加の削り込み（yomi.clean_tail）を当て直す（2026-11-22）。

openBD には再問い合わせしない（元の collationkey は保存していないので、今の値に追加で当てる形）。
- 「/」以降（副題）、末尾の「~」「-」「・」、題名に無い数字以降（巻数・特典・副題）、巻数のカナ読み（その本の volume から逆算）を削る。
- どの本にも使われていない旧キー（series_key が現行データに無いもの）は削除する。
- 読みが無い（yomi: null）エントリ、source/isbn/checked 等の他の項目は変えない。

使い方: python3 scripts/renormalize_yomi_20261122.py [--dry-run] [--data DIR] [--list FILE]
再実行しても結果は変わらない（削り込みは冪等）。--list に変更一覧（TSV）を書く。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import yomi as yomi_mod  # noqa: E402

FILES = ("books.json", "books_kodansha.json", "books_shueisha.json")


def load_books(data):
    books = []
    for f in FILES:
        p = Path(data) / f
        if p.exists():
            books.extend(json.loads(p.read_text(encoding="utf-8")))
    return books


def renormalize(state, books):
    """(新しい state, 変更 [(key, title, volume, old, new)], 削除したキー) を返す。state は書き換えない。"""
    by_isbn = {b["isbn13"]: b for b in books if b.get("isbn13")}
    by_key = {}
    for b in books:
        if b.get("series_key"):
            by_key.setdefault(b["series_key"], b)
    new, changes, dead = {}, [], []
    for key, e in state.items():
        if key not in by_key:
            dead.append(key)
            continue
        e = dict(e)
        old = e.get("yomi")
        if old:
            b = by_isbn.get(e.get("isbn")) or {}
            title = b.get("series_title") or by_key[key].get("series_title")
            y = yomi_mod.normalize_yomi(old) or old
            y = yomi_mod.clean_tail(y, title, b.get("volume"))
            if y != old:
                e["yomi"] = y
                changes.append((key, title, b.get("volume"), old, y))
        new[key] = e
    return new, changes, dead


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--list", help="変更一覧（TSV）の出力先")
    a = ap.parse_args(argv)
    path = Path(a.data) / "yomi.json"
    state = yomi_mod.load_state(path)
    new, changes, dead = renormalize(state, load_books(a.data))
    print(f"yomi.json {len(state)}件 → {len(new)}件。読みを変更 {len(changes)}件、旧キー削除 {len(dead)}件")
    if a.list:
        lines = ["key\ttitle\tvolume\told\tnew"] + ["\t".join(str(x) for x in c) for c in changes]
        Path(a.list).write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not a.dry_run:
        yomi_mod.save_state(path, new)
    return 0


if __name__ == "__main__":
    sys.exit(main())

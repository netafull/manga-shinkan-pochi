#!/usr/bin/env python3
"""【1回限りの移行】巻数・series_key の取り方の修正（2026-11-22）を保存済みデータに反映する。

コード（parse_pub.volume_hint / parse_book）を直しても、data/ の books*.json は取得時に series_key・volume が
確定した値を持ち越すので直らない。ここで volume が None のレコードだけ、題名（title）から
series_key / volume / series_title / editions の4項目を再計算して書き直す。他の項目は触らない。
volume が取れているレコードは対象外（既存の巻数・URLを変えない）。

あわせて data/yomi.json（五十音の読み。series_key がキー）のキーを、旧キー→新キー（ISBN で対応付け）に付け替える。
読みの値は変えない。

使い方: python3 scripts/migrate_volume_fix_20261122.py [--dry-run] [--data DIR]
再実行しても結果は変わらない（2回目は volume が None のまま再計算しても同じ値になる）。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import common  # noqa: E402
import parse_pub as pp  # noqa: E402
import yomi as yomi_mod  # noqa: E402

FILES = ("books.json", "books_kodansha.json", "books_shueisha.json")
AMAZON_FILES = ("books_kodansha.json", "books_shueisha.json")   # Amazon の題名（レーベル括弧付き）から作ったもの


def recompute(rec, amazon):
    """レコード1件の (series_key, volume, series_title, editions)。amazon=True はレーベル括弧付きの題名。"""
    if amazon:
        key, vol, display, flags, _label = pp.parse_book(rec["title"] or "", rec["publisher"])
    else:
        key, vol, display, flags = pp.parse_title(pp.volume_hint(rec["title"] or "", rec["publisher"]))
    return key, vol, display, flags


def migrate_records(records, amazon):
    """volume が None のレコードだけ書き直す。(書き直した件数, 巻数が取れた件数, [(旧key, 新key)]) を返す。"""
    changed = got_vol = 0
    pairs = []
    for r in records:
        if r.get("volume") is not None:
            continue
        key, vol, display, flags = recompute(r, amazon)
        if (key, vol, display, flags) == (r["series_key"], r["volume"], r["series_title"], r["editions"]):
            continue
        if key != r["series_key"]:
            pairs.append((r["series_key"], key))
        r["series_key"], r["volume"], r["series_title"], r["editions"] = key, vol, display, flags
        changed += 1
        got_vol += vol is not None
    return changed, got_vol, pairs


def migrate_yomi(state, pairs, books_after):
    """旧キーの読みを新キーへ移す。新キーが既に読みを持っていれば上書きしない。戻り値: (移した件数, 消した旧キー数)。"""
    used = {b["series_key"] for b in books_after}
    moved = removed = 0
    by_new = {}
    for old, new in pairs:
        by_new.setdefault(new, []).append(old)
    for new, olds in by_new.items():
        # 読みが取れている旧キーを優先（同じ作品の巻ごとのキーが1つの新キーに集まる）
        olds = sorted(set(olds), key=lambda o: (not (state.get(o) or {}).get("yomi"), o))
        olds = [o for o in olds if o in state]
        if olds and new not in state:
            state[new] = state[olds[0]]
            moved += 1
        for o in olds:
            if o not in used and o != new:
                del state[o]
                removed += 1
    return moved, removed


def run(data_dir, dry_run=False, log=print):
    data_dir = Path(data_dir)
    all_pairs, all_books, summary = [], [], {}
    loaded = {}
    for name in FILES:
        p = data_dir / name
        if not p.exists():
            continue
        recs = json.loads(p.read_text(encoding="utf-8"))
        changed, got, pairs = migrate_records(recs, amazon=name in AMAZON_FILES)
        loaded[name] = recs
        all_pairs += pairs
        all_books += recs
        summary[name] = {"changed": changed, "volume_found": got, "key_changed": len(pairs)}
        log(f"{name}: 書き直し {changed} 件（うち巻数が取れた {got} 件、series_key が変わった {len(pairs)} 件）")
        if changed and not dry_run:
            common.dump_records(p, recs)
    yp = data_dir / "yomi.json"
    if yp.exists() and all_pairs:
        state = yomi_mod.load_state(yp)
        moved, removed = migrate_yomi(state, all_pairs, all_books)
        summary["yomi"] = {"moved": moved, "removed_old_keys": removed}
        log(f"yomi.json: 新キーへ移した {moved} 件、使われなくなった旧キーを削除 {removed} 件")
        if not dry_run:
            yomi_mod.save_state(yp, state)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--data", default=str(ROOT / "data"))
    a = ap.parse_args()
    run(a.data, dry_run=a.dry_run)


if __name__ == "__main__":
    main()

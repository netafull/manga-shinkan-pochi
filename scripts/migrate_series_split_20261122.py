#!/usr/bin/env python3
"""【1回限りの移行】同じ作品が2つの series_key に割れていた件の修正（2026-11-22）を保存済みデータに反映する。

対象は「X(5) 特典付き特装版」「X(14)限定版」型（括弧の巻数が取れず series_key に「(5)」が残った）と、
「公式フルカラー版『副題』」「カラー版」型（版表記が題名の一部として series_key に入った）。
全レコードを parse_pub.parse_book / parse_title で再計算し、series_key が変わるレコードだけ
series_key / volume / series_title / editions の4項目を書き直す。series_key が変わらないレコードは一切触らない。

あわせて data/yomi.json と config/yomi_manual.json のキーを旧→新に付け替える（読みの値は変えない。新キーに既にあれば旧キーを消すだけ）。

使い方: python3 scripts/migrate_series_split_20261122.py [--dry-run] [--data DIR] [--config DIR]
再実行しても結果は変わらない。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import common  # noqa: E402
import yomi as yomi_mod  # noqa: E402
import migrate_volume_fix_20261122 as base  # noqa: E402

FILES = base.FILES
AMAZON_FILES = base.AMAZON_FILES


def migrate_records(records, amazon):
    """series_key が変わるレコードだけ書き直す。(書き直した件数, [(旧key, 新key, 題名)]) を返す。"""
    pairs = []
    for r in records:
        key, vol, display, flags = base.recompute(r, amazon)
        if key == r["series_key"]:
            continue
        pairs.append((r["series_key"], key, r["title"]))
        r["series_key"], r["volume"], r["series_title"], r["editions"] = key, vol, display, flags
    return len(pairs), pairs


def migrate_manual(manual, pairs):
    """手動辞書の旧キーを新キーへ。新キーに既にあればそちらを優先し、旧キーは消す。"""
    moved = 0
    for old, new, _t in pairs:
        if old in manual and old != new:
            v = manual.pop(old)
            if new not in manual:
                manual[new] = v
                moved += 1
    return moved


def run(data_dir, config_dir, dry_run=False, log=print):
    data_dir, config_dir = Path(data_dir), Path(config_dir)
    all_pairs, all_books, loaded = [], [], {}
    for name in FILES:
        p = data_dir / name
        if not p.exists():
            continue
        recs = json.loads(p.read_text(encoding="utf-8"))
        n, pairs = migrate_records(recs, amazon=name in AMAZON_FILES)
        loaded[name] = recs
        all_pairs += pairs
        all_books += recs
        log(f"{name}: series_key が変わった {n} 件")
        for old, new, t in pairs:
            log(f"  {old!r} -> {new!r}  ({t})")
        if n and not dry_run:
            common.dump_records(p, recs)
    yp = data_dir / "yomi.json"
    if yp.exists() and all_pairs:
        state = yomi_mod.load_state(yp)
        moved, removed = base.migrate_yomi(state, [(o, n) for o, n, _ in all_pairs], all_books)
        log(f"yomi.json: 移した {moved} 件、旧キー削除 {removed} 件")
        if not dry_run:
            yomi_mod.save_state(yp, state)
    mp = config_dir / "yomi_manual.json"
    if mp.exists() and all_pairs:
        manual = json.loads(mp.read_text(encoding="utf-8"))
        before = dict(manual)
        moved = migrate_manual(manual, all_pairs)
        log(f"yomi_manual.json: 付け替え {moved} 件、削除 {len(before) - len(manual) + moved} 件")
        if not dry_run and manual != before:
            mp.write_text(json.dumps(manual, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return all_pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--config", default=str(ROOT / "config"))
    a = ap.parse_args()
    run(a.data, a.config, dry_run=a.dry_run)


if __name__ == "__main__":
    main()

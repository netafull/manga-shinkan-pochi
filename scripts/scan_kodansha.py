#!/usr/bin/env python3
"""講談社コミックスをAmazonの新着順検索で拾う（講談社サイトには一切アクセスしない）。
NewestArrivals は未来日付を含む降順で、1クエリ最大10ページ(100件)しか届かないため、
レーベル名キーワードで分割して今日-7日まで掘る。結果は slim（ホワイトリスト項目）にして返す。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import amazon  # noqa: E402

NODE = "466280"  # 本 > コミック
IMPRINTS = ["講談社", "講談社コミックス", "KC デザート", "ヤンマガKC", "モーニング KC", "アフタヌーンKC",
            "シリウスKC", "なかよしKC", "別冊フレンドKC", "少年マガジンKC", "マガジンポケットKC",
            "ライバルKC", "ヒーローズコミックス", "ARIA", "KCデラックス", "講談社 文庫版"]


def scan(store, today, max_calls, found, log=print):
    """見つかった講談社の slim を found(dict asin->slim) と store["items"] に入れる。使った呼び出し数を返す。
    Stop（上限・429・エラー）は呼び出し側へ伝える。それまでの成果は found / store に残る。
    講談社以外の検索結果は保存しない（store が膨らむため）。"""
    lo = today.fromordinal(today.toordinal() - 7).isoformat()
    hi = today.fromordinal(today.toordinal() + 60).isoformat()
    n = 0
    for kw in IMPRINTS:
        for page in range(1, 11):
            if n >= max_calls:
                log(f"scan: 呼び出し枠 {max_calls} に到達")
                return n
            r, hit = amazon.search_items(keywords=kw, browse_node_id=NODE, sort_by="NewestArrivals",
                                         page=page, label=f"scan {kw} p{page}")
            n += 0 if hit else 1
            items = (r.get("searchResult") or {}).get("items") or []
            if not items:
                break
            dates = []
            for i in items:
                s = amazon.slim(i, today.isoformat())
                if s["published"]:
                    dates.append(s["published"])
                if s["manufacturer"] == "講談社" and lo <= s["published"] <= hi:
                    found[s["asin"]] = s
                    store["items"][s["asin"]] = s
            if dates and min(dates) < lo:
                break
    return n

#!/usr/bin/env python3
"""講談社コミックスをAmazonの新着順検索で拾う（講談社サイトには一切アクセスしない）。
NewestArrivals は未来日付を含む降順で、1クエリ最大10ページ(100件)しか届かないため、
レーベル名キーワードで分割して今日-7日まで掘る。"""
import datetime, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import amazon

NODE = "466280"  # 本 > コミック
TODAY = datetime.date.today()
LO = (TODAY - datetime.timedelta(days=7)).isoformat()
HI = (TODAY + datetime.timedelta(days=60)).isoformat()
IMPRINTS = ["講談社", "講談社コミックス", "KC デザート", "ヤンマガKC", "モーニング KC", "アフタヌーンKC",
            "シリウスKC", "なかよしKC", "別冊フレンドKC", "少年マガジンKC", "マガジンポケットKC",
            "ライバルKC", "ヒーローズコミックス", "ARIA", "KCデラックス", "講談社 文庫版"]
STEP3_STOP_AT = 125  # この累計に達したらStep3を打ち切る(Step4用に残す)

def main():
    found = {}
    for kw in IMPRINTS:
        for page in range(1, 11):
            if amazon.calls_used() >= STEP3_STOP_AT:
                print("step3 budget reached"); break
            r, hit = amazon.search_items(keywords=kw, browse_node_id=NODE, sort_by="NewestArrivals",
                                         page=page, label=f"step3 {kw} p{page}")
            items = (r.get("searchResult") or {}).get("items") or []
            if not items:
                print(kw, page, "no items", r.get("errors")); break
            dates = []
            for i in items:
                ii = i.get("itemInfo", {})
                d = (ii.get("contentInfo", {}).get("publicationDate", {}) or {}).get("displayValue", "")[:10]
                dates.append(d)
                man = (ii.get("byLineInfo", {}).get("manufacturer", {}) or {}).get("displayValue", "")
                if man == "講談社" and LO <= d <= HI:
                    found[i["asin"]] = i
            print(kw, page, "min", min(d for d in dates if d) if any(dates) else None, "found", len(found), "calls", amazon.calls_used(), flush=True)
            if any(dates) and min(d for d in dates if d) < LO:
                break
    Path(ROOT / "data" / "kodansha_found.json").write_text(json.dumps(list(found.values()), ensure_ascii=False), encoding="utf-8")
    print("total found", len(found), "calls", amazon.calls_used())

main()

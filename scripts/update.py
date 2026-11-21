#!/usr/bin/env python3
"""毎日の更新: 出版社 → 講談社・集英社(Amazon新着スキャン) → getItems(新規ISBN・価格更新) → 作品名の読み(openBD) → ビルド。

  source ~/.secrets/env     # CREATORSAPI_*（無ければAmazonの段は飛ばして既存データでビルド）
  GA4_ID=G-XXXX python3 scripts/update.py

状態は data/ にコミットされる（books.json / books_kodansha.json / amazon_items.json / api_usage.json）。
どの段が失敗しても既存データは消さず、最後に必ずビルドする。
Amazon の呼び出しは amazon.DAILY_CAP（日次の硬い上限）と 429 で止まる。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import amazon  # noqa: E402
import build_backbone  # noqa: E402
import common  # noqa: E402
import enrich  # noqa: E402
import scan_kodansha  # noqa: E402
import yomi  # noqa: E402

# 1回の実行での段ごとの呼び出し枠（合計が DAILY_CAP 以下になるように）
SCAN_MAX_CALLS = 70
SCAN_SHUEISHA_MAX_CALLS = 60
ENRICH_MAX_CALLS = 80
REFRESH_MAX_CALLS = 40


def _read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def run(data_dir=None, today=None, net=True, build_fn=None, log=print):
    data = Path(data_dir) if data_dir else ROOT / "data"
    today = today or common.today()
    amazon.reset_run()
    amazon.USAGE = data / "api_usage.json"
    calls = {"scan": 0, "shueisha": 0, "enrich": 0, "refresh": 0}
    warnings = []

    def warn(msg):
        warnings.append(msg)
        log("WARNING: " + msg)

    # 1) 出版社
    prev = _read(data / "books.json", [])
    try:
        books, rep = build_backbone.run(today, prev, net=net, use_cache=False, log=log)
        warnings += rep["warnings"]
    except Exception as e:  # 想定外でも前回データを保つ
        warn(f"出版社の更新で例外 ({type(e).__name__})。前回のデータを保持")
        books, rep = prev, {"publishers": {}}
    if prev and len(books) < len(prev) * 0.5:
        warn(f"出版社データが大きく減っています ({len(prev)} → {len(books)})")
    common.dump_records(data / "books.json", books)

    # 2) Amazon（講談社・集英社スキャン・新規ISBN・価格更新）
    store = enrich.load_store(data / "amazon_items.json")
    kprev = _read(data / "books_kodansha.json", [])
    sprev = _read(data / "books_shueisha.json", [])
    found = {}
    found_s = {}
    stop_reason = None
    if not net:
        stop_reason = "ネットワークなしの実行"
    elif not amazon.has_credentials():
        stop_reason = "認証情報の環境変数が未設定"
        warn("Amazon: " + stop_reason + "。既存データでビルドします")
    else:
        stages = (("enrich", lambda: enrich.enrich_new(store, books + kprev + sprev, today, ENRICH_MAX_CALLS, log=log)),
                  ("scan", lambda: scan_kodansha.scan(store, today, SCAN_MAX_CALLS, found, log=log)),
                  ("shueisha", lambda: scan_kodansha.scan_shueisha(store, today, SCAN_SHUEISHA_MAX_CALLS, found_s, log=log)),
                  ("refresh", lambda: enrich.refresh_prices(store, books + kprev + sprev, today, REFRESH_MAX_CALLS)))
        try:
            for name, fn in stages:
                c0 = amazon.run_calls()
                try:
                    fn()
                finally:
                    calls[name] = amazon.run_calls() - c0
        except amazon.Stop as e:
            stop_reason = str(e)
            warn(f"Amazon: {stop_reason}。以後この実行では呼ばず、既存データでビルドします")
        except Exception as e:
            stop_reason = type(e).__name__
            warn(f"Amazon: 想定外の例外 ({stop_reason})。既存データでビルドします")
        if not found and stop_reason is None:
            warn("Amazon: 講談社の新着が0件でした。前回のデータを保持します")
        if not found_s and stop_reason is None:
            warn("Amazon: 集英社の新着が0件でした。前回のデータを保持します")
    kb = enrich.merge_kodansha(kprev, list(found.values()))
    common.dump_records(data / "books_kodansha.json", kb)
    sb = enrich.merge_kodansha(sprev, list(found_s.values()), "集英社")
    common.dump_records(data / "books_shueisha.json", sb)

    # store は使われている本のISBN-10だけ残す（検索で拾った無関係な商品を溜めない）
    used = {b["isbn10"] for b in books + kb + sb if b.get("isbn10")}
    store["items"] = {k: v for k, v in store["items"].items() if k in used}
    common.dump_store(data / "amazon_items.json", store)

    # 3) 作品名の読み（openBD。失敗してもビルドは続ける）
    ystats = {"queries": 0, "got": 0, "pending": 0, "stopped": None}
    try:
        ystats = yomi.run(books + kb + sb, data / "yomi.json", today, net=net, log=log)
        if ystats["stopped"] and net:
            warnings.append("yomi: " + ystats["stopped"])
    except Exception as e:
        ystats["stopped"] = type(e).__name__
        warn(f"読みの更新で例外 ({type(e).__name__})。前回のデータでビルドします")

    # 4) ビルド
    if build_fn is None:
        import build
        build_fn = lambda: build.build(today=today, data=data)  # noqa: E731
    info = build_fn()

    used_calls = amazon.run_calls()
    log("[update] today=%s amazon_calls=%d (enrich=%d scan=%d shueisha=%d refresh=%d) today_total=%d/%d stopped=%s "
        "books=%d kodansha=%d shueisha=%d items=%d yomi_queries=%d yomi_got=%d yomi_pending=%d warnings=%d"
        % (today, used_calls, calls["enrich"], calls["scan"], calls["shueisha"], calls["refresh"],
           amazon.calls_today(), amazon.DAILY_CAP,
           stop_reason or "no", len(books), len(kb), len(sb), len(store["items"]), ystats["queries"], ystats["got"], ystats["pending"], len(warnings)))
    return {"calls": calls, "run_calls": used_calls, "stopped": stop_reason, "warnings": warnings,
            "books": len(books), "kodansha": len(kb), "shueisha": len(sb), "yomi": ystats, "build": info}


if __name__ == "__main__":
    run()

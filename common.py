"""共通の小物。日付は日本時間（GitHub Actions は UTC で動くため date.today() を使わない）。"""
import datetime
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JST = datetime.timezone(datetime.timedelta(hours=9))


def today():
    """日本時間の今日。環境変数 SHINKAN_TODAY=YYYY-MM-DD で上書き（テスト・再現用）。"""
    v = os.environ.get("SHINKAN_TODAY")
    return datetime.date.fromisoformat(v) if v else datetime.datetime.now(JST).date()


def dump_records(path, records):
    """レコード1件1行のJSON配列で書く（差分が読みやすく、サイズも小さい）。"""
    import json
    body = ",\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    Path(path).write_text("[\n" + body + "\n]\n", encoding="utf-8")


def dump_store(path, store):
    """{"invalid":[...], "items":{key:{...}}} をキー順・1件1行で書く。"""
    import json
    items = ",\n".join(f"{json.dumps(k)}:{json.dumps(v, ensure_ascii=False)}" for k, v in sorted(store["items"].items()))
    inv = json.dumps(sorted(set(store.get("invalid", []))))
    Path(path).write_text('{"invalid":' + inv + ',"items":{\n' + items + "\n}}\n", encoding="utf-8")

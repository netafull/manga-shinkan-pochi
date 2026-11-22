#!/usr/bin/env python3
"""GitHub Issue（タイトルが [embed-overrides] で始まる）の本文から埋め込みの除外操作を読み、
config/embed_overrides.json に反映する。Amazon・出版社サイトには一切アクセスしない。

本文の ```json ブロック:
  {"exclude":[{"id","title"}], "exclude_series":[{"series_key","title"}], "include":[{"id","title"}],
   "remove_exclude":[{"id"}], "remove_exclude_series":[{"series_key"}]}
Issue 本文はシェルに展開しない。GITHUB_EVENT_PATH の JSON を読む（ワークフロー側の取り決め）。
不正な入力のときは設定を一切変えず、理由を結果ファイルとエラー出力に書いて終了コード1。
"""
import datetime
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import common  # noqa: E402

MAX_OPS = 100
MAX_LEN = 200
KEYS = ("exclude", "exclude_series", "include", "remove_exclude", "remove_exclude_series")
TITLE_PREFIX = "[embed-overrides]"


class OverrideError(Exception):
    pass


def load_known(data_dir):
    """data/ の books*.json から {id: book} と series_key の集合を作る。"""
    ids, series = {}, set()
    for p in sorted(Path(data_dir).glob("books*.json")):
        for b in json.loads(p.read_text(encoding="utf-8")):
            ids[b["id"]] = b
            if b.get("series_key"):
                series.add(b["series_key"])
    return ids, series


def parse_body(body):
    m = re.search(r"```json\s*\n(.*?)\n\s*```", body or "", re.S)
    if not m:
        raise OverrideError("本文に ```json ブロックが見つかりません")
    try:
        ops = json.loads(m.group(1))
    except ValueError as e:
        raise OverrideError(f"JSON を読めません: {e}")
    if not isinstance(ops, dict):
        raise OverrideError("JSON はオブジェクトである必要があります")
    unknown = set(ops) - set(KEYS)
    if unknown:
        raise OverrideError("知らないキー: " + ", ".join(sorted(map(str, unknown)))[:100])
    return {k: ops.get(k) or [] for k in KEYS}


def validate(ops, ids, series):
    total = 0
    for k in KEYS:
        rows = ops[k]
        if not isinstance(rows, list):
            raise OverrideError(f"{k} は配列である必要があります")
        total += len(rows)
        field = "series_key" if "series" in k else "id"
        for r in rows:
            if not isinstance(r, dict) or not isinstance(r.get(field), str) or not r[field]:
                raise OverrideError(f"{k} の要素に文字列の {field} が必要です")
            if len(r[field]) > MAX_LEN or len(str(r.get("title") or "")) > MAX_LEN:
                raise OverrideError(f"{k} の文字列が長すぎます（{MAX_LEN}字まで）")
            if "title" in r and not isinstance(r["title"], str):
                raise OverrideError(f"{k} の title は文字列です")
            if field == "id" and k != "remove_exclude" and r[field] not in ids:
                raise OverrideError(f"{k}: 存在しない id です: {r[field]}")
            if field == "series_key" and k == "exclude_series" and r[field] not in series:
                raise OverrideError(f"{k}: 存在しない series_key です: {r[field]}")
    if total == 0:
        raise OverrideError("操作が1件もありません")
    if total > MAX_OPS:
        raise OverrideError(f"件数が多すぎます（{total}件。{MAX_OPS}件まで）。分けて作り直してください")


def apply(ops, ov, ids, today_iso):
    """ov を書き換える。戻り値は集計 dict。titles は data 側の正しい題名を使う（本文の title は信用しない）。"""
    res = {k: 0 for k in ("excluded", "excluded_series", "included", "removed", "removed_series", "skipped")}

    def have(rows, field, v):
        return any(r.get(field) == v for r in rows)

    for r in ops["exclude"]:
        if have(ov["exclude"], "id", r["id"]):
            res["skipped"] += 1
            continue
        b = ids[r["id"]]
        ov["exclude"].append({"id": r["id"], "title": b["title"][:MAX_LEN], "added": today_iso})
        res["excluded"] += 1
    for r in ops["exclude_series"]:
        if have(ov["exclude_series"], "series_key", r["series_key"]):
            res["skipped"] += 1
            continue
        title = next((b["series_title"] for b in ids.values() if b.get("series_key") == r["series_key"]), r.get("title", ""))
        ov["exclude_series"].append({"series_key": r["series_key"], "title": title[:MAX_LEN], "added": today_iso})
        res["excluded_series"] += 1
    for r in ops["include"]:
        if have(ov["include"], "id", r["id"]):
            res["skipped"] += 1
            continue
        ov["include"].append({"id": r["id"], "title": ids[r["id"]]["title"][:MAX_LEN], "added": today_iso})
        res["included"] += 1
    for r in ops["remove_exclude"]:
        n = len(ov["exclude"])
        ov["exclude"] = [x for x in ov["exclude"] if x.get("id") != r["id"]]
        res["removed" if len(ov["exclude"]) < n else "skipped"] += 1
    for r in ops["remove_exclude_series"]:
        n = len(ov["exclude_series"])
        ov["exclude_series"] = [x for x in ov["exclude_series"] if x.get("series_key") != r["series_key"]]
        res["removed_series" if len(ov["exclude_series"]) < n else "skipped"] += 1
    return res


def summary(res):
    names = [("excluded", "除外"), ("excluded_series", "作品ごとに除外"), ("included", "自動除外を戻す"),
             ("removed", "手動除外を取り消し"), ("removed_series", "作品ごとの手動除外を取り消し")]
    parts = [f"{label} {res[k]}件" for k, label in names if res[k]]
    s = "、".join(parts) or "変更なし"
    if res["skipped"]:
        s += f"（すでに反映済み・該当なし {res['skipped']}件）"
    return s


def run(event_path, config_path, data_dir, today_iso, result_path=None):
    """戻り値: (ok, message)。ok のときだけ config_path を書く。"""
    try:
        ev = json.loads(Path(event_path).read_text(encoding="utf-8"))
        issue = ev["issue"]
        if not (issue.get("title") or "").startswith(TITLE_PREFIX):
            raise OverrideError("タイトルが [embed-overrides] で始まっていません")
        ops = parse_body(issue.get("body"))
        ids, series = load_known(data_dir)
        validate(ops, ids, series)
        p = Path(config_path)
        ov = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        for k in ("exclude", "exclude_series", "include"):
            ov.setdefault(k, [])
        res = apply(ops, ov, ids, today_iso)
        p.write_text(json.dumps(ov, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ok, msg = True, summary(res)
    except OverrideError as e:
        ok, msg = False, str(e)
    except (KeyError, TypeError, ValueError, OSError) as e:
        ok, msg = False, f"処理できませんでした（{type(e).__name__}）"
    if result_path:
        Path(result_path).write_text(msg, encoding="utf-8")
    return ok, msg


def main():
    ok, msg = run(os.environ["GITHUB_EVENT_PATH"], ROOT / "config/embed_overrides.json", ROOT / "data",
                  common.today().isoformat(), os.environ.get("EMBED_RESULT_FILE"))
    print(("OK: " if ok else "ERROR: ") + msg, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

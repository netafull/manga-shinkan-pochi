"""Amazon Creators API クライアント（標準ライブラリのみ）。

方針
- 1日あたりの呼び出し数に硬い上限(DAILY_CAP)を置く。数は data/api_usage.json に日付ごとに記録
  （コミットされる小さなファイル）し、同じ日に何度実行しても合算される。呼ぶ直前に毎回確認する。
- 429・その他の非200・通信エラーが起きたら、その実行の残りではもうAPIを呼ばない（Stop）。
  呼び出し側は既存データでビルドを続ける。
- 呼び出し1件ごとのログは logs/api_log.jsonl（gitignore。認証情報は書かない）。
- 応答キャッシュ cache/api/（gitignore）。あればAPIを叩かない。
- 認証情報は環境変数 CREATORSAPI_CREDENTIAL_ID / CREATORSAPI_CREDENTIAL_SECRET / CREATORSAPI_PARTNER_TAG
  のみから読む。値は表示しない。
- 枠は家電ポチ・電書ポチと共有。DAILY_CAP をオーナーの確認なしに増やさないこと。
- minSavingPercent は絶対に送らない。
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import common

ROOT = common.ROOT
CACHE = ROOT / "cache" / "api"
LOG = ROOT / "logs" / "api_log.jsonl"
USAGE = ROOT / "data" / "api_usage.json"

TOKEN_URL = "https://api.amazon.co.jp/auth/o2/token"
SEARCH_URL = "https://creatorsapi.amazon/catalog/v1/searchItems"
GET_ITEMS_URL = "https://creatorsapi.amazon/catalog/v1/getItems"
SCOPE = "creatorsapi::default"
MARKETPLACE = "www.amazon.co.jp"
DAILY_CAP = 260   # 1日の上限。共有枠。オーナーが2026-11-21に200→260を承認（集英社スキャン分）。今後もオーナーの確認なしに上げない
GAP = 1.1         # 呼び出し間隔(秒)
KEEP_DAYS = 30    # api_usage.json に残す日数

ITEM_RESOURCES = [
    "itemInfo.title",
    "itemInfo.byLineInfo",
    "itemInfo.classifications",
    "itemInfo.contentInfo",
    "itemInfo.externalIds",
    "itemInfo.productInfo",
    "images.primary.large",
    "offersV2.listings.price",
]


class Stop(Exception):
    """この実行ではもうAPIを呼ばない（上限・429・エラー）。"""


_state = {"token": None, "last": 0.0, "stopped": None, "run_calls": 0}


def reset_run():
    """実行ごとの状態を初期化（テスト・update.py用）。"""
    _state.update(token=None, last=0.0, stopped=None, run_calls=0)


def stopped_reason():
    return _state["stopped"]


def run_calls():
    return _state["run_calls"]


def has_credentials():
    return all(os.environ.get(k) for k in
               ("CREATORSAPI_CREDENTIAL_ID", "CREATORSAPI_CREDENTIAL_SECRET", "CREATORSAPI_PARTNER_TAG"))


# ---------- 1日の使用回数 ----------
def _load_usage():
    try:
        return json.loads(USAGE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def calls_today():
    return int(_load_usage().get(common.today().isoformat(), 0))


def _count_call():
    u = _load_usage()
    k = common.today().isoformat()
    u[k] = int(u.get(k, 0)) + 1
    for old in sorted(u)[:-KEEP_DAYS]:
        del u[old]
    USAGE.parent.mkdir(parents=True, exist_ok=True)
    USAGE.write_text(json.dumps(u, sort_keys=True, indent=0) + "\n", encoding="utf-8")


# ---------- HTTP（テストで差し替える） ----------
def _creds():
    cid = os.environ.get("CREATORSAPI_CREDENTIAL_ID")
    sec = os.environ.get("CREATORSAPI_CREDENTIAL_SECRET")
    tag = os.environ.get("CREATORSAPI_PARTNER_TAG")
    if not (cid and sec and tag):
        raise Stop("認証情報の環境変数が未設定")
    return cid, sec, tag


def _token():
    if _state["token"]:
        return _state["token"]
    cid, sec, _ = _creds()
    body = json.dumps({"grant_type": "client_credentials", "client_id": cid,
                       "client_secret": sec, "scope": SCOPE})
    req = urllib.request.Request(TOKEN_URL, data=body.encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        _state["token"] = json.loads(r.read().decode())["access_token"]
    return _state["token"]


def _http_post(url, body):
    """(status, payload) を返す。"""
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json",
                 "x-marketplace": MARKETPLACE}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(txt)
        except ValueError:
            return e.code, {"raw": txt[:200]}


def _ckey(kind, body):
    b = {k: v for k, v in body.items() if k not in ("partnerTag", "resources")}
    return hashlib.sha1(json.dumps([kind, b], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def _log(kind, label, status):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.strftime("%F %T"), "kind": kind, "label": label,
                            "status": status}, ensure_ascii=False) + "\n")


def _stop(reason):
    _state["stopped"] = reason
    raise Stop(reason)


def call(kind, url, body, label=""):
    """キャッシュ優先でAPIを呼ぶ。戻り値は (応答dict, キャッシュ命中か)。Stop を投げたらその実行では以後呼ばない。"""
    if _state["stopped"]:
        raise Stop(_state["stopped"])
    cp = CACHE / f"{kind}_{_ckey(kind, body)}.json"
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8")), True
    if calls_today() >= DAILY_CAP:
        _stop(f"1日の上限 {DAILY_CAP} 回に到達")
    wait = GAP - (time.time() - _state["last"])
    if wait > 0:
        time.sleep(wait)
    tag = _creds()[2]       # 未設定ならここで Stop（数えない）
    _count_call()           # 送る前に数える（失敗しても1回分として扱う）
    _state["run_calls"] += 1
    try:
        status, payload = _http_post(url, dict(body, partnerTag=tag, partnerType="Associates",
                                               marketplace=MARKETPLACE))
    except Stop:
        raise
    except Exception as e:  # 通信エラー等。内容に認証情報は含まれない
        _log(kind, label, f"error:{type(e).__name__}")
        _stop(f"通信エラー({type(e).__name__})")
    _state["last"] = time.time()
    _log(kind, label, status)
    if status == 429:
        _stop("HTTP 429")
    if status != 200:
        _stop(f"HTTP {status}")
    CACHE.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload, False


def get_items(asins, resources=None, label=""):
    assert 1 <= len(asins) <= 10
    return call("getItems", GET_ITEMS_URL,
                {"itemIds": list(asins), "resources": resources or ITEM_RESOURCES}, label)


def search_items(*, keywords=None, browse_node_id=None, search_index="Books", sort_by=None,
                 page=1, resources=None, label=""):
    body = {"searchIndex": search_index, "itemPage": page, "itemCount": 10,
            "resources": resources or ITEM_RESOURCES}
    if keywords:
        body["keywords"] = keywords
    if browse_node_id:
        body["browseNodeId"] = browse_node_id
    if sort_by:
        body["sortBy"] = sort_by
    return call("searchItems", SEARCH_URL, body, label)


def slim(i, today_iso=None):
    """応答1件から保存してよい項目だけを抜く（ホワイトリスト）。"""
    ii = i.get("itemInfo", {})
    by = ii.get("byLineInfo", {})
    listing = ((i.get("offersV2") or {}).get("listings") or [{}])[0]
    money = (listing.get("price") or {}).get("money") or {}
    img = (((i.get("images") or {}).get("primary") or {}).get("large") or {})
    eans = ((ii.get("externalIds") or {}).get("eans") or {}).get("displayValues") or []
    adult = (ii.get("productInfo") or {}).get("isAdultProduct")
    adult = adult.get("displayValue") if isinstance(adult, dict) else adult
    out = {
        "asin": i["asin"], "url": i.get("detailPageURL"),
        "title": (ii.get("title") or {}).get("displayValue"),
        "manufacturer": (by.get("manufacturer") or {}).get("displayValue"),
        "brand": (by.get("brand") or {}).get("displayValue"),
        "authors": [c.get("name") for c in by.get("contributors") or []],
        "published": ((ii.get("contentInfo") or {}).get("publicationDate") or {}).get("displayValue", "")[:10],
        "ean": eans[0] if eans else None,
        "price": money.get("amount"),
        # 幅100px未満の画像は「画像なし」のプレースホルダー
        "image": img.get("url") if (img.get("width") or 0) >= 100 else None,
        "binding": ((ii.get("classifications") or {}).get("binding") or {}).get("displayValue"),
        "updated": today_iso or common.today().isoformat(),
    }
    if isinstance(adult, bool):  # 成人向けフラグ（埋め込み可否の判定に使う）。取れなければキー無し
        out["adult"] = adult
    return out

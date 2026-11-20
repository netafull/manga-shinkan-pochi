"""Amazon Creators API クライアント（標準ライブラリのみ）。

方針
- 全呼び出しを data/api_log.jsonl に1行ずつ記録する（認証情報は書かない）。
- 同じものは二度呼ばない: 応答は cache/api/ に保存し、キャッシュがあればAPIを叩かない。
- 呼び出し間隔は1.1秒以上。HTTP 429 は即中断（Stop例外）。
- このタスク全体の上限は250回。ここでは安全側に 245 で強制停止する。
- minSavingPercent は絶対に送らない（kindle-sale-site/scripts/fetch_sales.py の注意書き）。
認証/リクエストの書き方は kindle-sale-site の fetch_sales.py と kaden-sale-site の fetch_deals.py に合わせている。
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
CACHE = ROOT / "cache" / "api"
LOG = ROOT / "data" / "api_log.jsonl"

TOKEN_URL = "https://api.amazon.co.jp/auth/o2/token"
SEARCH_URL = "https://creatorsapi.amazon/catalog/v1/searchItems"
GET_ITEMS_URL = "https://creatorsapi.amazon/catalog/v1/getItems"
NODES_URL = "https://creatorsapi.amazon/catalog/v1/getBrowseNodes"
SCOPE = "creatorsapi::default"
MARKETPLACE = "www.amazon.co.jp"
HARD_CAP = 245
GAP = 1.1

ITEM_RESOURCES = [
    "itemInfo.title",
    "itemInfo.byLineInfo",
    "itemInfo.classifications",
    "itemInfo.contentInfo",
    "itemInfo.externalIds",
    "images.primary.large",
    "offersV2.listings.price",
]


class Stop(Exception):
    pass


def calls_used() -> int:
    if not LOG.exists():
        return 0
    return sum(1 for _ in LOG.open(encoding="utf-8"))


_state = {"token": None, "last": 0.0}


def _creds():
    cid = os.environ.get("CREATORSAPI_CREDENTIAL_ID")
    sec = os.environ.get("CREATORSAPI_CREDENTIAL_SECRET")
    tag = os.environ.get("CREATORSAPI_PARTNER_TAG")
    if not (cid and sec and tag):
        raise SystemExit("環境変数が未設定: source ~/.secrets/env してください")
    return cid, sec, tag


def partner_tag():
    return _creds()[2]


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


def _ckey(kind, body):
    b = {k: v for k, v in body.items() if k not in ("partnerTag", "resources")}
    return hashlib.sha1(json.dumps([kind, b], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def call(kind: str, url: str, body: dict, label: str = ""):
    """キャッシュ優先でAPIを呼ぶ。戻り値は (応答dict, キャッシュ命中か)。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    cp = CACHE / f"{kind}_{_ckey(kind, body)}.json"
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8")), True
    if calls_used() >= HARD_CAP:
        raise Stop(f"API上限 {HARD_CAP} に到達")
    wait = GAP - (time.time() - _state["last"])
    if wait > 0:
        time.sleep(wait)
    full = dict(body, partnerTag=partner_tag(), partnerType="Associates", marketplace=MARKETPLACE)
    req = urllib.request.Request(
        url, data=json.dumps(full).encode(),
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json",
                 "x-marketplace": MARKETPLACE}, method="POST")
    status, payload = None, None
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status = r.status
            payload = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        status = e.code
        txt = e.read().decode("utf-8", "replace")
        try:
            payload = json.loads(txt)
        except ValueError:
            payload = {"raw": txt[:500]}
    _state["last"] = time.time()
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.strftime("%F %T"), "kind": kind, "label": label,
                            "status": status}, ensure_ascii=False) + "\n")
    if status == 429:
        raise Stop("HTTP 429: 即停止")
    if status == 401:
        _state["token"] = None
    if status == 200:
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


def get_browse_nodes(ids, resources=None, label=""):
    return call("getBrowseNodes", NODES_URL,
                {"browseNodeIds": list(ids), "resources": resources or ["browseNodes.children", "browseNodes.ancestor"]}, label)

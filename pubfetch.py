"""出版社ページの礼儀正しい取得。1URLにつき1回・リクエスト間隔を守る・正直なUA。
講談社(kodansha.co.jp)には一切アクセスしない。

- 毎日の更新(update.py)は一覧ページを use_cache=False で取りに行く（各1回）。
- cache/pub/ は手元での再実行用（gitignore）。GitHub Actions では空から始まる。
- 失敗（HTTPエラー・通信エラー）は None を返す。呼び出し側が「前回データを残す」判断をする。
"""
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import common

UA = "MangaShinkanPochi/1.0 (+https://shinkan.netaful.jp/)"
ROOT = common.ROOT
CACHE = ROOT / "cache" / "pub"
LOG = ROOT / "logs" / "publisher_requests.jsonl"
MIN_GAP = 3.0
HOST_GAP = {"www.shogakukan.co.jp": 10.0,   # Crawl-delay に合わせる
            "www.kadokawa.co.jp": 20.0}    # robots.txt の Crawl-delay: 20
_last = {"any": 0.0}
_last_host = {}


def cache_path(url: str) -> Path:
    return CACHE / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".html")


def fetch(url: str, allow_network: bool = True, use_cache: bool = True):
    """use_cache=True ならキャッシュ優先。なければ(許可されていれば)取得して保存。"""
    host = urlparse(url).netloc
    if "kodansha" in host:
        raise RuntimeError("kodansha.co.jp へはアクセスしない")
    p = cache_path(url)
    if use_cache and p.exists():
        return p.read_text(encoding="utf-8")
    if not allow_network:
        return None
    wait = max(MIN_GAP - (time.time() - _last["any"]),
               HOST_GAP.get(host, 0) - (time.time() - _last_host.get(host, 0)))
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    body, status = None, None
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception as e:
        status = f"error:{type(e).__name__}"
    _last["any"] = _last_host[host] = time.time()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.strftime("%F %T"), "url": url, "status": status}, ensure_ascii=False) + "\n")
    if body is None:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return body

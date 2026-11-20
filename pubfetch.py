"""出版社ページの礼儀正しい取得。キャッシュ優先・1URLにつき1回・リクエスト間隔を守る。
講談社(kodansha.co.jp)には一切アクセスしない。"""
import hashlib
import json
import time
import urllib.request
from pathlib import Path

UA = "MangaShinkanPochi/0.1 (prototype; +https://www.netaful.jp/)"
ROOT = Path(__file__).parent
CACHE = ROOT / "cache" / "pub"
LOG = ROOT / "data" / "publisher_requests.jsonl"
MIN_GAP = 3.0
HOST_GAP = {"www.shogakukan.co.jp": 10.0}
_last = {"any": 0.0}
_last_host = {}


def cache_path(url: str) -> Path:
    return CACHE / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".html")


def fetch(url: str, allow_network: bool = True):
    """キャッシュがあればそれを返す。なければ(許可されていれば)取得して保存。"""
    from urllib.parse import urlparse
    host = urlparse(url).netloc
    if "kodansha" in host:
        raise RuntimeError("kodansha.co.jp へはアクセスしない")
    p = cache_path(url)
    if p.exists():
        return p.read_text(encoding="utf-8")
    if not allow_network:
        return None
    wait = max(MIN_GAP - (time.time() - _last["any"]),
               HOST_GAP.get(host, 0) - (time.time() - _last_host.get(host, 0)))
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
        body = None
    _last["any"] = _last_host[host] = time.time()
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.strftime("%F %T"), "url": url, "status": status}, ensure_ascii=False) + "\n")
    if body is None:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return body

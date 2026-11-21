#!/usr/bin/env python3
"""data/ から docs/ 一式を書き出す。標準ライブラリのみ。
実行: python3 build.py            （今日は日本時間。SHINKAN_TODAY=YYYY-MM-DD で上書き可）
      GA4_ID=G-XXXX python3 build.py   （GA4_ID があるときだけ計測タグを出す。付けないと消える）
ページ: / , /date/YYYY-MM-DD/ , /month/YYYY-MM/ , /publisher/<slug>/ , /work/ , /work/<slug>/ , 404.html
他: sitemap.xml , robots.txt , CNAME , .nojekyll
"""
import datetime
import hashlib
import json
import os
import shutil
import unicodedata
from html import escape

import common
import embed_pages
import pochi_verify
import yomi as yomi_mod
from common import today  # noqa: F401  (build.today() として使われる)

ROOT = common.ROOT
DOCS = ROOT / "docs"
DATA = ROOT / "data"
SITE_URL = "https://shinkan.netaful.jp"
CNAME = "shinkan.netaful.jp"
NAME = "マンガ新刊ポチ"
TAGLINE = "コミック新刊の発売日を、まとめてチェック"
DESCRIPTION = ("コミック新刊（マンガの新刊）の発売日を発売日順にまとめたサイトです。"
               "小学館・秋田書店・白泉社・KADOKAWA・双葉社・竹書房・少年画報社・講談社・集英社の紙のコミックスについて、今日・今週・来週の発売をひと目で確認できます。")
MANGA_POCHI = "https://manga.netaful.jp/"
WEEKDAYS = "月火水木金土日"
PUBLISHERS = {  # slug -> (表示名, 公式ページ)
    "shogakukan": ("小学館", "https://www.shogakukan.co.jp/calendar/paper/comics"),
    "akitashoten": ("秋田書店", "https://www.akitashoten.co.jp/books/upcoming"),
    "hakusensha": ("白泉社", "https://www.hakusensha.co.jp/shinkan/"),
    "kadokawa": ("KADOKAWA", "https://www.kadokawa.co.jp/calendar/?largeGenre=13"),
    "futabasha": ("双葉社", "https://www.futabasha.co.jp/new-release-calendar/"),
    "takeshobo": ("竹書房", "https://www.takeshobo.co.jp/search/g106010.html?amount=100&order=book_date_desc"),
    "shonengahosha": ("少年画報社", "https://www.shonengahosha.co.jp/cal.php"),
    "kodansha": ("講談社", None),
    "shueisha": ("集英社", None),
}
AMAZON_SOURCED = ("講談社", "集英社")  # 公式サイトに触れず、Amazonの商品情報だけから作る出版社
PUB_SLUG = {v[0]: k for k, v in PUBLISHERS.items()}

# フッターの関連サイト（ポチシリーズ。netafull-pochi-rotator/pochi.js の一覧から自サイトを除いたもの）
SERIES_SITES = (
    ("電書ポチ", "Kindle本セール", "https://book.netaful.jp/"),
    ("家電ポチ", "ガジェット・家電セール", "https://kaden.netaful.jp/"),
    ("林檎ポチ", "Apple整備済製品", "https://apple.netaful.jp/"),
    ("漫画ポチ", "Webマンガ横断検索", "https://manga.netaful.jp/"),
    ("コンビニポチ", "コンビニ新商品アーカイブ", "https://conbini.netaful.jp/"),
    ("ファストフードポチ", "ファストフード限定メニュー", "https://fastfood.netaful.jp/"),
    ("カフェポチ", "カフェ季節限定メニュー", "https://cafe.netaful.jp/"),
    ("回転寿司ポチ", "回転寿司の期間限定ネタ", "https://sushi.netaful.jp/"),
    ("カップ麺ポチ", "カップ麺の新商品", "https://cupmen.netaful.jp/"),
    ("ホテルポチ", "空室ホテルを安い順に検索", "https://hotel.netaful.jp/"),
    ("温泉宿ポチ", "温泉地の空室を、すぐ探す", "https://onsen.netaful.jp/"),
    ("離島宿ポチ", "島の空室を、すぐ探す", "https://ritou.netaful.jp/"),
    ("道の駅ポチ", "道の駅の駐車場・設備", "https://michinoeki.netaful.jp/"),
    ("新発売ポチ", "食の新商品を発売日で集約", "https://shinhatsubai.netaful.jp/"),
)

_pages = {}  # 書き出したページ: パス -> html（sitemap の lastmod 判定に使う）


def norm_title(s):
    return "".join(unicodedata.normalize("NFKC", s).lower().split())


def work_slug(series_key, publisher):
    return hashlib.sha1(f"{publisher}|{series_key}".encode()).hexdigest()[:10]


def load_all(data=None):
    d = data or DATA
    books = json.loads((d / "books.json").read_text(encoding="utf-8"))
    seen = {b["isbn13"] for b in books if b["isbn13"]}
    for kp in (d / "books_kodansha.json", d / "books_shueisha.json"):
        if kp.exists():
            for b in json.loads(kp.read_text(encoding="utf-8")):
                if b["isbn13"] not in seen:
                    books.append(b)
                    seen.add(b["isbn13"])
    sp = d / "amazon_items.json"
    store = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {"items": {}}
    pochi = {}
    pp = d / "manga_pochi_candidates.json"  # scripts/verify_pochi_links.py が作る（題名→候補。採否は group_works で裏取り）
    if pp.exists():
        pochi = json.loads(pp.read_text(encoding="utf-8"))
    for b in books:
        it = store["items"].get(b.get("isbn10") or "")
        b["amazon"] = it
    books = [b for b in books if b["release_date"]]
    books.sort(key=lambda b: (b["release_date"], b["publisher"], b["series_title"], b["volume"] or 0))
    return books, pochi


def group_works(books, pochi):
    works = {}
    for b in books:
        slug = work_slug(b["series_key"], b["publisher"])
        w = works.setdefault(slug, {"slug": slug, "title": b["series_title"], "publisher": b["publisher"],
                                    "author": b["author"], "books": [], "pochi": None, "series_key": b["series_key"],
                                    "yomi": None})
        w["books"].append(b)
        b["work_slug"] = slug
    fuzzy = None
    for w in works.values():
        cands = pochi.get(norm_title(w["title"]))
        if cands:
            pick = pochi_verify.pick_candidate(w["author"], w["publisher"], cands)[0]
            if pick:
                w["pochi"] = pick["catalogId"]
        if not w["pochi"]:
            # 二段目: 題名の表記ゆれ（記号・括弧書き・版の付記）。著者が一致したものだけ採用する
            if fuzzy is None:
                fuzzy = {}
                for t, cs in pochi.items():
                    fuzzy.setdefault(pochi_verify.fuzzy_key(t), []).extend(cs)
            fk = pochi_verify.fuzzy_key(w["title"])
            fc = fuzzy.get(fk) if len(fk) >= 3 else None
            if fc:
                pick = pochi_verify.pick_confirmed(w["author"], w["publisher"], fc)
                if pick:
                    w["pochi"] = pick["catalogId"]
    return works


def apply_yomi(works, data=None):
    """作品に読み（w["yomi"]）を付ける。手動辞書 config/yomi_manual.json が最優先、次に data/yomi.json（openBD）。"""
    d = data or DATA
    manual = yomi_mod.load_manual()
    state = yomi_mod.load_state(d / "yomi.json")
    for w in works.values():
        k = w["series_key"]
        y = manual.get(k) or (state.get(k) or {}).get("yomi")
        w["yomi"] = yomi_mod.to_katakana(unicodedata.normalize("NFKC", y)) if y else None


# ---------- HTML ----------
def ga4_snippet():
    """GA4 の標準 gtag.js タグ。環境変数 GA4_ID が空なら出さない。"""
    gid = os.environ.get("GA4_ID", "").strip()
    if not gid:
        return ""
    gid = escape(gid, quote=True)
    return ('<script async src="https://www.googletagmanager.com/gtag/js?id=%s"></script>\n'
            '<script>\nwindow.dataLayer = window.dataLayer || [];\n'
            'function gtag(){dataLayer.push(arguments);}\n'
            "gtag('js', new Date());\n"
            "gtag('config', '%s');\n</script>\n" % (gid, gid))


def jsonld(obj):
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return '<script type="application/ld+json">%s</script>\n' % body


def crumbs(items):
    """items=[(名前, パス or None), ...]。見えるパンくずHTMLと BreadcrumbList の dict を返す。
    JSON-LD側は絶対URL、最後（現在ページ）は item なし。"""
    html = " › ".join(f'<a href="{p}">{escape(n)}</a>' if p else escape(n) for n, p in items)
    lst = []
    for i, (n, p) in enumerate(items, 1):
        e = {"@type": "ListItem", "position": i, "name": n}
        if p and i < len(items):
            e["item"] = SITE_URL + p
        lst.append(e)
    return (f'<p class="crumbs">{html}</p>',
            {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": lst})


def canonical_of(path):
    """書き出しパス(例 date/2026-11-20/index.html)から正規URLを作る。"""
    if path.endswith("index.html"):
        path = path[:-len("index.html")]
    return f"{SITE_URL}/{path}"


def head(title, desc, canonical=None, ld=""):
    """canonical=None は 404 用（canonical・OGPなし）。"""
    meta = ""
    if canonical:
        t, d, c = escape(title, quote=True), escape(desc, quote=True), escape(canonical, quote=True)
        meta = f"""<link rel="canonical" href="{c}">
<meta property="og:type" content="website">
<meta property="og:title" content="{t}">
<meta property="og:description" content="{d}">
<meta property="og:url" content="{c}">
<meta property="og:site_name" content="{NAME}">
<meta property="og:locale" content="ja_JP">
<meta property="og:image" content="{SITE_URL}/static/assets/ogp.jpg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
"""
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{ga4_snippet()}<title>{escape(title)}</title>
<meta name="description" content="{escape(desc, quote=True)}">
{meta}<link rel="icon" type="image/png" sizes="96x96" href="/static/assets/favicon.png">
<link rel="icon" type="image/x-icon" href="/static/assets/favicon.ico" sizes="48x48">
<link rel="apple-touch-icon" href="/static/assets/apple-touch-icon.png">
<link rel="stylesheet" href="/static/style.css">
<script src="/static/search.js" defer></script>
{ld}</head>
<body>
<header class="site-header">
<p class="site-title"><a href="/"><img src="/static/assets/logo.png" width="44" height="44" alt="">{NAME}</a></p>
<p class="tagline">{TAGLINE}</p>
<nav class="nav" aria-label="サイト内">
<div class="nav-group"><span class="nav-label">発売日で探す</span><a href="/#today">今日</a><a href="/#week">今週</a><a href="/#nextweek">来週</a><a href="/month/{{MONTH}}/">月別</a></div>
<div class="nav-group"><span class="nav-label">出版社で探す</span>{{PUBNAV}}</div>
<div class="nav-group"><a href="/work/">作品一覧</a></div>
<form class="search" role="search" action="/work/" method="get"><label class="sr" for="q">作品を検索</label><input id="q" name="q" type="search" placeholder="作品名・作者で検索" autocomplete="off"><button type="submit">検索</button><ul id="sr" class="sr-list" hidden></ul></form>
</nav>
</header>
<main>
"""


def series_nav():
    links = "\n".join('<a href="%s">%s<span class="lbl"> %s</span></a>' % (escape(u, quote=True), escape(n), escape(d))
                      for n, d, u in SERIES_SITES)
    return ('<nav class="sites"><span class="lbl">関連サイト</span>\n%s\n</nav>\n' % links
            + '<nav class="sites"><span class="lbl">ポチシリーズ一覧：</span>\n'
            + '<a href="https://pochi.netaful.jp/">ポチフル</a>\n</nav>\n')


def foot(extra=""):
    return f"""{extra}
</main>
<footer class="site-footer">
<p class="affil">Amazonのアソシエイトとして、当サイトは適格販売により収入を得ています。</p>
<p>発売日などは出版社の公式情報とAmazonの商品情報をもとに掲載しています。購入前に公式情報をご確認ください。</p>
<p>当サイトは各出版社・Amazonとは関係のない非公式サイトです。</p>
<p><a href="/">トップ</a> ｜ <a href="https://netaful.jp/policy.html">メディアポリシー</a></p>
{series_nav()}</footer>
</body>
</html>
"""


def fmt_date(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d.month}月{d.day}日（{WEEKDAYS[d.weekday()]}）"


def date_label(iso, ref):
    """見出し用の日付。今年なら「11月20日」、それ以外は「2027年1月8日」。"""
    d = datetime.date.fromisoformat(iso)
    return f"{d.month}月{d.day}日" if d.year == ref.year else f"{d.year}年{d.month}月{d.day}日"


def card(b, show_date=False):
    a = b.get("amazon") or {}
    img = a.get("image")
    cover = (f'<img class="cover" src="{escape(img)}" alt="{escape(b["title"])}の表紙" loading="lazy" width="64">'
             if img else '<div class="cover cover-none" aria-hidden="true">No<br>Image</div>')
    vol = f'<span class="vol">{b["volume"]}巻</span>' if b.get("volume") else ""
    eds = "".join(f'<span class="ed">{escape(e)}</span>' for e in b.get("editions") or [])
    price = f'<span class="price">￥{a["price"]:,.0f}</span>' if a.get("price") else ""
    date = f'<span class="rd">{fmt_date(b["release_date"])}</span>' if show_date else ""
    btn = (f'<a class="btn" href="{escape(a["url"])}" rel="sponsored nofollow noopener" target="_blank">Amazonで見る</a>'
           if a.get("url") else "")
    if b["publisher"] in AMAZON_SOURCED:
        src = "Amazon の商品情報より"
    else:
        src = f'出典: <a href="{escape(b["source_url"])}" rel="noopener" target="_blank">{escape(b["publisher"])}公式</a>'
    label = f' / {escape(b["label"])}' if b.get("label") else ""
    return f"""<li class="card">
{cover}
<div class="card-main">
<h3><a href="/work/{b["work_slug"]}/">{escape(b["series_title"])}</a> {vol}{eds}</h3>
<p class="meta">{escape(b["author"] or "")}　<a href="/publisher/{PUB_SLUG[b["publisher"]]}/">{escape(b["publisher"])}</a>{label}</p>
<p class="meta2">{date}{price}</p>
<p class="src">{src}</p>
{btn}
</div>
</li>"""


def day_section(iso, books, link=True):
    h = fmt_date(iso)
    h = f'<a href="/date/{iso}/">{h}</a>' if link else h
    return (f'<section><h2 id="d{iso}">{h}<small>{len(books)}冊</small></h2><ul class="cards">'
            + "".join(card(b) for b in books) + "</ul></section>")


def by_date(books):
    out = {}
    for b in books:
        out.setdefault(b["release_date"], []).append(b)
    return out


def write(path, html):
    p = DOCS / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")
    _pages[path] = html


# 作品一覧の分類。読みの情報がないので、先頭の文字の種類で分ける。
# 仮名ではじまるものは五十音の行、英数字、漢字、その他。漢字ではじまる作品は読みが分からないため、
# 読みが分からない作品（漢字ではじまるもの）は五十音に入れず題名の文字コード順に並べる（README参照）。
ROWS = [("あ", "あいうえお"), ("か", "かきくけこ"), ("さ", "さしすせそ"), ("た", "たちつてと"), ("な", "なにぬねの"),
        ("は", "はひふへほ"), ("ま", "まみむめも"), ("や", "やゆよ"), ("ら", "らりるれろ"), ("わ", "わをん")]
SMALL = dict(zip("ぁぃぅぇぉっゃゅょゎ", "あいうえおつやゆよわ"))
ALNUM = "英数字"
KANJI = "漢字ではじまる作品"
OTHER = "その他"


def kana_row(title, yomi=None):
    """読み（あれば）、なければ題名の先頭文字から分類を返す。「あ」〜「わ」の行・「英数字」・「漢字ではじまる作品」・「その他」。"""
    if yomi:
        r = kana_row(yomi)
        if r not in (KANJI, OTHER):
            return r
    t = unicodedata.normalize("NFKC", title).strip()
    t = t.lstrip("「『【（([〈<~〜-・!?！？ ")
    if not t:
        return OTHER
    c = t[0]
    if "ァ" <= c <= "ヶ":
        c = chr(ord(c) - 0x60)
    c = SMALL.get(c, c)
    base = unicodedata.normalize("NFD", c)[0]  # 濁点・半濁点を外す
    for label, chars in ROWS:
        if base in chars:
            return label
    if c.isascii() and c.isalnum():
        return ALNUM
    if "一" <= c <= "鿿" or "㐀" <= c <= "䶿" or c in "々〆" or "豈" <= c <= "﫿":
        return KANJI
    return OTHER


def latest_book(w):
    return sorted(w["books"], key=lambda b: (b["release_date"], b["volume"] or 0))[-1]


def latest_of(w):
    b = latest_book(w)
    v = f'{b["volume"]}巻' if b.get("volume") else "最新刊"
    return v, b["release_date"]


def work_title(w):
    """作品ページの見出し・タイトル: 「{作品名} 最新刊{N}巻の発売日」（巻数が分からなければ「新刊の発売日」）。"""
    vol = latest_book(w).get("volume")
    return f'{w["title"]} 最新刊{vol}巻の発売日' if vol else f'{w["title"]} 新刊の発売日'


def build_work_index(works, page):
    groups = {}
    for w in works.values():
        groups.setdefault(kana_row(w["title"], w.get("yomi")), []).append(w)
    order = [l for l, _c in ROWS] + [ALNUM, KANJI, OTHER]
    rows = {r for r, _c in ROWS}

    def label_of(l):
        return f"{l}行" if l in rows else l

    chips = '<ul class="chips">' + "".join(
        f'<li><a href="#row-{i}">{label_of(l)}</a></li>' for i, l in enumerate(order) if l in groups) + "</ul>"
    crumb_html, crumb_ld = crumbs([("トップ", "/"), ("作品一覧", None)])
    body = (crumb_html + f'<h1>マンガ・コミック作品一覧（{len(works)}作品）</h1>'
            '<p class="intro">当サイトが把握している発売予定のある作品です。作品名の読みが分かる作品は五十音順に、'
            '読みが分からない漢字ではじまる作品は別にまとめて題名の文字コード順に並べています。</p>' + chips)
    for i, l in enumerate(order):
        if l not in groups:
            continue
        ws = sorted(groups[l], key=lambda w: (yomi_mod.to_katakana(w.get("yomi") or unicodedata.normalize("NFKC", w["title"])), w["publisher"]))
        body += f'<section><h2 id="row-{i}">{label_of(l)}<small>{len(ws)}作品</small></h2><ul class="works">'
        for w in ws:
            v, d = latest_of(w)
            body += (f'<li><a href="/work/{w["slug"]}/">{escape(w["title"])}</a> '
                     f'<span class="meta">{escape(w["author"] or "")}　{escape(w["publisher"])}　最新: {v}（{d[:4]}年{fmt_date(d)}）</span></li>')
        body += "</ul></section>"
    page(f"マンガ・コミック作品一覧（五十音順）｜{NAME}",
         f"{NAME}が発売予定を把握しているマンガ・コミック{len(works)}作品の一覧です。作品名から最新刊の発売日を確認できます。",
         "work/index.html", body, jsonld(crumb_ld))


def write_search_index(works):
    idx = []
    for w in works.values():
        v, d = latest_of(w)
        idx.append({"t": w["title"], "a": w["author"] or "", "p": w["publisher"], "s": w["slug"], "v": v, "d": d})
    idx.sort(key=lambda x: x["d"])
    (DOCS / "static" / "search.json").write_text(json.dumps(idx, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def pochi_latest(works, t):
    """漫画ポチ（検証済みリンクのある作品）の最新刊・次の巻。docs/api/pochi-latest.json の中身。"""
    iso = t.isoformat()

    def brief(b):
        return {"volume": b.get("volume"), "release_date": b["release_date"], "title": b["title"]}
    out = {}
    for w in works.values():
        if not w["pochi"]:
            continue
        bs = sorted(w["books"], key=lambda b: (b["release_date"], b["volume"] or 0))
        past = [b for b in bs if b["release_date"] <= iso]
        nxt = [b for b in bs if b["release_date"] > iso]
        out[str(w["pochi"])] = {"title": w["title"], "work_url": f'{SITE_URL}/work/{w["slug"]}/',
                                "latest": brief(past[-1]) if past else None,
                                "next": brief(nxt[0]) if nxt else None}
    return {"generated": iso, "site": SITE_URL + "/", "works": out}


def write_pochi_latest(works, t):
    p = DOCS / "api" / "pochi-latest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(pochi_latest(works, t), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


FEED_MAX = 20


def feed_items(books, t):
    """ポチフル用。明日〜今日発売＋3日前までに発売された本を新しい順に最大20件。Amazon の画像・リンクは既存データのみ。"""
    lo = (t - datetime.timedelta(days=3)).isoformat()
    hi = (t + datetime.timedelta(days=1)).isoformat()
    iso = t.isoformat()
    tomorrow = hi
    picked = sorted((b for b in books if lo <= b["release_date"] <= hi),
                    key=lambda b: (b["release_date"], b["publisher"], b["series_title"], b["volume"] or 0),
                    reverse=True)
    items = []
    for b in picked[:FEED_MAX]:
        d = b["release_date"]
        if d == iso:
            note = "今日発売"
        elif d == tomorrow:
            note = "明日発売"
        else:
            dd = datetime.date.fromisoformat(d)
            note = f"{dd.month}月{dd.day}日発売"
        title = f'{b["series_title"]} {b["volume"]}巻' if b.get("volume") else b["title"]
        a = b.get("amazon") or {}
        it = {"id": "shinkan:" + (b.get("isbn13") or b["id"]), "title": title,
              "url": f'{SITE_URL}/work/{b["work_slug"]}/', "date": d, "note": note}
        if a.get("image") and a.get("url"):
            it["image"] = a["image"]
            it["image_link"] = a["url"]
        it.update({"source": "shinkan", "source_name": NAME, "icon": None})
        items.append(it)
    return items


def write_feed(books, t):
    now = datetime.datetime.now(common.JST).replace(microsecond=0).isoformat()
    feed = {"version": 1, "site": "shinkan", "site_name": NAME, "site_url": SITE_URL + "/",
            "generated": now, "items": feed_items(books, t)}
    (DOCS / "feed.json").write_text(json.dumps(feed, ensure_ascii=False, indent=1), encoding="utf-8")


def write_sitemap_and_robots(lastmod_path, t):
    """sitemap.xml の lastmod は「そのページのHTMLが前回から変わった日」。ハッシュを data/page_lastmod.json に持つ。"""
    try:
        prev = json.loads(lastmod_path.read_text(encoding="utf-8")) if lastmod_path else {}
    except (OSError, ValueError):
        prev = {}
    cur = {}
    for path, html in _pages.items():
        if path == "404.html":
            continue
        h = hashlib.sha1(html.encode("utf-8")).hexdigest()[:12]
        old = prev.get(path)
        cur[path] = [h, old[1] if old and old[0] == h else t.isoformat()]
    if lastmod_path:
        lastmod_path.write_text("{\n" + ",\n".join(f"{json.dumps(k)}:{json.dumps(v)}" for k, v in sorted(cur.items())) + "\n}\n",
                                encoding="utf-8")
    urls = "".join(f"<url><loc>{escape(canonical_of(p))}</loc><lastmod>{v[1]}</lastmod></url>\n" for p, v in sorted(cur.items()))
    (DOCS / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + urls + "</urlset>\n", encoding="utf-8")
    (DOCS / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8")
    return len(cur)


def build(today=None, data=None, docs=None, write_lastmod=True):
    global DOCS
    t = today or common.today()
    data = data or DATA
    if docs is not None:
        DOCS = docs
    _pages.clear()
    books, pochi = load_all(data)
    works = group_works(books, pochi)
    apply_yomi(works, data)
    if DOCS.exists():
        shutil.rmtree(DOCS)
    (DOCS / "static").mkdir(parents=True)
    shutil.copy(ROOT / "static" / "style.css", DOCS / "static" / "style.css")
    shutil.copy(ROOT / "static" / "search.js", DOCS / "static" / "search.js")
    shutil.copytree(ROOT / "static" / "assets", DOCS / "static" / "assets")
    (DOCS / "CNAME").write_text(CNAME + "\n", encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")

    months = sorted({b["release_date"][:7] for b in books})
    cur_month = t.isoformat()[:7]
    month_nav = cur_month if cur_month in months else months[0]
    pubnav = "".join(f'<a href="/publisher/{s}/">{n}</a>' for s, (n, _u) in PUBLISHERS.items())

    def fill(h):
        return h.replace("{MONTH}", month_nav).replace("{PUBNAV}", pubnav)

    def page(title, desc, path, body, ld=""):
        write(path, fill(head(title, desc, canonical_of(path), ld)) + body + foot())

    dd = by_date(books)
    iso = t.isoformat()
    week_end = t + datetime.timedelta(days=(6 - t.weekday()))        # 今週の日曜
    next_end = week_end + datetime.timedelta(days=7)

    def span(a, b):
        return [(d, dd[d]) for d in sorted(dd) if a.isoformat() <= d <= b.isoformat()]
    today_books = dd.get(iso, [])
    this_week = span(t + datetime.timedelta(days=1), week_end)
    next_week = span(week_end + datetime.timedelta(days=1), next_end)

    body = (f'<div class="hero"><h1>マンガ・コミック新刊の発売日一覧</h1><p class="intro">{fmt_date(iso)} 時点。'
            '小学館・秋田書店・白泉社・KADOKAWA・双葉社・竹書房・少年画報社・講談社・集英社の紙のコミックスを掲載しています。</p></div>')
    body += '<h2 class="band" id="today">今日発売</h2>'
    body += (day_section(iso, today_books, True) if today_books else '<p class="empty">今日発売の新刊は登録がありません。</p>')
    body += '<h2 class="band" id="week">今週</h2>' + ("".join(day_section(d, bs) for d, bs in this_week) or '<p class="empty">今週の残りは登録がありません。</p>')
    body += '<h2 class="band" id="nextweek">来週</h2>' + ("".join(day_section(d, bs) for d, bs in next_week) or '<p class="empty">来週は登録がありません。</p>')
    body += '<h2 class="band" id="months">月別</h2><ul class="chips">' + "".join(
        f'<li><a href="/month/{m}/">{m[:4]}年{int(m[5:])}月</a></li>' for m in months) + "</ul>"
    page(f"{NAME}｜コミック新刊の発売日一覧（今日・今週・来週）", DESCRIPTION, "index.html", body,
         jsonld({"@context": "https://schema.org", "@type": "WebSite", "name": NAME, "url": SITE_URL + "/",
                 "inLanguage": "ja", "description": DESCRIPTION}))

    for d, bs in dd.items():
        lab = date_label(d, t)
        wd = WEEKDAYS[datetime.date.fromisoformat(d).weekday()]
        crumb_html, crumb_ld = crumbs([("トップ", "/"), (f"{d[:4]}年{int(d[5:7])}月", f"/month/{d[:7]}/"), (fmt_date(d), None)])
        page(f"{lab}発売のマンガ・コミック新刊｜{NAME}",
             f"{lab}（{wd}）発売のマンガ・コミック新刊{len(bs)}冊の一覧です。作品名・巻数・出版社を確認できます。",
             f"date/{d}/index.html",
             crumb_html + f"<h1>{lab}発売のマンガ・コミック新刊</h1><ul class=\"cards\">" + "".join(card(b) for b in bs) + "</ul>",
             jsonld(crumb_ld))

    for m in months:
        mb = [b for b in books if b["release_date"].startswith(m)]
        md = by_date(mb)
        cur = ' aria-current="page"'
        nav = '<ul class="chips">' + "".join(
            '<li><a href="/month/%s/"%s>%s年%d月</a></li>' % (x, cur if x == m else "", x[:4], int(x[5:])) for x in months) + "</ul>"
        ml = f"{m[:4]}年{int(m[5:])}月"
        crumb_html, crumb_ld = crumbs([("トップ", "/"), (ml, None)])
        body = (crumb_html + f'<h1>{ml}発売のコミック新刊（マンガ）一覧</h1>'
                f'<p class="intro">{len(mb)}冊</p>{nav}')
        body += "".join(day_section(d, bs) for d, bs in sorted(md.items()))
        page(f"{ml}発売のコミック新刊（マンガ）一覧｜{NAME}",
             f"{ml}に発売されるコミック新刊（マンガ）{len(mb)}冊を発売日順にまとめた一覧です。", f"month/{m}/index.html", body, jsonld(crumb_ld))

    for slug, (name, url) in PUBLISHERS.items():
        pb = [b for b in books if b["publisher"] == name]
        pd = by_date(pb)
        if url:
            src = f'公式の発売予定: <a href="{url}" rel="noopener" target="_blank">{escape(name)}</a>'
        else:
            src = f"{escape(name)}の作品はAmazonの商品情報（Amazon の商品情報より）から拾っています。網羅はしていません。"
        upcoming = [(d, bs) for d, bs in sorted(pd.items()) if d >= iso]
        crumb_html, crumb_ld = crumbs([("トップ", "/"), (name, None)])
        body = (crumb_html + f'<h1>{escape(name)}のコミック新刊 発売日一覧</h1>'
                f'<p class="intro">{src}</p>')
        body += "".join(day_section(d, bs) for d, bs in upcoming) or '<p class="empty">登録がありません。</p>'
        page(f"{name}のコミック新刊 発売日一覧｜{NAME}",
             f"{name}のコミック新刊（紙のコミックス）を発売日順にまとめた一覧です。", f"publisher/{slug}/index.html", body, jsonld(crumb_ld))

    for w in works.values():
        bs = sorted(w["books"], key=lambda b: (b["release_date"], b["volume"] or 0))
        past = [b for b in bs if b["release_date"] <= iso]
        nxt = [b for b in bs if b["release_date"] > iso]
        parts = []
        if past:
            n = past[-1]
            parts.append(f'最新刊: {n["volume"] and str(n["volume"]) + "巻" or escape(n["title"])}（{fmt_date(n["release_date"])}）')
        if nxt:
            n = nxt[0]
            parts.append(f'次の発売: {n["volume"] and str(n["volume"]) + "巻" or escape(n["title"])}（{n["release_date"][:4]}年{fmt_date(n["release_date"])}）')
        pochi_link = ""
        if w["pochi"]:
            pochi_link = f'<p class="pochi"><a class="btn" href="{MANGA_POCHI}manga/{w["pochi"]}" rel="noopener" target="_blank">漫画ポチでフォローする</a></p>'
        wt = work_title(w)
        pub_path = f'/publisher/{PUB_SLUG[w["publisher"]]}/'
        crumb_html, _ = crumbs([("トップ", "/"), ("作品一覧", "/work/"), (w["publisher"], pub_path)])
        _, crumb_ld = crumbs([("トップ", "/"), ("作品一覧", "/work/"), (w["publisher"], pub_path), (wt, None)])
        body = (crumb_html +
                f'<h1>{escape(wt)}</h1><p class="meta">{escape(w["author"] or "")}　{escape(w["publisher"])}</p>'
                f'<p class="intro">{"　".join(parts)}</p>{pochi_link}'
                '<p class="note">掲載は当サイトが把握している発売予定の範囲です（それ以前の巻は含みません）。</p>'
                '<ul class="cards">' + "".join(card(b, True) for b in bs) + "</ul>")
        lb = latest_book(w)
        desc = (f'{w["title"]}の最新刊{lb["volume"]}巻は{date_label(lb["release_date"], t)}発売。' if lb.get("volume")
                else f'{w["title"]}の新刊は{date_label(lb["release_date"], t)}発売。') + "既刊・新刊の発売日を一覧で確認できます。"
        items = []
        for i, b in enumerate(bs, 1):
            book = {"@type": "Book", "name": b["title"], "datePublished": b["release_date"]}
            if b.get("isbn13"):
                book["isbn"] = b["isbn13"]
            items.append({"@type": "ListItem", "position": i, "item": book})
        page(f"{wt}｜{NAME}", desc, f"work/{w['slug']}/index.html", body,
             jsonld({"@context": "https://schema.org", "@type": "ItemList", "name": wt, "itemListElement": items})
             + jsonld(crumb_ld))

    build_work_index(works, page)
    write_search_index(works)
    write_pochi_latest(works, t)
    write_feed(books, t)
    embed_stats = embed_pages.write_all(DOCS, books, t)  # sitemap には入れない（_pages を通さない）
    write("404.html", fill(head("ページが見つかりません｜" + NAME, "お探しのページは見つかりませんでした。"))
          + '<h1>ページが見つかりません</h1><p><a href="/">トップへ</a></p>' + foot())
    n_sitemap = write_sitemap_and_robots(data / "page_lastmod.json" if write_lastmod else None, t)
    n_works = sum(1 for w in works.values() if w["pochi"])
    print(f"books={len(books)} works={len(works)} dates={len(dd)} months={len(months)} "
          f"pochi_matched={n_works} sitemap_urls={n_sitemap} embed={embed_stats}")
    return books, works


if __name__ == "__main__":
    build()

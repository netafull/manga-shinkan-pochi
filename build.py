#!/usr/bin/env python3
"""data/ から docs/ 一式を書き出す。標準ライブラリのみ。
実行: python3 build.py            （今日の日付は date.today()。SHINKAN_TODAY=YYYY-MM-DD で上書き可）
ページ: / , /date/YYYY-MM-DD/ , /month/YYYY-MM/ , /publisher/<slug>/ , /work/<slug>/
"""
import datetime
import hashlib
import json
import os
import shutil
import unicodedata
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
NAME = "マンガ新刊ポチ"
TAGLINE = "マンガの新刊が出る日を、発売日順に。"
MANGA_POCHI = "https://manga.netaful.jp/"
WEEKDAYS = "月火水木金土日"
PUBLISHERS = {  # slug -> (表示名, 公式ページ)
    "shogakukan": ("小学館", "https://www.shogakukan.co.jp/calendar/paper/comics"),
    "akitashoten": ("秋田書店", "https://www.akitashoten.co.jp/books/upcoming"),
    "hakusensha": ("白泉社", "https://www.hakusensha.co.jp/shinkan/"),
    "kodansha": ("講談社", None),
}
PUB_SLUG = {v[0]: k for k, v in PUBLISHERS.items()}


def today():
    v = os.environ.get("SHINKAN_TODAY")
    return datetime.date.fromisoformat(v) if v else datetime.date.today()


def norm_title(s):
    return "".join(unicodedata.normalize("NFKC", s).lower().split())


def work_slug(series_key, publisher):
    return hashlib.sha1(f"{publisher}|{series_key}".encode()).hexdigest()[:10]


def load_all():
    d = ROOT / "data"
    books = json.loads((d / "books.json").read_text(encoding="utf-8"))
    kp = d / "books_kodansha.json"
    seen = {b["isbn13"] for b in books if b["isbn13"]}
    if kp.exists():
        for b in json.loads(kp.read_text(encoding="utf-8")):
            if b["isbn13"] not in seen:
                books.append(b)
    sp = d / "amazon_items.json"
    store = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {"items": {}}
    pochi = {}
    pp = d / "manga_pochi_titles.json"
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
                                    "author": b["author"], "books": [], "pochi": None})
        w["books"].append(b)
        b["work_slug"] = slug
    for w in works.values():
        hit = pochi.get(norm_title(w["title"]))
        if hit:
            w["pochi"] = hit
    return works


# ---------- HTML ----------
def head(title, desc, path, root_prefix="/"):
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{escape(title)}</title>
<meta name="description" content="{escape(desc)}">
<link rel="icon" type="image/svg+xml" href="/static/logo.svg">
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header class="site-header">
<p class="site-title"><a href="/"><img src="/static/logo.svg" width="44" height="44" alt="">{NAME}</a></p>
<p class="tagline">{TAGLINE}</p>
<nav class="nav" aria-label="サイト内"><a href="/">今日・今週</a><a href="/month/{{MONTH}}/">月別</a>{{PUBNAV}}</nav>
</header>
<main>
"""


def foot(extra=""):
    return f"""{extra}
</main>
<footer class="site-footer">
<p class="affil">このサイトにはAmazonアソシエイトのリンク（広告）が含まれます。商品画像・価格・リンクはAmazonの商品情報によるもので、価格は変動します。</p>
<p>発売日などの書誌情報は各出版社の公式発売予定ページによります。誤りや変更があり得るため、購入前に公式情報をご確認ください。</p>
<p>講談社の作品は「Amazon の商品情報より」掲載しています。</p>
<p class="proto">※ 試作版です（サイト名は仮）。</p>
</footer>
</body>
</html>
"""


def fmt_date(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d.month}月{d.day}日（{WEEKDAYS[d.weekday()]}）"


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
    if b["publisher"] == "講談社":
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


def build():
    t = today()
    books, pochi = load_all()
    works = group_works(books, pochi)
    if DOCS.exists():
        shutil.rmtree(DOCS)
    (DOCS / "static").mkdir(parents=True)
    shutil.copy(ROOT / "static" / "style.css", DOCS / "static" / "style.css")
    shutil.copy(ROOT / "static" / "logo.svg", DOCS / "static" / "logo.svg")

    months = sorted({b["release_date"][:7] for b in books})
    cur_month = t.isoformat()[:7]
    pubnav = "".join(f'<a href="/publisher/{s}/">{n}</a>' for s, (n, _u) in PUBLISHERS.items())

    def page(title, desc, path, body):
        h = head(title, desc, path).replace("{MONTH}", cur_month if cur_month in months else months[0]).replace("{PUBNAV}", pubnav)
        write(path, h + body + foot())

    dd = by_date(books)
    iso = t.isoformat()
    week_end = t + datetime.timedelta(days=(6 - t.weekday()))        # 今週の日曜
    next_end = week_end + datetime.timedelta(days=7)
    def span(a, b):
        return [(d, dd[d]) for d in sorted(dd) if a.isoformat() <= d <= b.isoformat()]
    today_books = dd.get(iso, [])
    this_week = span(t + datetime.timedelta(days=1), week_end)
    next_week = span(week_end + datetime.timedelta(days=1), next_end)

    body = f'<div class="hero"><h1>{NAME}</h1><p class="intro">マンガ新刊の発売日一覧（{fmt_date(iso)} 時点）。小学館・秋田書店・白泉社・講談社の紙のコミックスを掲載しています。</p></div>'
    body += '<h2 class="band">今日発売</h2>'
    body += (day_section(iso, today_books, True) if today_books else '<p class="empty">今日発売の新刊は登録がありません。</p>')
    body += '<h2 class="band">今週</h2>' + ("".join(day_section(d, bs) for d, bs in this_week) or '<p class="empty">今週の残りは登録がありません。</p>')
    body += '<h2 class="band">来週</h2>' + ("".join(day_section(d, bs) for d, bs in next_week) or '<p class="empty">来週は登録がありません。</p>')
    body += '<h2 class="band">月別</h2><ul class="chips">' + "".join(
        f'<li><a href="/month/{m}/">{m[:4]}年{int(m[5:])}月</a></li>' for m in months) + "</ul>"
    page(f"{NAME}｜マンガ新刊の発売日一覧", f"マンガの新刊を発売日順に一覧。{fmt_date(iso)}時点。", "index.html", body)

    for d, bs in dd.items():
        crumbs = f'<p class="crumbs"><a href="/">トップ</a> › {fmt_date(d)}</p>'
        page(f"{d} 発売のマンガ新刊｜{NAME}", f"{fmt_date(d)}発売のマンガ新刊{len(bs)}冊。", f"date/{d}/index.html",
             crumbs + f"<h1>{d[:4]}年{fmt_date(d)} 発売</h1><ul class=\"cards\">" + "".join(card(b) for b in bs) + "</ul>")

    for m in months:
        mb = [b for b in books if b["release_date"].startswith(m)]
        md = by_date(mb)
        cur = ' aria-current="page"'
        nav = '<ul class="chips">' + "".join(
            '<li><a href="/month/%s/"%s>%s年%d月</a></li>' % (x, cur if x == m else "", x[:4], int(x[5:])) for x in months) + "</ul>"
        body = f'<p class="crumbs"><a href="/">トップ</a> › {m}</p><h1>{m[:4]}年{int(m[5:])}月のマンガ新刊（{len(mb)}冊）</h1>{nav}'
        body += "".join(day_section(d, bs) for d, bs in sorted(md.items()))
        page(f"{m[:4]}年{int(m[5:])}月のマンガ新刊一覧｜{NAME}", f"{m[:4]}年{int(m[5:])}月発売のマンガ新刊{len(mb)}冊。", f"month/{m}/index.html", body)

    for slug, (name, url) in PUBLISHERS.items():
        pb = [b for b in books if b["publisher"] == name]
        pd = by_date(pb)
        if url:
            src = f'公式の発売予定: <a href="{url}" rel="noopener" target="_blank">{escape(name)}</a>'
        else:
            src = "講談社の作品はAmazonの商品情報（Amazon の商品情報より）から拾っています。網羅はしていません。"
        body = f'<p class="crumbs"><a href="/">トップ</a> › {escape(name)}</p><h1>{escape(name)}の新刊（{len(pb)}冊）</h1><p class="intro">{src}</p>'
        upcoming = [(d, bs) for d, bs in sorted(pd.items()) if d >= iso]
        body += "".join(day_section(d, bs) for d, bs in upcoming) or '<p class="empty">登録がありません。</p>'
        page(f"{name}のマンガ新刊一覧｜{NAME}", f"{name}の紙のコミックス新刊を発売日順に。", f"publisher/{slug}/index.html", body)

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
            pochi_link = f'<p class="pochi"><a class="btn" href="{MANGA_POCHI}manga/{w["pochi"]}" rel="noopener" target="_blank">漫画ポチで読む・フォローする</a></p>'
        body = (f'<p class="crumbs"><a href="/">トップ</a> › <a href="/publisher/{PUB_SLUG[w["publisher"]]}/">{escape(w["publisher"])}</a></p>'
                f'<h1>{escape(w["title"])}</h1><p class="meta">{escape(w["author"] or "")}　{escape(w["publisher"])}</p>'
                f'<p class="intro">{"　".join(parts)}</p>{pochi_link}'
                '<p class="note">掲載は当サイトが把握している発売予定の範囲です（それ以前の巻は含みません）。</p>'
                '<ul class="cards">' + "".join(card(b, True) for b in bs) + "</ul>")
        page(f"{w['title']} の新刊・発売日｜{NAME}", f"{w['title']}の既刊・新刊の発売日一覧。", f"work/{w['slug']}/index.html", body)

    write("404.html", head("ページが見つかりません", "", "404.html").replace("{MONTH}", cur_month).replace("{PUBNAV}", pubnav)
          + '<h1>ページが見つかりません</h1><p><a href="/">トップへ</a></p>' + foot())
    print(f"books={len(books)} works={len(works)} dates={len(dd)} months={len(months)} pochi_matched={sum(1 for w in works.values() if w['pochi'])}")
    return books, works


if __name__ == "__main__":
    build()

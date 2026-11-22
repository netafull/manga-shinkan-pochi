"""ブログ記事に iframe で埋め込む「○月○日発売のマンガ一覧」を docs/embed/ に書き出す。
sitemap には入れない（noindex）。判定は embed_safety.judge。生成物なので build.py から呼ぶ。
"""
import datetime
import json
from html import escape

import embed_safety

SITE_URL = "https://shinkan.netaful.jp"
NOIMAGE_URL = SITE_URL + "/static/noimage.png"  # 書影なしの仮画像（自作。出版社の表紙は使わない）
AFFIL = "Amazonのアソシエイトとして、当サイトは適格販売により収入を得ています。"
PAGE_BACK, PAGE_FWD = 7, 60      # 埋め込みページの対象（今日の7日前〜60日先）
REVIEW_BACK, REVIEW_FWD = 7, 21  # 目視確認ページの対象

CSS = """*{box-sizing:border-box}body{margin:0;padding:8px;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Yu Gothic",Meiryo,sans-serif;color:#222;background:#fff}
h1{font-size:16px;margin:0 0 8px}ul{list-style:none;margin:0;padding:0}
.card{display:flex;gap:10px;padding:8px 0;border-top:1px solid #e5e5e5}
.cover{flex:0 0 56px;width:56px;height:auto;align-self:flex-start;border:1px solid #ddd}
.card-main{min-width:0;flex:1}.t{margin:0;font-weight:bold;overflow-wrap:anywhere}.t a{color:#0b57d0;text-decoration:none}
.m{margin:2px 0 0;font-size:12px;color:#666;overflow-wrap:anywhere}
.foot{margin:10px 0 0;padding-top:8px;border-top:1px solid #e5e5e5;font-size:11px;color:#666}.foot p{margin:2px 0}
textarea{font-size:12px}"""

def _head(title, extra=""):
    return ('<!DOCTYPE html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<meta name="robots" content="noindex">\n'
            f"<title>{escape(title)}</title>\n<style>{CSS}{extra}</style>\n</head>\n<body>\n")


def book_title(b):
    return f'{b["series_title"]} {b["volume"]}巻' if b.get("volume") else b["title"]


def judged(books, rules, overrides):
    """[(book, show, show_cover, reason)]"""
    out = []
    for b in books:
        s, c, r = embed_safety.judge(b, b.get("amazon"), rules, overrides)
        out.append((b, s, c, r))
    return out


COPY_JS = """<script>(function(){var b=document.getElementById("copy"),t=document.getElementById("src"),m=document.getElementById("msg");
function ok(){m.textContent=" コピーしました"}
function fb(){t.select();try{document.execCommand("copy");ok()}catch(e){m.textContent=" コピー失敗。手で選んでコピーしてください"}}
b.onclick=function(){if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t.value).then(ok,fb)}else fb()};})();</script>"""

# ---- 貼り付け用HTML（WordPress本文向け。style属性のみ・class/script無し） ----
S_WRAP = "max-width:640px;margin:1em 0;padding:12px;border:1px solid #ddd;border-radius:6px;font-size:14px;line-height:1.5"
S_H = "margin:0 0 8px;font-size:16px;font-weight:bold"
S_CARD = "display:flex;gap:10px;padding:8px 0;border-top:1px solid #e5e5e5"
S_IMG = "width:56px;height:auto;flex:0 0 56px;align-self:flex-start;border:1px solid #ddd"
S_MAIN = "min-width:0;flex:1"
S_T = "margin:0;font-weight:bold"
S_M = "margin:2px 0 0;font-size:12px;color:#666"
S_FOOT = "margin:8px 0 0;padding-top:8px;border-top:1px solid #e5e5e5;font-size:12px;color:#666"


def _card(b, cover):
    a = b.get("amazon") or {}
    url, img = a.get("url"), a.get("image")
    title = escape(book_title(b))
    link = (f'<a href="{escape(url, quote=True)}" target="_blank" rel="nofollow sponsored noopener">{title}</a>'
            if url else title)
    img_html = ""
    if cover and img:
        alt = escape(book_title(b) + "の表紙", quote=True)
        img_html = (f'<img src="{escape(img, quote=True)}" width="56" height="80" alt="{alt}" loading="lazy" '
                    f'style="{S_IMG}">')
    else:
        img_html = (f'<img src="{NOIMAGE_URL}" width="56" height="80" alt="書影なし" loading="lazy" '
                    f'style="{S_IMG}">')
    label = embed_safety.label_of(b, a)
    meta = escape(b["publisher"]) + (f' / {escape(label)}' if label else "")
    return (f'<div style="{S_CARD}">{img_html}<div style="{S_MAIN}"><p style="{S_T}">{link}</p>'
            f'<p style="{S_M}">{meta}</p></div></div>')


def _fmt(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d.month}月{d.day}日（{'月火水木金土日'[d.weekday()]}）"


def heading(iso, pub_name=None):
    return f"{_fmt(iso)}発売のマンガ" + (f"（{pub_name}）" if pub_name else "")


def snippet_html(iso, shown, pub_name=None):
    """記事本文にそのまま貼る HTML。shown = [(book, show_cover)]。
    改行を入れない1行にする（WordPress の wpautop が改行を <br>/<p> に変えて崩さないように）。"""
    out = f'<div style="{S_WRAP}"><p style="{S_H}">{escape(heading(iso, pub_name))}</p>'
    out += "".join(_card(b, c) for b, c in shown)
    out += (f'<p style="{S_FOOT}"><a href="{SITE_URL}/date/{iso}/" target="_blank" rel="noopener">マンガ新刊ポチで全部見る</a><br>'
            f"{AFFIL}</p></div>")
    return out


def page_html(iso, shown, pub_name=None, today=None):
    """コピー元ページ（noindex）。プレビュー＋貼り付け用HTMLの textarea＋コピーボタン。"""
    h = heading(iso, pub_name)
    snip = snippet_html(iso, shown, pub_name)
    when = f"{today.month}月{today.day}日" if today else "生成"
    body = (f'<p><a href="{SITE_URL}/embed/">一覧へ戻る</a></p>\n<h1>{escape(h)}：コピー元</h1>\n'
            f"<p>{when}時点の内容です。貼った後は自動では更新されません。</p>\n"
            "<h2>プレビュー</h2>\n" + snip + "\n"
            '<h2>貼り付け用HTML</h2>\n<p>記事本文の「HTML（カスタムHTML）」に貼ってください。</p>\n'
            '<p><button id="copy" type="button">HTMLをコピー</button><span id="msg"></span></p>\n'
            f'<textarea id="src" readonly rows="12" style="width:100%">{escape(snip)}</textarea>\n')
    return _head(h + "（コピー元）") + body + COPY_JS + "\n</body>\n</html>\n"


def index_html(by_day, pubs):
    """by_day={iso: [(book, cover)]}, pubs=[(slug, name)]。日付・出版社を選んでコピー元へ行く一覧。"""
    body = ("<h1>マンガ新刊ポチ 発売日一覧のコピー元</h1>\n"
            "<p>日付（出版社）を選ぶと、記事に貼れるHTMLのコピー元ページに進みます。成人向け・BL・TL系などは自動で外しています。</p>\n"
            "<p><a href=\"/embed/review/\">目視確認ページ（外す本・戻す本を選ぶ）</a></p>\n<ul>\n")
    for iso in sorted(by_day):
        names = {b["publisher"] for b, _c in by_day[iso]}
        links = "".join(f' <a href="/embed/{iso}/{s}/">{escape(n)}</a>' for s, n in pubs if n in names)
        body += (f'<li><a href="/embed/{iso}/">{escape(_fmt(iso))}（全出版社・{len(by_day[iso])}冊）</a>'
                 f'<br><small>{links}</small></li>\n')
    return _head("埋め込み用HTMLのコピー元") + body + "</ul>\n</body>\n</html>\n"


def json_payload(iso, shown):
    pubs = {}
    for b, c in shown:
        a = b.get("amazon") or {}
        pubs.setdefault(b["publisher"], []).append({
            "id": b["id"], "title": book_title(b), "volume": b.get("volume"),
            "label": embed_safety.label_of(b, a), "url": a.get("url"),
            "image": a.get("image") if c else None})
    return {"date": iso, "publishers": pubs}


ISSUE_URL = "https://github.com/netafull/manga-shinkan-pochi/issues/new"
ISSUE_PREFIX = "[embed-overrides]"
ISSUE_URL_MAX = 6000  # これを超えるURLはGitHubが受け付けないことがあるので、分割を促す

REVIEW_JS = """<script>(function(){var T=__TODAY__,REPO=__REPO__,PRE=__PRE__,MAX=__MAX__;
var msg=document.getElementById("msg");
function pick(){return Array.prototype.slice.call(document.querySelectorAll(".row")).filter(function(r){return r.querySelector(".ck").checked})}
function copy(text){function ok(){msg.textContent=" コピーしました";}
function fb(){var t=document.createElement("textarea");t.value=text;document.body.appendChild(t);t.select();try{document.execCommand("copy");ok()}catch(e){msg.textContent=" コピー失敗"}document.body.removeChild(t)}
if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(ok,fb)}else fb();}
function ops(kind){var o={exclude:[],exclude_series:[],include:[],remove_exclude:[],remove_exclude_series:[]},seen={};
pick().forEach(function(r){var d=r.dataset,ex=d.ex;
if(kind=="ex"){if(!ex)o.exclude.push({id:d.id,title:d.title})}
else if(kind=="series"){if(d.sk&&ex!="series"&&!seen[d.sk]){seen[d.sk]=1;o.exclude_series.push({series_key:d.sk,title:d.st})}}
else if(kind=="back"){if(ex=="auto")o.include.push({id:d.id,title:d.title});else if(ex=="manual")o.remove_exclude.push({id:d.id});
else if(ex=="series"&&d.sk&&!seen[d.sk]){seen[d.sk]=1;o.remove_exclude_series.push({series_key:d.sk})}}});return o}
function count(o){return o.exclude.length+o.exclude_series.length+o.include.length+o.remove_exclude.length+o.remove_exclude_series.length}
function issue(kind){var o=ops(kind),n=count(o);
if(!n){msg.textContent=" 対象の本が選ばれていません（チェックを入れてください）";return}
var name={ex:"除外",series:"作品ごとに除外",back:"戻す"}[kind];
var lines=[];o.exclude.forEach(function(x){lines.push("- 除外: "+x.title+" ("+x.id+")")});
o.exclude_series.forEach(function(x){lines.push("- 作品ごとに除外: "+x.title+" ("+x.series_key+")")});
o.include.forEach(function(x){lines.push("- 自動除外を戻す: "+x.title+" ("+x.id+")")});
o.remove_exclude.forEach(function(x){lines.push("- 手動除外を取り消す: "+x.id)});
o.remove_exclude_series.forEach(function(x){lines.push("- 作品ごとの手動除外を取り消す: "+x.series_key)});
var body=lines.join("\\n")+"\\n\\n```json\\n"+JSON.stringify(o)+"\\n```\\n";
var url=REPO+"?title="+encodeURIComponent(PRE+" "+name+" "+n+"件")+"&body="+encodeURIComponent(body);
if(url.length>MAX){msg.textContent=" 件数が多くてURLが長すぎます（"+url.length+"字）。数件ずつに分けてください";return}
msg.textContent=" GitHubのIssue画面を開きます。「Create」を押すと自動で反映されます";window.open(url,"_blank","noopener")}
document.getElementById("ie").onclick=function(){issue("ex")};
document.getElementById("is").onclick=function(){issue("series")};
document.getElementById("ib").onclick=function(){issue("back")};
document.getElementById("cb").onclick=function(){copy(pick().map(function(r){return JSON.stringify({id:r.dataset.id,title:r.dataset.title,added:T})}).join(",\\n"))};
document.getElementById("cs").onclick=function(){var seen={};copy(pick().filter(function(r){var k=r.dataset.sk;if(!k||seen[k])return false;seen[k]=1;return true}).map(function(r){return JSON.stringify({series_key:r.dataset.sk,title:r.dataset.st})}).join(",\\n"))};
})();</script>
"""


def review_html(rows, today, overrides):
    """rows = [(book, show, show_cover, reason)] 日付順。"""
    manual_ex = {r["id"] for r in overrides["exclude"] if r.get("id")}
    css = (".row{display:flex;gap:10px;padding:8px 0;border-top:1px solid #ddd;align-items:flex-start}"
           ".row img{width:56px;height:auto}.blur img{filter:blur(12px);cursor:pointer}"
           ".st{font-size:12px;padding:1px 6px;border-radius:3px;background:#eee}.st.ng{background:#fdd}.st.nc{background:#ffe9b3}"
           "h2{font-size:15px;margin:18px 0 4px}.bar{position:sticky;top:0;background:#fff;padding:8px 0;border-bottom:1px solid #ccc}"
           "button{margin-right:6px}.row p{margin:0}.row .m{font-size:12px;color:#555}")
    out = _head("埋め込み目視確認", css)
    out += ('<div class="bar"><b>埋め込み目視確認</b>（非公開）　'
            '<button id="ie">選んだ本を除外する</button>'
            '<button id="is">選んだ本を作品ごと除外する</button>'
            '<button id="ib">選んだ除外済みの本を戻す</button>'
            '<span id="msg"></span><br><small>ボタンを押すと GitHub の新規Issue画面が開きます。そのまま「Create」を押すと、'
            '埋め込みから外す／戻す設定が自動で反映されます（サイト本体の掲載は変わりません）。表紙のぼかしはクリックで解除。<br>'
            '予備：<button id="cb">選んだ本を除外リスト用にコピー</button>'
            '<button id="cs">選んだ本を作品ごと除外用にコピー</button></small></div>\n<div id="list">\n')
    cur = None
    for b, show, cover, reason in rows:
        if b["release_date"] != cur:
            cur = b["release_date"]
            out += f"<h2>{_fmt(cur)}</h2>\n"
        a = b.get("amazon") or {}
        ex = ""
        if reason.startswith("手動除外"):
            st, cls = reason, "ng"
            ex = "series" if "作品ごと" in reason else "manual"
        elif not show:
            st, cls = f"自動除外：{reason}", "ng"
            ex = "auto"
        elif not cover:
            st, cls = "表紙なしで表示", "nc"
        else:
            st, cls = "表示", ""
        blur = " blur" if (a.get("adult") is True or (not show and not reason.startswith("手動"))) else ""
        img = (f'<img src="{escape(a["image"], quote=True)}" alt="" loading="lazy" onclick="this.parentNode.classList.remove(\'blur\')">'
               if a.get("image") else "")
        if img:
            img = f'<div class="imgw{blur}">{img}</div>'
        label = embed_safety.label_of(b, a)
        data = (f'data-id="{escape(b["id"], quote=True)}" data-title="{escape(book_title(b), quote=True)}" '
                f'data-ex="{ex}" data-sk="{escape(b.get("series_key") or "", quote=True)}" data-st="{escape(b["series_title"], quote=True)}"')
        out += (f'<div class="row" {data}><input type="checkbox" class="ck" aria-label="選ぶ">{img}'
                f'<div><p>{escape(book_title(b))}</p><p class="m">{escape(b["publisher"])} / {escape(label)}　id: {escape(b["id"])}</p>'
                f'<span class="st {cls}">{escape(st)}</span></div></div>\n')
    out += "</div>\n"
    out += (REVIEW_JS.replace("__TODAY__", json.dumps(today.isoformat())).replace("__REPO__", json.dumps(ISSUE_URL))
            .replace("__PRE__", json.dumps(ISSUE_PREFIX)).replace("__MAX__", str(ISSUE_URL_MAX)))
    return out + "</body>\n</html>\n"


def write_all(docs, books, today, rules=None, overrides=None):
    """docs/embed/ 一式を書く。戻り値は件数の dict。"""
    import build  # PUBLISHERS（循環importを避けて遅延）
    rules = rules or embed_safety.load_rules()
    overrides = overrides or embed_safety.load_overrides()
    base = docs / "embed"
    base.mkdir(parents=True, exist_ok=True)

    def put(rel, text):
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    lo = (today - datetime.timedelta(days=PAGE_BACK)).isoformat()
    hi = (today + datetime.timedelta(days=PAGE_FWD)).isoformat()
    rlo = (today - datetime.timedelta(days=REVIEW_BACK)).isoformat()
    rhi = (today + datetime.timedelta(days=REVIEW_FWD)).isoformat()
    n_pages = n_json = 0
    by_day = {}
    review = []
    for b, s, c, r in judged([b for b in books if lo <= b["release_date"] <= hi], rules, overrides):
        if s:
            by_day.setdefault(b["release_date"], []).append((b, c))
        if rlo <= b["release_date"] <= rhi:
            review.append((b, s, c, r))
    for iso, shown in sorted(by_day.items()):
        put(f"{iso}/index.html", page_html(iso, shown, today=today))
        n_pages += 1
        for slug, (name, _u) in build.PUBLISHERS.items():
            sub = [(b, c) for b, c in shown if b["publisher"] == name]
            if sub:
                put(f"{iso}/{slug}/index.html", page_html(iso, sub, name, today))
                n_pages += 1
        put(f"{iso}.json", json.dumps(json_payload(iso, shown), ensure_ascii=False, indent=1))
        n_json += 1
    put("index.html", index_html(by_day, [(k, v[0]) for k, v in build.PUBLISHERS.items()]))
    put("review/index.html", review_html(review, today, overrides))
    return {"pages": n_pages, "json": n_json, "review_rows": len(review)}

"""出版社ページ(キャッシュ)のパーサ。ネットワークには触らない。"""
import html
import hashlib
import json
import re
import unicodedata

import isbnlib

SHOGAKUKAN_BASE = "https://www.shogakukan.co.jp/calendar/paper/comics"
SHOGAKUKAN_URLS = [SHOGAKUKAN_BASE, SHOGAKUKAN_BASE + "/next", SHOGAKUKAN_BASE + "/next2"]
AKITA_URL = "https://www.akitashoten.co.jp/books/upcoming"
KADOKAWA_BASE = "https://www.kadokawa.co.jp"
FUTABA_CALENDAR_URL = "https://www.futabasha.co.jp/new-release-calendar/"
TAKE_BASE = "https://www.takeshobo.co.jp"
SGH_BASE = "https://www.shonengahosha.co.jp"
SGH_COMICS_LIST_URL = SGH_BASE + "/comics.php?@ps@=none"   # コミックスの新着一覧(詳細ページ book_Info.php へのリンク元)


def haku_months(today):
    """白泉社の新刊ページで見る月: 今月と先2か月。"""
    out = []
    y, m = today.year, today.month
    for _ in range(3):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def haku_url(y, m):
    return f"https://www.hakusensha.co.jp/shinkan/?shinkan_year={y}&shinkan_month={m}"


# ---------- 小学館 ----------
def parse_shogakukan(page_html: str):
    m = re.search(r'data-page="([^"]*)"', page_html)
    d = json.loads(html.unescape(m.group(1)))
    cd = d["props"]["calendar_data"]
    y, mo = int(cd["year"]), int(cd["month"])
    out = []
    for day in cd["data"]:
        for b in day.get("books") or []:
            try:
                isbn13 = isbnlib.isbn13_from_isbn8(b["isbn8_cd"])
            except ValueError:
                continue
            authors = " / ".join(a["auth_name"] for a in b.get("auth_notations") or [])
            out.append({
                "isbn13": isbn13, "title_raw": b["title"], "author": authors,
                "publisher": "小学館", "label": "",
                "release_date": f"{y:04d}-{mo:02d}-{int(day['day']):02d}",
                "source_url": SHOGAKUKAN_BASE,
            })
    return out


# ---------- 秋田書店 ----------
def parse_akita(page_html: str, today=None):
    """秋田書店は年が書かれていないので、今月以降の月は今年、それより前の月は来年と推定する。"""
    if today is None:
        import common
        today = common.today()
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', page_html, re.S)
    txt = "".join(json.loads('"' + c + '"') for c in chunks)
    dec = json.JSONDecoder()
    out = []
    for m in re.finditer(r'\{"id":"(\d{1,2})","label":', txt):
        mo = int(m.group(1))
        j = txt.find('"releaseData":', m.end())
        if j < 0:
            continue
        rd, _ = dec.raw_decode(txt[j + len('"releaseData":'):])
        y = today.year if mo >= today.month else today.year + 1
        for g in rd["dateGroups"]:
            for b in g["books"]:
                link = b["link"]
                mm = re.fullmatch(r"/books/(97[89]\d{10})", link)
                if not mm:
                    continue  # 電子版などは対象外(紙のみ)
                out.append({
                    "isbn13": mm.group(1), "title_raw": b["title"], "author": b.get("author", ""),
                    "publisher": "秋田書店", "label": "",
                    "release_date": f"{y:04d}-{mo:02d}-{int(g['date']):02d}",
                    "source_url": "https://www.akitashoten.co.jp" + link,
                })
    return out


# ---------- 白泉社 ----------
def parse_haku_month(page_html: str):
    out = []
    parts = re.split(r'<h3 class="headingLine1 break"><span class="headingItem1[^"]*">', page_html)
    for part in parts[1:]:
        label = part.split("<", 1)[0].strip()
        if label in ("書籍", "電子版のみ"):
            continue
        for tr in re.findall(r"<tr>(.*?)</tr>", part, re.S):
            mm = re.search(r'<a href="(https://www\.hakusensha\.co\.jp/comicslist/(\d+)/)">(.*?)</a>', tr, re.S)
            dm = re.search(r'releaseDate">(\d{4})\.(\d{2})\.(\d{2})<', tr)
            if not mm or not dm:
                continue
            authors = re.findall(r's=[^"]*">([^<]+)</a>', tr)
            out.append({
                "isbn13": None, "title_raw": html.unescape(mm.group(3)).strip(),
                "author": " / ".join(html.unescape(a) for a in authors),
                "publisher": "白泉社", "label": label,
                "release_date": "-".join(dm.groups()), "source_url": mm.group(1),
                "haku_id": mm.group(2),
            })
    return out


def parse_haku_detail_isbn(page_html: str):
    m = re.search(r"ISBN[^0-9]{0,60}(97[89][-0-9]{10,16})", page_html)
    cands = [m.group(1)] if m else []
    cands += re.findall(r"97[89]-?\d-?\d{2,7}-?\d{1,7}-?\d", page_html)
    for v in cands:
        v = v.replace("-", "")
        if len(v) == 13 and isbnlib.valid_isbn13(v):
            return v
    return None


# ---------- KADOKAWA ----------
def kadokawa_months(today):
    """KADOKAWAの新刊カレンダーで見る (target, 年, 月): 今月(target=0)と来月(target=2)。"""
    y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return [(0, today.year, today.month), (2, y, m)]


def kadokawa_url(target):
    return f"{KADOKAWA_BASE}/calendar/?target={target}&largeGenre=13"


def parse_kadokawa(page_html: str, paper_only=True):
    """KADOKAWA 新刊カレンダー(コミック)の1か月分。ISBNは表紙画像URLのファイル名からだけ取る(画像自体は保存しない)。
    ISBNが取れない本は電子専用(分冊版・単話・デジタル限定など)なので、既定(paper_only=True)では除く。
    paper_only=False なら kadokawa_id を持った ISBN 無しの本も返す。"""
    tm = re.search(r"<title>[^<]*?(\d{4})年(\d{1,2})月発売", page_html)
    if not tm:
        raise ValueError("年月が読み取れない")
    y, mo = int(tm.group(1)), int(tm.group(2))
    out = []
    parts = re.split(r'<div id="date-(\d+)"', page_html)
    for k in range(1, len(parts) - 1, 2):
        day = int(parts[k])
        for blk in parts[k + 1].split('<div class="calendar-result-list ')[1:]:
            pm = re.search(r'href="/product/(\w+)/', blk)
            tt = re.search(r'<h2 class="book-title">(.*?)</h2>', blk, re.S)
            if not pm or not tt:
                continue
            um = re.search(r'unique="[^"]*/(97[89]\d{10})\.\w+"', blk)
            isbn = um.group(1) if um and isbnlib.valid_isbn13(um.group(1)) else None
            if isbn is None and paper_only:
                continue
            names = []
            roles = []
            for li in re.findall(r"<li>(.*?)</li>", (re.search(r'<ul class="book-auther">(.*?)</ul>', blk, re.S) or [None, ""])[1], re.S):
                li = html.unescape(re.sub(r"<[^>]+>", "", li)).replace("\xa0", " ").strip()
                names.append(li.split(" ", 1)[1].strip() if " " in li else li)  # 先頭は役割(漫画/原作など)
                if " " in li:
                    roles.append(li.split(" ", 1)[0].strip())
            lm = re.search(r"レーベル：([^<]+)", blk)
            out.append({
                "isbn13": isbn, "title_raw": html.unescape(re.sub(r"<[^>]+>", "", tt.group(1))).strip(),
                "author": " / ".join(n for n in names if n), "publisher": "KADOKAWA",
                **({"roles": roles} if roles else {}),
                "label": html.unescape(lm.group(1)).strip() if lm else "",
                "release_date": f"{y:04d}-{mo:02d}-{day:02d}",
                "source_url": f"{KADOKAWA_BASE}/product/{pm.group(1)}/", "kadokawa_id": pm.group(1),
            })
    return out


# ---------- 双葉社 ----------
def futaba_months(today):
    """双葉社の公開JSONで見る年月 (YYYYMM): 今月と来月。"""
    y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return [f"{today.year:04d}{today.month:02d}", f"{y:04d}{m:02d}"]


def futaba_url(ym):
    return f"https://book-api.futabasha.co.jp/calendar_books?request_ym={ym}&display_order=1&age_verification=3&image_size=330"


def futaba_clean_title(name: str) -> str:
    """「X ： 29」「X 9 【コミック】」「X 2 完」を「X 29」の形にそろえる(parse_title が巻数を取れるように)。"""
    t = name.replace("\u3000", " ").strip()
    t = re.sub(r"\s*[(（【\[]\s*コミック\s*[)）】\]]", "", t)
    t = re.sub(r"\s*[：:]\s*(?=[0-9０-９]+\s*$)", " ", t)       # 「X ： 29」
    t = re.sub(r"(\s[0-9０-９]{1,4})\s*完\s*$", r"\1", t)       # 「X 2 完」
    return re.sub(r"\s+", " ", t).strip()


def parse_futabasha(text: str, ym=None):
    """双葉社の公開JSON(calendar_books)から、紙のコミック(release_dt あり)だけを取る。
    release_dt が空で start_dt だけのものは電子先行なので除く。ym(YYYYMM)を渡すと、その月以外の発売日は捨てる。"""
    d = json.loads(text)
    out = []
    for b in d["books"]["book_informations"]:
        if b.get("publication_form_value") != "コミック" or not b.get("release_dt"):
            continue
        isbn = (b.get("isbn_code") or "").replace("-", "")
        if not isbnlib.valid_isbn13(isbn):
            continue
        rd = b["release_dt"][:10]
        if ym and rd[:4] + rd[5:7] != ym:
            continue
        names = []
        for a in b.get("book_authors") or []:
            if a.get("author_name") and a["author_name"] not in names:
                names.append(a["author_name"])
        out.append({
            "isbn13": isbn, "title_raw": futaba_clean_title(b["book_name"]), "author": " / ".join(names),
            "publisher": "双葉社", "label": (b.get("label_name") or "").strip() or None,
            "release_date": rd, "source_url": f"https://www.futabasha.co.jp/book/{isbn}",
        })
    return out


# ---------- 竹書房 ----------
def take_url(page=1):
    """竹書房の書籍検索(ジャンル=コミック)。発売日の新しい順、100件/ページ。"""
    q = "amount=100&order=book_date_desc" if page <= 1 else f"page={page}&amount=100&order=book_date_desc"
    return f"{TAKE_BASE}/search/g106010.html?{q}"


def _take_items(page_html: str):
    body = page_html.split('<div class="booklist">', 1)
    if len(body) < 2:
        raise ValueError("一覧が見つからない")
    return body[1].split('<div class="item">')[1:]


def take_dates(page_html: str):
    """一覧ページ(除外前の全件)に出てくる発売日。ページ送りをやめる判断に使う。"""
    out = []
    for it in _take_items(page_html):
        dm = re.search(r"\[ (\d{4})/(\d{2})/(\d{2}) 発売", it)
        if dm:
            out.append("-".join(dm.groups()))
    return out


def parse_takeshobo(page_html: str, min_date=None):
    """竹書房の一覧1ページから、紙のコミックの書誌事実だけを取る。ISBNは詳細ページにしかない(isbn13=None, take_id を持たせる)。
    書名末尾が「（電子書籍）」のものは電子版なので除く。「（コミック）」は外す。判型の付かない廉価版コミックなどは残す。
    min_date(YYYY-MM-DD)を渡すと、それより前の発売日は捨てる。"""
    out = []
    for it in _take_items(page_html):
        tm = re.search(r'<div class="ttl">\s*<a href="/book/b(\d+)\.html">\s*(.*?)\s*</a>', it, re.S)
        dm = re.search(r"\[ (\d{4})/(\d{2})/(\d{2}) 発売", it)
        if not tm or not dm:
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", tm.group(2)))
        title = re.sub(r"[\s\u3000]+", " ", title).strip()
        fm = re.search(r"[（(](コミック|電子書籍)[)）]$", title)
        if fm:
            if fm.group(1) == "電子書籍":
                continue
            title = title[:fm.start()].strip()
        rd = "-".join(dm.groups())
        if min_date and rd < min_date:
            continue
        am = re.search(r'<div class="author">(.*?)</div>', it, re.S)
        names = []
        for n in re.findall(r'<a href="/author/[^"]*">([^<]+)</a>', am.group(1) if am else ""):
            n = html.unescape(n).strip()
            if n and n not in names:
                names.append(n)
        tags = [html.unescape(t).strip() for t in re.findall(r'<div class="tag"><a href="/search/g\d+\.html"><span>([^<]*)</span>', it)]
        specific = [t for t in tags if t != "バンブーコミックス"]   # 「バンブーコミックス」は全体の総称。あれば細かいレーベルを優先
        out.append({
            "isbn13": None, "title_raw": title, "author": " / ".join(names),
            "publisher": "竹書房", "label": (specific or tags or [None])[0],
            "release_date": rd, "source_url": f"{TAKE_BASE}/book/b{tm.group(1)}.html", "take_id": tm.group(1),
        })
    return out


def parse_take_detail_isbn(page_html: str):
    m = re.search(r"<th>ISBN</th>\s*<td>\s*([0-9-]{13,17})\s*</td>", page_html)
    if m:
        v = m.group(1).replace("-", "")
        if len(v) == 13 and isbnlib.valid_isbn13(v):
            return v
    return None


# ---------- 少年画報社 ----------
def sgh_months(today):
    """少年画報社のカレンダーで見る年月 (YYYY-MM): 今月と来月。"""
    y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return [f"{today.year:04d}-{today.month:02d}", f"{y:04d}-{m:02d}"]


def sgh_url(ym):
    return f"{SGH_BASE}/cal.php?release={ym}"


def sgh_norm_title(s: str) -> str:
    return "".join(unicodedata.normalize("NFKC", html.unescape(s)).lower().split())


def parse_shonengahosha(page_html: str, ym=None):
    """少年画報社のカレンダー1か月分。区分が「コミックス」のものだけ取る(雑誌・コンビニコミックスは除く)。
    一覧には詳細ページへのリンクもISBNも無いので isbn13=None。sgh_id は「発売日-書名のハッシュ」で作る。"""
    hm = re.search(r"<h2>\s*(\d{4})年\s*(\d{1,2})月\s*</h2>", page_html)
    if not hm:
        raise ValueError("年月が読み取れない")
    y, mo = int(hm.group(1)), int(hm.group(2))
    if ym and ym != f"{y:04d}-{mo:02d}":
        raise ValueError("取得した月が違う")
    out = []
    for blk in page_html.split('<tr class="border1">')[1:]:
        blk = blk.split("</tr>")[0]
        km = re.search(r'<span class="ico-\w+">([^<]*)</span>', blk)
        dm = re.search(r"<th>\s*(\d{1,2})（", blk)
        tt = re.search(r"<b>(.*?)</b>(.*?)<br>", blk, re.S)
        if not km or km.group(1).strip() != "コミックス" or not dm or not tt:
            continue
        title = re.sub(r"[\s\u3000]+", " ", html.unescape(re.sub(r"<[^>]+>", "", tt.group(1)))).strip()
        am = re.sub(r"<[^>]+>", "", tt.group(2))
        names = [n.strip() for n in re.split(r"[/／]", html.unescape(am)) if n.strip()]
        rd = f"{y:04d}-{mo:02d}-{int(dm.group(1)):02d}"
        sid = rd.replace("-", "") + "-" + hashlib.sha1(sgh_norm_title(title).encode()).hexdigest()[:8]
        out.append({
            "isbn13": None, "title_raw": title, "author": " / ".join(names),
            "publisher": "少年画報社", "label": None,
            "release_date": rd, "source_url": sgh_url(f"{y:04d}-{mo:02d}"), "sgh_id": sid,
        })
    return out


def parse_sgh_comics_list(page_html: str):
    """少年画報社コミックス一覧(新着順)から [(詳細ID, 書名)]。"""
    return [(i, re.sub(r"[\s\u3000]+", " ", html.unescape(t)).strip()) for i, t in re.findall(
        r'href="book_Info\.php\?id=(\d+)"[^>]*>.*?<span class="itemText">(.*?)</span>', page_html, re.S)]


def parse_sgh_detail(page_html: str):
    """少年画報社の詳細ページから (isbn13 or None, 発売日 or None)。"""
    m = re.search(r"\[ISBN\]\s*([0-9-]{13,17})", page_html)
    isbn = None
    if m:
        v = m.group(1).replace("-", "")
        isbn = v if len(v) == 13 and isbnlib.valid_isbn13(v) else None
    d = re.search(r"\[発売日\]\s*(\d{4}-\d{2}-\d{2})", page_html)
    return isbn, (d.group(1) if d else None)


# ---------- 巻数表記の整形（volume_hint） ----------
_LABEL_WORDS = r"KC|コミックス|コミック|COMICS|Comics|文庫|デラックス|リミックス|キャラクターズ|講談社|集英社"
LABEL_RE = re.compile(r"\s*[(（]([^()（）]*(?:" + _LABEL_WORDS + r")[^()（）]*)[)）]\s*$")
_NOT_WORK_WORDS = re.compile(r"画集|図鑑|図かん|ずかん|ガイド|ファンブック|設定資料集|アートワークス|ポスターコレクション")
_ED_TAIL = re.compile(r"\S*?(?:特装版|限定版|特別版|同梱版|通常版)")
_KAN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
            "壱": 1, "弐": 2, "参": 3}
_ROM_NUM = {"II": 2, "III": 3, "IV": 4, "VI": 6, "VII": 7, "VIII": 8, "IX": 9}   # I・V・X 単独は題名の一部のことが多いので取らない
_JOUGE = {"上": 1, "中": 2, "下": 2}   # 上・下の2冊が基本（上=1、下=2）。「中」もある3部作は個別に判断する
_UNIT_AFTER = re.compile(r"^(?:章|話|部|期|人|年|月|日|周年|回|時|歳|冊|本|個|つ|次元|nd|rd|th|st)")


def _norm(raw: str) -> str:
    t = unicodedata.normalize("NFKC", raw).replace("\u3000", " ")
    t = re.sub(r"(?<=[Vv])\u043e(?=l)", "o", t)   # 「Vоl.1」のキリル文字の о
    return re.sub(r"\s+", " ", t).strip()


def split_label(raw: str):
    """題名末尾のレーベル括弧（「(ヤングジャンプコミックス)」「(講談社文庫 ふ 96-3)」）を外す。(題名, レーベル) を返す。"""
    t = _norm(raw)
    m = LABEL_RE.search(t)
    if m:
        return t[:m.start()].strip(), m.group(1).strip()
    return t, ""


def is_novel_label(label: str, title: str = "") -> bool:
    """文庫系のレーベル（ダッシュエックス文庫など）か。コミック版の文庫（講談社文庫の「文庫版」）は含めない。"""
    return bool(label) and "文庫" in label and "コミック" not in label and "文庫版" not in title


def _tail_has_volume(t: str) -> bool:
    return bool(re.search(r"(?:\s\d{1,4}|\d{1,4}\s*巻)\s*$", t))


def volume_hint(raw: str, publisher: str) -> str:
    """parse_title に渡す前の巻数表記の整形（全出版社共通）。
    末尾のレーベル括弧・全集の番号を外し、「…（12）」「…vol.02」「…[2]」「VOLUME 2 TWO」「上・下」「二・VII」
    「N ～副題～」「（N） 副題」などを「… N」の形にそろえる。
    KADOKAWA だけ「物語2」（空白なしで付く数字）も巻数とみなす。少年画報社の「全１巻」は「１巻」にする。
    すでに末尾から巻数が取れる題名は、中途の数字を見ずにそのまま返す。"""
    t, _label = split_label(raw)
    t = re.sub(r"(?<=\s)\S*全集\d{2,4}$", "", t).strip()   # 「本宮ひろ志漫画大全集030」の番号は巻数ではない
    if publisher == "少年画報社":
        t = re.sub(r"\s*全\s*(\d{1,4})\s*巻\s*$", r" \1巻", t)
    t = re.sub(r"\s*[(（\[](\d{1,4})[)）\]]$", r" \1", t)
    # 「X(5) キラキラスリーブケース付き特装版」「X(14)限定版」型: 括弧の巻数を取り、特典名は捨てて版表記だけ残す
    m = re.search(r"\s*[(（](\d{1,4})[)）]\s*([^()（）]*?(特装版|限定版|特別版|同梱版|通常版))$", t)
    if m:
        return re.sub(r"^\S*付き?\s+(?=\S)", "", t[:m.start()]).strip() + f" {int(m.group(1))} {m.group(3)}"
    t = re.sub(r"\s*[Vv]ol\.?\s*(\d{1,4})$", lambda m: " " + str(int(m.group(1))), t)
    t = re.sub(r"\s*\[VOLUME\]\s*(\d{1,4})$", lambda m: " " + str(int(m.group(1))), t)
    t = re.sub(r"\s*VOLUME\s*(\d{1,4})(?:\s+[A-Za-z]+)?$", lambda m: " " + str(int(m.group(1))), t)
    if publisher == "KADOKAWA":
        t = re.sub(r"(?<=[^\d\s])(\d{1,3})$", r" \1", t)   # 「物語2」→「物語 2」
    if _tail_has_volume(t):
        return t
    m = re.search(r"\s([上中下])巻?$", t)
    if m:
        return t[:m.start()] + f" {_JOUGE[m.group(1)]}"
    m = re.search(r"\s([一二三四五六七八九十壱弐参]|[IVX]{2,4})$", t)
    if m and (m.group(1) in _KAN_NUM or m.group(1) in _ROM_NUM):
        return t[:m.start()] + f" {_KAN_NUM.get(m.group(1)) or _ROM_NUM[m.group(1)]}"
    return _mid_volume(t, publisher)


def _mid_volume(t: str, publisher: str) -> str:
    """題名の途中に巻数があり副題が続く型。巻数より後ろを捨てて「… N」にする（版表記だけは残す）。"""
    cands = []
    for m in re.finditer(r"\s*[(（\[](\d{1,3})[)）\]]\s+(?=\S)", t):                  # 「（3） 副題」「[2] ~副題~」
        cands.append((m.start(), m.end(), m.group(1)))
    for m in re.finditer(r"(?<=\S)\s(\d{1,3})\s+(?=[～~‐\-ー―－])", t):               # 「5 ～副題～」
        cands.append((m.start(), m.end(), m.group(1)))
    for m in re.finditer(r"(?<=[!?。」』])(\d{1,3})\s+(?=\S)", t):                        # 「！1 副題」
        cands.append((m.start(), m.end(), m.group(1)))
    for m in re.finditer(r"(?<=\S)\s(\d{1,3})\s+(?=\S)", t):                            # 「14 魔物の力を…」
        if not re.search(r"(?:第|[Pp]art|No\.?|#)$", t[:m.start()]) and not _UNIT_AFTER.match(t[m.end():]):
            cands.append((m.start(), m.end(), m.group(1)))
    if publisher == "KADOKAWA" and not _NOT_WORK_WORDS.search(t):
        for m in re.finditer(r"(?<=[^\d\s!?。」』])(\d{1,3})\s+(?=\S)", t):                 # 「ブレイズ1 副題」（KADOKAWAの空白なし巻数）
            if not _UNIT_AFTER.match(t[m.end():]):
                cands.append((m.start(), m.end(), m.group(1)))
    if not cands:
        return t
    start, end, n = min(cands)
    rest = t[end:]
    if _ED_TAIL.fullmatch(rest.strip()):
        return t                       # 「12 シャカシャカアクキー付き特装版」型。parse_title が版表記として処理する
    ed = re.search(r"特装版|限定版|特別版|同梱版|通常版|(?:フル)?カラー版", rest)
    return t[:start] + f" {int(n)}" + (f" {ed.group(0)}" if ed else "")


def parse_book(raw: str, publisher: str):
    """(series_key, volume, display_title, edition_flags, label) を返す。レーベル括弧は題名から外し label に入れる。
    文庫系（ライトノベル）のレーベルは、同名の漫画とまとまらないよう series_key / 表示名の末尾にレーベルを付ける。"""
    title, label = split_label(raw)
    key, vol, display, flags = parse_title(volume_hint(raw, publisher))
    if is_novel_label(label, title):
        display = f"{display} ({label})"
        key = re.sub(r"\s+", "", display)
    return key, vol, display, flags, label


# ---------- タイトル解析 ----------
EDITION_WORDS = [("特装版", "特装版"), ("限定版", "限定版"), ("特別版", "限定版"), ("同梱版", "特装版"),
                 ("小冊子付き", "特装版"), ("特典付き", "特装版"), ("通常版", "通常版")]
_COLOR_ED = re.compile(r"(?<=\S)\s+((?:公式)?(?:フル)?カラー版)(?:『[^』]*』)?(?=\s*$)")
_EDWORDS = "特装版|限定版|特別版|同梱版|通常版|小冊子付き|特典付き|フィギュア付き|DVD付き|Blu-ray付き"


def parse_title(raw: str):
    """(series_key, volume, display_title, edition_flags) を返す。"""
    t = unicodedata.normalize("NFKC", raw).replace("　", " ").strip()
    flags = []
    t = re.sub(r"\S*(?:付き?|つき)(?=特装版|限定版|特別版)", " ", t) if re.search(r"\S(?:付き?|つき)(?:特装版|限定版|特別版)", t) else t
    for w, f in EDITION_WORDS:
        if w in t and f not in flags:
            flags.append(f)
    base = re.sub(r"[【\[(〈<][^】\])〉>]*?(?:" + _EDWORDS + r")[^】\])〉>]*?[】\])〉>]", " ", t)
    vol = None
    m = re.search(r"(?:第\s*)?(\d{1,4})\s*巻\s*$", base)
    if m:
        vol = int(m.group(1))
        base = base[:m.start()]
    else:
        m = re.search(r"\s(\d{1,4})\s*$", base)
        if m:
            vol = int(m.group(1))
            base = base[:m.start()]
    for w, _f in EDITION_WORDS:
        base = base.replace(w, " ")
    # カラー版（「公式フルカラー版『副題』」を含む）は同じ作品の版表記。題名の先頭にある場合は作品名の一部とみて外さない
    cm = _COLOR_ED.search(base)
    if cm:
        flags.append("フルカラー版" if "フル" in cm.group(1) else "カラー版")
        base = base[:cm.start()]
    # 版表記を除いたあとの末尾の巻数（「3 特装版」型）
    if vol is None:
        m = re.search(r"(?:第\s*)?(\d{1,4})\s*巻\s*$", base) or re.search(r"\s(\d{1,4})\s*$", base)
        if m:
            vol = int(m.group(1))
            base = base[:m.start()]
    base = re.sub(r"\s+", " ", base).strip(" -~・")
    display = base or t
    key = re.sub(r"\s+", "", display)
    return key, vol, display, flags

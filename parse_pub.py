"""出版社ページ(キャッシュ)のパーサ。ネットワークには触らない。"""
import html
import json
import re
import unicodedata

import isbnlib

SHOGAKUKAN_BASE = "https://www.shogakukan.co.jp/calendar/paper/comics"
SHOGAKUKAN_URLS = [SHOGAKUKAN_BASE, SHOGAKUKAN_BASE + "/next", SHOGAKUKAN_BASE + "/next2"]
AKITA_URL = "https://www.akitashoten.co.jp/books/upcoming"
KADOKAWA_BASE = "https://www.kadokawa.co.jp"
FUTABA_CALENDAR_URL = "https://www.futabasha.co.jp/new-release-calendar/"


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
            for li in re.findall(r"<li>(.*?)</li>", (re.search(r'<ul class="book-auther">(.*?)</ul>', blk, re.S) or [None, ""])[1], re.S):
                li = html.unescape(re.sub(r"<[^>]+>", "", li)).replace("\xa0", " ").strip()
                names.append(li.split(" ", 1)[1].strip() if " " in li else li)  # 先頭は役割(漫画/原作など)
            lm = re.search(r"レーベル：([^<]+)", blk)
            out.append({
                "isbn13": isbn, "title_raw": html.unescape(re.sub(r"<[^>]+>", "", tt.group(1))).strip(),
                "author": " / ".join(n for n in names if n), "publisher": "KADOKAWA",
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


def volume_hint(raw: str, publisher: str) -> str:
    """parse_title に渡す前の巻数表記の整形。KADOKAWA の「…vol.02」「…（12）」を「… 2」「… 12」にする。他社は何もしない。"""
    if publisher != "KADOKAWA":
        return raw
    t = unicodedata.normalize("NFKC", raw).replace("\u3000", " ").strip()
    t = re.sub(r"\s*[(（](\d{1,4})[)）]$", r" \1", t)
    t = re.sub(r"\s*[Vv]ol\.?\s*(\d{1,4})$", lambda m: " " + str(int(m.group(1))), t)
    t = re.sub(r"\s*\[VOLUME\]\s*(\d{1,4})$", lambda m: " " + str(int(m.group(1))), t)
    t = re.sub(r"(?<=[^\d\s])(\d{1,3})$", r" \1", t)   # 「物語2」→「物語 2」(空白なしで巻数が付く表記)
    return t


# ---------- タイトル解析 ----------
EDITION_WORDS = [("特装版", "特装版"), ("限定版", "限定版"), ("特別版", "限定版"), ("同梱版", "特装版"),
                 ("小冊子付き", "特装版"), ("特典付き", "特装版"), ("通常版", "通常版")]
_EDWORDS = "特装版|限定版|特別版|同梱版|通常版|小冊子付き|特典付き|フィギュア付き|DVD付き|Blu-ray付き"


def parse_title(raw: str):
    """(series_key, volume, display_title, edition_flags) を返す。"""
    t = unicodedata.normalize("NFKC", raw).replace("　", " ").strip()
    flags = []
    t = re.sub(r"\S*付(?=特装版|限定版|特別版)", " ", t) if re.search(r"\S付(?:特装版|限定版|特別版)", t) else t
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
    # 版表記を除いたあとの末尾の巻数（「3 特装版」型）
    if vol is None:
        m = re.search(r"\s(\d{1,4})\s*$", base)
        if m:
            vol = int(m.group(1))
            base = base[:m.start()]
    base = re.sub(r"\s+", " ", base).strip(" -~・")
    display = base or t
    key = re.sub(r"\s+", "", display)
    return key, vol, display, flags

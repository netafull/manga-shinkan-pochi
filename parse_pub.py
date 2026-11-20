"""出版社ページ(キャッシュ)のパーサ。ネットワークには触らない。"""
import html
import json
import re
import unicodedata

import isbnlib

SHOGAKUKAN_BASE = "https://www.shogakukan.co.jp/calendar/paper/comics"
SHOGAKUKAN_URLS = [SHOGAKUKAN_BASE, SHOGAKUKAN_BASE + "/next", SHOGAKUKAN_BASE + "/next2"]
AKITA_URL = "https://www.akitashoten.co.jp/books/upcoming"


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

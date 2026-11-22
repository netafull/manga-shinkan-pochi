"""作品名の「読み」を openBD から補う（作品一覧の五十音分け用）。

- openBD（https://openbd.jp/ 、販促・紹介目的に限り使用可）。ISBNをまとめて1回で問い合わせ、
  リクエスト間隔は1秒以上、正直なUA。エラー・429・タイムアウトが出たらその実行では以後問い合わせない。
- 読みは ONIX の TitleText.collationkey。巻数・括弧書き・特典注記を落としてカタカナにそろえる。
- 状態は data/yomi.json（update.py が書く。手で編集しない）。手動辞書 config/yomi_manual.json が最優先。
- NDLサーチ API は営利目的の申請が要るので使わない。
"""
import datetime
import json
import re
import time
import unicodedata
import urllib.request
from pathlib import Path

import common

API = "https://api.openbd.jp/v1/get"
UA = "MangaShinkanPochi/1.0 (+https://shinkan.netaful.jp/)"
BATCH = 100          # 1リクエストのISBN数
MIN_GAP = 1.0        # リクエスト間隔（秒）
MAX_ROUNDS = 3       # 作品ごとに、発売日の古い本から最大この冊数まで試す
GIVE_UP_DAYS = 60    # 最新の発売日からこの日数を過ぎても取れなければ、以後は問い合わせない
RETRY_AFTER_RELEASED = 7
MANUAL = common.ROOT / "config" / "yomi_manual.json"

_last = {"t": 0.0}
# 数字（巻数）のあとに付く特典・版の注記。「006デンシゲンテイオマケツキ」のように数字の直後から始まるものだけ落とす
_NOTE = re.compile(r"\d+(?=(?:デンシゲンテイ|ゲンテイ|トクソウ|トクセン|トクテン|オマケ|ツキ|アイゾウ|ショカイ|ドクジ|カンゼン|ガイドブック|ファンブック))")


_TAIL_MARK = re.compile(r"[~〜\-‐・=＝:：]+$")


def to_katakana(s):
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)


def normalize_yomi(raw):
    """openBD の collationkey などをカタカナの読みにそろえる。使えなければ None（先頭がカナでないものは採用しない）。"""
    if not raw or not isinstance(raw, str):
        return None
    s = unicodedata.normalize("NFKC", raw)
    s = re.sub(r"[(（\[【][^)）\]】]*[)）\]】]", "", s)      # 括弧書き（(013) など）
    s = "".join(s.split())
    s = to_katakana(s)
    s = s.split("/")[0]                                       # 「題名/副題」の副題
    m = _NOTE.search(s)
    if m:
        s = s[:m.start()]
    s = re.sub(r"(?:ショウサッシ)?ツキ(?:トクソウバン|ゲンテイバン)$|(?:トクソウバン|ゲンテイバン)$", "", s)  # 末尾の版の注記
    s = _TAIL_MARK.sub("", s)                                 # 末尾の「~」「-」「・」など
    s = re.sub(r"\d+$", "", s)                                # 末尾の巻数
    s = _TAIL_MARK.sub("", s)
    if not s or not ("ァ" <= s[0] <= "ヶ"):
        return None
    return s


# ---- 巻数の読み・副題の混入を削る（保存前／再正規化で使う） ----
_ONES = {0: ["ゼロ", "レイ"], 1: ["イチ"], 2: ["ニ"], 3: ["サン"], 4: ["ヨン", "シ", "ヨ"], 5: ["ゴ"],
         6: ["ロク"], 7: ["ナナ", "シチ"], 8: ["ハチ"], 9: ["キュウ", "ク"]}
_HUND = {1: ["ヒャク"], 2: ["ニヒャク"], 3: ["サンビャク"], 4: ["ヨンヒャク"], 5: ["ゴヒャク"], 6: ["ロッピャク", "ロクヒャク"],
         7: ["ナナヒャク"], 8: ["ハッピャク", "ハチヒャク"], 9: ["キュウヒャク"]}


_AMBIGUOUS = {"シ", "ク", "ゴ", "ヨ"}


def volume_readings(n):
    """巻数 n（1〜999）のカナ読みの候補（ヨン/シ、ナナ/シチ 等）。"""
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 999:
        return []
    h, t, o = n // 100, n // 10 % 10, n % 10
    heads = _HUND[h] if h else [""]
    if t == 0:
        mids = [""]
    elif t == 1:
        mids = ["ジュウ"]
    else:
        mids = [d + "ジュウ" for d in _ONES[t]]
    tails = _ONES[o] if o else [""]
    out = {a + b + c for a in heads for b in mids for c in tails}
    return sorted(out, key=lambda x: -len(x))


def _title_kana_tail(title):
    t = to_katakana(unicodedata.normalize("NFKC", title or ""))
    t = re.sub(r"[^\w]+$", "", t)                       # 末尾の「!」「。」「~」など
    m = re.search(r"[ァ-ヶー]+$", t)
    return m.group(0) if m else ""


def _title_ends_in_kana(title):
    t = unicodedata.normalize("NFKC", title or "")
    t = re.sub(r"[^\w]+$", "", t)
    return bool(re.search(r"[ぁ-ゖァ-ヶー]$", t))


def _title_digit_runs(title):
    return set(re.findall(r"\d+", unicodedata.normalize("NFKC", title or "")))


def clean_tail(y, title=None, volume=None):
    """読み y の末尾に混ざった巻数の読み・副題を削る。title は作品名（series_title）、volume はその本の巻数。
    題名自体がその音で終わる場合（「〜さん」で終わる作品の3巻など）は、巻数の読みが重なって付いているときだけ削る。"""
    if not y:
        return y
    s = y
    title_digits = _title_digit_runs(title)
    # 数字（巻数）以降は副題・特典。題名に無い数字の手前で切る（「ダイ22カン」は「ダイ」ごと）
    for m in re.finditer(r"\d+", s):
        if m.group(0) in title_digits or m.start() == 0:
            continue
        s = s[:m.start()]
        s = re.sub(r"(?:VOLUME|VOL\.?|ダイ)$", "", s)
        break
    s = _TAIL_MARK.sub("", s)
    # 巻数のカナ読み
    cands = volume_readings(volume)
    tt = _title_kana_tail(title)
    for k in cands:
        for pat in ("ダイ" + k + "カン", k + "カン", k):
            if not s.endswith(pat) or len(s) <= len(pat):
                continue
            if pat == k and tt.endswith(k) and not s.endswith(k + k):
                continue            # 題名が同じ音で終わる（〜さん 等）。重なっていなければ題名の一部
            if pat == k and k in _AMBIGUOUS and not _title_ends_in_kana(title):
                continue            # 1音（シ・ク・ゴ・ヨ）で題名が漢字終わり（「〜話」→ハナシ 等）は題名側の音かもしれない。削らない
            s = s[:-len(pat)]
            break
        else:
            continue
        break
    s = _TAIL_MARK.sub("", s)
    return s or y


def extract_collationkey(item):
    """openBD 1件の応答から collationkey を探す（書籍そのものの題名を優先）。無ければ None。"""
    try:
        td = item["onix"]["DescriptiveDetail"]["TitleDetail"]
    except (TypeError, KeyError):
        return None
    cands = []
    for d in (td if isinstance(td, list) else [td]):
        els = d.get("TitleElement") if isinstance(d, dict) else None
        for e in (els if isinstance(els, list) else [els]):
            if isinstance(e, dict) and isinstance(e.get("TitleText"), dict):
                cands.append((e.get("TitleElementLevel") != "01", e["TitleText"].get("collationkey")))
    cands.sort(key=lambda x: x[0])
    for _lvl, k in cands:
        if k:
            return k
    return None


class Stop(Exception):
    pass


def fetch_batch(isbns):
    """openBD に1回問い合わせ、ISBN→collationkey（無ければ None）の辞書を返す。失敗は Stop。"""
    wait = MIN_GAP - (time.time() - _last["t"])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(API + "?isbn=" + ",".join(isbns), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # 429・タイムアウト・通信/JSONエラー: この実行では以後呼ばない
        raise Stop(type(e).__name__ if not hasattr(e, "code") else f"HTTP {e.code}")
    finally:
        _last["t"] = time.time()
    if not isinstance(data, list) or len(data) != len(isbns):
        raise Stop("予期しない応答の形")
    out = {}
    for isbn, item in zip(isbns, data):
        out[isbn] = extract_collationkey(item) if item else None
    return out


def load_state(path):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    body = ",\n".join(f"{json.dumps(k, ensure_ascii=False)}:{json.dumps(v, ensure_ascii=False)}" for k, v in sorted(state.items()))
    Path(path).write_text("{\n" + body + "\n}\n", encoding="utf-8")


def load_manual(path=None):
    try:
        d = json.loads(Path(path or MANUAL).read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if isinstance(v, str) and v} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _works(books):
    """series_key -> 発売日の古い順の [(release_date, isbn13)]（ISBN13のある本だけ。日付だけの本も日付用に残す）。"""
    w = {}
    for b in books:
        if not b.get("series_key") or not b.get("release_date"):
            continue
        w.setdefault(b["series_key"], []).append((b["release_date"], b.get("isbn13")))
    for v in w.values():
        v.sort(key=lambda x: (x[0], x[1] or ""))
    return w


def next_retry(dates, today):
    """未取得の作品の再試行日: 最も近い発売日が今日より後ならその翌日、過ぎていれば今日から7日後。"""
    future = [d for d in dates if d > today.isoformat()]
    if future:
        return (datetime.date.fromisoformat(min(future)) + datetime.timedelta(days=1)).isoformat()
    return (today + datetime.timedelta(days=RETRY_AFTER_RELEASED)).isoformat()


def _due(entry, dates, today):
    if entry is None:
        return True
    if entry.get("yomi"):
        return False
    last = datetime.date.fromisoformat(max(dates))
    if last + datetime.timedelta(days=GIVE_UP_DAYS) < today:
        return False            # 発売から60日たっても取れない → 手動辞書に任せる
    ra = entry.get("retry_after")
    return not ra or ra <= today.isoformat()


def run(books, state_path, today=None, net=True, manual=None, fetch=None, log=print):
    """未取得・再試行日が来た作品の読みを問い合わせ、state_path に保存する。{"queries","got","pending","stopped"} を返す。"""
    today = today or common.today()
    fetch = fetch or fetch_batch
    manual = load_manual() if manual is None else manual
    state = load_state(state_path)
    stats = {"queries": 0, "got": 0, "pending": 0, "stopped": None}
    if not net:
        stats["stopped"] = "ネットワークなしの実行"
        return stats
    works = _works(books)
    by_isbn = {b["isbn13"]: b for b in books if b.get("isbn13")}
    todo = {}
    for key, items in works.items():
        if key in manual:
            continue
        if _due(state.get(key), [d for d, _i in items], today):
            todo[key] = [i for _d, i in items if i]
    stamp = today.isoformat()
    try:
        for rnd in range(MAX_ROUNDS):
            asks = {}  # isbn -> series_key（同じISBNは1回だけ）
            for key, isbns in todo.items():
                if state.get(key, {}).get("yomi") or rnd >= len(isbns):
                    continue
                asks.setdefault(isbns[rnd], key)
            isbn_list = list(asks)
            for i in range(0, len(isbn_list), BATCH):
                chunk = isbn_list[i:i + BATCH]
                stats["queries"] += 1
                res = fetch(chunk)
                for isbn in chunk:
                    key = asks[isbn]
                    b = by_isbn.get(isbn) or {}
                    y = clean_tail(normalize_yomi(res.get(isbn)), b.get("series_title"), b.get("volume"))
                    if y and not state.get(key, {}).get("yomi"):
                        state[key] = {"yomi": y, "source": "openbd", "isbn": isbn, "checked": stamp}
                        stats["got"] += 1
    except Stop as e:
        stats["stopped"] = str(e)
        log(f"WARNING: yomi: openBD {e}。この実行では以後問い合わせません")
    except Exception as e:
        stats["stopped"] = type(e).__name__
        log(f"WARNING: yomi: 想定外の例外 ({type(e).__name__})")
    finally:
        # 問い合わせ済みで取れなかった作品に再試行日を付ける（途中で止まったときは、問い合わせていない作品を触らない）
        if stats["stopped"] is None:
            for key in todo:
                if not state.get(key, {}).get("yomi"):
                    dates = [d for d, _i in works[key]]
                    state[key] = {"yomi": None, "checked": stamp, "retry_after": next_retry(dates, today)}
        stats["pending"] = sum(1 for k in todo if not state.get(k, {}).get("yomi"))
        save_state(state_path, state)
    return stats

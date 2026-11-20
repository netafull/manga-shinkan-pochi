"""ISBN変換（標準ライブラリのみ）。"""
import re


def isbn13_check(first12: str) -> str:
    s = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(first12))
    return str((10 - s % 10) % 10)


def isbn13_from_isbn8(isbn8: str, prefix: str = "9784") -> str:
    """小学館のisbn8_cd(8桁: 出版社+書名+...)に9784を付けてチェックディジットを計算。
    isbn8_cdが9桁(チェックなし)の場合も末尾以外を使う。"""
    body = prefix + isbn8
    if len(body) == 13:
        body = body[:12]
    if len(body) != 12:
        raise ValueError(f"bad isbn8: {isbn8}")
    return body + isbn13_check(body)


def isbn13_to_isbn10(isbn13: str) -> str:
    if not re.fullmatch(r"978\d{10}", isbn13):
        raise ValueError(isbn13)
    core = isbn13[3:12]
    s = sum((10 - i) * int(c) for i, c in enumerate(core))
    chk = (11 - s % 11) % 11
    return core + ("X" if chk == 10 else str(chk))


def isbn10_to_isbn13(isbn10: str) -> str:
    core = "978" + isbn10[:9]
    return core + isbn13_check(core)


def valid_isbn13(s: str) -> bool:
    return bool(re.fullmatch(r"\d{13}", s)) and isbn13_check(s[:12]) == s[12]

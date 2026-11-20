#!/usr/bin/env python3
"""マンガ新刊ポチのアイコン・OGP画像を static/assets/ に書き出す。

pochi-branding の関数(icon_html・render_html・png_to_jpeg・make_ico・ogp_html)を
import して流用する。pochi-branding には何も書かない(中間ファイルは一時フォルダ)。
実行: python3 make_icons.py   (ヘッドレスChromeとネット接続(Googleフォント)が必要)
サイト側(build.py)はこの出力を docs/static/assets/ へコピーするだけで、画像はビルドのたびには作り直さない。
"""
import sys
import tempfile
from pathlib import Path

BRANDING = Path.home() / "Desktop/Claude/pochi-branding"
sys.path.insert(0, str(BRANDING))
from make_branding import icon_html, render_html, png_to_jpeg, make_ico  # noqa: E402
from ogp_html import ogp_html  # noqa: E402

# マンガ新刊ポチ専用色（濃い紫。漫画ポチの親戚色）。色の定義はここ1か所。
# static/style.css の --accent も同じ値にしてある（変えるときは両方）。
BRAND_COLOR = "#5E35B1"
TITLE = "マンガ新刊ポチ"
TAGLINE = "コミック新刊の発売日を、まとめてチェック"

OUT = Path(__file__).parent / "static/assets"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        render_html(icon_html(BRAND_COLOR, "large", 132), 132, 132, tmp / "logo.png", transparent=True)
        render_html(icon_html(BRAND_COLOR, "small", 96), 96, 96, tmp / "favicon.png", transparent=True)
        render_html(icon_html(BRAND_COLOR, "large", 180, square=True, transparent=False), 180, 180,
                    tmp / "apple-touch-icon.png")
        sizes = {}
        for s in (16, 32, 48):
            p = tmp / f"f{s}.png"
            render_html(icon_html(BRAND_COLOR, "small", s), s, s, p, transparent=True)
            sizes[s] = p
        for n in ("logo.png", "favicon.png", "apple-touch-icon.png"):
            (OUT / n).write_bytes((tmp / n).read_bytes())
        make_ico(sizes, OUT / "favicon.ico")
        render_html(ogp_html(TITLE, TAGLINE, BRAND_COLOR), 1200, 630, tmp / "ogp.png")
        png_to_jpeg(tmp / "ogp.png", OUT / "ogp.jpg")
    for p in sorted(OUT.iterdir()):
        print(p)


if __name__ == "__main__":
    main()

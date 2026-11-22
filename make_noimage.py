#!/usr/bin/env python3
"""「書影なし」の仮書影 static/noimage.png（280x400。表紙の 7:10 と同じ比率で2倍解像度）を作る。
マンガ新刊ポチの色 BRAND_COLOR の本の形。書名は入れない（出版社の表紙は使わない方針）。
実行: python3 make_noimage.py   (ヘッドレスChromeが必要。pochi-branding の render_html を流用、pochi-branding には書かない)
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Desktop/Claude/pochi-branding"))
from make_branding import render_html  # noqa: E402

BRAND_COLOR = "#5E35B1"  # make_icons.py と同じ値（変えるときは両方）
OUT = Path(__file__).parent / "static/noimage.png"

HTML = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:280px;height:400px;background:{BRAND_COLOR};position:relative;overflow:hidden;
font-family:-apple-system,"Helvetica Neue",Arial,sans-serif}}
.spine{{position:absolute;left:0;top:0;bottom:0;width:26px;background:rgba(0,0,0,.22)}}
.frame{{position:absolute;left:50px;right:24px;top:36px;bottom:36px;border:4px solid rgba(255,255,255,.85);border-radius:10px;
display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff}}
.t{{font-size:34px;font-weight:800;letter-spacing:3px;line-height:1.25;text-align:center}}
.bar{{width:60px;height:4px;background:rgba(255,255,255,.85);margin:16px 0}}
</style></head><body><div class="spine"></div>
<div class="frame"><div class="t">NO<br>IMAGE</div><div class="bar"></div></div></body></html>"""


def main():
    with tempfile.TemporaryDirectory() as t:
        render_html(HTML, 280, 400, Path(t) / "noimage.png")
        OUT.write_bytes((Path(t) / "noimage.png").read_bytes())
    print(OUT)


if __name__ == "__main__":
    main()

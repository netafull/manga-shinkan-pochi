#!/usr/bin/env python3
"""漫画ポチの作品名→catalogId の対応表を data/manga_pochi_titles.json に作る（読み取り専用）。
元: manga-rss-reader/scripts/wikidata/data/matches.csv（漫画ポチのカタログ題名）。
wikidataLinks.json に載っている catalogId は wikidata=true として別に数える。
作品ページURL: https://manga.netaful.jp/manga/{catalogId}（client/src/App.tsx のルート）。
同題が複数サイトにある場合は最初の catalogId を採用。"""
import csv, json, unicodedata
from pathlib import Path
SRC = Path.home() / "Desktop/Claude/manga-rss-reader"
out = {}
links = json.loads((SRC / "server/data/wikidataLinks.json").read_text(encoding="utf-8"))["links"]
n = lambda s: "".join(unicodedata.normalize("NFKC", s).lower().split())
with (SRC / "scripts/wikidata/data/matches.csv").open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        k = n(r["title"])
        if k and (k not in out or (r["catalogId"] in links and out[k] not in links)):
            out[k] = r["catalogId"]
Path(__file__).resolve().parent.parent.joinpath("data/manga_pochi_titles.json").write_text(
    json.dumps(out, ensure_ascii=False), encoding="utf-8")
print(len(out), "titles;", sum(1 for v in out.values() if v in links), "with wikidata")

#!/usr/bin/env python3
"""漫画ポチの題名→候補一覧 data/manga_pochi_candidates.json を作る（手元でだけ実行。ネットワークなし）。
元: manga-rss-reader の matches.csv と wikidataLinks.json（読み取りのみ）。
候補の採否（著者・出版社の裏取り）は build.py が build 時に pochi_verify.pick_candidate で行う。
同時に、今の作品ごとの判定を data/manga_pochi_verify_report.json に書く。"""
import csv, json, sys, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build, pochi_verify as pv

SRC = Path.home() / "Desktop/Claude/manga-rss-reader"
links = json.loads((SRC / "server/data/wikidataLinks.json").read_text(encoding="utf-8"))["links"]
cands = collections.defaultdict(list)
with (SRC / "scripts/wikidata/data/matches.csv").open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        authors = []
        for col in ("authors", "illustrators"):
            authors += [x for x in (r[col] or "").split("|") if x]
        authors += links.get(r["catalogId"], {}).get("authors") or []
        authors = list(dict.fromkeys(authors))
        c = {"catalogId": r["catalogId"], "site": r["site"], "authors": authors}
        if r["catalogId"] in links:
            c["wikidata"] = True
        cands[pv.norm_title(r["title"])].append(c)
(ROOT / "data/manga_pochi_candidates.json").write_text(
    json.dumps(cands, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")

books, pochi = build.load_all()
works = build.group_works(books, pochi)
report = []
for w in sorted(works.values(), key=lambda w: w["title"]):
    cs = cands.get(pv.norm_title(w["title"]))
    if not cs:
        continue
    pick, st, why, judged = pv.pick_candidate(w["author"], w["publisher"], cs)
    rep = {"title": w["title"], "author": w["author"], "publisher": w["publisher"], "status": st, "reason": why,
           "catalogId": pick["catalogId"] if pick else None,
           "candidates": [{"catalogId": j[2]["catalogId"], "site": j[2]["site"], "authors": j[2]["authors"],
                           "status": j[0]} for j in judged]}
    report.append(rep)
(ROOT / "data/manga_pochi_verify_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
print("titles:", len(cands), "works with candidates:", len(report),
      dict(collections.Counter(r["status"] for r in report)),
      "linked:", sum(1 for r in report if r["catalogId"]))

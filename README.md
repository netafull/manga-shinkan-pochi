# マンガ新刊ポチ（仮称・ローカル試作）

マンガの新刊を発売日順に並べるサイトの試作。ローカルのみ（リモート・push・デプロイ・DNSなし）。標準ライブラリのみ。

## 構成
- `isbnlib.py` ISBN13/10変換。小学館 `isbn8_cd` → ISBN13。
- `pubfetch.py` 出版社ページの取得（キャッシュ優先・間隔厳守・講談社ホストは拒否）。
- `parse_pub.py` 小学館(Inertia JSON)・秋田書店(Next.js RSC)・白泉社(HTML表)のパーサとタイトル解析（巻数・series_key・版表記）。
- `amazon.py` Creators API（ログ `data/api_log.jsonl`、応答キャッシュ `cache/api/`、245回で強制停止、429で即停止）。
- `scripts/build_backbone.py` 出版社3社 → `data/books.json`。
- `scripts/scan_kodansha.py` Amazon新着順検索で講談社コミックスを拾う → `data/kodansha_found.json`。
- `scripts/enrich.py` getItems(ISBN-10)で画像・価格・URLを補い `data/amazon_items.json` に集約、`data/books_kodansha.json` を作る。
- `scripts/make_pochi_titles.py` 漫画ポチの題名→catalogId 表 `data/manga_pochi_titles.json`（manga-rss-reader は読み取りのみ）。
- `build.py` → `docs/`（`/`, `/date/YYYY-MM-DD/`, `/month/YYYY-MM/`, `/publisher/<slug>/`, `/work/<slug>/`）。
- `test_build.py` unittest。

## 実行
```
source ~/.secrets/env                      # CREATORSAPI_* （値は表示・ログ・コミットしない）
python3 scripts/build_backbone.py --fetch  # 出版社。未キャッシュのページだけ取得（2回目以降は --fetch なしでキャッシュのみ）
python3 scripts/scan_kodansha.py           # 講談社スキャン（約50回のAPI）
python3 scripts/enrich.py                  # 不足分のgetItems
python3 build.py                           # docs/ 生成（SHINKAN_TODAY=YYYY-MM-DD で今日を上書き）
python3 -m unittest test_build
cd docs && python3 -m http.server 8765
```

## ルール
- kodansha.co.jp には一切アクセスしない（規約で自動収集禁止）。講談社の作品は「Amazon の商品情報より」と表示。
- 出版社ページは1URL1回、小学館は10秒、その他も3秒以上の間隔、UA `MangaShinkanPochi/0.1 (prototype; +https://www.netaful.jp/)`。生応答は `cache/`（gitignore）。
- Amazon Creators API は他の稼働中サイトと枠を共有。タスク全体で250回未満（245で強制停止）、同一リクエストは再送しない、`minSavingPercent` は送らない。
- 出版社から保存するのは書誌事実のみ（発売日・書名・巻数・著者・出版社・レーベル・ISBN・出典URL）。表紙・あらすじ・試し読みは使わない。画像・価格・リンクはAmazonのみ。
- 認証情報は `~/.secrets/env` から環境変数で読む。リポジトリに含めない。

## 未解決・既知の問題
- Kindle版の有無は getItems の応答に含まれず取得できていない（`relatedProducts` 等のリソース名は未検証）。
- 発売前の本はAmazon画像がプレースホルダー（幅<100pxは「No Image」扱い）。ISBN-10がAmazonに未登録の本（17件）は画像・リンクなし。
- NewestArrivals検索は1クエリ100件までで、未来日付から降順。講談社はレーベル名キーワードで分割して掘っているため取りこぼしがあり得る。年明け以降は特に薄い。
- 白泉社のISBNは詳細ページが必要で、今日〜30日先のみ取得。それ以外は仮ID(`haku:ID`)でAmazonリンクなし。
- 秋田書店は電子版を除外。月から年を推定（6月以下は翌年）。
- 愛蔵版・新装版・完全版などは別作品として扱う（series_key統一は未対応）。
- 漫画ポチ照合は題名の完全一致(NFKC・空白除去)のみ。同名別作品の取り違えが起こり得る。リンクは `https://manga.netaful.jp/manga/{catalogId}`。
- サイト名は仮。ロゴは仮のSVG。`noindex` 付き。GA4等は未設定。

# マンガ新刊ポチ

マンガ（コミック）の新刊を発売日順に並べるサイト。公開先は https://shinkan.netaful.jp/（GitHub Pages、`docs/` を配信）。標準ライブラリのみ（テスト・アイコン生成を除く）。

開発ルールは [AGENTS.md](AGENTS.md)（エージェント共通ルール＋このサイト固有の注意）。作業前に読むこと。

## 構成
- `common.py` 日付（日本時間。`SHINKAN_TODAY` で上書き）と JSON の書き出し。
- `isbnlib.py` ISBN13/10変換。小学館 `isbn8_cd` → ISBN13。
- `pubfetch.py` 出版社ページの取得（1URL1回・間隔厳守・正直なUA・講談社ホストは拒否）。
- `parse_pub.py` 小学館(Inertia JSON)・秋田書店(Next.js RSC)・白泉社(HTML表)のパーサとタイトル解析（巻数・series_key・版表記）。
- `amazon.py` Creators API クライアント。1日の上限 `DAILY_CAP`（200）、429で停止、`slim()` で保存項目をホワイトリスト化。
- `scripts/build_backbone.py` 出版社3社 → `data/books.json`（失敗したページの月は前回データを保持）。
- `scripts/scan_kodansha.py` Amazon新着順検索で講談社コミックスを拾う（講談社サイトにはアクセスしない）。
- `scripts/enrich.py` getItems(ISBN-10)で画像・価格・URLを補う／価格を更新する。`data/amazon_items.json` に集約。
- `scripts/update.py` 毎日の更新のエントリ（上の3つ＋ビルド）。
- `scripts/make_pochi_titles.py` 漫画ポチの題名→catalogId 表 `data/manga_pochi_titles.json`（manga-rss-reader は読み取りのみ。手元でだけ実行。通常の更新では触らない）。
- `build.py` → `docs/`（`/`, `/date/YYYY-MM-DD/`, `/month/YYYY-MM/`, `/publisher/<slug>/`, `/work/`, `/work/<slug>/`, `404.html`, `sitemap.xml`, `robots.txt`, `CNAME`）。
- `make_icons.py` ロゴ・favicon・apple-touch-icon・OGP を `static/assets/` に作る（pochi-branding の関数を流用。専用色 `BRAND_COLOR` = #5E35B1）。ヘッドレスChromeとネット接続（Googleフォント）が必要。画像は作り直さない限り `static/assets/` のものを `docs/` にコピーする。
- `test_build.py`（パーサ・サイト生成）、`test_pipeline.py`（上限・429・出版社の失敗・資格情報の扱い。すべてモックでネットワークなし）。

## データ（`data/`、コミットする）
| ファイル | 内容 |
|---|---|
| `books.json` | 出版社3社の書誌事実（発売日・書名・巻数・著者・出版社・レーベル・ISBN・出典URL） |
| `books_kodansha.json` | 講談社（Amazon新着スキャンの結果。蓄積する） |
| `amazon_items.json` | Amazon の応答から抜いた項目だけ（画像URL・価格・リンク・取得日 `updated`）。生応答は持たない |
| `api_usage.json` | 日付ごとのAmazon呼び出し回数（上限の判定に使う。直近30日） |
| `page_lastmod.json` | ページごとのHTMLハッシュと最終変更日（sitemap の lastmod 用） |
| `manga_pochi_titles.json` | 漫画ポチの題名→catalogId |

`cache/`（生HTML・生API応答）と `logs/`（呼び出しごとのログ）は gitignore。

## ローカルでの実行
```
python3 build.py                       # 今のデータから docs/ を作り直す（APIも出版社も叩かない）
GA4_ID=G-XXXXXXXXXX python3 build.py   # 計測タグ付き（GA4_ID が無ければタグは出ない）
SHINKAN_TODAY=2026-11-20 python3 build.py
python3 -m unittest test_build test_pipeline
cd docs && python3 -m http.server 8765
```
毎日の更新を手元で再現するときは（出版社へのアクセスとAmazonの枠を使うので、必要なときだけ）:
```
source ~/.secrets/env                  # CREATORSAPI_*（値は表示・ログ・コミットしない）
python3 scripts/update.py
```
認証情報が無ければ Amazon の段は飛ばして既存データでビルドする。

## 毎日の更新（GitHub Actions）
`.github/workflows/update.yml` は `workflow_dispatch` のみ。Cloud Scheduler のジョブ `shinkan-pochi-update`（毎日 5:50 JST）が起動する。時刻は 家電ポチ（毎時 :07）・電書ポチ（4時間ごと :37）と重ならないよう選んだ（Amazonの枠を共有）。`schedule:` は使わない。

`scripts/update.py` の流れ:
1. 出版社3社の一覧ページを各1回取得 → `books.json` を更新。1ページが失敗・0件・パース例外のときは、そのページが受け持つ月の前回データを残して警告を出す。
2. Amazon（`DAILY_CAP` と 429 に従う。段ごとの枠: 新規ISBN 80 / 講談社スキャン 70 / 価格更新 40）:
   新規ISBNの getItems → 講談社の新着スキャン → 期間内の本の価格更新（取得日が古い順）。
   上限・429・通信エラーが出たら、その実行では以後呼ばずに既存データでビルドする。講談社のスキャンが0件でも前回分は消さない。
3. `build.py` で `docs/` を作る。最後に `[update] ... amazon_calls=N ...` の1行を出力する。
4. ワークフローがテストを走らせ、`docs/` と `data/` に変更があればコミット・pushする。

### 必要な設定（値はここに書かない）
- リポジトリのシークレット: `CREATORSAPI_CREDENTIAL_ID` / `CREATORSAPI_CREDENTIAL_SECRET` / `CREATORSAPI_PARTNER_TAG`
- リポジトリの変数: `GA4_ID`（GA4の測定ID。未設定なら計測タグなし）
- GitHub Pages: `docs/` を配信、カスタムドメイン `shinkan.netaful.jp`（`docs/CNAME`）
- Cloud Scheduler: ジョブ `shinkan-pochi-update`（`workflow_dispatch` を呼ぶ）

## ルール（要点。詳細は AGENTS.md）
- kodansha.co.jp には一切アクセスしない（規約で自動収集禁止）。講談社の作品は「Amazon の商品情報より」と表示。
- 出版社ページは1日1回・各URL1回、小学館は10秒、その他は3秒以上の間隔、UA `MangaShinkanPochi/1.0 (+https://shinkan.netaful.jp/)`。
- 出版社から保存するのは書誌事実のみ。表紙・あらすじ・試し読みは使わない。画像・価格・リンクはAmazonのみ。
- Amazon の枠は家電ポチ・電書ポチと共有。`DAILY_CAP` はオーナーの確認なしに上げない。`minSavingPercent` は送らない。

## 既知の制約・未解決
- 作品一覧の五十音は先頭文字による簡易分類。読みの情報がないため、漢字ではじまる作品（約半数）は「漢字ではじまる作品」にまとめ、題名の文字コード順に並べている。「英数字」は別枠。形態素解析などの重い依存は入れていない。
- Kindle版の有無は getItems の応答に含まれず取得できていない。
- 発売前の本はAmazon画像がプレースホルダー（幅<100pxは「No Image」扱い）。ISBN-10がAmazonに未登録の本は画像・リンクなし。価格更新で画像が付くことがある。
- NewestArrivals検索は1クエリ100件までで、未来日付から降順。講談社はレーベル名キーワードで分割して掘っているため取りこぼしがあり得る。年明け以降は特に薄い。
- 白泉社のISBNは詳細ページが必要で、今日〜30日先の未取得分だけ取得（1日最大40ページ）。それ以外は仮ID(`haku:ID`)でAmazonリンクなし。分かったISBNは `books.json` に残して再取得しない。
- 秋田書店は電子版を除外。月から年を推定（今月以降は今年、それより前の月は来年）。
- 愛蔵版・新装版・完全版などは別作品として扱う（series_key統一は未対応）。
- 漫画ポチ照合は題名の完全一致(NFKC・空白除去)のみ。同名別作品の取り違えが起こり得る。リンクは `https://manga.netaful.jp/manga/{catalogId}`。
- 出版社データは過去分も残す（作品ページの履歴のため）。データ量は日々増えるので、将来古いものの整理が必要になる。
- sitemap の lastmod は「ページのHTMLが前回から変わった日」（`data/page_lastmod.json`）。トップページは毎日変わる。

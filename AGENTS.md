# 開発ルール（エージェント共通）

このリポジトリは、複数のAIエージェント（Claude Code／マル）と所有者（マサト）が触る。作業前に必ずこのファイルを読むこと。

## 同時作業の禁止
- 同じリポジトリを複数のエージェントが同時に編集しない。作業を始める前に、作業中ブランチや未マージのPRがないか確認する。
- 作業前に必ず最新の main を取り込む。

## ブランチとマージ
- 作業は必ずブランチで行う。main へ直接 push しない。
- マージとデプロイは所有者（マサト）の確認後。勝手にマージしない。
- 作業が終わったら、変更内容・検証結果・見送ったことを PR の説明かレポートファイル（Markdown）に残す。

## 変更の作法
- 依頼された範囲だけを変更する。ついでのリファクタリングや無関係な整形をしない。
- URL・canonical・広告まわり・外部APIの契約や課金まわりは、明示の依頼がない限り変更しない。
- 既存ページ・既存機能の挙動を変える変更は、変更前後で差分を確認して報告する。

## 報告
- 完了報告には「何を変えたか」「どう検証したか」「やらなかったこと・未確認のこと」を含める。
- 事実と推測を分けて書く。確認できていないことは未確認と明記する。

## このリポジトリ固有の注意
対象サイト：https://shinkan.netaful.jp/（マンガ新刊ポチ。コミック新刊の発売日を発売日順にまとめる）。

- **講談社のサイト（kodansha.co.jp）には絶対にアクセスしない。** 規約で自動収集が禁止されている。講談社の作品はAmazonの新着順検索（scripts/scan_kodansha.py）の結果だけから作り、「Amazon の商品情報より」と表示する。pubfetch.py は kodansha を含むホストを拒否する。この拒否を外さない。
- 出版社ページ（小学館・秋田書店・白泉社）の取得は礼儀正しく。一覧は1日1回、各URL1回だけ。小学館は10秒、その他は3秒以上の間隔（Crawl-delay）、正直なUA（`MangaShinkanPochi/1.0 (+https://shinkan.netaful.jp/)`）。UAを偽装しない・間隔を詰めない・取得頻度を上げない。
- 出版社から保存するのは書誌事実だけ（発売日・書名・巻数・著者・出版社・レーベル・ISBN・出典URL）。出版社の表紙画像・あらすじ・試し読みは保存も表示もしない。画像・価格・リンクはAmazonの商品情報のみ。生のAPI応答・生HTMLはコミットしない（cache/ は gitignore）。
- **Amazon Creators API の枠は家電ポチ・電書ポチと共有。** 1日の呼び出し上限は `amazon.py` の `DAILY_CAP`（既定200）。オーナーの確認なしに上げない。429が出たらその実行では以後呼ばない。ローカルでの確認でも、むやみにAPIを叩かない（テストはモックで書く）。`minSavingPercent` は送らない。
- 認証情報は環境変数 `CREATORSAPI_CREDENTIAL_ID` / `CREATORSAPI_CREDENTIAL_SECRET` / `CREATORSAPI_PARTNER_TAG` からだけ読む。値を表示・ログ・コミットしない。
- 更新は Cloud Scheduler のジョブ `shinkan-pochi-update` が毎日 5:50（JST）に `.github/workflows/update.yml` を `workflow_dispatch` で起動する。時刻は家電ポチ（毎時:07）・電書ポチ（4時間ごと:37）と重ならないように選んである。同じAmazon枠を共有するので、時刻や頻度を変えるときは先に確認する。`schedule:` は使わない。
- `docs/` は生成物。直接直さず `python3 build.py` で作り直す（`GA4_ID` を付けないと計測タグが消える）。`data/` の `books.json` / `books_kodansha.json` / `amazon_items.json` / `api_usage.json` / `page_lastmod.json` は更新スクリプトが書く状態なので、手で編集しない。
- ロゴ・OGP は `make_icons.py`（pochi-branding の関数を流用。専用色 `BRAND_COLOR`）で作る。pochi-branding 側のファイルは変更しない。

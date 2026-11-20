# フェーズ2: 漫画ポチ向け最新刊JSON（2026-11-20）

ブランチ: `claude/phase2-latest-sale`（コミット・push・デプロイは未実施）

## 変えたこと
- `build.py`: `docs/api/pochi-latest.json` を毎回書く。検証済み漫画ポチリンク（confirmed / publisher_consistent）のある作品だけ、漫画ポチの catalogId キーで `latest`（発売日が今日以前で最新）と `next`（今日より後で最も早い）を載せる。空白なしの1行JSON。今日は `build.today()`。今日発売の巻は `latest` 側。
- `update.yml` は `scripts/update.py` → `build.build()` を走らせるので、毎日作り直される。
- README に仕様を追記（CORSヘッダはPagesで付けられないため、利用側はサーバー側で取得）。
- テスト追加（`test_build.py` の `PochiLatestTest` と、ビルド後のファイル確認）。

## 結果
- 275作品（最新刊あり60・次の巻あり215・両方ありは0）。

## 検証
- `python3 -m unittest -q` 全件OK。`python3 build.py` 後に docs/ と page_lastmod.json は git checkout で戻し、未追跡の docs/api/ は削除。
- Amazon API・講談社サイト・update.py は未使用。

## 見送り: Kindleセール表示（Step B）
2026-11-20 に所有者が取り下げ。実装は取り除いた（ファイル・テスト・README・CSSとも残していない）。
- 理由: 電書ポチの公開 `data/sales.json` の `fetched_at` が 2026-07-30 のまま。更新ワークフローは `campaign_state.json` しかコミットしないため。
- 古いデータで照合しても、636作品のうち一致は約6作品。誤爆は見当たらなかったが効果が小さい。
- 補足: `book.netaful.jp/widget.json` は新しいが、著者・ASINがなく安全に照合できない。

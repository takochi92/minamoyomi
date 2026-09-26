# 艇ログ（ボートレース直前予想サイト）

BOAT RACE 公式サイトの出走表・直前情報（展示タイム、スタート展示、風向き、風速、波高）を 5 分おきに自動取得し、
レース場ごとのコース別成績と照らし合わせて参考買い目を掲載する公開サイトです。
**サーバー代 0 円**で動かせる構成です（GitHub Actions + Cloudflare Pages）。

```
GitHub Actions（5分おき）
  └ scraper/run.py  … 公式サイトから取得 → 予想 → site/data/*.json を更新
       └ Cloudflare Pages へ公開（site/ フォルダがそのままサイト）
閲覧者のブラウザ … site/data の JSON を読んで表示（1分ごとに自動更新）
```

## フォルダ構成

| パス | 役割 |
|---|---|
| `scraper/parse.py` | 公式サイトの HTML を読み取る（出走表・直前情報・結果・開催一覧） |
| `scraper/predict.py` | 予想本体。学習済みの `model.json` で1〜3着の確率を出し、3連単の買い目を選ぶ |
| `scraper/venues.json` | 24場のコース別1〜3着率・決まり手・水質・干満差（公式の直近3か月データ） |
| `scraper/run.py` | 定期実行の本体。締切2時間前に事前予想、展示後に直前予想、締切12分後に結果と的中判定 |
| `scraper/update_venues.py` | 場データを毎月取り直す |
| `scraper/history.py` | 公式の競走成績(K)・番組表(B)を毎朝取り込み（`history/` に約3年分）、直近1年のコース戦績を集計 |
| `scraper/model.py` | 特徴量の計算（学習と本番で共通）と集計クラス |
| `scraper/train_model.py` | 過去データで予想モデルを学習・検証（毎月自動）。`model.json` と検証結果 `model_report.json` を出力 |
| `scraper/odds.py` | 3連単オッズの取得・保存、オッズ×AIの合成確率と期待値買い目 |
| `scraper/odds_backfill.py` | 過去の確定オッズと直前情報（展示の進入など）を少しずつ集める |
| `scraper/ev_eval.py` | 期待値買いを過去データで交差検証し、合成の割合を `model.json` の `blend` に保存 |
| `scraper/coursestats.py` | レースページの「コース戦績」欄とコメント |
| `scraper/lzh.py` / `kfile.py` / `bfile.py` | 公式データファイル（.lzh）の展開と読み取り |
| `site/` | 公開するサイト（index.html / app.js / style.css / about.html / config.js） |
| `tools/build_real_preview.py` | 1日分の実データから確認用のバンドルを作る（開発用） |
| `.github/workflows/` | 自動実行（5分おき更新・月次の場データ更新・テスト） |

## 公開までの手順

### 1. GitHub にリポジトリを作る
1. GitHub アカウントを作成し、新しいリポジトリを **Public** で作成（Public なら Actions が無料で使い放題。Private だと月2,000分の無料枠を超えます）。
2. このフォルダの中身をすべてアップロード（`.github` フォルダも忘れずに）。

### 2. Cloudflare Pages を用意する
1. Cloudflare アカウントを作成 → Workers & Pages → Create → Pages → **Direct Upload** でプロジェクトを作成（名前例：`teilog`）。最初は `site` フォルダをドラッグ&ドロップでOK。
2. My Profile → API Tokens → Create Token →「Cloudflare Pages: Edit」権限のトークンを作成。
3. アカウントID（ダッシュボード右側に表示）を控える。

### 3. GitHub に設定を入れる
リポジトリの Settings → Secrets and variables → Actions で：

| 種類 | 名前 | 値 |
|---|---|---|
| Secret | `CLOUDFLARE_API_TOKEN` | 手順2で作ったトークン |
| Secret | `CLOUDFLARE_ACCOUNT_ID` | アカウントID |
| Variable | `CF_PROJECT_NAME` | `teilog`（手順2の名前） |
| Variable | `SITE_URL` | 公開URL（例 `https://teilog.pages.dev`） |

Settings → Actions → General → Workflow permissions を **Read and write** にします。

### 4. 動かす
Actions タブ → `update-races` → Run workflow で手動実行。成功すれば数分でサイトに当日のデータが出ます。
以降は JST 7:00〜22:00 に 5 分おきで自動更新されます（GitHub 側の混雑で数分遅れることがあります）。

### 5. 過去データについて
`history/` に 2023/9〜2026/9 の3年分（約16.5万レース）、`scraper/course_stats.json.gz` と `scraper/model.json` は作成済みです。
以降は毎朝6:15に前日分を追加（`update-course-stats`）、毎月2日に学習し直し（`train-model`）が自動で動きます。

### 6. 独自ドメイン・広告
- Cloudflare Pages の Custom domains で独自ドメインを設定（アフィリエイト審査・AdSense 審査には独自ドメインが有利）。
- 広告・アフィリエイトのタグは `site/config.js` に貼るだけで、トップとレースページの広告枠に表示されます。
- `site/about_body.html` の運営者名・お問い合わせ先を必ず埋めてください（多くの ASP・AdSense の審査項目です）。

### 7. Google 検索に出す
- GitHub の Settings → Variables に `SITE_URL`（例 `https://teilog.com`）を登録。canonical・サイトマップのURLになります。
- 公開後、[Google Search Console](https://search.google.com/search-console) にサイトを登録し、`https://あなたのドメイン/sitemap.xml` を送信。
- ページは `python -m scraper.sitegen` が5分ごとに作り直します（コミットはせず、公開時に生成）。
  - トップ / レース（`race/日付/場-R.html`、30日分）/ 24場（`venue/`）/ 選手約1,600人（`racer/`）/ 狙い目レーサー（`targets.html`）
  - 合成オッズ計算（`tools/composite.html`）/ 初心者ガイド（`guide/`）/ 的中実績・予想の根拠 / `sitemap.xml`・`robots.txt`
- 選手名簿（`scraper/racers.json`）は公式の期別成績から毎月4日に更新（`update-racers`）。

### 8. ライブオッズ（試作・1分ごと）
レースページに「ライブオッズ」欄が出ます（推奨買い目の合成オッズの今、単勝と3連単人気順の5分前比、全120通り）。
公式から取るのは **各場の締切30分前〜締切のレースだけ**、1分ごと（3連単＋単勝で1分に20回前後、0.3秒間隔）。

1. Cloudflare のダッシュボード → Workers & Pages → KV → 「LIVE」という名前で作成し、ID を `worker/wrangler.toml` の `id` に貼る。
2. GitHub の Variables に `LIVE_ENABLED` = `true` を追加 → Actions の `deploy-live-worker` を手動実行。
3. 出てきた `https://teilog-live.<あなた>.workers.dev/health` を開き、数分後に `updated` が入り `errors` が空なら公式から取れています
   （エラーが続く＝公式にはじかれている。その場合はすぐ止めて相談を）。
4. `site/config.js` の `liveApi` に Worker のURLを入れると、レースページにライブ欄が出ます。

注意：KV の無料枠は書き込み1日1,000回。1分1回なので1日約900回で収まりますが、余裕がないので安定運用は Workers Paid（月5ドル）推奨。
公式データを1分ごとに再表示するため、本格公開の前に公式へ利用の可否を問い合わせてください。

### 9. オリジナル展示データ（一周・まわり足・直線）
各レース場が独自に計測し、公式映像サービス BOATCAST（一般財団法人BOATRACE振興会）が公開しているデータ。
展示が終わったレースで `race.boatcast.jp/txt/{場}/bc_oriten_{日付}_{場}_{R}.txt` を1回だけ取得し、レースページの「展示の数字」に順位つきで表示します。
BOATCAST のサイトポリシーは「私的使用の範囲を超える無断使用（複製・頒布）禁止」「大量アクセス禁止」です。公開前に公式へ問い合わせる際、**BOATCASTのオリジナル展示データの掲載可否もあわせて確認**してください。許可が出るまでは `scraper/run.py` の取得を止める運用も可能です。

## ローカルで画面を確認する

```bash
pip install -r requirements.txt
python -m scraper.run                  # 公式サイトから当日分を取得して site/data を作る
python -m scraper.sitegen              # 静的ページを生成
cd site && python -m http.server 8000  # http://localhost:8000 を開く
```

実データで試す場合は `python -m scraper.run`（公式サイトにアクセスします）。
テストは `pip install pytest && python -m pytest -q tests`。

## 期待値買い（このサイトの主役）

AIが全レースの着順を当てにいっても、人気サイドはオッズが安く、長く続けると必ず負けます（検証：回収率約80%）。
そこで締切7分前に3連単オッズを取り、**オッズが示す確率にAIの予想を少しだけ混ぜた確率 × オッズ ≧ 1.0**
（200倍以下）になる目があるレースだけを「勝負レース」として出し、それ以外は「見送り推奨」にします。

- 混ぜる割合（例：市場0.9・AI0.2）は `scraper/ev_eval.py` が過去の確定オッズで決めます（偶数日で決めて奇数日で検証、その逆も）。
- 検証の95%区間の下限が100%を超えるまでは、サイト上で「検証中」と表示します。
- 検証では「締切前に分かる情報」だけを使います（進入は展示の並び。実際の進入は使わない）。
- 過去1年分の確定オッズ・直前情報は `odds-backfill` が毎晩少しずつ集め、そのたびに再検証します。

## 検証中の仮説：B級のコース巧者（単勝で追跡）

B級で展示の進入が3・4コース、かつそのコースの1着率が全国平均の約1.5倍以上の艇（`odds.SPECIALIST_RULE`）。
過去9,083レースでは、4コースで単勝回収率141%・3コースで85%（どちらも95%区間は100%をまたぐ＝まだ偶然と区別できない）。
逆に2・6コースの「巧者」は買われすぎで、単勝回収率43%・24%。
本番では該当艇に「注目」を付け、締切前の単勝オッズと結果を記録して回収率を公開していきます。

## 予想ロジックの概要（すべてデータで学習）

各艇の特徴量（場のコース別1着率、選手のコース別成績、インの負け方×攻め手、全国・当地勝率、級別、
モーター・ボート、展示タイム、平均ST、F持ち、風速・波高）から、1着・2着・3着それぞれの
条件付きロジットで確率を出し、3連単120通りの確率で買い目を選びます。係数は手で決めていません。

検証（学習に使っていない2025/9/25〜2026/9/24の54,108レース）:

| | 結果 |
|---|---|
| 本命の1着的中率 | 57.0%（コースだけで予想すると55.4%） |
| 3連単 上位8点 | 的中 44.5%・回収率 80.7% |
| 3連単 上位1点 | 的中 9.5%・回収率 82.3% |

3連単の払戻率は75%なので、でたらめに買う場合の回収率は約75%。このモデルはそれを上回るが100%には届かない。
黒字を狙うにはオッズを取り込み、モデル確率×オッズ＞1 の買い目だけに絞る仕組みが次の課題。

仮説「捲られやすいイン×捲りの多い攻め手」は実データで強く確認できた（3コースの捲り勝ち率 1.8%→10.7%）。
ただし勝率やコース別成績と重なる部分が大きく、モデルへの上乗せ効果は小さい。詳細はサイトの「予想の根拠」ページ。

## 注意（運用前に必ず確認）

- **公式サイトの利用条件**：BOAT RACE 公式のサイトポリシーでは、コンテンツの無断転載・営利目的での利用が制限されています。
  レース結果や展示タイムなどの数値そのものは事実情報ですが、商用サイトでの大量取得・掲載にはリスクがあります。
  本格運用の前に、公式への問い合わせや専門家への相談をおすすめします。取得間隔は 1 秒以上空け、
  必要なページだけ取るように作ってあります（1日あたり 600 リクエスト前後）。
- **ボートレース日和のデータは使っていません**。日和の利用規約は事前許可のないスクレイピング・再構築・商業利用を禁止しています。
  代わりに、日和のコース戦績の元になっている公式の競走成績データ（公式サイトのデータダウンロードで公開されているもの）から同じ種類の統計を自前で集計しています。
- 風向きの変換は「公式の水面図でスタンドが下、1マークが右」を前提にしています。万一逆だと感じたら
  `predict.py` の `wind_info` の `tail` の符号を反転してください。
- 公式サイトの HTML が変わると取得が止まります。Actions が失敗したら `tests/fixtures.py` を最新 HTML に合わせて修正します。
- 20歳未満の購入禁止・のめり込み注意の表記は削除しないでください。

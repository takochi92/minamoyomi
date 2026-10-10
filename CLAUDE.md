# 艇ろぐ（teilog）— Claude 向けの説明書

ボートレース（競艇）予想サイト。サイト：https://teilog.pages.dev（Cloudflare Pages）
リポジトリ：takochi92/minamoyomi（静的サイト。GitHub Actions で数分ごとに更新）
持ち主は「たこ」さん。広島の人で、説明はやさしい日本語・短めが好み。

## たこさんとの約束（必ず守る）
- 日和競艇のデータ・ページは使わない（規約）。ボートフロンティアなど他サイトの数字も使わない（アイデアだけ参考にする）
- Claude はアカウント作成・パスワード・トークン・支払いの入力をしない。トークンをチャットに貼らない
- 「20歳未満は購入不可」「のめり込み注意」の表示は消さない。「必ず儲かる」とは書かない
- まとめファイル（zip）は「まとめて」「フォルダ作って」と言われたときだけ作る
- 機能を作ったら、X 用のツイート文と画像（1200×675）をセットで出す。出したツイートは Atelier に入れる（下の「投稿原稿（Atelier）」）
- 説明はやさしい日本語で短く。偶数日・奇数日ではなく「前半・後半」と言う

## しくみ
- scraper/run.py：取得・判定・集計（ワークフロー update から）
- scraper/predict.py：AI予想・買い目。`PRED_VERSION` を上げると締切前の予想を作り直す
- scraper/sitegen.py：全ページ生成（Site.build）
- scraper/model.py：集計 Stats と特徴量／train_model.py：学習
- scraper/history.py：公式Kファイルの過去データ（約5年）／motor.py：モーター（入れ替え日を自動判定）
- scraper/fan.py：公式の期別成績 → racers.json（養成期 ki・女子 lady は値を確かめてから入れる）
- fstart.py、windmap.py（公式の風向き矢印→方角を場ごとに対応）
- site/：style.css、app.js、clock.js、note.js（マイノート・お気に入り。localStorage）、search.js（選手・モーター検索）、live.js、pick.js
- ワークフロー：update、update-course-stats（history.yml。days を指定）、update-racers、train、test ほか

## 作業のしかた
- テスト：`pip install -r requirements.txt pytest` → `python -m pytest -q tests`
- 公式サイト（boatrace.jp）には、Claude の作業場所からはつながらないことがある。そのときはテスト用データ（tests/fixtures.py）で確かめる
- 画面の確認：tests/test_sitegen.py の `_site()` でページを作り、Playwright でスクショを撮る
- 変更したら push する前にテストを全部通す。ブランチ・PR の運用はたこさんに合わせる

## 投稿原稿（Atelier）
- 司令塔（claude-hub）はもう使わない（2026-10-10 で更新終了）。claude-hub に記録しない。
- SNS の原稿は、たこさんの下書き置き場 Atelier の「自動作成された投稿」に入れる。艇ろぐは **X のみ**（project: teirogu）。
- 毎朝 8:13 に `.github/workflows/daily-x.yml` が `tools/make_daily_x.py` で原稿を作り、Atelier へ送る（Secrets の ATELIER_* 3つ）。
- 送る形：`{"project":"teirogu","channel":"X","date":"YYYY-MM-DD","slot":"morning","text":"…"}`。同じ日・媒体・slot は上書き。機能紹介のツイートは slot を `feature` などにする。

## いまの状態・保留
HANDOFF.md を参照（最新の状態・入れたもの・検討中のこと）。

# boatcast — BOATCAST 展示リプレイの再生・フレーム取得・記録ツール

自宅サーバー **homesv**（Ubuntu 24.04.5 / Chrome 156 / Node v22 / Asia/Tokyo）で実行する、コード一式です。
展示リプレイを Chrome で**通常再生**し、指定した秒のフレームを **PNG で保存**し、結果を **manifest.json に記録**します。

- 対象は「再生・フレーム取得・記録」まで。**動画ファイルそのもののダウンロード・再配布はしません**。
- このコードはクラウド上で作成・テストしました（homesv には接続していません）。**homesv 実機での確認は未実施**で、
  下の「[未検証項目](#未検証項目homesv-実機でしか確認できない)」が残っています。
- 外部の npm 依存はありません（Node v22 の標準機能 `fetch` / `WebSocket` / `node:test` だけ）。

## ファイル構成

| ファイル | 役割 |
|---|---|
| `capture.mjs` | **本体**。Chrome 起動 → 再生 → フレーム PNG 保存 → manifest.json 記録 → 自分の Chrome だけ終了 |
| `verify.mjs` | 自己点検モード。7項目を `PASS` / `FAIL` で1行ずつ出す |
| `player-url.mjs` | 日付・場・レース番号からプレイヤーURLを組み立てる（検証済みは平和島の展示だけ） |
| `cdp.mjs` | CDP ドライバ（`/json/list` → WebSocket。`Runtime.evaluate` / `Page.navigate` / `Page.captureScreenshot` / `Input.dispatchMouseEvent`） |
| `chrome.mjs` | Chrome の起動・終了（必須フラグ、ポート使用中の検出、古いロックの掃除、自分の PID だけ終了） |
| `player.mjs` | プレイヤーページの操作（video 待ち、再生確認、シーク＆撮影、ネットワーク失敗の収集） |
| `failures.mjs` | 失敗の分類（`decode` / `geo` / `player-load` / `cdp`）と、推定原因・対処の文言 |
| `redact.mjs` | **伏せ字処理の共通関数**。URL はドメイン＋パスまで、クエリは必ず落とす |
| `args.mjs` | 引数・環境変数の解釈と既定値 |
| `util.mjs` | 出力先（既存を壊さない命名）、時刻、PNG サイズ |
| `test/*.test.mjs` | サーバー不要のテスト（`node --test`）。`test/e2e-local.smoke.mjs` は Chrome と ffmpeg を使う通しテスト |

## homesv への配置

デスクトップの PowerShell から（鍵は接続に使うだけ。中身を表示・コピーしないこと）：

```powershell
scp -P 2222 -i $env:USERPROFILE\.ssh\id_ed25519_homesv -r tools\boatcast work@100.102.247.93:/home/work/boatcast-check/claude-code/
```

- 送り先は `/home/work/boatcast-check/claude-code/boatcast/` になります（成果物の置き場 `claude-code/` の下）。
- 共有スクリプト（`cdp.mjs` / `video.mjs` / `cdpw.mjs` など）は読み取り専用で、ここのファイルとは別物です。上書きしないこと。
- ポートが 9454 以外のときは `--port` か `BOATCAST_PORT` で変えます（9447 と 9453 は他用途。`args.mjs` が拒否します）。
- サーバー設定・パッケージ・サービスには手を入れません（Chrome と Node v22 があれば動きます）。

最初に接続を確認します。

```bash
hostname            # homesv であること
id                  # uid=1001(work) であること
ls /home/work/boatcast-check
```

## 実行手順

### 1. 自己点検（まずこれ）

```bash
cd /home/work/boatcast-check/claude-code/boatcast
node verify.mjs --date 20261112 --race 12
```

```
PASS  1 Chrome のバージョン  Google Chrome ...
PASS  2 デバッグポートの空き  9454 は空き
PASS  3 Chrome 起動とデバッグ接続  PID=...
PASS  4 プレイヤー読込（video 要素）  854x480
PASS  5 duration > 0  348s
PASS  6 5秒間で currentTime が 3秒以上進む  ...
PASS  7 エラーなし  ...
RESULT: PASS (7/7)
```

終了コードは PASS=0 / FAIL=1 / 引数エラー=2。

### 2. フレーム取得

```bash
# 既定の秒 [10, 60, 120, 180, 200, 240, 280, 320]
node capture.mjs --date 20261112 --race 12

# 複数レース・秒を指定
node capture.mjs --date 20261112 --races 11,12 --seconds 10,60,120

# 計画だけ見る（Chrome は起動しない）
node capture.mjs --date 20261112 --race 12 --dry-run
```

主な引数（`node capture.mjs --help` で全部）：

| 引数 | 意味 | 既定 |
|---|---|---|
| `--date` | YYYYMMDD（`today` は日本時間の今日） | 必須 |
| `--race` / `--races` | レース番号 1〜12（複数可） | 必須 |
| `--seconds` | 取得する秒のカンマ区切り。duration を超える分は末尾に切り詰め | `10,60,120,180,200,240,280,320` |
| `--venue` | 場コード・場名 | `04`（平和島。検証済みはこれだけ） |
| `--port` | デバッグポート（`BOATCAST_PORT`） | `9454` |
| `--profile` | Chrome プロファイル（`BOATCAST_PROFILE`） | `/home/work/boatcast-check/profile-claude-code` |
| `--out` | 出力の親フォルダ（`BOATCAST_OUT`） | `/home/work/boatcast-check/claude-code/captures` |
| `--mode` | `seek`=一時停止してシーク / `play`=再生したまま撮る | `seek` |
| `--attach` | すでに起動中の Chrome（`--port`）に繋ぐ。起動も終了もしない | なし |
| `--video-timeout` | video と duration を待つ秒数 | 45 |
| `--pad-race` | 1桁のレース番号を `01` の形にする（未検証。1〜9R が開けないときの切り分け用） | なし |
| `--chrome` | Chrome の実行ファイル（`BOATCAST_CHROME`） | `google-chrome-stable` → `google-chrome` → `chromium` |

`BOATCAST_CHROME_ARGS` で Chrome に引数を足せます（必須フラグは常に付きます）。

### Chrome を手で起動して繋ぐ場合（`--attach`）

```bash
google-chrome --headless=new --disable-gpu --disable-accelerated-video-decode \
  --autoplay-policy=no-user-gesture-required \
  --user-data-dir=/home/work/boatcast-check/profile-claude-code \
  --remote-debugging-port=9454 --remote-debugging-address=127.0.0.1 \
  --no-first-run --window-size=1280,900 about:blank &
echo $!        # この PID を控える。終了は kill <その PID> だけ
node capture.mjs --attach --date 20261112 --race 12
```

- `--disable-gpu --disable-accelerated-video-decode` は**必須**です（既定設定だと映像が `PIPELINE_ERROR_DECODE` で再生できない）。
- 起動前に 9454 が空いているか確認します。使われていたら**落とさず**、ポートを変えるか作業を止めて報告します。
- `pkill` の広いパターンは使いません（自分の SSH セッションごと落ちる事故が起きる）。終了は自分が起動した PID だけ。
- `SingletonLock` が残った場合だけ、**自分のプロファイル内**のものを削除してよい（`capture.mjs` は持ち主のプロセスがいないロックだけ自動で消します）。

## 出力の見方

```
captures/20261112-heiwajima-12/
  f_0010s.png … f_0320s.png     フレーム（ファイル名の数字は指定秒。小数は 12.5 → f_0012p5s.png）
  manifest.json                 記録
```

- 同じレースをもう一度実行しても**既存を壊しません**（`...-12-2`、`...-12-3` と増える。ファイルも上書きしない）。
- 画像は**ブラウザ画面全体**（1280 幅のビューポート）です。映像は 854×480 で左上に表示されます（プレイヤー側のレイアウトに依存）。

`manifest.json` の主な項目：

| 項目 | 内容 |
|---|---|
| `status` | `ok` / `partial`（シーク位置がずれたフレームあり）/ `failed` |
| `date` `venue` `race` | 日付・場（jo / slug / 名前）・レース番号 |
| `playerUrl` | **ドメイン＋パスまで**（クエリは載せない） |
| `video` | `duration`・`width`・`height` |
| `playback` | `progressed`（currentTime が進んだか）、`samples`（2回のサンプリング値）、`clicked`（中央クリックを使ったか） |
| `frames[]` | `requestedSec` / `targetSec` / `clamped` / `file` / `actualCurrentTime` / `seekOk` / `paused` / `error` |
| `networkErrors` | HTTP 400 以上・読み込み失敗（**ホストとパスだけ**） |
| `failure` | 失敗時の `stage`（段階）・`cause`（推定原因）・`hint`（対処） |

## 失敗したとき（段階と推定原因）

| 段階 | 表示される例 | 推定原因と対処 |
|---|---|---|
| `decode` | `video.error ... PIPELINE_ERROR_DECODE` | **起動フラグ不足**の可能性。`--disable-gpu --disable-accelerated-video-decode` が付いているか。`--attach` / `--chrome` を使っているならその Chrome の起動フラグを確認 |
| `geo` | 配信の取得が 403／視聴不可の表示 | **実行環境のIPが日本国内でない**可能性（海外／データセンターIPは地域制限で 403）。homesv の家庭回線で実行する |
| `player-load` | video 要素が見つからない／duration が NaN | **レース未開催・リプレイ未公開**の可能性。日付・レース番号・場を見直し、時間をおいて再試行 |
| `cdp` | 対象ページが取れない／ポートが使用中 | `--port 9455` など**空いているポートに変えて**再試行。使用中の Chrome は落とさない |

## 伏せ字処理

配信まわりの URL にはセッショントークンが含まれることがあるため、**すべてのログ・manifest・エラーメッセージ**を `redact.mjs` に通します。

- URL は `スキーム＋ドメイン＋パス` まで。クエリ・ハッシュ・認証情報は落とす
- `Cookie` / `Authorization` / `token=` などの値も `[REDACTED]` にする
- ネットワーク失敗は、最初から**ホストとパスだけ**を保持する（クエリを持たない）
- 報告にも、ドメインとパスまでだけを書く（クエリ・Cookie・認証情報は書かない）

## テスト

```bash
# サーバー不要（URL組み立て・伏せ字・引数・失敗の分類・出力先・ロック処理・dry-run）
node --test 'tools/boatcast/test/*.test.mjs'

# 通しテスト（Chrome と ffmpeg が必要。テスト用の動画をローカルで配信し、実際の配信には触れない）
node tools/boatcast/test/e2e-local.smoke.mjs
```

## 未検証項目（homesv 実機でしか確認できない）

- 平和島 12R 展示（2026-11-12）以外のレース・日付で URL が開けるか
- **1桁のレース番号**（1〜9R）の書き方（`raceNumber=1` か `01` か）。既定は `1`、`--pad-race` で `01`
- 平和島以外の場の `stadium` 表記（`player-url.mjs` の `STADIUMS` は空欄 TODO）
- レース本編リプレイの `raceType` の値（未定義 TODO）
- `bitrate=low`（854×480）以外の画質
- 展示リプレイが**公開される時刻**（レース前なのか後なのか）
- H.264 の再生（クラウドでのテストは VP9。実機での通常再生は別途確認済み）
- `--mode seek`（一時停止してシーク）で、実際の配信（HLS/MSE と思われる）のフレームが正しく描画されること。ずれたら `--mode play` を試す
- プレイヤーの再生開始に**中央クリックが必要か**（必要なら自動でクリックする。`playback.clicked` に記録）
- 「視聴は許可されていません」系の**実際の文言**（`failures.mjs` の `GEO_TEXT_RE` は当て推量）
- 画像の中のプレイヤー UI（操作バー等）の写り込み
- Chrome 156 での挙動（クラウドのテストは Chrome 153）

## 既知の制約

- 場ページ（`race.boatcast.jp/?jo=04`）経由だとプレイヤーは別ドメインの iframe になり、iframe 側ではスクリーンショットが撮れません。**単体プレイヤーURLを直接開く**方式が正です。
- Chrome は同時に 1 つだけ起動します（homesv は本番機で負荷が高め）。重い並列処理はしません。
- 日本国内の家庭回線以外（クラウド・海外）では 403 になります。クラウド上では実行しないでください。

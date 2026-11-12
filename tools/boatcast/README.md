# boatcast — BOATCAST 展示リプレイの再生・フレーム取得・記録ツール

自宅サーバー **homesv**（Ubuntu 24.04.5 / Chrome 156 / Node v22 / Asia/Tokyo）で実行する、コード一式です。
展示リプレイを Chrome で**通常再生**し、指定した秒のフレームを **PNG で保存**し、
「どのフレームを撮ったか」まで **manifest.json に記録**します。

- 対象は「再生・フレーム取得・記録」まで。**動画ファイルそのもののダウンロード・再配布はしません**。
- 外部の npm 依存はありません（Node v22 の標準機能 `fetch` / `WebSocket` / `node:test` だけ）。

## 確認の出どころ（混ぜない）

| 出どころ | 内容 |
|---|---|
| **PR 版の実機確認**（homesv・work ユーザー・Chrome 156・Node 22、版 `e041f13`） | ユニットテスト 45/45、verify 7/7。2026-11-12 平和島の **12R と 1R** で、通常再生と PNG 保存に成功。1R は `raceNumber=1` で開けた。12R で 248.167 秒と 248.197 秒を指定したところ、PNG は同じ SHA-256（別セッションの確認で、どちらも表示フレームの mediaTime=248.166667 秒＝同じコマ）→ 今回の修正の発端 |
| **別の検証ツールの実測** | ゼロ埋めしたレース番号で、**24場・288本の再生開始**を確認済み。ただし場コード／stadium の対応表は、この PR の作成時点で受け取っていないため、`player-url.mjs` の `STADIUMS`（平和島以外）には**反映していない** |
| **クラウドでの確認**（このコンテナ・Chrome 153・VP9 のテスト動画） | 下の「テスト」。実際の配信には接続していない |

## ファイル構成

| ファイル | 役割 |
|---|---|
| `capture.mjs` | **本体**。Chrome 起動 → 再生 → フレーム確認 → PNG 保存 → manifest.json 記録 → 自分の Chrome だけ終了 |
| `verify.mjs` | 自己点検。9項目を `PASS` / `FAIL` で1行ずつ出す |
| `report.mjs` | manifest.json を表にして、計測に使える画像・同じコマの重複・要確認を出す（実機確認用。ブラウザ不要） |
| `frames.mjs` | 「撮った画像が、どのフレームか」の判定と、同じコマのまとめ（純粋なロジック） |
| `player.mjs` | プレイヤー操作：video 待ち、再生確認、**表示フレーム時刻の監視（requestVideoFrameCallback）**、シーク＆撮影 |
| `player-url.mjs` | URL 組み立て（検証済みは平和島の展示だけ。確認の出どころ `evidence` を持つ） |
| `cdp.mjs` | CDP ドライバ（`/json/list` → WebSocket。`Runtime.evaluate` / `Page.navigate` / `Page.captureScreenshot` / `Input.dispatchMouseEvent`） |
| `chrome.mjs` | Chrome の起動・終了（必須フラグ、ポート使用中の検出、古いロックの掃除、自分の PID だけ終了） |
| `failures.mjs` | 失敗の分類（`decode` / `forbidden` / `player-load` / `cdp`）と、推定原因・対処の文言 |
| `redact.mjs` | **伏せ字処理の共通関数**。URL はドメイン＋パスまで、クエリは必ず落とす |
| `args.mjs` / `util.mjs` / `package.json` | 引数・環境変数、出力先・時刻、実行コマンド一覧 |
| `test/*.test.mjs` | サーバー不要のテスト（`node --test`） |
| `test/e2e-local.smoke.mjs` | Chrome と ffmpeg を使うローカルの通しテスト（実配信には触れない） |

## homesv への配置

デスクトップの PowerShell から（鍵は接続に使うだけ。中身を表示・コピーしないこと）：

```powershell
scp -P 2222 -i $env:USERPROFILE\.ssh\id_ed25519_homesv -r tools\boatcast work@100.102.247.93:/home/work/boatcast-check/claude-code/
```

- 送り先は `/home/work/boatcast-check/claude-code/boatcast/`（成果物の置き場 `claude-code/` の下）。
- 共有スクリプト（`cdp.mjs` / `video.mjs` / `cdpw.mjs` など）は読み取り専用で、ここのファイルとは別物です。上書きしないこと。
- ポートが 9454 以外のときは `--port` か `BOATCAST_PORT` で変えます（9447 と 9453 は他用途。`args.mjs` が拒否します）。
- サーバー設定・パッケージ・サービスには手を入れません。

最初に接続を確認します。

```bash
hostname            # homesv であること
id                  # uid=1001(work) であること
ls /home/work/boatcast-check
```

## 撮った画像は、どのフレームか（3つの時刻を混ぜない）

プレイヤーが「指定秒にシークした」ことと、「その秒のコマが画面に出た」ことは別です。
動画のコマは一定の間隔（例：約 1/30 秒）なので、近い2つの秒を指定すると、**同じコマが表示される**のは正常です。
そのため manifest には、次の3つを**別々に**記録します。

| 項目 | 意味 | 取り方 |
|---|---|---|
| `requestedSec` | 指定秒（頼まれた秒。末尾を超える分は `targetSec` に切り詰め） | 引数 |
| `playerPosition` | プレイヤーの再生位置（`video.currentTime`）。`afterSeek` / `beforeShot` / `afterShot` | 読み取り |
| `frame.mediaTime` | **実際に表示されたフレームの時刻**。あわせて `presentedFrames` など | `requestVideoFrameCallback` の metadata |

`seek` モード（既定）の手順：

1. **シークの前に** `requestVideoFrameCallback` を登録する（ページに残して、表示されたフレームごとに記録）
2. 一時停止 → シーク → `seeked` を待つ → **新しいフレームの表示通知**を待つ → 通知が落ち着くのを待つ
   - 同じコマの上へのシークでは、新しい通知が出ないことがある。その場合は一度別の位置（±2秒）へ動かしてから戻す（`nudged: true`）
3. 撮影の**前後**で、最後に表示されたフレームが変わっていないこと（`stable`）と、再生位置が動いていないことを確認してから保存する
   - 変わっていたら、1回だけやり直す。それでも変わるなら**計測可にしない**

### 計測に使える画像か（`measurable`）

次のどれかに当たる画像は `measurable: false`（画像は保存するが、計測には使わない）。理由は `notMeasurableReasons`：

| 理由 | 意味 |
|---|---|
| `frame-time-unavailable` | 表示フレームの時刻（mediaTime）を取得できない（`requestVideoFrameCallback` が使えない、通知が来ない など） |
| `seek-not-completed` | `seeked` を確認できない |
| `frame-changed-during-capture` | 撮影の前後で表示フレームが変わった＝**別のコマを撮った可能性** |
| `frame-time-off-target` | 表示フレームの時刻が、指定秒から離れすぎている（既定：0.5 秒前〜0.1 秒後を許容。`--frame-tolerance` で前側を変更） |
| `play-frame-range-only` | `play` モードで、撮影中にフレームが進んだ（下記） |

### 同じコマの扱い

**同じ映像で `mediaTime` が同じ画像は、計測上は同じコマ**です。指定秒や再生位置が違っても、独立した計測値としては1つしか数えません。

- 最初の画像だけ `independentMeasurement: true`。同じコマの2枚目以降は `duplicateOf: <最初のファイル名>`、同じ `frameId`
- `measurement.duplicates` に、同じコマのファイル・指定秒・画像が同一か（`identicalImages`）を残す
- 画像の内容が違っても同じコマとして扱う（シークバーなど、画面の部品が再生位置で変わるだけのことがあるため）。同じコマかどうかは **mediaTime で決める**
- 逆に「画像のバイト列は同じなのに mediaTime が違う」ものは、古い画面を撮った疑いがあるので `measurement.anomalies` に出し、`status` を `partial` にする

### `--mode play`（再生したまま撮る）

`play` モードで確認できるのは、**撮影の前後で最後に表示されたフレームが同じだったとき**だけです。
その場合は「画像はそのフレーム」とみなして `measurable: true`。撮影中にフレームが進んだときは、画像に対応するフレームを1つに決められないので
`measurable: false`（`play-frame-range-only`）とし、`mediaTimeRange`（撮影前〜後の mediaTime と、撮影中に進んだフレーム数）だけを記録します。
フレーム時刻つきの計測には、`seek` モードを使ってください。

## 実行手順

### 1. 自己点検（まずこれ）

```bash
cd /home/work/boatcast-check/claude-code/boatcast
node verify.mjs --date 20261112 --race 12
```

| 項目 | 内容 |
|---|---|
| 1 | Chrome のバージョン |
| 2 | デバッグポートの空き |
| 3 | Chrome 起動とデバッグ接続 |
| 4 | プレイヤー読込（video 要素があること。**この時点の映像サイズは見ない**：読込直後は 0×0 のことがある） |
| 5 | duration > 0 |
| 6 | 5秒間で currentTime が 3秒以上進む |
| 7 | **再生後の映像サイズ**（幅・高さが 0 より大きい） |
| 8 | **フレーム数が実際に増える**（5秒間に 10 フレーム以上。requestVideoFrameCallback の通知数と `getVideoPlaybackQuality` の両方を見て、片方でも増えていなければ FAIL） |
| 9 | エラーなし（video.error なし・403 なし） |

終了コード：PASS=0 / FAIL=1 / 引数エラー=2。

### 2. フレーム取得

```bash
# 既定の秒 [10, 60, 120, 180, 200, 240, 280, 320]
node capture.mjs --date 20261112 --race 12

# 複数レース・秒を指定（小数も可）
node capture.mjs --date 20261112 --races 11,12 --seconds 10,60,120

# 計画だけ見る（Chrome は起動しない）
node capture.mjs --date 20261112 --race 12 --dry-run
```

| 引数 | 意味 | 既定 |
|---|---|---|
| `--date` | YYYYMMDD（`today` は日本時間の今日） | 必須 |
| `--race` / `--races` | レース番号 1〜12（複数可） | 必須 |
| `--seconds` | 取得する秒のカンマ区切り。duration を超える分は末尾に切り詰め | `10,60,120,180,200,240,280,320` |
| `--venue` | 場コード・場名 | `04`（平和島。検証済みはこれだけ） |
| `--port` | デバッグポート（`BOATCAST_PORT`） | `9454` |
| `--profile` | Chrome プロファイル（`BOATCAST_PROFILE`） | `/home/work/boatcast-check/profile-claude-code` |
| `--out` | 出力の親フォルダ（`BOATCAST_OUT`） | `/home/work/boatcast-check/claude-code/captures` |
| `--mode` | `seek`（既定）／`play` | `seek` |
| `--frame-tolerance` | 表示フレームが指定秒より何秒前まで許すか（seek モードの計測可判定） | `0.5` |
| `--attach` | すでに起動中の Chrome（`--port`）に繋ぐ。起動も終了もしない | なし |
| `--video-timeout` | video と duration を待つ秒数 | 45 |
| `--pad-race` | 1桁のレース番号を `01` の形にする | なし |
| `--chrome` | Chrome の実行ファイル（`BOATCAST_CHROME`） | `google-chrome-stable` → `google-chrome` → `chromium` |

`BOATCAST_CHROME_ARGS` で Chrome に引数を足せます（必須フラグは常に付きます）。

### 3. 結果を読む

```bash
# 出力先は、capture.mjs の実行ログの「→」に出る（既定：/home/work/boatcast-check/claude-code/captures/<日付>-heiwajima-<R>。同じレースを再実行すると -2, -3）
node report.mjs /home/work/boatcast-check/claude-code/captures/20261112-heiwajima-12
```

```
指定秒      再生位置    mediaTime     計測  重複(同じコマ)      sha256        file
 248.167   248.167    248.166667   可                      ...           f_0248p167s.png
 248.197   248.197    248.166667   可    = f_0248p167s.png ...           f_0248p197s.png
画像 2 枚 / 計測可 2 枚 / 別々のコマ 1 / 独立した計測値 1
```

計測に使えない画像や、画像と時刻の食い違いの疑いがあれば `⚠` で出て、終了コードが 1 になります。

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
/home/work/boatcast-check/claude-code/captures/20261112-heiwajima-12/
  f_0248p167s.png …           フレーム（ファイル名の数字は指定秒。小数は 248.167 → f_0248p167s.png）
  manifest.json                記録（schema 2）
```

- 同じレースをもう一度実行しても**既存を壊しません**（`...-12-2`、`...-12-3` と増える。ファイルも上書きしない）。
- 画像は**ブラウザ画面全体**（ビューポート）です。映像は 854×480 で左上に表示されます（プレイヤー側のレイアウトに依存）。

`manifest.json` の主な項目：

| 項目 | 内容 |
|---|---|
| `status` | `ok` / `partial`（計測に使えない画像、または画像と時刻の食い違いの疑いがある）/ `failed` |
| `venue` | `jo` / `slug` / `name` / `evidence`（確認の出どころ） |
| `playerUrl` | **ドメイン＋パスまで**（クエリは載せない） |
| `video` | `duration`・`width`・`height` |
| `playback` | `progressed`、`samples`（2回のサンプリング値）、`clicked` |
| `frames[]` | `requestedSec` / `targetSec` / `playerPosition` / `frame.mediaTime`・`presentedFrames` / `frameOffsetSec` / `measurable`・`notMeasurableReasons` / `frameId`・`duplicateOf`・`independentMeasurement` / `seeked`・`stable`・`nudged` / `sha256` / `mediaTimeRange`（play のみ） |
| `measurement` | `uniqueFrames`・`independentMeasurements`・`duplicates`・`notMeasurable`・`anomalies` |
| `networkErrors` | HTTP 400 以上・読み込み失敗（**ホストとパスだけ**） |
| `failure` | 失敗時の `stage`（段階）・`cause`（推定原因）・`hint`（対処） |

## 失敗したとき（段階と推定原因）

| 段階 | 表示される例 | 推定原因と対処 |
|---|---|---|
| `decode` | `video.error ... PIPELINE_ERROR_DECODE` | **起動フラグ不足**の可能性。`--disable-gpu --disable-accelerated-video-decode` が付いているか。`--attach` / `--chrome` を使っているならその Chrome の起動フラグを確認 |
| `forbidden` | 配信の取得が 403／視聴不可の表示 | **403 の理由は未確認です**。地域制限の可能性はありますが、断定しません（セッション・トークンの期限、URL の組み立て、公開状態なども考えられる）。切り分け：ブラウザで同じ URL が開けるか／別のレース番号で再生できるか／時間をおいて変わるか。参考：homesv の実機では平和島の 12R・1R で 403 にならなかった。GitHub Actions で出た 403 の理由は未調査 |
| `player-load` | video 要素が見つからない／duration が NaN | **レース未開催・リプレイ未公開**の可能性。日付・レース番号・場を見直し、時間をおいて再試行 |
| `cdp` | 対象ページが取れない／ポートが使用中 | `--port 9455` など**空いているポートに変えて**再試行。使用中の Chrome は落とさない |

※ 以前の版では `forbidden` を `geo` と呼んでいました（地域制限を前提にした名前だったため、理由が未確認のうちは使いません）。

## 伏せ字処理

配信まわりの URL にはセッショントークンが含まれることがあるため、**すべてのログ・manifest・エラーメッセージ**を `redact.mjs` に通します。

- URL は `スキーム＋ドメイン＋パス` まで。クエリ・ハッシュ・認証情報は落とす
- `Cookie` / `Authorization` / `token=` などの値も `[REDACTED]` にする
- ネットワーク失敗は、最初から**ホストとパスだけ**を保持する（クエリを持たない）
- 報告にも、ドメインとパスまでだけを書く（クエリ・Cookie・認証情報は書かない）

## テスト

```bash
# サーバー不要（URL組み立て・伏せ字・引数・失敗の分類・フレーム判定・同じコマのまとめ・verify の判定・出力先・ロック処理・dry-run）
node --test 'tools/boatcast/test/*.test.mjs'

# 通しテスト（Chrome と ffmpeg が必要。テスト用の動画をローカルで配信し、実際の配信には触れない）
node tools/boatcast/test/e2e-local.smoke.mjs
```

通しテストで確かめること：通常の撮影／**異なる指定秒が同じコマに当たる**（5fps の動画で 10.02 秒と 10.10 秒）／
同じコマへの再シークで新しいフレーム通知が出ない場合の「別位置から戻して取得」／**別のコマを撮る**（seeked のあとにページが再生を進める）／
**表示フレーム時刻が取れない**（`requestVideoFrameCallback` が無い）／`play` モード／verify が映像サイズ 0×0・フレームが増えない映像を FAIL にすること／失敗の4段階。

## 実機（homesv）での再検証コマンド

実機の再検証はデスクトップ側の Codex が担当します。Chrome は1つだけ、ポートは 9454（使用中なら止めて報告）。

```bash
cd /home/work/boatcast-check/claude-code/boatcast
node --test 'test/*.test.mjs'                                  # 1. ユニットテスト（全件通ること）
node verify.mjs --date 20261112 --race 12                      # 2. 自己点検（RESULT: PASS (9/9)）
# 3. 発端の再現：同じコマに当たる2つの秒（12R）
node capture.mjs --date 20261112 --race 12 --seconds 248.167,248.197
node report.mjs <実行ログの「→」に出た出力先>                   # 同じ mediaTime・同じコマ・独立した計測値が1つ、と出ること
# 4. 1R（raceNumber=1）と、離れた秒
node capture.mjs --date 20261112 --race 1 --seconds 10,60,120
node report.mjs <実行ログの「→」に出た出力先>
# 5. play モードの対応（計測可は「撮影中にフレームが進まなかった画像」だけであること）
node capture.mjs --date 20261112 --race 12 --seconds 100,101 --mode play
node report.mjs <実行ログの「→」に出た出力先>
```

見るポイント：

- 3 で、2枚の画像の `frame.mediaTime` が同じ（例：248.166667）なら、`duplicateOf` が付き、`independentMeasurement` は最初の1枚だけが `true`
- `frame.mediaTime` が取れた画像は `measurable: true`、別のコマの疑いがある画像は `false`（理由つき）
- `playerPosition`（再生位置）と `frame.mediaTime`（表示フレーム）が**別々の値**で記録されている
- 実機で `requestVideoFrameCallback` の通知が出ない・`nudged` が多いなど、想定と違う動きをしたら、manifest の `frames[].frame` と `nudged` を報告する

## 未検証項目（homesv 実機でしか確認できない）

PR 版の実機確認は、平和島の 12R・1R（2026-11-12）、`e041f13` 時点まで。**今回の修正（フレーム時刻の確認・同じコマの扱い・verify の追加項目）は、実機ではまだ確認していません。**

- 今回の修正が実機で動くこと：`requestVideoFrameCallback` の通知が出るか、`mediaTime` が取れるか、`stable` / `nudged` の挙動、`--mode seek` と `--mode play` の画像とフレーム時刻の対応
- verify の項目7・8（再生後の映像サイズ、フレーム数の増加）が実機の配信で PASS すること（基準の「5秒間に10フレーム以上」は、実配信の fps が未確認のための暫定値）
- 平和島以外の場の stadium 表記：別ツールで24場・288本の再生開始を確認済みだが、対応表を受け取っていないため `STADIUMS` は空欄のまま（反映するときは、別ツールの実測 `other-tool-288` と、PR 版の実機確認 `pr-tool-homesv` を区別する）
- ゼロ埋めしたレース番号（`--pad-race`）：別ツールでは確認済み。**PR 版では未実機**（`raceNumber=1` は PR 版で実機確認済み）
- レース本編リプレイの `raceType` の値（未定義 TODO）
- `bitrate=low`（854×480）以外の画質
- リプレイが公開される時刻
- プレイヤーの再生開始に、中央クリックが必要か（必要なら自動でクリックし、`playback.clicked` に記録）
- 「視聴は許可されていません」系の実際の文言（`failures.mjs` の `DENIED_TEXT_RE` は当て推量）
- 403 の理由（地域制限・セッション・トークンなど。**未確認**）

## 既知の制約

- 場ページ（`race.boatcast.jp/?jo=04`）経由だとプレイヤーは別ドメインの iframe になり、iframe 側ではスクリーンショットが撮れません。**単体プレイヤーURLを直接開く**方式が正です。
- Chrome は同時に 1 つだけ起動します（homesv は本番機で負荷が高め）。重い並列処理はしません。
- 同じコマが続く場合、`mediaTime` は動画のコマ間隔（fps）でしか変わりません。コマ間隔より細かい差は区別できません。
- クラウド（海外・データセンターIP）での実行は想定していません。配信が 403 になる理由は未確認です。

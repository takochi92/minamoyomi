# 周回展示の区間計測

全24場で同じ計測コードを使う。場・周回・カメラごとに基準線と画角の設定が必要。再生の確認と計測の確認は、台帳に別々に記録する。

## 計測する区間

| 区間 | 基準線 | 用途 |
|---|---|---|
| 入口 | A–B | 進入からターン中の基準線まで |
| 出口 | B–C | ターン中から出口まで |
| ターン全体 | A–C | 旋回区間の比較 |
| 出口直後 | C–D | 立ち上がりの候補指標 |
| 直線前半・後半 | D–E、E–F | 同じ線の間を通る時間の比較 |
| 直線 | D–F | 画角内で観測した直線区間 |

各タイムは艇首が基準線をはさむ前後のコマを見つけ、近くの連続5コマの軌跡を直線に当てはめて求める。当てはめの残差が設定を超えた場合は欠測にする。推定時刻が最初の通過幅をわずかに外れた場合は、基準線の両側に残差より遠い実測点があるときに限り、観測幅を広げ、最初の範囲も残す。区間内で艇首を見失った場合は欠測のままにする。出力に各コマの時刻・座標・残差と、区間時間の取り得る範囲を保存する。この範囲には、艇首を読み取る人の違いやリプレイの再生倍率による誤差は含まれない。出力単位はリプレイ上の秒。直線前半・後半の長さ、バックストレッチ全長、撮影位置による遠近の差は別途確認が必要。

2026年11月12日の平和島12Rの `exhibition_segment_sample_20261112.json` は、レビュー対象になった旧方式の参考値。新しい方式の試験は `exhibition_segment_followup_20261112.json` に記録した。再採点は1号艇のみで、旧結果とは別の参考値として扱う。

Chromeの窓サイズを変える運用では、PR #68のキャプチャを別の作業先に用意し、撮影の直前・直後で映像領域が一致した場合だけ、各コマに `videoLayout` を記録する。

```sh
python -m tools.prepare_boatcast_layout --source PRIVATE/pr68/tools/boatcast --output PRIVATE/layout-capture
node PRIVATE/layout-capture/capture.mjs --date 20261112 --venue 04 --race 12 --seconds 248,250,252
```

映像内の座標を使う設定は `coordinate_space: "video"` を指定し、`image_size` に映像の解像度を入れる。基準線・固定物・艇首もこの座標にそろえ、校正PNGは同じ解像度に切り出す。確認用シートにも同じ `--profile` を渡せる。領域の情報が欠けたコマや、画面サイズ・映像サイズが合わないコマは拒否する。平和島12Rの3コマを2種類の窓サイズから854×480にそろえ、固定物が一致した。別の場・画角への適用は個別に確認する。

## 実行手順

1. homesv の作業専用ユーザーから PR #68 の通常再生キャプチャを使う。最初に粗い間隔で固定画角の候補を探し、候補区間を 0.1 秒間隔で取り直す。外部への成果物は数値だけを使う。
2. 場・周回・画像サイズ、物理的な固定物3点、基準線A〜Fの方向と有効範囲を設定する。A〜Cは必須。基準線を設定したPNGを作業専用領域に保管し、SHA-256を `calibration_sha256` に記録する。 `max_bow_pixels_per_video_second` と `max_crossing_fit_residual_pixels` はその画角の試験で決める。
3. レビュー用JSONを生成し、固定画角の開始・終了時刻、基準フレーム、艇番ごとの艇首座標を記録する。各区間内の採用可能な全コマと、各通過点周辺の連続5コマが必要。色または艇番を確認できたコマを `identity` に記録する。形式は `{"1":{"boat":1,"method":"boat_color","file":"f_0248s.png"}}`。艇番を画面で読めた場合は `visible_number` を使う。固定物と基準線を確認してから `camera_layout_reviewed` を `true` にする。1周目と2周目の両方で固定物が一致することがあるため、周回の字幕を確認したコマを `lap_evidence` に記録する。形式は `{"lap":1,"method":"broadcast_caption","file":"f_0248s.png"}`。
4. 計測を実行する。重複、フレーム欠落、ハッシュの違い、急な座標の飛び、同じ軌跡への複数艇の割り当て、画角の変化を検査する。艇の色・番号は人が確認する。

```sh
python -m tools.exhibition_review_sheet --manifest PRIVATE/manifest.json --start 247.7 --end 253.5 --scale 0.30 --output PRIVATE/sheets
python -m tools.measure_exhibition scan-camera --manifest PRIVATE/manifest.json --profile PROFILE.json --calibration PRIVATE/calibration.png --output PRIVATE/camera-scan.json
python -m tools.measure_exhibition template --manifest PRIVATE/manifest.json --profile PROFILE.json --output PRIVATE/review.json
python -m tools.measure_exhibition measure --manifest PRIVATE/manifest.json --profile PROFILE.json --review PRIVATE/review.json --calibration PRIVATE/calibration.png --output PRIVATE/result.json
python -m tools.measure_exhibition inventory --stadiums PRIVATE/stadiums.json --profiles research/improvements/exhibition_profiles --result PRIVATE/result.json --output PRIVATE/coverage.json
python -m tools.measure_exhibition batch --index PRIVATE/queue.json --output PRIVATE/measurements
```

`queue.json` は `{"jobs":[{"date":"20261112","venue":"04","race":12,"manifest":"manifest.json","profile":"PROFILE.json","review":"review.json","calibration":"calibration.png"}]}` の形式。相対パスはキューファイルを基準にする。未準備のレースは日付・場・レース番号だけで登録できる。

単発・一括とも結果の書き込みは排他・一時ファイル経由。採用済みの結果と異なる場合は候補版と区間差分を保存し、採用中の結果を維持する。採用を変更するには候補のハッシュと理由を指定する。単発は `--replacement-version` と `--replacement-reason`、一括は各レースの `replacement_version` と `replacement_reason`。誤りの撤回で区間が減る場合も、同じ手順で更新できる。版は出力先の `.exhibition-versions/` に保存する。同時実行は「実行中」を返し、読み込めないレースは理由付きで記録して次のレースへ進む。映像の取得・艇首追跡・定期実行は現在のバッチの外で行う。

## A〜D評価に必要な確認

- 出足の候補はターン出口と出口直後、伸びの候補は固定距離または同等の基準線で測った直線と公式展示タイム。ターン入口・旋回は回り足の候補として別に検証する。
- 同じ場・節・条件で他艇と比較し、風・波・気温、艇の通った位置、選手、チルト・部品交換を考慮する。モーターは交換期を含めて識別する。
- 複数日・複数選手の測定で、誤差と欠測率を確認する。別の節や別選手の成績を使い、機力指標として再現するか、公式の直線・回り足データがある場ではそちらとの整合も検証する。
- 種別と総合の評価基準はこの検証後に固定する。比較に必要な走数や種別が足りないときは評価保留にする。

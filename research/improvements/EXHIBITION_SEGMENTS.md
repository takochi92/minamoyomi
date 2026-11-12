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

各タイムは艇首の通過前後の表示フレーム時刻から補間する。出力に前後のフレームと区間時間の取り得る範囲を保存する。この範囲には、艇首を読み取る人の違いやリプレイの再生倍率による誤差は含まれない。現時点の出力単位はリプレイ上の秒。直線前半・後半の長さが同じか、バックストレッチの全長が映っているかは別途確認が必要。

## 実行手順

1. homesv の作業専用ユーザーから PR #68 の通常再生キャプチャを使う。最初に粗い間隔で固定画角の候補を探し、候補区間を 0.1 秒間隔で取り直す。外部への成果物は数値だけを使う。
2. `exhibition_profiles/` に、場・周回・画像サイズ、物理的な固定物3点、基準線A〜Fの方向と有効範囲を設定する。A〜Cは必須。カメラに映る範囲に応じてD〜Fを設定する。リプレイ時刻とカメラはレースごとに照合する。
3. レビュー用JSONを生成し、固定画角の開始・終了時刻、基準フレーム、艇番ごとの艇首座標を記録する。各線をはさむフレームの座標が必要。物理的な固定物と基準線がこの映像にも合うことを確認してから `camera_layout_reviewed` を `true` にする。
4. 計測を実行する。重複、フレーム欠落、ハッシュの違い、座標や通過順の不整合、画角の変化は、理由付きの欠測として記録する。判定対象の区間中も映像を確認する。

```sh
python -m tools.exhibition_review_sheet --manifest PRIVATE/manifest.json --start 247.7 --end 253.5 --scale 0.30 --output PRIVATE/sheets
python -m tools.measure_exhibition template --manifest PRIVATE/manifest.json --profile PROFILE.json --output PRIVATE/review.json
python -m tools.measure_exhibition measure --manifest PRIVATE/manifest.json --profile PROFILE.json --review PRIVATE/review.json --output PRIVATE/result.json
python -m tools.measure_exhibition inventory --stadiums PRIVATE/stadiums.json --profiles research/improvements/exhibition_profiles --output PRIVATE/coverage.json
python -m tools.measure_exhibition batch --index PRIVATE/queue.json --output PRIVATE/measurements
```

`queue.json` は `{"jobs":[{"date":"20261112","venue":"04","race":12,"manifest":"manifest.json","profile":"PROFILE.json","review":"review.json"}]}` の形式。相対パスはキューファイルを基準にする。未準備のレースは日付・場・レース番号だけで登録できる。1回の実行で各レースの結果と集計を保存する。書き込みは排他・一時ファイル経由で、既存の計測済みの艇・区間が減る再計測結果は、理由（`replace_reason`）がなければ上書きしない。映像の取得・艇首追跡・定期実行は現在のバッチの外で行う。

## 独立レビュー後に入れた検査（2026-11-12）

レビューで再現した問題に対して、次の検査を入れた。平和島12Rの保存済みサンプル（`exhibition_segment_sample_20261112.json`）は**変更前のコードの出力**で、基準線の前後2コマだけを読んだ軌跡のため、いまの規則では `bow_track_not_continuous`（計測不可）になる。読み直すまで参考値として扱う。

| 検査 | 内容 | 欠測・エラーの名前 |
|---|---|---|
| 軌跡の連続性 | 区間の最初から最後まで、艇首を毎コマ読んでいること（コマの間隔 0.15 秒以内） | `bow_track_not_continuous` / `bow_track_has_unusable_observation` |
| 艇首の跳び | 0.1 秒あたりの移動が画像の長辺の 8% を超えない（設定の `max_bow_step_px` で変更可）。別の艇への乗り移りを止める | `bow_jump_too_large` |
| 艇番の重複 | 2艇の艇首が 2px 以内で重なるコマが2つ以上あれば、両方を計測しない | `bow_track_shared_with_another_boat` |
| 画角の見本 | 設定に固定物3点の見本（`anchor_patches`）があれば、全コマをそれと照合する。別の日・別のズームは止まる | `camera_view_differs_from_profile` |
| 読み取りのばらつき | 基準線の前後 0.25 秒の点を直線に当てはめた通過時刻も出す（`fit_video_seconds`、補間との差、残差 px）。残差が大きい区間は読み直す | （数値として保存） |

- 見本の作り方：確認済みのコマを1つ選び `python -m tools.measure_exhibition profile-patches --manifest … --profile … --reference f_XXXX.png --output NEW_PROFILE.json`。見本のない設定で測った結果は `camera_layout_check: "human_review_only"` と記録される（人の確認だけが頼り）。
- 再実行：内容が同じなら何もしない。値が変わるときは前の結果を `history/` に残してから書く（`replaces` に前の入力ハッシュと保存先）。計測済みの艇・区間が**減る**結果は、キューの `replace_reason`（`measure` は `--replace-reason`）に理由を書いたときだけ置き換える。`measure` もバッチと同じ排他・保護を通る。
- 同時実行は「実行中」として何も変えずに終わる。読めない入力はそのレースだけ `input_unreadable` にして、残りを続ける。
- 台帳（`inventory --measurements DIR`）は、再生できた／設定がある／見本つき設定がある／一部計測／6艇計測 を別々に数える。

まだ残っていること：`image_size` はブラウザ画面のスクリーンショットの大きさで、Chrome の版や窓の設定が変わると設定が使えなくなる（そのときは `frame_dimensions_mismatch` で止まる）。映像の座標で持つ形への変更は未着手。艇番そのものの確認（色など）は人の確認のまま。

## A〜D評価に必要な確認

- 出足の候補はターン出口と出口直後、伸びの候補は固定距離または同等の基準線で測った直線と公式展示タイム。ターン入口・旋回は回り足の候補として別に検証する。
- 同じ場・節・条件で他艇と比較し、風・波・気温、艇の通った位置、選手、チルト・部品交換を考慮する。モーターは交換期を含めて識別する。
- 複数日・複数選手の測定で、誤差と欠測率を確認する。別の節や別選手の成績を使い、機力指標として再現するか、公式の直線・回り足データがある場ではそちらとの整合も検証する。
- 種別と総合の評価基準はこの検証後に固定する。比較に必要な走数や種別が足りないときは評価保留にする。

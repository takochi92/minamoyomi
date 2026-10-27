# レース更新の停止調査（2026-10-27）

## 確認した障害

- 15:20台の利用者画像と15:30台の実ブラウザで、ホームと公開 `/freshness.json` がともに13:46時点。尼崎8R以降の結果も未反映。
- `update-races` の予約実行は11:31開始（run 40438905128）を最後に、調査時点まで新しい実行がなかった。ワークフローはactive、リポジトリはmain・public・非アーカイブ、Actionsは有効。
- 13:46のデータは画面変更を契機とするpush実行（40451451377）で収集したもの。その実行自体は成功していた。
- 15:28に既存workflow_dispatchで復旧実行40461267631を開始。これは恒久対策の検証とは別。
- 復旧実行は成功。実ブラウザでホームとfreshness.jsonが15:29へ進み、尼崎8R（1-5-6）、9R（1-3-5）、10R（1-5-3）の結果表示を確認した。
- アプリ用Service Workerは公開ページを保存せずネットワークを取得する。新規ブラウザでも同じ公開データが古く、端末だけのキャッシュ削除では解決しない。

## 今回の緩和

GitHub公式の案内に合わせ、5分間隔を保ったまま予約を毎時2/7/12…57分に移動。深夜の10分間隔も3/13…53分に移す。混雑する毎時0分を避ける措置であり、予約起動の保証にはならない。

## 運用上の限界と次の対策

GitHub予約は遅延や取りこぼしがあり、外部から独立して起動・監視する仕組みが未設置。予約時刻変更だけで「停止しなくなった」とは判定しない。公開時刻と後続の自動実行・公開を別々に確認する。

独立したタイマーを導入する場合は、対象リポジトリのActions起動に限定した専用認証を使い、既存の個人用GitHubログイン資格情報を外部サービスへコピーしない。停止監視は公開データ時刻と実行中ジョブを照合し、同時実行・重複起動を抑止する。

## 独立タイマーの実装（未配備）

`update-watchdog/` にCloudflare Cron Workerを用意した。公開データが8分以上古く、update.ymlの実行中・待機中ジョブがなければmainのworkflow_dispatchを呼ぶ。直近起動から5分は再起動しない。公開時刻の取得失敗・不正な応答では連打せず失敗を記録する。HTTPから起動できる公開操作口は作らない。

配備には、GitHubで **Only select repositories: takochi92/minamoyomi / Repository permissions: Actions Read and write** のfine-grained PATを作り、このリポジトリのActions Secret `UPDATE_DISPATCH_TOKEN` へ保存する。アカウントの全リポジトリ用トークンは使わない。Contentsへの書き込み権限は不要。有効期限を記録し、期限前に交換する。

その後 `.github/workflows/update-watchdog.yml` を手動起動する。既存Cloudflare資格情報でWorker公開権限が足りなければ配備失敗として扱い、サイト更新の復旧とは分けて報告する。Workerのdispatchと、後続GitHub更新・公開時刻の前進を実測するまで配備完了・恒久対策完了とはしない。専用トークンはまだ未登録のため、このタイマーは動いていない。

参考：[GitHub公式の予約実行に関する制約](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

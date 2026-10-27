# 朝のお気に入り出走通知（実装版、配信未有効化）

ユーザー希望：朝に対象レースをまとめる。お気に入り選手ごとに通知する枠番を選択する。
所有者限定の機能ではない。既存・新規の全ログイン利用者が自分の端末・お気に入りに対して利用する設計。利用者にSupabase連携は求めない。ChatGPT側のSupabase管理接続は所有者の開発作業用であり、サイトのGoogleログイン接続と別物。

## 動作

- マイノートに通知のオン・オフと選手別1〜6号艇の選択。初期はオフ・全選手未選択。端末ごとの設定で、本人操作で通知許可を求める。枠番と実際の進入コースは区別する。
- 配信はJST 8:13/33/53、9:13/33/53の候補時刻。GitHubの遅延を考慮し8:00〜9:59だけ実行。原子的な日次claimで端末ごとに1回。予定は保証時刻ではない。
- 公開の当日出走表と、本人の現在のお気に入り、明示設定の枠番の共通部分だけ。締切済み・古い日付・中止場は除外。対象なしは無通知。新しいお気に入りも勝手に通知対象にしない。
- 通知タップは同一サイトのマイノートへ。選択条件に合う今日のレースへのリンクを表示する。表示時点で締切済みのものも今日の確認用に残る。
- DBはRLS＋所有者RPC、revisionによる競合拒否。端末の配信先・鍵は公開git、ログ、成果物に含めない。配信先ホストを限定し任意URLへのサーバー通信を防ぐ。ユーザー削除は通知設定にもcascade。
- 明示ログアウト時にその端末のPush購読を解除。再ログイン後は「オン」で再登録する。ブラウザ権限の取り消しや購読失効でも再登録が必要。
- 送信の結果が不明な失敗はその日の再送をしない。重複より欠配を選ぶ。claim後のオン・オフ変更は進行中の1件を取り消せない場合がある。通知文は端末ロック画面へ表示されることがある。

## 本番で残る設定（これが済むまで通知可能とは報告しない）

1. 専用Supabase `teilog-notes` に `supabase/migrations/20261027_morning_push.sql` を適用する。既存ノートと別テーブルで、ノート本体の形を変えない。
2. 実DBで匿名拒否、A/Bユーザーの読み書き分離、所有者不一致、古いrevision、重複endpoint、日次claim、削除cascadeを確認する。ローカルの模擬ブラウザ試験はこの検証の代わりではない。
3. VAPIDの鍵ペアを生成し、秘密鍵はGitHub Actions Secret `PUSH_VAPID_PRIVATE_KEY`、Supabaseのサーバー用キーは `PUSH_SUPABASE_SERVICE_KEY` へ登録。チャット・公開ファイルへ貼らない。公開鍵だけ `SITE_CONFIG.notifications.vapidPublicKey` へ。
4. `SITE_CONFIG.notifications.enabled` とGitHub variable `PUSH_ENABLED` は、実DB確認とテスト端末の登録後に有効化。まず所有者端末への受信を実確認し、画面を閉じた状態で届くこと、オフ・別枠番・解除済みお気に入りで届かないことを確認する。
5. iPhone/iPadはホーム画面追加と対応OSが必要。AndroidもOS・ブラウザの通知設定が必要。正確な配信・到着時刻は保証しない。

本セッションの管理画面操作ランタイムは `failed to write kernel assets` で起動できず、専用Supabaseの変更・本番鍵の登録は未実行。既存のログインや公開サイトの設定を壊さないよう、通知フラグはfalseのまま。
Supabaseの管理連携を検索し、未接続を確認して提案済み。ユーザーは前回の接続との違いと全員利用を質問。既存のログインは接続済みであり、一般利用者には新しい外部連携不要と説明した。新規アカウント作成やSupabaseプロジェクト作り直しは不要。

## 開発環境での確認

- 実Edge・390pxで選手別の枠番、オン・オフ、保存、登録失敗時の購読解除、別アカウントの分離を確認。Push/認証APIは模擬で、本番受信試験ではない。
- ローカルPostgreSQL（PGlite）で既存ノートSQLと今回のSQLを実行。匿名拒否・A/BのRLS分離・所有者/旧revisionの拒否・不正な枠番/配信先の拒否・service_roleだけの日次claim・重複排除・オフ・自己アカウント削除時のcascadeを確認。本番Supabaseの設定確認とは区別する。
- 実pywebpushでP-256の一時鍵を使った暗号化とVAPID署名・TTLとtimeoutを確認。HTTP送信はMock、秘密鍵はメモリ内のみ。
- Pythonで絞り込み、古い日付、締切、中止、重複、配信先URL、日次claimとログ非公開、昼の実行停止を検査。既存worker・JS検査も成功。
- 検査画像とX下書きは `private/morning-push/`。未投稿・Atelier未送信。

## 出典

- [Push API / MDN](https://developer.mozilla.org/en-US/docs/Web/API/Push_API)
- [Apple Web Push](https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers)
- [pywebpush 2.0.3](https://pypi.org/project/pywebpush/2.0.3/)

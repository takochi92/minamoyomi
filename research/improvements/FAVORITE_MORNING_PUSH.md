# 朝のお気に入り出走通知

全ログイン利用者が自分のお気に入りについて、選手ごとの通知対象枠番と端末ごとのオン・オフを設定する。所有者限定ではない。一般利用者にSupabase連携を求めない。

## 動作

- 初期はオフ・全枠番未選択。本人のボタン操作で端末の通知許可を求める。枠番（号艇）を選ぶもので、実際の進入コースは未確定。
- 朝8:13/33/53・9:13/33/53（JST）の定期実行で、その日にまだ締切を迎えていない対象をまとめる。配信・端末の状態による遅れ・欠配はあり、時刻を保証しない。対象なしは無通知。
- ユーザーのGoogleログインを使い、本人の端末設定だけをRLSと保存RPCで扱う。CASで古いrevisionを拒否。お気に入りから外した選手は、保存時の連動処理で通知条件から除外する。新規お気に入りは勝手に通知対象へ加えない。
- 通知側に保存するのは明示設定の枠番・登録番号と選手の表示名。配信側に既存ノート表の読取権限を与えない。個人メモ本文・収支をコピーしない。
- 当日付の公開番組だけ。中止場・中止Rは公開フィード生成で除外。送信側でも日付・締切・枠番・URLを検査する。
- 端末・日・種類の原子的claimで重複防止。通常の朝通知と本人用テスト通知は別枠。どちらも1端末1日1回。結果不明時は再送しない。
- 通知タップは同一サイトのマイノート。今日の選択条件に合う出走へリンク。通知文に選手名とレース情報が含まれ、端末設定によってロック画面へ表示される。
- 明示ログアウトは保存側をオフにし端末購読を解除。アカウント切替時も購読解除。サーバー停止時でも端末側の解除を試みる。新規アカウントへの再登録を旧オフ状態のendpointが妨げない。
- アカウント削除は通知設定・送信記録にもcascadeする。進行中の送信はオフ操作で取り消せない場合がある。

## 配信構成

- `supabase/functions/favorite-morning/`：Deno Edge Function、Node互換web-push固定版、依存ロック。公開ゲートウェイJWTチェックはfalseだが、関数本体でAuth APIによるユーザー確認、または定期実行専用秘密キーを必須にする。
- 本人テストは有効なユーザーJWTで、その本人が登録した端末だけを選択する。定期処理は秘密キーを定数時間比較して照合する。認証なし・無効セッション・誤ったjobキーは401。
- `pg_cron`＋`pg_net`で既知の自分のEdge URLへだけ呼出し。jobキーとVAPID鍵はSupabase Vaultへ暗号化保管。VAPID秘密鍵はEdge内で生成し、チャット・ローカルファイル・Git・ログへ出さない。公開鍵だけsite/config.jsに記載。
- Edge組込のサーバー認証を使うため、ユーザーから追加の管理キーを受け取らず、GitHub Secretsへservice_role鍵を移さない。
- GitHub配信案のPythonとワークフローは削除した。Supabase側だけが実送信を担当する。

## 本番設定・承認と確認

- 専用プロジェクト `teilog-notes`（`xkibgkdniwlfocwpmuzy`）を確認。既存ログインの作り直し・新規プロジェクト・有料契約なし。
- 自動承認が個人メモ全体へのSELECT追加案を拒否。全体読取のGRANTを除き、本人の保存時のfav部分だけを使う形へ変更した。
- 本番DBへの通知表・保存関数・解除連動の追加について、ユーザーが明示的に許可。`favorite_morning_push`適用成功。
- 別途、定期実行・HTTP・Vault・Edge配信・通知画面の本番反映についてもユーザーが明示的に許可。`favorite_push_runtime`適用、Edge v2、Vault初期化、定期実行の登録を確認。
- Bootstrap呼出しはHTTP200・ready=true。秘密鍵を返さず公開鍵だけ取得。正午のmorning呼出しはHTTP200・outside morning windowで停止。runtimeとcronは有効。
- 本番SQLで匿名拒否・所有者分離・お気に入り限定コピーと解除連動・claim重複防止・テスト枠分離・自己削除cascadeを確認。合成データは全てrollback済み。
- 実端末でのOS通知の受信は未確認。公開後、本人がマイノートでオン→テスト通知を操作して確認する。サイトを開いていない状態で受け取れるかも確認対象。

## 検査

- `supabase/tests/morning_push.sql`：本番上の権限検査（合成データ・rollback）。
- `tests/test_push_database.cjs`：PGlite上で既存ノートSQLと通知SQLを実行。所有者・匿名・CAS・URL・枠番・削除・endpoint再登録。
- `tests/test_edge_morning.cjs`：実配信と共有するJS計算。JST、未選択、古い番組、締切、対象枠番、送信先制限、テスト区分。
- `tests/morning_push_browser.cjs`：実Edge390px、認証とPushはMock。選手別設定・オンオフ・テスト通知・保存失敗・アカウント切替・ログアウト。実受信の証明ではない。
- 既存のログイン・PWA・予想表示を含む全検査とDeno型検査を実行。検査画像・紹介用1200×675画像・X下書きは `private/morning-push/`。外部投稿・Atelier送信なし。

## 参考

- [Supabase Edge Functions scheduling](https://supabase.com/docs/guides/functions/schedule-functions)
- [Supabase Vault](https://supabase.com/docs/guides/database/vault)
- [Push API](https://developer.mozilla.org/en-US/docs/Web/API/Push_API)
- [Apple Web Push](https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers)

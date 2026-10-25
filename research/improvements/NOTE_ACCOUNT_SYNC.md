# アカウントノート同期（2026-10-26）

## 状態

- 専用Supabase、権限SQL、Google OAuthの設定が完了。本番URLでGoogleログイン、実保存・再取得・再読み込み、ログアウトを確認。`site/config.js` は公開用キーのみを使い `verificationOnly: false` へ切替。通常URLのログイン欄の表示・操作可能を確認し、一般公開済み。
- 接続確認は一時的に `verificationOnly: true` と `https://teilog.com/mynote?note-sync-check=1` を使用した。明示的に開いたタブのsessionStorageで確認モードを保持し、OAuthの戻り先は既定の `/mynote` のまま。これは画面表示の段階的公開用で、アクセス制御ではない。RLSは別に適用。
- Cloudflare独自ドメインは https://teilog.com/ 。旧URLのノートと必要な静的ファイルを転送除外している。新しい note-store.js / note-account.js も転送除外へ追加・保存し、再表示で確認済み。

## 構成

- `site/note-store.js` は旧形式の正規化、項目単位の変更、三者比較、削除、競合・安全なバックアップ取込。収支の重複IDは加算しない。
- `site/note-account.js` はオプションのGoogle認証、本人だけの同期、状態表示、競合選択、ログアウト、自己アカウント削除。SDKは公式npm配布2.118.0をSHA512検証してvendorへ固定保存。管理用キーは不要。
- ノート本体は登録なしの `teilog_note_v1` と混ぜない。ログイン時に端末内の記録を自動でアップロードしない。取り込みは本人が明示操作。ゲストの元記録は削除しない。
- クラウド本体はメモリ上。未同期の変更だけをユーザーIDと固有操作IDごとにlocalStorageへ保存し、成功した操作だけ削除。ログアウト後はアカウントの記録を画面に出さない。未同期操作は同じアカウントで再ログインしたときだけ再開する。共有端末の開発者ツール等からのローカル保存閲覧を暗号化で防ぐものではない。
- 書込はrevisionの比較更新。衝突時は再取得。別項目の編集は統合、同じ項目の異なる変更は双方を提示し選択する。削除も比較対象。更新応答だけが失われた場合の再送は冪等。
- 非表示中は定期取得を止め、表示中は90秒ごとに小さなrevisionだけ確認。変更時のみ本体を取得。編集は約900msまとめて送る。常時Realtimeは使わない。
- リクエスト準備中にアカウントが切り替わっても、JWTの本人と `expected_user_id` が違えばRPCが拒否。ブラウザ側も世代番号の違う遅延応答を破棄。

## セットアップ手順

1. 所有者がSupabaseの規約・登録とパスワード設定を行う。専用の無料プロジェクトを作り、近い地域を選ぶ。既存の他プロジェクトへ適用しない。
2. SQL editorで `supabase/migrations/20261025_private_notes.sql` を適用。匿名不可、本人だけSELECT。直接書込は禁止。RPCはJWTから本人を決める。管理キーをブラウザや公開ファイルに入れない。
3. `supabase/tests/private_notes.sql` を実行して匿名拒否・A/B読取分離・古いrevision拒否・アカウント切替ガード・自己削除のcascadeを確認。合成データは全てrollback。
4. Supabase AuthのSite URLを `https://teilog.com`、許可する戻り先を `https://teilog.com/mynote` に設定。ワイルドカードや旧ドメインは認証の戻り先にしない。
5. Google CloudでWeb OAuthを設定。要求scopeは基本の認証（openid/email/profile）だけ。Supabaseのcallback URLを正確に登録。外部向け公開設定・ブランド・ホームページ・プライバシーURLを確認する。秘密鍵をチャットに出さない。
6. プロジェクトURLと公開用publishable keyだけを `site/config.js` に設定する。service_role・secret keyは絶対に使わない。
7. 別々の2アカウントと同じアカウントの2ブラウザで実検証。旧ノートの端末保存、別人への非表示、ログアウト、同期競合、通信失敗、削除を確認。
8. Python全テスト、worker、2種類のノートNodeテスト、実画面確認の後に公開。Cloudflare旧ドメインの除外条件も更新し、旧ノートの書出しが動くことを再確認。

## テスト

```text
node tests/test_note_store.cjs
node tests/test_note_account.cjs
python -m pytest -q tests
node worker/test.mjs
```

Nodeテストはモデル・ブラウザ状態の検査であり、実SupabaseのRLSやGoogle OAuthの成功を証明しない。上記SQLと実ログイン検証が必須。

### 接続前の確認結果

- Python 173件成功（298.30秒）、workerテスト成功。
- Nodeモデルテストとアカウント状態テスト成功。ログイン時のゲスト自動取込なし、ログアウト・別アカウントへの非表示、通信失敗後の再送、読み書き要求中のアカウント切替を確認。
- サンプルの通信先を使う実ブラウザで、2ブラウザのノート・予算共有、競合時の両方の表示と選択、ログアウト、設定なしの端末保存を確認。320/360/390/430/768/1440pxで横はみ出しなし。
- 接続前の確認画面の記録は合成データ。実接続の確認結果は下記。X原稿は一般公開の完了確認後に準備し、許可なしに投稿しない。

### 外部サービスの準備状況

- Supabase無料組織「艇ろぐ」、専用プロジェクト `teilog-notes`（ref: `xkibgkdniwlfocwpmuzy`、東京）を作成。正常稼働を確認。
- マイグレーション適用成功。実DBで `supabase/tests/private_notes.sql` がPASS。匿名拒否、所有者のみの参照、直接書込拒否、CAS、アカウント切替ガード、本人削除のcascadeを確認。テスト用レコードはrollback済み。
- AuthのSite URLは `https://teilog.com`、許可する戻り先は `https://teilog.com/mynote` のみ。
- 所有者がGoogleの2段階認証を有効化。専用Google Cloudプロジェクト `Teilog Notes`（ID: `fluted-century-512714-r5`）を作成。
- 本人の明示同意でGoogleユーザーデータポリシーに同意し、アプリ「艇ろぐ」を保存。別途の明示承認でWeb OAuthクライアントを作成し、専用Supabaseへ登録、GoogleプロバイダーのENABLEDを確認。秘密情報は公開コード・文書へ保存していない。
- Googleホームページ `https://teilog.com/`、プライバシー `https://teilog.com/about`、承認ドメイン `teilog.com` を保存。scopeはopenid・email・profileの3種類だけ。Gmail/Drive権限なし。
- Googleは所有者の運営用アカウント1件に限定して確認後、「本番環境」に切替済み。
- Google側へ登録する戻り先は、Supabase画面で確認した `https://xkibgkdniwlfocwpmuzy.supabase.co/auth/v1/callback`。
- メール登録方式を停止し、Googleログインだけを有効化。実APIでも公開用キーの有効性・Google有効・Email無効・匿名のノート参照拒否を確認。

### 本番での実接続確認

- `https://teilog.com/mynote` から実Googleログイン成功。OAuth codeの交換後、URLからcodeが除かれ「アカウントのノート」「同期済み」を確認。
- 空の運営者アカウントで予算に確認値を一時入力し、別タブで同期・再読み込み後も同じ値になることを確認。確認後は元の未設定へ戻し、両タブで反映を確認。購入・払戻の架空記録は追加していない。
- 別タブでログアウトし、両方のタブでアカウント表示が消えて登録不要の端末保存へ戻ることを確認。
- 選手検索でお気に入りを登録し、選手ページで確認用メモを入力。別タブの再読み込みでお気に入り1人・選手メモ1人と本文を確認。確認後に両方を元の0件へ戻し、再取得で残存なしを確認。
- 開発側の実接続確認は同じブラウザの別タブ。2026/10/26、スマホ・PC間の同期確認の依頼にユーザーから「できたよ」と回答あり（ユーザー報告として記録）。別の実Googleアカウントでの動作は未確認。別アカウントの分離は実DBの合成2ユーザーテストで検証し、別ブラウザのUI・競合は合成バックエンドで検証済み。これらを混同しない。
- 最新mainに合わせ、Python 173件成功（283.36秒）、worker・Node2種・実ブラウザの合成テスト成功。

### 既存ブラウザのキャッシュ対策

- 実公開後、JSに `Cache-Control: public, max-age=14400, must-revalidate` が付くことを確認。既にサイトを見ているブラウザでは、古い設定や旧端末保存の処理が4時間残り得る。HTMLはmax-age=0。
- Page.assetで設定・共通ノートJS・時計・共通CSS・検索JSに内容のSHA256先頭12桁をクエリとして付ける。更新されたファイルだけURLが変わり、古いキャッシュを避ける。未変更ファイルのURLは安定させる。
- ファイル読込の指紋はパス・更新時刻・サイズ単位でメモ化し、全ページ生成での重複読込を避ける。入れ子ページでも相対パスを保持。
- 古い設定が残ってログイン欄が出なかった実ブラウザで、通常URLを再読み込みし、ログイン欄の表示・ボタン操作可能・画面エラーなしを確認済み。
- 対策後のPython全体テスト174件成功（272.27秒）、worker・Node2種・指紋付きURLでの合成ブラウザテストも成功。
- 新旧両ドメインの公開ノートHTMLと全共通アセットをHTTPで再取得し、指紋と配信内容が一致することを確認。旧ノート・必要なファイルが旧ドメインに保持されることも確認。
- Cloudflare公開処理成功: https://github.com/takochi92/minamoyomi/actions/runs/40234266805 （機能コード `cd86a752a3`）。
- 同じ機能コードのGitHubテスト・全ページ生成も成功: https://github.com/takochi92/minamoyomi/actions/runs/40234266627 。

## 変更対象外

予想AI、買い目、締切前固定記録、実績の計算、公開データバンクは変更しない。PWA・通知・有料会員は今回の範囲外。

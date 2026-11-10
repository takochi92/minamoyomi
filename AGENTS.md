# 艇ろぐを保守するAIへ

- この既存サイトのソースは `takochi92/minamoyomi`、本番は https://teilog.com、公開先はCloudflare Pagesの `teilog` です。
- 作業の最初に [MAINTAINING.md](MAINTAINING.md) の権限確認を実行し、[CLAUDE.md](CLAUDE.md) の業務ルールを読んでください。変更履歴は [HANDOFF.md](HANDOFF.md) です。
- 編集前に、使っている接続のアカウント、対象リポジトリへの書き込み、PR、Actionsの実行可否を確認してください。別AIの接続は、このPCのGitHub CLI認証を共有するとは限りません。
- `.github/workflows/` を変更する作業では、OAuthの `workflow` scopeまたは接続のWorkflows書き込み権限を先に確認してください。不足がある場合は、実装を積み上げる前に具体的な不足と本人の接続手順を伝えます。
- 既存のGitHub Actions Secretsを使って公開します。通常の編集でCloudflareキーの値をチャットへ求めたり、別の公開プロジェクトを作ったりしないでください。
- 生成されたHTMLではなく生成元を編集します。公開URLは拡張子なしに揃え、Search Console確認タグ・IndexNowキーを維持してください。
- ユーザーが本番反映を依頼している場合は、検査・PR・mainへの反映・Actionsの公開ステップ・実ページの確認まで進めます。権限確認を、既に許可済みの通常操作について再度許可を求める手順にしないでください。

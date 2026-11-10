# 艇ろぐの編集・公開手順

このリポジトリは既に公開中の https://teilog.com のソースです。所有者は GitHub の `takochi92`、リポジトリは `takochi92/minamoyomi` です。特定のAIや会話に依存する公開権限はありません。編集ツールには、このリポジトリへ書き込める本人のGitHub接続が必要です。

## まず権限を確認する

変更を始める前に、使う環境で次を実行します。この確認にはトークンの表示・貼り付けは必要ありません。

```sh
gh auth status --hostname github.com
gh api user --jq .login
gh api repos/takochi92/minamoyomi --jq .permissions
gh api repos/takochi92/minamoyomi/actions/workflows/update.yml --jq '{name,state}'
```

- `push: true` が、ソースを送れることの目安です。公開フローは `update-races`、ファイル名は `update.yml`、状態は `active` です。
- 別AIのGitHub接続は、このPCのログイン状態を共有するとは限りません。そのAIの接続先で、同じリポジトリへの書き込みとActionsの実行が可能かを確認してください。
- 接続先のアカウント名・リポジトリ・必要な操作を確認してから編集します。公開まで依頼された作業を、ローカル保存やPR作成だけで完了とは報告しません。

### このPCのGitHub CLI

2026年11月11日に、本人アカウント `takochi92` の既存認証をGitHub CLIのWindows資格情報ストアへ登録し、Gitと接続しました。今後の確認は `gh auth status` です。認証の取り消し・失効や別端末への移行時には、本人の再ログインが必要です。

別端末で初めて使う場合は、GitHub CLIで本人のブラウザ認証を行います。

```sh
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git --hostname github.com
```

既存ログインに不足がある場合は、アカウントを確認してから修復します。コマンド履歴、公開ソース、AIとの会話へトークンを貼り付けないでください。

### 公開手順ファイルを変更するとき

`.github/workflows/` の変更には、通常のソース書き込みに加えて権限が必要です。OAuth認証の場合は `gh auth status` のToken scopesに `workflow` があるか、編集前に確認します。不足時は次で本人承認を行います。

```sh
gh auth refresh --hostname github.com --scopes workflow
gh auth setup-git --hostname github.com
gh auth status --hostname github.com
```

GitHubの認証画面で、アカウントとアプリ名が正しいことを本人が確認してください。認証コードには有効期限があります。

別AIの接続やFine-grained tokenを使う場合は、`minamoyomi` に対して必要な操作だけ許可します。

| 操作 | 必要なリポジトリ権限 |
|---|---|
| ソース変更・ブランチ作成 | Contents / Read and write |
| PR作成・更新 | Pull requests / Read and write |
| 手動公開・再実行 | Actions / Read and write |
| `.github/workflows/` の変更 | Contents と Workflows / Read and write |

通常の画面修正と既存の公開フロー実行のために、公開用Cloudflareキーを編集AIへ渡す必要はありません。GitHubのブラウザ画面で本人が変更・マージ・手動実行する方法も利用できます。

## ソースを取得して編集する

```sh
gh repo clone takochi92/minamoyomi -- --depth 1
cd minamoyomi
git switch -c fix/変更内容
```

既存の作業フォルダがある場合は、リモートと未保存の変更を確認し、ユーザーの変更を保ったうえで最新mainに合わせます。履歴や集計データが大きいため、取得に時間がかかることがあります。途中まで取得したフォルダを完成したチェックアウトとして扱わないでください。

主な編集箇所は次のとおりです。

| 変更内容 | 主なソース |
|---|---|
| ページ共通部分・レース・結果のHTML | `scraper/sitegen.py` |
| 見た目 | `site/style.css` |
| ブラウザの動作 | `site/*.js` |
| 自動実行・公開の手順 | `.github/workflows/update.yml` |

`site/index.html` やレース・選手のHTMLは生成物です。公開時にソースから再生成されるため、生成元を修正します。公開URLは拡張子なし、一覧のindexは末尾スラッシュです。ファイル上の `.html` 名との区別を保ちます。

業務ルールと検査方法は [CLAUDE.md](CLAUDE.md)、過去の変更は [HANDOFF.md](HANDOFF.md) を参照してください。ルートの [AGENTS.md](AGENTS.md) は他のコーディングAI向けの入口です。

## 本番へ反映する

1. 変更を確認し、リポジトリで指定された検査を実行します。
2. ブランチをpushしてPRを作成し、本番反映の依頼がある場合は検証後にmainへマージします。
3. `update-races` の実行を確認します。ファイル別のpush起動条件があるため、起動しない変更では既存の手動実行を使います。

```sh
gh workflow run update.yml --repo takochi92/minamoyomi --ref main
gh run list --repo takochi92/minamoyomi --workflow update.yml --limit 5
```

表示された対象のrun IDで進行を確認します。

```sh
gh run watch RUN_ID --repo takochi92/minamoyomi --exit-status
gh run view RUN_ID --repo takochi92/minamoyomi --log-failed
```

ブラウザでの操作先は [update-races](https://github.com/takochi92/minamoyomi/actions/workflows/update.yml) です。`Run workflow` で `main` を選べます。

公開は既存のCloudflare Pagesプロジェクト `teilog` へGitHub Actionsから行います。通常の修正でプロジェクトやドメインを新設する必要はありません。

### 完了の確認

- Actionsの「Cloudflare Pages へ公開」が成功したか確認します。ワークフロー全体が成功でも、このステップがskippedなら公開完了とは扱いません。
- https://teilog.com の実ページを取得して、依頼された変更を確認します。
- 全ページ共通の変更時はキャッシュを再生成します。2026年11月の実測では全体生成に10分前後かかる場合があり、通常のレース差分更新より長くなります。並行実行は順番待ちになるため、同じ公開を何度も起動しないでください。

## 公開の設定と鍵

2026年11月11日の確認では、次の既存設定が揃い、公開成功履歴がありました。

| 場所 | 名前・値 |
|---|---|
| GitHub Actions Secret | `CLOUDFLARE_API_TOKEN` |
| GitHub Actions Secret | `CLOUDFLARE_ACCOUNT_ID` |
| GitHub Actions Variable | `CF_PROJECT_NAME=teilog` |
| GitHub Actions Variable | `SITE_URL=https://teilog.com` |

値の確認や再発行が必要なときは、本人のGitHub／Cloudflare管理画面で確認します。ソースの編集担当へ鍵の値を配布する構成にはしません。

## 反映できないときの切り分け

| 症状 | 最初の確認 |
|---|---|
| cloneや閲覧はできるがpushできない | GitHubのログイン先と、その接続のContents書き込み権限 |
| `.github/workflows/` の変更だけ拒否される | OAuthの `workflow` scope、または接続のWorkflows書き込み権限 |
| PRを作れない・Actionsを起動できない | 別AIの接続にPull requests／Actionsの権限があるか |
| mainに入れたのに公開が始まらない | pushの対象パス、順番待ち、既存の `workflow_dispatch` |
| 公開ステップがskipped | Cloudflare用Secretsの存在とワークフローの条件 |
| 公開ステップが401／403 | Cloudflare用キーの有効期限と対象アカウント・Pages権限 |
| Actions成功後も表示が違う | 本番ブランチ、公開対象ソース、生成物への直接編集になっていないか |

公開手順の根拠は [GitHub CLIの認証](https://cli.github.com/manual/gh_auth_login)、[追加scopeの承認](https://cli.github.com/manual/gh_auth_refresh)、[GitとCLIの接続](https://docs.github.com/en/github-cli/github-cli/authenticating-with-github-cli)、[Fine-grained tokenの権限一覧](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens) を参照してください。

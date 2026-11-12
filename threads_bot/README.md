# Threads 自動投稿ボット

AI（Claude）が毎回投稿文を考え、Threads の公式 API で1日3回自動投稿します。
GitHub Actions 上で動くので、自分のパソコンをつけっぱなしにする必要はありません。

## しくみ

```
GitHub Actions（毎日 7:47 / 12:13 / 19:38 ごろ ＋ 0〜10分のずれ）
  ① config.toml のテーマに沿って、Claude が投稿文を書く
  ② チェック（文字数・URL・#・NGワード・最近の投稿と似すぎていないか）
     → 不合格なら理由を伝えて書き直し（最大3回）
  ③ Threads 公式 API で投稿
  ④ 投稿内容を data/history.jsonl に保存（アカウントに何かあっても手元に残る）

毎週1回: Threads のトークン（60日で切れる）を自動で延長
```

## 最初の設定（1回だけ）

画面の名前やボタンの位置は、各サービスの更新で変わることがあります。

### 手順0：このボットを main ブランチに取り込む

定期実行は main ブランチにあるファイルでしか動きません。このブランチのプルリクエストをマージしてください。

### 手順1：Threads 専用のアカウントを用意する

仕事や私生活で大事な Instagram とは別の、このテーマ専用のアカウントを使ってください。

### 手順2：Claude（Anthropic）の API キーを作る

1. https://console.anthropic.com にログインし、支払い方法を登録してクレジットを購入します（使った分だけの課金です）。
2. 「API Keys」でキーを作り、表示されたキーをコピーします（一度しか表示されません）。
3. GitHub のこのリポジトリで **Settings → Secrets and variables → Actions → Secrets → New repository secret** を開き、
   名前 `ANTHROPIC_API_KEY`、値にコピーしたキーを貼って保存します。

### 手順3：Meta（Threads）のアプリを作る

1. https://developers.facebook.com にログインし、アプリを新しく作ります。ユースケースは「Threads API にアクセス」を選びます。
2. 権限に `threads_basic` と `threads_content_publish` を追加します。
3. Threads の設定にある「リダイレクトコールバックURL」に、次をそのまま登録します。
   ```
   https://github.com/asumorita/auto-scheduler/
   ```
4. 「アプリの役割」で、手順1のアカウントを **Threads テスター** として追加します。
   そのあと Threads 側（設定 → アカウント → ウェブサイトのアクセス許可 → 招待）で招待を承認します。
   自分のアカウントに投稿するだけなら、アプリの審査は不要です。
5. Threads の設定画面にある **Threads アプリID** と **Threads app secret** を控えます。
6. GitHub の **Settings → Secrets and variables → Actions** で、次を登録します。
   - **Variables** タブ：名前 `THREADS_APP_ID`、値に Threads アプリID
   - **Secrets** タブ：名前 `THREADS_APP_SECRET`、値に Threads app secret

### 手順4：トークンを自動保存するための GitHub トークンを作る

Threads のトークンは60日で切れるので、ボットが自動で延長して Secrets に保存し直します。そのための鍵です。

1. GitHub 右上のアイコン → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
2. Repository access：**Only select repositories** で `auto-scheduler` だけを選びます。
3. Permissions → Repository permissions → **Secrets** を **Read and write** にします。
4. 有効期限は選べる中で長めにして作成し、表示されたトークンをコピーします。
5. このリポジトリの Secrets に、名前 `GH_PAT_FOR_SECRETS` で登録します。

### 手順5：Threads と接続する

1. このリポジトリの **Actions → Threads 初期設定 → Run workflow** を開き、「1. 認証用URLを表示」を選んで実行します。
2. 実行結果のページに出る「Threads で許可する」リンクを開き、手順1のアカウントで許可します。
3. 許可したあとに開いたページのURL（アドレスバーの内容、`?code=` を含む）を丸ごとコピーします。
4. もう一度 **Threads 初期設定 → Run workflow** を開き、「2. コードからトークンを保存」を選び、コピーしたURLを貼って実行します。
5. 緑のチェックになれば、`THREADS_ACCESS_TOKEN` が Secrets に保存されています。

コードは1時間で無効になる使い捨てのものです。公開リポジトリでは実行時の入力が他の人にも見えることがありますが、app secret がなければ使えません。

### 手順6：テスト実行（投稿はしません）

**Actions → Threads 自動投稿 → Run workflow** を、「テスト実行」にチェックが入ったまま実行します。
実行結果のページに、AI が作った投稿文と接続先のアカウント名が表示されます。内容を確認してください。

### 手順7：自動投稿を始める

**Settings → Secrets and variables → Actions → Variables** で、名前 `THREADS_BOT_ENABLED`、値 `true` を登録します。
次の予定時刻から自動で投稿が始まります。

## 止めるとき

Variables の `THREADS_BOT_ENABLED` を `false` に変えます（または削除します）。投稿もトークンの自動更新も止まります。

## 内容を変えるとき

`threads_bot/config.toml` を GitHub の画面で編集して保存します。テーマ・読者・文体・NGワード・投稿パターンを変えられます。

- **投稿時刻・回数**：`.github/workflows/threads-post.yml` の `cron` の行を増減します（時刻は UTC で書きます。日本時間から9時間引いた時刻です）。
- **リンクを付ける**：`[link]` の `url` にサイトのURLを入れ、`every` に「何回に1回付けるか」を入れます。リンク付きの投稿には先頭に `【PR】` が付きます。

## 料金の目安

- **GitHub Actions**：公開リポジトリは無料です。
- **Threads API**：無料です。
- **Claude API**：使った分だけかかります。モデル `claude-opus-5-5` の料金は100万トークンあたり入力 $4／出力 $20 です。
  1投稿あたり入力 約3,500トークン、出力（考える分を含む）数百〜2,000トークン程度と見込むと、**1投稿 $0.03〜0.06、1日3投稿で月 $3〜6 程度**です。
  これは見積もりです。実際の金額は https://console.anthropic.com の使用状況で確認してください。

## 安全のための決まりごと

- 1日3回と控えめな頻度にしています。回数を大きく増やすと、スパム判定でアカウントが止められる可能性が上がります。
- 自動で行うのは投稿だけです。自動フォロー・いいね・返信・DM はしません。
- AI には「体験談・実績・数字をでっちあげない」「誇大な表現をしない」と指示しています。それでも誤りはあり得るので、ときどき投稿を見て確認してください。

## うまく動かないとき

- 失敗すると GitHub から通知メールが届き、Actions の画面に赤いバツが付きます。そのページのログに、日本語で原因が出ます。
- 公開リポジトリでは、60日間リポジトリに更新がないと定期実行が自動で止まります。ボットは投稿のたびに履歴を保存して更新するので、通常は止まりません。止まった場合は Actions 画面で再度有効にしてください。
- 初期設定の直後は、トークンの自動更新が「まだ更新できない」と表示されることがあります。発行から24時間たつと更新できるようになるので、そのままで大丈夫です。

## 開発者向け

```bash
pip install -r threads_bot/requirements.txt
python -m unittest discover -s threads_bot/tests -t .   # テスト（外部 API は呼びません）
DRY_RUN=true python -m threads_bot.post                  # 投稿文を作るだけ（ANTHROPIC_API_KEY が必要）
```

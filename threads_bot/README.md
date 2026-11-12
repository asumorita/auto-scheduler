# Threads 自動投稿ボット（@200sai_life 用）

AI（Claude）が毎回投稿文を考え、Threads の公式 API で1日12回自動投稿します。
GitHub Actions 上で動くので、自分のパソコンをつけっぱなしにする必要はありません。

## しくみ

```
GitHub Actions（毎日 6:47〜22:31 の間に約1時間半おき・12回 ＋ 0〜10分のずれ）
  ① config.toml のテーマ・話題・切り口に沿って、Claude が投稿文を書く
  ② チェック（4〜8行・120〜350文字・URL や # がない・NGワードがない・最近の投稿と似すぎていない）
     → 不合格なら理由を伝えて書き直し（最大3回）
  ③ Threads 公式 API で投稿（トピック「健康」付き）
  ④ 投稿内容を data/history.jsonl に保存（アカウントに何かあっても手元に残る）

毎週1回: Threads のトークン（60日で切れる）を自動で延長
```

- 投稿は**リンクなしの文章だけ**です。楽天のリンクは、ご自身で別に投稿してください。
- 自動投稿は `config.toml` の `enabled = true` のときだけ動きます。

## 最初の設定

画面の名前やボタンの位置は、各サービスの更新で変わることがあります。

### あなたにお願いする作業

**A. Claude（Anthropic）の API キーを作って登録する**

1. https://console.anthropic.com にログインし、支払い方法を登録してクレジットを購入します（使った分だけの課金です）。
2. 「API Keys」でキーを作ってコピーします（一度しか表示されません）。
3. GitHub のこのリポジトリで **Settings → Secrets and variables → Actions → New repository secret** を開き、
   名前 `ANTHROPIC_API_KEY`、値にコピーしたキーを貼って保存します。

**B. Meta（Threads）のアプリを作る**

1. https://developers.facebook.com にログインし、アプリを新しく作ります。ユースケースは「Threads API にアクセス」を選びます。
2. 権限に `threads_basic` と `threads_content_publish` を追加します。
3. Threads の設定にある「リダイレクトコールバックURL」に、次をそのまま登録します。
   ```
   https://github.com/asumorita/auto-scheduler/
   ```
4. 「アプリの役割」で `200sai_life` を **Threads テスター** として追加します。
   そのあと Threads 側（設定 → アカウント → ウェブサイトのアクセス許可 → 招待）で招待を承認します。
   自分のアカウントに投稿するだけなら、アプリの審査は不要です。
5. **Threads app secret** を、A と同じ画面で名前 `THREADS_APP_SECRET` として登録します。
6. **Threads アプリID** を Claude に伝えるか、`config.toml` の `[threads]` の `app_id` に入れます（秘密の情報ではありません）。

**C. トークンを自動保存するための GitHub トークンを作る**

Threads のトークンは60日で切れるので、ボットが自動で延長して保存し直します。そのための鍵です。

1. GitHub 右上のアイコン → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
2. Repository access：**Only select repositories** で `auto-scheduler` だけを選びます。
3. Permissions → Repository permissions → **Secrets** を **Read and write** にします。
4. 有効期限は選べる中で長めにして作成し、表示されたトークンをコピーします。
5. A と同じ画面で、名前 `GH_PAT_FOR_SECRETS` として登録します。

**D. Threads との接続を許可する**

1. **Actions → Threads 初期設定 → Run workflow** で「1. 認証用URLを表示」を実行し、結果ページの「Threads で許可する」を開きます（Claude がリンクを渡すこともできます）。
2. `200sai_life` で許可したあとに開いたページのURL（`?code=` を含む）を丸ごとコピーします。
3. **Threads 初期設定 → Run workflow** で「2. コードからトークンを保存」を選び、URLを貼って実行します（URL を Claude に渡せば、代わりに実行できます）。

コードは1時間で無効になる使い捨てのものです。app secret がなければ使えません。

### そのあと（Claude が代わりにできる作業）

1. **Threads 自動投稿** をテスト実行（投稿しない）して、AI が書いた投稿文を確認する
2. 問題なければ `config.toml` の `enabled` を `true` にする → 次の予定時刻から自動投稿が始まる

## 止めるとき

`threads_bot/config.toml` の `enabled` を `false` にして保存します。

## 内容を変えるとき

`threads_bot/config.toml` を GitHub の画面で編集して保存します。

- **美容・コスメに広げる**：`theme`（テーマ）と `topics`（話題の一覧）を書き換えます。健康の話題と混ぜても構いません。
- **長さ**：`min_chars` / `max_chars`（文字数）、`min_lines` / `max_lines`（行数）。
- **書き方**：`persona`（人物像）、`tone`（文体）、`formats`（切り口）。
- **投稿時刻・回数**：`.github/workflows/threads-post.yml` の `cron` の行を増減します（UTC で書きます。日本時間から9時間引いた時刻です）。

## 料金の目安

- **GitHub Actions**：公開リポジトリは無料です。
- **Threads API**：無料です。
- **Claude API**：使った分だけかかります。モデル `claude-opus-5-5` の料金は100万トークンあたり入力 $4／出力 $20 です。
  1投稿あたり入力 約4,000トークン、出力（考える分を含む）数百〜2,000トークン程度と見込むと、**1投稿 $0.03〜0.06、1日12投稿で月 $11〜22 程度**です。
  これは見積もりです。実際の金額は https://console.anthropic.com の使用状況で確認してください。
  `config.toml` の `effort` を `low` にすると、考える量が減って安くなります（文章の質が下がる可能性があります）。

## 安全のための決まりごと

- 健康の話なので、AI には次のように指示しています。病気が治る・予防できると言い切らない、商品の効き目をうたわない（薬機法・健康増進法）、数字や出典を作らない、特定の人物や具体的な成果をでっちあげない、家族の不幸など個人的な出来事は書かない。
- 自動で行うのは投稿だけです。自動フォロー・いいね・返信・DM はしません。
- 1日12回は、スパム判定の基準（非公開）に近づく可能性があります。アカウントに制限がかかったら、回数を減らしてください。
- それでも AI が誤ったことを書く可能性はあるので、ときどき投稿を見て確認してください。

## うまく動かないとき

- 失敗すると GitHub から通知メールが届き、Actions の画面に赤いバツが付きます。そのページのログに日本語で原因が出ます。
- 公開リポジトリでは、60日間リポジトリに更新がないと定期実行が自動で止まります。ボットは投稿のたびに履歴を保存して更新するので、通常は止まりません。
- 初期設定の直後は、トークンの自動更新で「まだ更新できない」と表示されることがあります。発行から24時間たてば更新できるので、そのままで大丈夫です。

## 開発者向け

```bash
pip install -r threads_bot/requirements.txt
python -m unittest discover -s threads_bot/tests -t .   # テスト（外部 API は呼びません）
DRY_RUN=true python -m threads_bot.post                  # 投稿文を作るだけ（ANTHROPIC_API_KEY が必要）
```

# 録音→文字起こし→Google Docs 全自動化システム

Apple Silicon (M1/M2/M3) Mac で「録音停止」するだけで Google Docs に議事録が自動生成される仕組みです。

```
録音ファイル保存
    ↓ (自動検知: launchd WatchPaths)
whisper.cpp で文字起こし (Metal GPU / ローカル完結)
    ↓ (Claude API でタイトル自動生成)
Google Docs に保存
    ↓ (macOS 通知)
完了通知 "文字起こし完了 ✓"
```

## 特徴

- **完全ローカル処理**: 音声データはクラウドに送信しない
- **高速**: Metal GPU による whisper.cpp で 1時間音声を数分で処理
- **自動化**: ファイルを保存するだけ、操作不要
- **AI タイトル**: Claude Haiku が内容を要約してドキュメント名を自動生成

---

## セットアップ手順

### 1. システムビルド

```bash
bash ~/whisper-gdocs/setup.sh
```

内部処理:
- cmake インストール
- whisper.cpp のクローン & Metal GPU 対応ビルド
- large-v3-turbo モデルのダウンロード (~600MB)
- Python 仮想環境の構築

### 2. Google API 認証情報の取得 (必須)

#### 2-1. Google Cloud Console でプロジェクト作成

1. [console.cloud.google.com](https://console.cloud.google.com/) を開く
2. 上部の「プロジェクトを選択」→「新しいプロジェクト」
3. プロジェクト名: `whisper-gdocs` など任意
4. 「作成」をクリック

#### 2-2. API を有効化

左メニュー「APIとサービス」→「ライブラリ」で以下を検索して有効化:
- **Google Docs API**
- **Google Drive API**

#### 2-3. OAuth 認証情報の作成

1. 「APIとサービス」→「認証情報」→「認証情報を作成」→「OAuth クライアント ID」
2. 同意画面の設定: 「外部」→ 必要項目を入力
3. アプリの種類: **「デスクトップ アプリ」** を選択
4. 名前: `whisper-gdocs` など
5. 「作成」→ 「JSON をダウンロード」

#### 2-4. 認証情報を配置

```bash
mv ~/Downloads/client_secret_*.json \
   ~/whisper-gdocs/credentials/credentials.json
```

### 3. (任意) Claude API キーの設定

タイトル自動生成に使用します。設定しない場合は文字起こし冒頭がタイトルになります。

```bash
echo "sk-ant-xxxxxxxxxxxxx" > ~/whisper-gdocs/credentials/anthropic_api_key.txt
```

API キーは [console.anthropic.com](https://console.anthropic.com/) で取得できます。

### 4. 自動起動エージェントのインストール

```bash
bash ~/whisper-gdocs/install_launchd.sh
```

初回 Google 認証: 次にファイルを保存したとき、ブラウザが開いて Google アカウントのログインを求めます。許可するとトークンが保存され、以後は不要です。

---

## 使い方

### 通常の録音フロー

**方法 A: ボイスメモアプリ**
1. ボイスメモで録音
2. 録音を右クリック →「ファイルに書き出す」→ 監視フォルダに保存

**方法 B: 監視フォルダに直接保存**
- 監視フォルダ: `~/Documents/Recordings/`
- 対応形式: `.m4a`, `.wav`, `.mp3`, `.aiff`, `.aac`, `.flac`, `.ogg`, `.mp4`

ファイルを保存すると数秒〜数分後に macOS 通知が届き、Google Docs にドキュメントが作成されます。

### テスト実行

```bash
# 自分の音声ファイルでテスト
bash ~/whisper-gdocs/test_pipeline.sh ~/Desktop/sample.m4a

# ダミー音声（無音）でパイプラインをテスト
bash ~/whisper-gdocs/test_pipeline.sh --generate-test
```

### ログ確認

```bash
# リアルタイムログ
tail -f ~/whisper-gdocs/logs/whisper.log

# エラーログ
tail -f ~/whisper-gdocs/logs/launchd_stderr.log

# 処理履歴（JSON）
cat ~/Documents/Recordings/.whisper_state.json | python3 -m json.tool
```

---

## ファイル構成

```
~/whisper-gdocs/
├── setup.sh                    # 初期セットアップ
├── install_launchd.sh          # launchd エージェント設定
├── test_pipeline.sh            # テスト実行
├── transcribe_and_upload.py    # メイン処理スクリプト
├── com.user.whisperwatch.plist # launchd 設定
├── requirements.txt            # Python 依存パッケージ
├── venv/                       # Python 仮想環境
├── whisper.cpp/                # whisper.cpp ソース & モデル
│   ├── build/bin/whisper-cli  # コンパイル済みバイナリ
│   └── models/
│       └── ggml-large-v3-turbo.bin
├── credentials/                # 認証情報 (Git 除外)
│   ├── credentials.json       # Google OAuth クライアント
│   ├── token.json             # 認証トークン (自動生成)
│   └── anthropic_api_key.txt  # Claude API キー (任意)
└── logs/
    ├── whisper.log
    ├── launchd_stdout.log
    └── launchd_stderr.log

~/Documents/Recordings/         # 監視フォルダ (音声をここに保存)
└── .whisper_state.json         # 処理済みファイルの記録
```

---

## launchd エージェント管理

```bash
# 停止
launchctl unload ~/Library/LaunchAgents/com.user.whisperwatch.plist

# 起動
launchctl load ~/Library/LaunchAgents/com.user.whisperwatch.plist

# 状況確認
launchctl list | grep whisperwatch

# 手動実行 (テスト用)
~/whisper-gdocs/venv/bin/python3 ~/whisper-gdocs/transcribe_and_upload.py
```

---

## トラブルシューティング

### whisper バイナリが見つからない
```bash
bash ~/whisper-gdocs/setup.sh  # 再実行
```

### Google 認証エラー
```bash
# トークンを削除して再認証
rm ~/whisper-gdocs/credentials/token.json
~/whisper-gdocs/venv/bin/python3 ~/whisper-gdocs/transcribe_and_upload.py
```

### 日本語文字化け
```bash
# ロケールを確認
locale
# LANG=ja_JP.UTF-8 が設定されているか確認
```

### 処理済みリセット (再処理したい場合)
```bash
# 特定ファイルを再処理
python3 - << 'EOF'
import json
from pathlib import Path
state_file = Path.home() / "Documents/Recordings/.whisper_state.json"
state = json.loads(state_file.read_text())
state["processed"].remove("ファイル名.m4a")  # 削除したいファイル名
state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False))
print("Done")
EOF
```

---

## Core ML 追加最適化 (上級者向け)

Metal GPU よりさらに高速にしたい場合 (Apple Neural Engine を使用):

```bash
# 追加ツールのインストール
~/whisper-gdocs/venv/bin/pip install coremltools openai-whisper ane-transformers

# Core ML モデルの生成
cd ~/whisper-gdocs/whisper.cpp
python3 models/generate-coreml-model.py large-v3-turbo

# Core ML 有効でリビルド
cmake -B build -DCMAKE_BUILD_TYPE=Release -DWHISPER_COREML=1 -DGGML_METAL=ON
cmake --build build -j$(sysctl -n hw.logicalcpu)
```

---

## Google Docs 出力フォーマット

```
■ タイトル　: [AI生成タイトル]
■ 元ファイル: 20240301_meeting.m4a
■ 処理日時　: 2024年03月01日 14:30
■ 文字数　　: 5,432文字
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[文字起こし全文]
```

ドキュメント名: `20240301_1430_録音文字起こし_プロジェクト進捗会議`

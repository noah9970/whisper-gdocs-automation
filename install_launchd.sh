#!/bin/bash
# ============================================================
# install_launchd.sh - launchd エージェントのインストール/更新
# ============================================================
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

PLIST_NAME="com.user.whisperwatch"
PLIST_SRC="$HOME/whisper-gdocs/$PLIST_NAME.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
RECORDINGS_DIR="$HOME/Documents/Recordings"

echo ""
echo -e "${YELLOW}=== launchd エージェント インストール ===${NC}"
echo ""

# 前提確認
if [ ! -f "$PLIST_SRC" ]; then
    echo -e "${RED}エラー: $PLIST_SRC が見つかりません${NC}"
    exit 1
fi

if [ ! -f "$HOME/whisper-gdocs/venv/bin/python3" ]; then
    echo -e "${RED}エラー: Python 環境が未作成です。先に setup.sh を実行してください${NC}"
    exit 1
fi

# 録音フォルダ作成
mkdir -p "$RECORDINGS_DIR"
echo -e "${GREEN}✓ 監視フォルダ: $RECORDINGS_DIR${NC}"

# 既存のエージェントを停止
if launchctl list 2>/dev/null | grep -q "$PLIST_NAME"; then
    echo "  既存のエージェントを停止中..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
fi

# LaunchAgents ディレクトリ作成
mkdir -p "$HOME/Library/LaunchAgents"

# plist をインストール
cp "$PLIST_SRC" "$PLIST_DST"
chmod 644 "$PLIST_DST"

# エージェントを起動
launchctl load "$PLIST_DST"

# 確認
if launchctl list | grep -q "$PLIST_NAME"; then
    echo -e "${GREEN}✓ launchd エージェント起動完了${NC}"
else
    echo -e "${RED}警告: エージェントの起動確認ができませんでした${NC}"
fi

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     自動化システム 稼働開始！             ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════╝${NC}"
echo ""
echo "監視フォルダ: $RECORDINGS_DIR"
echo ""
echo "使い方:"
echo "  音声ファイル (.m4a/.wav/.mp3 等) を上記フォルダに保存すると"
echo "  自動的に文字起こし → Google Docs 保存が実行されます"
echo ""
echo "ログ確認:"
echo "  tail -f $HOME/whisper-gdocs/logs/whisper.log"
echo ""
echo "管理コマンド:"
echo "  停止: launchctl unload $PLIST_DST"
echo "  起動: launchctl load   $PLIST_DST"
echo "  状況: launchctl list | grep whisperwatch"
echo ""

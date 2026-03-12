#!/bin/bash
# ============================================================
# record.sh - MacBook マイク録音 → 自動文字起こし
# 使い方: bash ~/whisper-gdocs/record.sh
# ============================================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

RECORDINGS_DIR="$HOME/Documents/Recordings"
DATE=$(date +%Y%m%d_%H%M%S)
OUTPUT="$RECORDINGS_DIR/recording_$DATE.m4a"

mkdir -p "$RECORDINGS_DIR"

echo ""
echo -e "${YELLOW}🎙  録音準備中...${NC}"
echo ""

# マイク確認
if ! ffmpeg -f avfoundation -list_devices true -i "" 2>&1 | grep -q "MacBook"; then
    echo -e "${RED}エラー: マイクが見つかりません${NC}"
    exit 1
fi

echo -e "${GREEN}● 録音開始！${NC}  (Enter キーで停止)"
echo ""

# macOS 通知
osascript -e 'display notification "録音中... Enterキーで停止" with title "🎙 録音開始"' 2>/dev/null

# バックグラウンドで録音開始 (ビデオなし:video=-1、オーディオ=0)
ffmpeg -f avfoundation -i "none:0" \
    -c:a aac -b:a 128k \
    -loglevel quiet \
    "$OUTPUT" &
FFMPEG_PID=$!

# 録音開始を確認
sleep 1
if ! kill -0 $FFMPEG_PID 2>/dev/null; then
    echo -e "${RED}エラー: 録音を開始できませんでした${NC}"
    echo "マイクへのアクセス許可を確認してください:"
    echo "  システム設定 → プライバシーとセキュリティ → マイク → ターミナル をオン"
    exit 1
fi

# 録音時間カウンター
START_TIME=$(date +%s)
echo -n "   経過時間: "

# Enter キーを待ちながら時間表示
while kill -0 $FFMPEG_PID 2>/dev/null; do
    ELAPSED=$(( $(date +%s) - START_TIME ))
    MINS=$(( ELAPSED / 60 ))
    SECS=$(( ELAPSED % 60 ))
    printf "\r   経過時間: %02d:%02d  (Enter で停止)" $MINS $SECS

    # ノンブロッキングでEnterキーチェック
    if read -t 1 -r; then
        break
    fi
done

echo ""
echo ""

# 録音停止
if kill -0 $FFMPEG_PID 2>/dev/null; then
    kill -SIGINT $FFMPEG_PID
    wait $FFMPEG_PID 2>/dev/null
fi

# ファイル確認
if [ -f "$OUTPUT" ] && [ -s "$OUTPUT" ]; then
    SIZE=$(du -h "$OUTPUT" | cut -f1)
    echo -e "${GREEN}✓ 録音完了！${NC}"
    echo "  ファイル: recording_$DATE.m4a ($SIZE)"
    echo "  保存先 : $RECORDINGS_DIR"
    echo ""
    echo -e "${YELLOW}→ 文字起こしが自動開始されます...${NC}"
    echo "  完了時に macOS 通知が届きます"
    echo ""

    # macOS 通知
    osascript -e 'display notification "文字起こしを開始しています..." with title "✓ 録音完了"' 2>/dev/null
else
    echo -e "${RED}エラー: ファイルの保存に失敗しました${NC}"
    exit 1
fi

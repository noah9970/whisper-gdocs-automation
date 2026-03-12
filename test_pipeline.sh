#!/bin/bash
# ============================================================
# test_pipeline.sh - パイプラインのテスト実行
# 使い方: bash test_pipeline.sh [音声ファイルパス]
# ============================================================

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

PROJECT_DIR="$HOME/whisper-gdocs"
RECORDINGS_DIR="$HOME/Documents/Recordings"

echo ""
echo -e "${YELLOW}=== Whisper パイプライン テスト ===${NC}"
echo ""

# ── 引数チェック ─────────────────────────────────────────────────
if [ $# -eq 0 ]; then
    echo "使い方: bash test_pipeline.sh <音声ファイル>"
    echo ""
    echo "例:"
    echo "  bash test_pipeline.sh ~/Desktop/meeting.m4a"
    echo "  bash test_pipeline.sh ~/Desktop/voice.wav"
    echo ""
    echo "ダミー音声でテストする場合:"
    echo "  bash test_pipeline.sh --generate-test"
    exit 0
fi

# ── ダミー音声生成モード ─────────────────────────────────────────
if [ "$1" = "--generate-test" ]; then
    echo "ダミー音声ファイルを生成中..."
    TEST_WAV="$RECORDINGS_DIR/test_audio_$(date +%Y%m%d_%H%M%S).wav"
    # 5秒間の無音 WAV を生成
    ffmpeg -f lavfi -i anullsrc=channel_layout=mono:sample_rate=16000 \
        -t 5 -c:a pcm_s16le "$TEST_WAV" -y -loglevel quiet
    echo -e "${GREEN}✓ テスト音声: $TEST_WAV${NC}"
    AUDIO_FILE="$TEST_WAV"
else
    AUDIO_FILE="$1"
    if [ ! -f "$AUDIO_FILE" ]; then
        echo -e "${RED}エラー: ファイルが見つかりません: $AUDIO_FILE${NC}"
        exit 1
    fi
fi

# ── 依存関係チェック ────────────────────────────────────────────
echo "依存関係を確認中..."

# whisper バイナリ
WHISPER_BIN=""
for bin in \
    "$PROJECT_DIR/whisper.cpp/build/bin/whisper-cli" \
    "$PROJECT_DIR/whisper.cpp/build/bin/main"; do
    if [ -f "$bin" ] && [ -x "$bin" ]; then
        WHISPER_BIN="$bin"
        break
    fi
done

if [ -z "$WHISPER_BIN" ]; then
    echo -e "${RED}✗ whisper バイナリなし → bash setup.sh を実行してください${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓ whisper: $WHISPER_BIN${NC}"

# モデル
MODEL=""
for m in \
    "$PROJECT_DIR/whisper.cpp/models/ggml-large-v3-turbo.bin" \
    "$PROJECT_DIR/whisper.cpp/models/ggml-large-v3.bin" \
    "$PROJECT_DIR/whisper.cpp/models/ggml-medium.bin"; do
    if [ -f "$m" ]; then
        MODEL="$m"
        break
    fi
done

if [ -z "$MODEL" ]; then
    echo -e "${RED}✗ Whisper モデルなし → bash setup.sh を実行してください${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓ モデル: $(basename $MODEL)${NC}"

# Python venv
if [ ! -f "$PROJECT_DIR/venv/bin/python3" ]; then
    echo -e "${RED}✗ Python venv なし → bash setup.sh を実行してください${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓ Python venv: OK${NC}"

# ffmpeg
if ! command -v ffmpeg &>/dev/null; then
    echo -e "${RED}✗ ffmpeg なし → brew install ffmpeg${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓ ffmpeg: OK${NC}"

echo ""

# ── ファイルを監視フォルダにコピー ──────────────────────────────
BASENAME=$(basename "$AUDIO_FILE")
DEST="$RECORDINGS_DIR/$BASENAME"

if [ "$AUDIO_FILE" != "$DEST" ]; then
    cp "$AUDIO_FILE" "$DEST"
    echo -e "${YELLOW}→ $RECORDINGS_DIR/ にコピーしました${NC}"
    echo "  ファイル: $BASENAME"
else
    echo -e "${YELLOW}→ 既に監視フォルダにあります: $BASENAME${NC}"
fi

echo ""
echo "パイプラインを直接実行中..."
echo "（通常は launchd が自動的に起動します）"
echo ""

# ── 直接実行 ────────────────────────────────────────────────────
"$PROJECT_DIR/venv/bin/python3" "$PROJECT_DIR/transcribe_and_upload.py"

echo ""
echo -e "${GREEN}=== テスト完了 ===${NC}"
echo "ログ: tail -f $PROJECT_DIR/logs/whisper.log"
echo ""

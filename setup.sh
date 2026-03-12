#!/bin/bash
# ============================================================
# setup.sh - Whisper + Google Docs 自動化環境セットアップ
# Apple Silicon (M1/M2/M3) Mac 最適化版
# ============================================================
set -euo pipefail

# カラー表示
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_DIR="$HOME/whisper-gdocs"
WHISPER_DIR="$PROJECT_DIR/whisper.cpp"
VENV_DIR="$PROJECT_DIR/venv"

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Whisper + Google Docs 自動化セットアップ    ║${NC}"
echo -e "${BLUE}║  Apple Silicon (M1/M2/M3) Metal GPU対応      ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: cmake ────────────────────────────────────────────
echo -e "${YELLOW}[1/6] cmake を確認...${NC}"
if ! command -v cmake &>/dev/null; then
    echo "  cmake をインストール中..."
    brew install cmake
fi
echo -e "${GREEN}  ✓ cmake: $(cmake --version | head -1)${NC}"

# ── Step 2: whisper.cpp クローン ─────────────────────────────
echo -e "${YELLOW}[2/6] whisper.cpp を準備...${NC}"
if [ ! -d "$WHISPER_DIR/.git" ]; then
    echo "  cloning whisper.cpp..."
    git clone https://github.com/ggml-org/whisper.cpp "$WHISPER_DIR"
    echo -e "${GREEN}  ✓ クローン完了${NC}"
else
    echo "  最新版に更新中..."
    git -C "$WHISPER_DIR" pull --ff-only 2>/dev/null || echo "  (更新スキップ)"
    echo -e "${GREEN}  ✓ 既存の whisper.cpp を使用${NC}"
fi

# ── Step 3: Metal GPU 対応でビルド ───────────────────────────
echo -e "${YELLOW}[3/6] whisper.cpp をビルド (Metal GPU 有効)...${NC}"
cd "$WHISPER_DIR"

# Metal GPUはApple Siliconでデフォルト有効、GGML_METALで明示指定
cmake -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DGGML_METAL=ON \
    -DWHISPER_BUILD_EXAMPLES=ON \
    2>&1 | tail -5

cmake --build build \
    --config Release \
    -j"$(sysctl -n hw.logicalcpu)" \
    2>&1 | tail -10

# バイナリ探索
WHISPER_BIN=""
for candidate in \
    "$WHISPER_DIR/build/bin/whisper-cli" \
    "$WHISPER_DIR/build/bin/main"; do
    if [ -f "$candidate" ] && [ -x "$candidate" ]; then
        WHISPER_BIN="$candidate"
        break
    fi
done

if [ -z "$WHISPER_BIN" ]; then
    echo -e "${RED}  ✗ whisper バイナリが見つかりません。ビルドを確認してください${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓ バイナリ: $WHISPER_BIN${NC}"

# ── Step 4: モデルダウンロード ───────────────────────────────
echo -e "${YELLOW}[4/6] 日本語モデルをダウンロード...${NC}"
MODEL_DIR="$WHISPER_DIR/models"
PREFERRED_MODEL="large-v3-turbo"
PREFERRED_FILE="$MODEL_DIR/ggml-large-v3-turbo.bin"
FALLBACK_MODEL="large-v3"
FALLBACK_FILE="$MODEL_DIR/ggml-large-v3.bin"

if [ -f "$PREFERRED_FILE" ]; then
    echo -e "${GREEN}  ✓ large-v3-turbo モデル既存${NC}"
elif [ -f "$FALLBACK_FILE" ]; then
    echo -e "${GREEN}  ✓ large-v3 モデル既存${NC}"
else
    echo "  large-v3-turbo モデルをダウンロード中 (~600MB)..."
    cd "$WHISPER_DIR"
    if bash models/download-ggml-model.sh "$PREFERRED_MODEL" 2>&1; then
        echo -e "${GREEN}  ✓ large-v3-turbo ダウンロード完了${NC}"
    else
        echo "  fallback: large-v3 をダウンロード中 (~1.5GB)..."
        bash models/download-ggml-model.sh "$FALLBACK_MODEL"
        echo -e "${GREEN}  ✓ large-v3 ダウンロード完了${NC}"
    fi
fi

# ── Step 5: Python 仮想環境 ──────────────────────────────────
echo -e "${YELLOW}[5/6] Python 環境を構築...${NC}"
cd "$PROJECT_DIR"

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "  venv 作成完了"
fi

echo "  依存パッケージをインストール中..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt" -q
echo -e "${GREEN}  ✓ Python 依存関係インストール完了${NC}"

# ── Step 6: ディレクトリ整備 ─────────────────────────────────
echo -e "${YELLOW}[6/6] ディレクトリを整備...${NC}"
mkdir -p "$PROJECT_DIR/credentials"
mkdir -p "$PROJECT_DIR/logs"
mkdir -p "$HOME/Documents/Recordings"
echo -e "${GREEN}  ✓ ~/Documents/Recordings (監視フォルダ) 作成${NC}"

# ── 完了サマリー ─────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          セットアップ完了！                  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo "次のステップ:"
echo "  1. Google API 認証情報を取得 (README.md を参照)"
echo "  2. credentials.json を配置:"
echo "       $PROJECT_DIR/credentials/credentials.json"
echo "  3. 自動起動を有効化:"
echo "       bash $PROJECT_DIR/install_launchd.sh"
echo ""
echo "任意: Claude API タイトル生成を有効化:"
echo "  ANTHROPIC_API_KEY を以下に保存:"
echo "       $PROJECT_DIR/credentials/anthropic_api_key.txt"
echo ""

#!/usr/bin/env python3
"""
transcribe_and_upload.py
録音ファイル自動文字起こし & Google Docs アップロード

launchd の WatchPaths により ~/Documents/Recordings に
新しい音声ファイルが追加されると自動的に実行されます。
"""

import os
import sys
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime
import logging

# ── 設定 ────────────────────────────────────────────────────────
PROJECT_DIR    = Path.home() / "whisper-gdocs"
RECORDINGS_DIR = Path.home() / "Documents" / "Recordings"
STATE_FILE     = RECORDINGS_DIR / ".whisper_state.json"
CREDENTIALS    = PROJECT_DIR / "credentials" / "credentials.json"
TOKEN_FILE     = PROJECT_DIR / "credentials" / "token.json"
API_KEY_FILE   = PROJECT_DIR / "credentials" / "anthropic_api_key.txt"

AUDIO_EXTENSIONS = {".m4a", ".wav", ".mp3", ".aiff", ".aac", ".flac", ".ogg", ".mp4"}
GOOGLE_SCOPES    = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]

# ── ロギング ─────────────────────────────────────────────────────
LOG_DIR = PROJECT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "whisper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ── ユーティリティ ────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"状態ファイル読み込みエラー: {e}")
    return {"processed": [], "history": []}


def save_state(state: dict):
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def notify(title: str, subtitle: str, message: str = ""):
    """macOS 通知を送信する"""
    # サブタイトル内のシングルクォートをエスケープ
    title    = title.replace('"', '\\"')
    subtitle = subtitle.replace('"', '\\"')[:60]
    message  = message.replace('"', '\\"')[:100]
    script   = (
        f'display notification "{message}" '
        f'with title "{title}" subtitle "{subtitle}"'
    )
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def find_whisper_binary() -> Path:
    """whisper-cli バイナリを探す"""
    candidates = [
        PROJECT_DIR / "whisper.cpp" / "build" / "bin" / "whisper-cli",
        PROJECT_DIR / "whisper.cpp" / "build" / "bin" / "main",
    ]
    for path in candidates:
        if path.exists() and os.access(path, os.X_OK):
            return path
    raise FileNotFoundError(
        "whisper バイナリが見つかりません。\n"
        "先に 'bash ~/whisper-gdocs/setup.sh' を実行してください。"
    )


def find_whisper_model() -> Path:
    """利用可能な Whisper モデルを優先順で探す"""
    model_dir = PROJECT_DIR / "whisper.cpp" / "models"
    priority  = [
        "ggml-large-v3-turbo.bin",
        "ggml-large-v3.bin",
        "ggml-large-v2.bin",
        "ggml-medium.bin",
        "ggml-small.bin",
    ]
    for name in priority:
        path = model_dir / name
        if path.exists():
            log.info(f"使用モデル: {name}")
            return path
    raise FileNotFoundError(
        f"Whisper モデルが見つかりません: {model_dir}\n"
        "setup.sh を実行してモデルをダウンロードしてください。"
    )


# ── Google 認証 ───────────────────────────────────────────────────

def get_google_credentials():
    """Google OAuth2 認証情報を取得（必要に応じてブラウザ認証）"""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(
                str(TOKEN_FILE), GOOGLE_SCOPES
            )
        except Exception as e:
            log.warning(f"トークン読み込みエラー: {e}")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                log.info("アクセストークンを更新しました")
            except Exception as e:
                log.warning(f"トークン更新失敗: {e}")
                creds = None

        if not creds:
            if not CREDENTIALS.exists():
                raise FileNotFoundError(
                    "\n" + "=" * 60 + "\n"
                    "Google API 認証情報が見つかりません！\n\n"
                    "以下の手順で credentials.json を取得してください:\n"
                    "  1. https://console.cloud.google.com/ にアクセス\n"
                    "  2. 新規プロジェクトを作成\n"
                    "  3. Google Docs API & Drive API を有効化\n"
                    "  4. OAuth 2.0 クライアント ID を作成 (デスクトップアプリ)\n"
                    "  5. JSON をダウンロード\n"
                    f"  6. {CREDENTIALS} に配置\n"
                    "詳細は README.md を参照してください\n"
                    + "=" * 60
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS), GOOGLE_SCOPES
            )
            creds = flow.run_local_server(port=0)
            log.info("Google 認証が完了しました")

        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())
        log.info("認証トークンを保存しました")

    return creds


# ── AI タイトル生成 ───────────────────────────────────────────────

def generate_ai_title(text: str) -> str:
    """Claude API で要約タイトルを生成。失敗時は先頭文から抽出"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and API_KEY_FILE.exists():
        api_key = API_KEY_FILE.read_text().strip()

    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=80,
                messages=[{
                    "role": "user",
                    "content": (
                        "以下の文字起こしテキストの内容を表す簡潔な日本語タイトルを"
                        "20文字以内で作成してください。タイトルのみを返してください。\n\n"
                        f"{text[:1000]}"
                    ),
                }],
            )
            title = resp.content[0].text.strip().replace("\n", "").replace('"', "")
            if title:
                log.info(f"AI タイトル生成: {title}")
                return title
        except Exception as e:
            log.warning(f"AI タイトル生成失敗（フォールバック使用）: {e}")

    # フォールバック: 最初の有意な行を使用
    lines = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
    return lines[0][:25] if lines else "音声文字起こし"


# ── 音声変換 & 文字起こし ─────────────────────────────────────────

def convert_to_wav(audio_path: Path) -> tuple[Path, bool]:
    """
    音声ファイルを Whisper 最適な WAV に変換する。
    変換不要な場合はそのまま返す。(path, is_temp)
    """
    if audio_path.suffix.lower() == ".wav":
        return audio_path, False

    wav_path = LOG_DIR / f"_tmp_{audio_path.stem}.wav"
    if wav_path.exists():
        wav_path.unlink()

    cmd = [
        "ffmpeg", "-y",
        "-i", str(audio_path),
        "-ar", "16000",    # Whisper 推奨サンプルレート
        "-ac", "1",        # モノラル
        "-c:a", "pcm_s16le",
        str(wav_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 変換失敗: {result.stderr[-500:]}")

    return wav_path, True


def transcribe(audio_path: Path) -> str:
    """whisper.cpp で文字起こしを実行し、テキストを返す"""
    whisper_bin   = find_whisper_binary()
    whisper_model = find_whisper_model()

    wav_path, is_temp = convert_to_wav(audio_path)
    output_base = LOG_DIR / f"_transcript_{audio_path.stem}"

    try:
        cmd = [
            str(whisper_bin),
            "-m", str(whisper_model),
            "-l", "ja",                           # 日本語
            "-f", str(wav_path),
            "-otxt",                              # テキスト出力
            "-of", str(output_base),
            "-t", str(min(os.cpu_count() or 4, 8)),  # スレッド数
            "--print-progress",
        ]

        log.info(f"文字起こし開始: {audio_path.name}")
        log.info(f"コマンド: {' '.join(str(c) for c in cmd)}")

        start = time.time()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=7200,   # 最大2時間
        )
        elapsed = time.time() - start

        if result.returncode != 0:
            log.error(f"whisper stderr:\n{result.stderr[-1000:]}")
            raise RuntimeError(f"Whisper が終了コード {result.returncode} で失敗")

        log.info(f"文字起こし完了: {elapsed:.1f}秒")

        txt_file = Path(str(output_base) + ".txt")
        if not txt_file.exists():
            raise RuntimeError(f"出力ファイルが見つかりません: {txt_file}")

        text = txt_file.read_text(encoding="utf-8").strip()
        txt_file.unlink()  # 一時ファイル削除

        if not text:
            raise ValueError("文字起こし結果が空です")

        return text

    finally:
        if is_temp and wav_path.exists():
            wav_path.unlink()


# ── Google Docs アップロード ──────────────────────────────────────

def create_google_doc(title: str, content: str, creds) -> str:
    """Google ドキュメントを作成してURLを返す"""
    from googleapiclient.discovery import build

    docs_service = build("docs", "v1", credentials=creds)

    # 新規ドキュメント作成
    doc = docs_service.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]
    log.info(f"ドキュメント作成: {doc_id}")

    # テキストを挿入
    requests_body = [{
        "insertText": {
            "location": {"index": 1},
            "text": content,
        }
    }]
    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests_body},
    ).execute()

    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    log.info(f"Google Doc URL: {url}")
    return url


# ── メインパイプライン ────────────────────────────────────────────

def is_file_stable(path: Path, wait: int = 5) -> bool:
    """ファイルの書き込みが完了しているか確認（サイズが安定しているか）"""
    try:
        size_before = path.stat().st_size
        if size_before == 0:
            return False
        time.sleep(wait)
        size_after = path.stat().st_size
        return size_before == size_after
    except Exception:
        return False


def process_file(audio_path: Path) -> dict:
    """単一ファイルの完全処理パイプライン"""
    log.info(f"{'='*50}")
    log.info(f"処理開始: {audio_path.name}")
    log.info(f"{'='*50}")

    # Step 1: 文字起こし
    transcript = transcribe(audio_path)
    log.info(f"文字数: {len(transcript)}")

    # Step 2: AI タイトル生成
    ai_title = generate_ai_title(transcript)

    # Step 3: ドキュメント整形
    now       = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M")
    doc_title = f"{timestamp}_録音文字起こし_{ai_title}"

    header = (
        f"■ タイトル　: {ai_title}\n"
        f"■ 元ファイル: {audio_path.name}\n"
        f"■ 処理日時　: {now.strftime('%Y年%m月%d日 %H:%M')}\n"
        f"■ 文字数　　: {len(transcript):,}文字\n"
        f"{'━' * 50}\n\n"
    )
    full_content = header + transcript

    # Step 4: Google Docs アップロード
    creds = get_google_credentials()
    url   = create_google_doc(doc_title, full_content, creds)

    return {
        "file"        : audio_path.name,
        "doc_title"   : doc_title,
        "url"         : url,
        "chars"       : len(transcript),
        "processed_at": now.isoformat(),
    }


def main():
    log.info("Whisper ウォッチャー 起動")
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    state     = load_state()
    processed = set(state.get("processed", []))

    # 未処理の音声ファイルを検索
    new_files = sorted([
        f for f in RECORDINGS_DIR.iterdir()
        if f.is_file()
        and f.suffix.lower() in AUDIO_EXTENSIONS
        and f.name not in processed
        and not f.name.startswith(".")
    ])

    if not new_files:
        log.info("新しい音声ファイルはありません")
        return

    log.info(f"{len(new_files)}件の新規ファイルを検出: {[f.name for f in new_files]}")

    for audio_path in new_files:
        log.info(f"ファイル安定性チェック: {audio_path.name}")
        if not is_file_stable(audio_path, wait=5):
            log.warning(f"まだ書き込み中のためスキップ: {audio_path.name}")
            continue

        try:
            result = process_file(audio_path)

            # 状態を更新
            processed.add(audio_path.name)
            state["processed"] = list(processed)
            state.setdefault("history", []).append(result)
            save_state(state)

            notify(
                "文字起こし完了 ✓",
                result["doc_title"][:50],
                f"Google Docs に保存 ({result['chars']:,}文字)",
            )
            log.info(f"✓ 完了: {audio_path.name} → {result['url']}")

        except Exception as e:
            log.error(f"✗ 処理失敗: {audio_path.name}\n{e}", exc_info=True)
            notify(
                "文字起こしエラー",
                audio_path.name,
                str(e)[:100],
            )


if __name__ == "__main__":
    main()

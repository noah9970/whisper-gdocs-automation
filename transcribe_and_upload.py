#!/usr/bin/env python3
"""
transcribe_and_upload.py
録音ファイル自動文字起こし & Google Docs アップロード（Gemini 議事録生成付き）

launchd の StartInterval により30秒ごとに実行され、
Easy Voice Recorder フォルダの新しい音声ファイルを自動処理します。

処理フロー:
  音声ファイル検出 → Whisper 文字起こし → Gemini 議事録生成
  → Google Docs 作成（「議事録」フォルダに保存）→ macOS 通知
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
RECORDINGS_DIR = (
    Path.home()
    / "Library/CloudStorage/GoogleDrive-gnionadmuus@gmail.com"
    / "マイドライブ/Easy Voice Recorder"
)
STATE_FILE      = RECORDINGS_DIR / ".whisper_state.json"
CREDENTIALS     = PROJECT_DIR / "credentials" / "credentials.json"
TOKEN_FILE      = PROJECT_DIR / "credentials" / "token.json"
GEMINI_KEY_FILE = PROJECT_DIR / "credentials" / "gemini_api_key.txt"

GISIROKU_FOLDER_NAME = "議事録"   # Google Drive マイドライブ内の出力フォルダ

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
    """Google OAuth2 認証情報を取得（キャッシュ済みトークンを優先使用）"""
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
                    f"  {CREDENTIALS} に credentials.json を配置してください\n"
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


# ── Gemini 議事録生成 ─────────────────────────────────────────────

def generate_minutes_and_title(transcript: str) -> tuple[str, str]:
    """
    Gemini 2.5 Flash で議事録とタイトルを生成する。

    戻り値: (meeting_minutes: str, title: str)
    API 失敗時は (transcript, フォールバックタイトル) を返す。
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key and GEMINI_KEY_FILE.exists():
        api_key = GEMINI_KEY_FILE.read_text().strip()

    if not api_key:
        log.warning("Gemini API キーが見つかりません。フォールバックを使用します。")
        return transcript, _extract_fallback_title(transcript)

    try:
        from google import genai

        client     = genai.Client(api_key=api_key)
        model_name = "gemini-2.5-flash"
        log.info(f"Gemini モデル: {model_name}")

        prompt = f"""以下の音声文字起こしテキストを元に、次の2つを作成してください。

【出力形式】
必ず以下の厳密な形式で出力してください:

===タイトル===
（20文字以内の日本語タイトル。内容を簡潔に表すもの。）

===議事録===
（詳細な議事録の本文）

【議事録の要件】
- 会話・発言の内容を整理し、読みやすい構造にしてください
- 重要な議題・決定事項・アクションアイテムを明確にしてください
- 見出し（## など）と箇条書きを適切に使ってください
- 原文の重要な情報を漏らさないようにしてください
- 話し言葉を自然な書き言葉に整えてください

【文字起こし原文】
{transcript[:4000]}"""

        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        raw = response.text.strip()

        # タイトルと議事録を分離
        title   = "音声文字起こし"
        minutes = raw

        if "===タイトル===" in raw and "===議事録===" in raw:
            parts_title   = raw.split("===議事録===", 1)
            title_section = parts_title[0]
            minutes       = parts_title[1].strip() if len(parts_title) > 1 else raw

            # タイトル行を抽出（マーカー行を除く）
            title_lines = [
                ln.strip()
                for ln in title_section.split("\n")
                if ln.strip() and "===タイトル===" not in ln
            ]
            if title_lines:
                title = title_lines[0][:25].strip()

        # ファイル名に使えない文字を全角に変換
        for src, dst in [("/","／"), (":","："), ("*","＊"),
                         ("?","？"), ('"','"'), ("<","＜"), (">","＞"),
                         ("|","｜"), ("\\","￥")]:
            title = title.replace(src, dst)

        log.info(f"Gemini タイトル: {title}")
        log.info(f"議事録生成完了 ({len(minutes)}文字)")
        return minutes, title

    except Exception as e:
        log.warning(f"Gemini 生成失敗（フォールバック使用）: {e}")
        return transcript, _extract_fallback_title(transcript)


def _extract_fallback_title(text: str) -> str:
    """Gemini 失敗時のフォールバックタイトル"""
    lines = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
    return lines[0][:20] if lines else "音声文字起こし"


# ── Google Drive フォルダ管理 ────────────────────────────────────

def get_or_create_gisiroku_folder(drive_service) -> str:
    """
    マイドライブに「議事録」フォルダを検索し、なければ作成する。
    フォルダ ID を返す。
    """
    query = (
        f"name='{GISIROKU_FOLDER_NAME}' "
        "and mimeType='application/vnd.google-apps.folder' "
        "and trashed=false "
        "and 'root' in parents"
    )
    results = drive_service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
    ).execute()

    files = results.get("files", [])
    if files:
        folder_id = files[0]["id"]
        log.info(f"既存の議事録フォルダ: {folder_id}")
        return folder_id

    # フォルダ新規作成
    folder_meta = {
        "name": GISIROKU_FOLDER_NAME,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = drive_service.files().create(
        body=folder_meta,
        fields="id",
    ).execute()
    folder_id = folder["id"]
    log.info(f"議事録フォルダを作成しました: {folder_id}")
    return folder_id


# ── Google Docs 作成 & 保存 ──────────────────────────────────────

def create_google_doc(title: str, content: str, creds) -> str:
    """
    Google ドキュメントを作成し、「議事録」フォルダに移動してURLを返す。
    """
    from googleapiclient.discovery import build

    docs_service  = build("docs", "v1", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)

    # 議事録フォルダID取得（なければ作成）
    folder_id = get_or_create_gisiroku_folder(drive_service)

    # 新規ドキュメント作成
    doc    = docs_service.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]
    log.info(f"ドキュメント作成: {doc_id}")

    # テキストを挿入
    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{
            "insertText": {
                "location": {"index": 1},
                "text": content,
            }
        }]},
    ).execute()

    # 「議事録」フォルダに移動
    file_meta      = drive_service.files().get(fileId=doc_id, fields="parents").execute()
    current_parents = ",".join(file_meta.get("parents", []))
    drive_service.files().update(
        fileId=doc_id,
        addParents=folder_id,
        removeParents=current_parents,
        fields="id, parents",
    ).execute()
    log.info(f"議事録フォルダへ移動完了")

    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    log.info(f"Google Doc URL: {url}")
    return url


# ── 音声変換 & 文字起こし ─────────────────────────────────────────

def convert_to_wav(audio_path: Path) -> tuple[Path, bool]:
    """音声ファイルを Whisper 推奨 WAV に変換する。(path, is_temp)"""
    if audio_path.suffix.lower() == ".wav":
        return audio_path, False

    wav_path = LOG_DIR / f"_tmp_{audio_path.stem}.wav"
    if wav_path.exists():
        wav_path.unlink()

    cmd = [
        "ffmpeg", "-y",
        "-i", str(audio_path),
        "-ar", "16000",      # Whisper 推奨サンプルレート
        "-ac", "1",          # モノラル
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
            "-l", "ja",                              # 日本語
            "-f", str(wav_path),
            "-otxt",                                 # テキスト出力
            "-of", str(output_base),
            "-t", str(min(os.cpu_count() or 4, 8)), # スレッド数
            "--print-progress",
        ]

        log.info(f"文字起こし開始: {audio_path.name}")
        log.info(f"コマンド: {' '.join(str(c) for c in cmd)}")

        start  = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        elapsed = time.time() - start

        if result.returncode != 0:
            log.error(f"whisper stderr:\n{result.stderr[-1000:]}")
            raise RuntimeError(f"Whisper が終了コード {result.returncode} で失敗")

        log.info(f"文字起こし完了: {elapsed:.1f}秒")

        txt_file = Path(str(output_base) + ".txt")
        if not txt_file.exists():
            raise RuntimeError(f"出力ファイルが見つかりません: {txt_file}")

        text = txt_file.read_text(encoding="utf-8").strip()
        txt_file.unlink()   # 一時ファイル削除

        if not text:
            raise ValueError("文字起こし結果が空です")

        return text

    finally:
        if is_temp and wav_path.exists():
            wav_path.unlink()


# ── メインパイプライン ────────────────────────────────────────────

def is_file_stable(path: Path, wait: int = 5) -> bool:
    """ファイルの書き込みが完了しているか確認（サイズ変化をチェック）"""
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

    # Step 1: Whisper 文字起こし
    transcript = transcribe(audio_path)
    log.info(f"文字数: {len(transcript)}")

    # Step 2: Gemini で議事録生成 & タイトル作成
    log.info("Gemini で議事録を生成中...")
    minutes, ai_title = generate_minutes_and_title(transcript)

    # Step 3: ドキュメント整形
    now      = datetime.now()
    # タイトル形式: YYYY-MMDD-HHMM_タイトル（例: 2026-0312-2136_営業会議）
    date_str  = now.strftime("%Y-%m%d-%H%M")
    doc_title = f"{date_str}_{ai_title}"

    sep1 = "━" * 40
    sep2 = "═" * 40
    content = (
        f"【議事録】\n"
        f"{sep1}\n"
        f"日時　　: {now.strftime('%Y年%m月%d日 %H:%M')}\n"
        f"元ファイル: {audio_path.name}\n"
        f"文字数　: {len(transcript):,}文字\n"
        f"{sep1}\n\n"
        f"{minutes}\n\n\n"
        f"{sep2}\n"
        f"【文字起こし原文】\n"
        f"{sep2}\n\n"
        f"{transcript}\n"
    )

    # Step 4: Google Docs 作成（議事録フォルダへ）
    creds = get_google_credentials()
    url   = create_google_doc(doc_title, content, creds)

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

            processed.add(audio_path.name)
            state["processed"] = list(processed)
            state.setdefault("history", []).append(result)
            save_state(state)

            notify(
                "議事録作成完了 ✓",
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

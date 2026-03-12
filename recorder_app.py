#!/usr/bin/env python3
"""
録音して文字起こし - macOS 録音アプリ
ボタンを押すだけで録音→自動文字起こし→Google Docs
"""

import tkinter as tk
from tkinter import font as tkfont
import subprocess
import threading
import signal
import time
import os
from datetime import datetime
from pathlib import Path

RECORDINGS_DIR = Path.home() / "Library/CloudStorage/GoogleDrive-gnionadmuus@gmail.com/マイドライブ/Easy Voice Recorder"

class RecorderApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("録音して文字起こし")
        self.root.geometry("280x320")
        self.root.resizable(False, False)
        self.root.configure(bg="#1c1c1e")

        # ウィンドウを画面中央に
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 280) // 2
        y = (self.root.winfo_screenheight() - 320) // 2
        self.root.geometry(f"280x320+{x}+{y}")

        # 状態
        self.is_recording = False
        self.ffmpeg_process = None
        self.start_time = None
        self.output_file = None
        self.pulse_job = None

        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        self._build_ui()

    # ── UI 構築 ──────────────────────────────────────────

    def _build_ui(self):
        # タイトル
        tk.Label(
            self.root, text="🎙  録音して文字起こし",
            font=tkfont.Font(family="Helvetica", size=14, weight="bold"),
            bg="#1c1c1e", fg="#f2f2f7"
        ).pack(pady=(24, 0))

        # タイマー
        self.timer_var = tk.StringVar(value="00:00")
        self.timer_label = tk.Label(
            self.root, textvariable=self.timer_var,
            font=tkfont.Font(family="Helvetica", size=44, weight="bold"),
            bg="#1c1c1e", fg="#48484a"
        )
        self.timer_label.pack(pady=(16, 0))

        # ステータス
        self.status_var = tk.StringVar(value="ボタンを押して録音開始")
        self.status_label = tk.Label(
            self.root, textvariable=self.status_var,
            font=tkfont.Font(family="Helvetica", size=11),
            bg="#1c1c1e", fg="#636366"
        )
        self.status_label.pack(pady=(6, 0))

        # 録音ボタン (Canvas で丸く描画)
        self.canvas = tk.Canvas(
            self.root, width=100, height=100,
            bg="#1c1c1e", highlightthickness=0
        )
        self.canvas.pack(pady=24)

        self.outer_circle = self.canvas.create_oval(
            5, 5, 95, 95, fill="#2c2c2e", outline="#3a3a3c", width=2
        )
        self.inner_circle = self.canvas.create_oval(
            20, 20, 80, 80, fill="#ff3b30", outline=""
        )

        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Enter>", lambda e: self.canvas.config(cursor="hand2"))
        self.canvas.bind("<Leave>", lambda e: self.canvas.config(cursor=""))

        # ヒント
        tk.Label(
            self.root, text="録音中にもう一度押すと停止",
            font=tkfont.Font(family="Helvetica", size=9),
            bg="#1c1c1e", fg="#3a3a3c"
        ).pack()

    # ── ボタン操作 ────────────────────────────────────────

    def _on_click(self, _event=None):
        if self.is_recording:
            self._stop()
        else:
            self._start()

    def _start(self):
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_file = RECORDINGS_DIR / f"recording_{date_str}.m4a"

        cmd = [
            "ffmpeg", "-f", "avfoundation", "-i", "none:0",
            "-c:a", "aac", "-b:a", "128k",
            "-loglevel", "quiet",
            str(self.output_file)
        ]
        self.ffmpeg_process = subprocess.Popen(cmd)

        # 起動確認
        time.sleep(0.8)
        if self.ffmpeg_process.poll() is not None:
            self._show_error()
            return

        self.is_recording = True
        self.start_time = time.time()

        # UI → 録音中
        self.canvas.itemconfig(self.inner_circle, fill="#ff3b30")
        self.timer_label.config(fg="#ff3b30")
        self.status_var.set("録音中...  もう一度押すと停止")
        self._pulse()

        # タイマースレッド
        threading.Thread(target=self._tick, daemon=True).start()

        # 通知
        self._notify("● 録音開始", "もう一度ボタンを押すと停止します")

    def _stop(self):
        if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
            self.ffmpeg_process.send_signal(signal.SIGINT)
            self.ffmpeg_process.wait()

        self.is_recording = False
        if self.pulse_job:
            self.root.after_cancel(self.pulse_job)
            self.pulse_job = None

        # UI → 保存完了
        self.canvas.itemconfig(self.inner_circle, fill="#30d158")
        self.timer_label.config(fg="#30d158")
        self.status_var.set("✓ 保存完了！文字起こし中...")
        self._notify("✓ 録音終了", "文字起こしが自動で始まります")

        # 3秒後にリセット
        self.root.after(3000, self._reset)

    def _reset(self):
        self.canvas.itemconfig(self.inner_circle, fill="#ff3b30")
        self.canvas.itemconfig(self.outer_circle, fill="#2c2c2e")
        self.timer_var.set("00:00")
        self.timer_label.config(fg="#48484a")
        self.status_var.set("ボタンを押して録音開始")

    def _show_error(self):
        self.status_var.set("⚠ マイクのアクセスを確認してください")
        self.canvas.itemconfig(self.inner_circle, fill="#ff9f0a")
        self.root.after(3000, self._reset)

    # ── タイマー & パルスアニメ ──────────────────────────

    def _tick(self):
        while self.is_recording:
            elapsed = int(time.time() - self.start_time)
            m, s = divmod(elapsed, 60)
            self.root.after(0, lambda m=m, s=s:
                            self.timer_var.set(f"{m:02d}:{s:02d}"))
            time.sleep(1)

    def _pulse(self, bright=True):
        if not self.is_recording:
            return
        color = "#ff3b30" if bright else "#7a1a15"
        self.canvas.itemconfig(self.outer_circle, fill=color)
        self.pulse_job = self.root.after(600, self._pulse, not bright)

    # ── macOS 通知 ───────────────────────────────────────

    def _notify(self, title, message):
        script = f'display notification "{message}" with title "{title}"'
        subprocess.Popen(["osascript", "-e", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ── 起動 ─────────────────────────────────────────────

    def run(self):
        # ウィンドウを常に最前面
        self.root.attributes("-topmost", True)
        self.root.mainloop()


if __name__ == "__main__":
    app = RecorderApp()
    app.run()

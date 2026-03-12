#!/bin/bash
# Dock やランチャーから1クリックで録音できる .app を作成

APP_PATH="$HOME/Applications/録音して文字起こし.app"
SCRIPT_PATH="$HOME/whisper-gdocs/record.sh"

mkdir -p "$APP_PATH/Contents/MacOS"
mkdir -p "$APP_PATH/Contents/Resources"

# Info.plist
cat > "$APP_PATH/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleName</key>
    <string>録音して文字起こし</string>
    <key>CFBundleIdentifier</key>
    <string>com.user.recorder</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>
EOF

# 実行スクリプト
cat > "$APP_PATH/Contents/MacOS/launcher" << EOF
#!/bin/bash
osascript -e 'tell application "Terminal"
    activate
    do script "source ~/.zshrc && bash ~/whisper-gdocs/record.sh"
end tell'
EOF

chmod +x "$APP_PATH/Contents/MacOS/launcher"

echo "✓ アプリ作成完了: $APP_PATH"
echo ""
echo "→ ~/Applications/録音して文字起こし.app をダブルクリックするだけで録音開始！"
echo "→ Dock にドラッグして登録することもできます"

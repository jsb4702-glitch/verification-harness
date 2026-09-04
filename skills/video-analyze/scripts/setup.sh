#!/usr/bin/env bash
# video-analyze 의존성 설치 (1회). brew는 Xcode 라이선스 미동의로 막힐 수 있어 pip venv 사용.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/.venv"

command -v ffmpeg >/dev/null || { echo "[필요] ffmpeg 미설치 → brew install ffmpeg"; exit 1; }

if [ ! -d "$VENV" ]; then
  echo "[setup] venv 생성..."
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
echo "[setup] yt-dlp + faster-whisper 설치..."
"$VENV/bin/pip" install -q yt-dlp faster-whisper

echo "[setup] 검증:"
"$VENV/bin/yt-dlp" --version
"$VENV/bin/python" -c "from faster_whisper import WhisperModel; print('faster-whisper OK')"
echo "[setup] 완료. (Gemini 경로는 ~/.config/secrets.env 의 GEMINI_API_KEYS 사용 — AQ 형식 키. 구형 AIza 는 2026-09 부터 거부됨)"

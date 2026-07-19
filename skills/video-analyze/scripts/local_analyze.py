#!/usr/bin/env python3
"""로컬 영상분석 파이프라인 (외부전송 0).

URL/로컬파일 -> (yt-dlp 다운) -> ffmpeg 씬검출+균등fallback 프레임 -> faster-whisper 전사.
프레임 이미지 + 전사 JSON을 산출. 시각 해석은 호출한 Claude가 프레임을 Read해서 수행한다.

사용:
  python local_analyze.py <URL|파일> [--out DIR] [--model base|small|medium]
                          [--hint "도메인 용어들"] [--min-frames N] [--lang ko|en|auto]
"""
import os, sys, subprocess, json, glob, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(HERE, ".venv")
VENV_PY = os.path.join(VENV_DIR, "bin", "python")
YTDLP = os.path.join(VENV_DIR, "bin", "yt-dlp")

# 의존성(faster-whisper·yt-dlp)은 venv 안에만 있다. system python3로 호출돼도
# 자동으로 venv 인터프리터로 재실행해 ModuleNotFoundError를 방지한다.
# venv 판별은 sys.prefix로 한다 — venv python의 realpath는 base 인터프리터로
# resolve되므로 executable 경로 비교는 신뢰할 수 없다.
if not os.path.exists(VENV_PY):
    sys.exit("[오류] venv 없음 → 먼저 'bash scripts/setup.sh' 실행")
if os.path.realpath(sys.prefix) != os.path.realpath(VENV_DIR):
    os.execv(VENV_PY, [VENV_PY] + sys.argv)

# 기계설계 기본 도메인 힌트 — whisper가 동음이의 한자어(계수/개수, 변위/편의)와
# 외래 전문어(트라이볼로지)를 정확히 받아쓰게 하는 핵심 장치. PoC에서 전문용어 인식률 거의 0→100%.
DEFAULT_HINT = ("기계설계 용어: 열팽창 계수, 볼트 체결, 예압, 안전계수, 공차, 진동 시험, "
                "피로수명, 표면조도, 베어링, 열변형.")


def run(cmd, **kw):
    return subprocess.run(cmd, stderr=subprocess.DEVNULL, **kw)


def extract_frames(vid, fr_dir, min_frames):
    """씬검출 우선, 결과가 min_frames 미만이면 균등간격으로 보강(2-pass).

    긴 정적 씬(예: 고정 카메라 10초)은 씬검출이 1~2장밖에 못 잡아 시각정보를 놓친다.
    그래서 장수가 부족하면 영상 길이를 min_frames로 나눈 간격으로 다시 깐다.
    """
    os.makedirs(fr_dir, exist_ok=True)
    for f in glob.glob(os.path.join(fr_dir, "*.jpg")):
        os.remove(f)
    run(["ffmpeg", "-y", "-i", vid, "-vf", "select='eq(n,0)+gt(scene,0.3)'",
         "-vsync", "vfr", os.path.join(fr_dir, "scene_%03d.jpg")], check=True)
    frames = sorted(glob.glob(os.path.join(fr_dir, "scene_*.jpg")))
    if len(frames) >= min_frames:
        return frames, "scene"

    # fallback: 균등간격
    dur = float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", vid]).strip() or "0")
    fps = max(min_frames / dur, 0.001) if dur > 0 else 1.0
    run(["ffmpeg", "-y", "-i", vid, "-vf", f"fps={fps}",
         "-vsync", "vfr", os.path.join(fr_dir, "uniform_%03d.jpg")], check=True)
    frames = sorted(glob.glob(os.path.join(fr_dir, "*.jpg")))
    return frames, "scene+uniform-fallback"


def transcribe(vid, work, model_size, hint, lang):
    wav = os.path.join(work, "audio.wav")
    run(["ffmpeg", "-y", "-i", vid, "-ar", "16000", "-ac", "1", wav], check=True)
    if not os.path.exists(wav):
        return {"language": None, "segments": [], "note": "오디오 트랙 없음"}
    from faster_whisper import WhisperModel
    m = WhisperModel(model_size, device="cpu", compute_type="int8")
    segs, info = m.transcribe(wav, language=(None if lang == "auto" else lang),
                              initial_prompt=hint)
    out = [{"t": round(s.start, 1), "text": s.text.strip()} for s in segs]
    return {"language": info.language,
            "language_probability": round(info.language_probability, 2),
            "segments": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", default="video_analyze_out")
    ap.add_argument("--model", default="small")          # base=빠름/부정확, small=권장, medium=정확/느림
    ap.add_argument("--hint", default=DEFAULT_HINT)
    ap.add_argument("--min-frames", type=int, default=4)
    ap.add_argument("--lang", default="auto")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)

    if a.src.startswith("http"):
        vid = os.path.join(a.out, "video.mp4")
        print(f"[1/3] yt-dlp 다운로드: {a.src}", file=sys.stderr)
        if subprocess.run([YTDLP, "-f", "mp4/best", "-o", vid, a.src]).returncode != 0:
            sys.exit("[오류] yt-dlp 다운로드 실패 (JS런타임/포맷 문제일 수 있음)")
    else:
        vid = a.src
        if not os.path.exists(vid):
            sys.exit(f"[오류] 파일 없음: {vid}")
        print(f"[1/3] 로컬 파일: {vid}", file=sys.stderr)

    print("[2/3] 프레임 추출(씬검출+fallback)...", file=sys.stderr)
    fr_dir = os.path.join(a.out, "frames")
    frames, method = extract_frames(vid, fr_dir, a.min_frames)

    print("[3/3] 오디오 전사(faster-whisper)...", file=sys.stderr)
    tr = transcribe(vid, a.out, a.model, a.hint, a.lang)

    result = {
        "source": a.src,
        "video": vid,
        "frame_method": method,
        "frames": [os.path.abspath(f) for f in frames],
        "transcript": tr,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

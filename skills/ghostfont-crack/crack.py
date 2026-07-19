#!/usr/bin/env python3
"""
Ghost Font cracker — recover text hidden in an anti-motion random-dot clip.

Ghost Font encodes text as a random-dot kinematogram: dots inside the glyphs
drift one way, background dots the opposite way. A single frame is noise; the
text lives only in the *relative motion*. This tool reconstructs the still text
image via dense optical-flow accumulation, then reads it (Tesseract + local
vision model).

Three input modes (auto-detected, or forced with --mode):
  file : a local video/gif  (.mp4/.mov/.mkv/.avi/.gif/.webm)
  url  : a remote video/gif or a YouTube-style page (ffmpeg direct, yt-dlp fallback)
  live : grab a screen region for a few seconds (macOS avfoundation / mss)

Usage:
  python crack.py ghost.mp4
  python crack.py "https://example.com/ghost.mp4"
  python crack.py --mode live --seconds 3 --region 400,300,900,300
  python crack.py ghost.mp4 --axis auto --model qwen2.5vl:7b --save out
"""
import argparse
import os
import subprocess
import sys
import tempfile
import numpy as np
import cv2

VIDEO_EXT = (".mp4", ".mov", ".mkv", ".avi", ".gif", ".webm", ".m4v")


# ---------------------------------------------------------------- input loaders
def frames_from_file(path, max_frames=60):
    cap = cv2.VideoCapture(path)
    out = []
    while len(out) < max_frames:
        ok, f = cap.read()
        if not ok:
            break
        out.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
    cap.release()
    if not out:
        raise RuntimeError(f"no frames decoded from {path}")
    return out


def download_url(url, dst):
    """Try ffmpeg direct copy first (direct media URLs); fall back to yt-dlp."""
    try:
        subprocess.run(["ffmpeg", "-y", "-i", url, "-t", "8", "-c", "copy", dst],
                       check=True, capture_output=True, timeout=120)
        if os.path.getsize(dst) > 1000:
            return dst
    except Exception:
        pass
    # yt-dlp fallback (YouTube / embedded players)
    try:
        subprocess.run(["yt-dlp", "-f", "mp4", "-o", dst, url],
                       check=True, capture_output=True, timeout=300)
        return dst
    except Exception as e:
        raise RuntimeError(f"could not fetch {url}: {e}")


def frames_from_url(url, max_frames=60):
    tmp = os.path.join(tempfile.mkdtemp(), "ghost_dl.mp4")
    download_url(url, tmp)
    return frames_from_file(tmp, max_frames)


def frames_from_live(seconds=3, fps=20, region=None, screen_index="2"):
    """Grab the screen for a few seconds. region=(x,y,w,h) crops after capture."""
    n = int(seconds * fps)
    # Prefer mss (fast, croppable); fall back to ffmpeg avfoundation.
    try:
        import mss
        MSS = getattr(mss, "MSS", mss.mss)   # new API name, fall back to old
        with MSS() as sct:
            mon = sct.monitors[1]
            if region:
                x, y, w, h = region
                mon = {"left": x, "top": y, "width": w, "height": h}
            out = []
            import time
            for _ in range(n):
                img = np.array(sct.grab(mon))
                out.append(cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY))
                time.sleep(1.0 / fps)
            return out
    except Exception:
        pass
    tmp = os.path.join(tempfile.mkdtemp(), "ghost_live.mp4")
    subprocess.run(["ffmpeg", "-y", "-f", "avfoundation", "-framerate", str(fps),
                    "-t", str(seconds), "-i", screen_index, tmp],
                   check=True, capture_output=True, timeout=seconds + 60)
    fr = frames_from_file(tmp, n)
    if region:
        x, y, w, h = region
        fr = [f[y:y + h, x:x + w] for f in fr]
    return fr


def load(source, mode, **kw):
    if mode == "auto":
        if source and (source.startswith("http://") or source.startswith("https://")):
            mode = "url"
        elif source and os.path.isfile(source):
            mode = "file"
        elif source is None:
            mode = "live"
        else:
            raise SystemExit(f"cannot resolve input {source!r}; use --mode")
    if mode == "file":
        return frames_from_file(source, kw.get("max_frames", 60)), mode
    if mode == "url":
        return frames_from_url(source, kw.get("max_frames", 60)), mode
    if mode == "live":
        return frames_from_live(kw.get("seconds", 3), kw.get("fps", 20),
                                kw.get("region")), mode
    raise SystemExit(f"unknown mode {mode}")


# ---------------------------------------------------------------- attack core
def recover_field(frames, mag_thresh=0.12, winsize=9, axis="x"):
    """
    Accumulate signed flow along a motion axis across the clip.
    axis: 'x' (default anti-motion is horizontal) or 'auto'
          ('auto' finds the dominant motion direction via mean-flow PCA and
           projects onto it -- handles non-horizontal anti-motion).
    Returns signed mean-vote field in [-1, 1].
    """
    H, W = frames[0].shape
    vote = np.zeros((H, W), np.float64)
    count = np.zeros((H, W), np.float64)
    axis_vec = None

    prev = frames[0]
    for cur in frames[1:]:
        flow = cv2.calcOpticalFlowFarneback(
            prev, cur, None, 0.5, 3, winsize, 3, 5, 1.2, 0)
        if axis == "auto":
            fx, fy = flow[..., 0], flow[..., 1]
            mag = np.hypot(fx, fy)
            m = mag > mag_thresh
            if m.sum() > 50:
                vv = np.array([fx[m].mean(), fy[m].mean()])
                nv = np.linalg.norm(vv)
                if nv > 1e-6:
                    axis_vec = vv / nv
            comp = (fx * axis_vec[0] + fy * axis_vec[1]) if axis_vec is not None else fx
        else:
            comp = flow[..., 0]
        active = np.abs(comp) > mag_thresh
        vote += np.sign(comp) * active
        count += active
        prev = cur

    safe = np.where(count > 0, count, 1)
    field = vote / safe
    field[count < 0.05 * len(frames)] = 0.0
    return field


def fill_holes(mask):
    h, w = mask.shape
    ff = mask.copy()
    m2 = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(ff, m2, (0, 0), 255)
    return cv2.bitwise_or(mask, cv2.bitwise_not(ff))


def reconstruct(field, polarity=1, close_k=9, min_area=None, dilate_k=3):
    """Signed field -> clean binary text image.
    polarity: +1 = letters drift along +axis (default); -1 flips it."""
    H, W = field.shape
    if min_area is None:
        min_area = max(120, int(H * W * 0.0006))
    m = (((field * polarity) > 0.0).astype(np.uint8)) * 255
    n, lbl, st, _ = cv2.connectedComponentsWithStats(m, 8)
    out = np.zeros_like(m)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= min_area:
            out[lbl == i] = 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k))
    out = cv2.morphologyEx(out, cv2.MORPH_CLOSE, k, 1)
    out = fill_holes(out)
    if dilate_k > 1:
        out = cv2.dilate(out, cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (dilate_k, dilate_k)), 1)
    return out


def coverage(mask):
    return float((mask > 127).mean())


# ---------------------------------------------------------------- readout
def tesseract_read(mask):
    try:
        import pytesseract
    except Exception:
        return None
    up = cv2.resize(mask, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    inv = 255 - up
    inv = cv2.copyMakeBorder(inv, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    best = ""
    for c in ["--psm 7", "--psm 6", "--psm 8", "--psm 11"]:
        t = " ".join(pytesseract.image_to_string(inv, config=c).split())
        if len(t) > len(best):
            best = t
    return best


def vision_read(mask, model="qwen2.5vl:7b"):
    import base64, json, urllib.request
    up = cv2.resize(mask, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    inv = 255 - up
    inv = cv2.copyMakeBorder(inv, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    ok, buf = cv2.imencode(".png", inv)
    b64 = base64.b64encode(buf.tobytes()).decode()
    prompt = ("This image is white-on-black block text that may span ONE or MORE "
              "lines. Transcribe ALL the text, reading top to bottom then left to "
              "right. Give your single best reading. Do NOT list the alphabet. "
              "Respond with ONLY the transcribed words in order, nothing else.")
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=json.dumps({"model": model, "prompt": prompt, "images": [b64],
                         "stream": False, "options": {"temperature": 0.0}}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())["response"].strip()
    except Exception as e:
        return f"<vision unavailable: {e}>"


# ---------------------------------------------------------------- orchestration
def crack(frames, axis="x", winsize=None, model="qwen2.5vl:7b", save=None):
    """
    Runs the attack. Since a real clip has no ground truth, it auto-scans a few
    winsizes and both polarities, and picks the reconstruction whose text region
    is most plausible (letter-like coverage 5-45%, largest connected structure).
    """
    winsizes = [winsize] if winsize else [7, 9, 13]
    best = None
    for ws in winsizes:
        for ax in ([axis] if axis != "both" else ["x", "auto"]):
            field = recover_field(frames, winsize=ws, axis=ax)
            for pol in (1, -1):
                rec = reconstruct(field, polarity=pol)
                cov = coverage(rec)
                if not (0.03 <= cov <= 0.5):
                    continue
                n, _, st, _ = cv2.connectedComponentsWithStats(rec, 8)
                # score: prefer several letter-sized components, target ~15% cover,
                # penalize a single giant blob (letters merged) or confetti.
                areas = sorted(st[1:, cv2.CC_STAT_AREA].tolist(), reverse=True)
                letters = [a for a in areas if a > 150]
                score = min(len(letters), 14) - abs(cov - 0.15) * 12
                if letters and letters[0] > 0.6 * sum(letters):
                    score -= 6  # one blob dominates -> probably not segmented text
                if best is None or score > best[0]:
                    best = (score, rec, ws, ax, pol, cov)
    if best is None:
        raise RuntimeError("no plausible text reconstruction found; "
                           "clip may not be Ghost-Font-style or motion too fast")
    _, rec, ws, ax, pol, cov = best
    if save:
        cv2.imwrite(f"{save}_recon.png", rec)
    tess = tesseract_read(rec)
    vis = vision_read(rec, model) if model else None
    return dict(reconstruction=rec, winsize=ws, axis=ax, polarity=pol,
                coverage=round(cov, 3), tesseract=tess, vision=vis, save=save)


def main():
    ap = argparse.ArgumentParser(description="Ghost Font cracker")
    ap.add_argument("source", nargs="?", help="video file path or URL (omit for --mode live)")
    ap.add_argument("--mode", choices=["auto", "file", "url", "live"], default="auto")
    ap.add_argument("--seconds", type=float, default=3.0, help="live capture duration")
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--region", type=str, default=None, help="live crop x,y,w,h")
    ap.add_argument("--max-frames", type=int, default=60)
    ap.add_argument("--axis", choices=["x", "auto", "both"], default="both",
                    help="motion axis: x=horizontal, auto=PCA, both=try both")
    ap.add_argument("--winsize", type=int, default=None, help="fix Farneback winsize (else scan)")
    ap.add_argument("--model", default="qwen2.5vl:7b", help="ollama vision model ('' to skip)")
    ap.add_argument("--save", default="ghostcrack")
    a = ap.parse_args()

    region = tuple(int(v) for v in a.region.split(",")) if a.region else None
    frames, mode = load(a.source, a.mode, seconds=a.seconds, fps=a.fps,
                        region=region, max_frames=a.max_frames)
    print(f"[+] mode={mode}  frames={len(frames)}  size={frames[0].shape[1]}x{frames[0].shape[0]}",
          file=sys.stderr)
    res = crack(frames, axis=a.axis, winsize=a.winsize,
                model=(a.model or None), save=a.save)
    print(f"[+] recon: winsize={res['winsize']} axis={res['axis']} "
          f"polarity={res['polarity']} coverage={res['coverage']}", file=sys.stderr)
    if res["save"]:
        print(f"[+] reconstruction saved -> {res['save']}_recon.png", file=sys.stderr)
    print(f"Tesseract : {res['tesseract']!r}")
    print(f"Vision    : {res['vision']!r}")


if __name__ == "__main__":
    main()

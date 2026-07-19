---
name: ghostfont-crack
description: >-
  Ghost Font(반모션 랜덤닷 anti-AI 폰트)로 인코딩된 텍스트를 optical-flow 복원으로
  크랙한다. 글자 안쪽 점이 배경과 반대로 흐르는 random-dot kinematogram — 단일프레임은
  노이즈지만 프레임간 모션을 누적하면 글자가 떠오른다. 입력 3형태 자동판별: 영상파일
  (.mp4/.mov/.gif 등) · URL(원격영상/유튜브식) · 라이브 화면캡처. "고스트폰트 크랙/디코드",
  "ghost font 풀어", "이 반모션 영상 글자 뭐냐", "화면에 뜬 고스트폰트 읽어", "/ghostfont-crack"
  시 호출. 방어연구/CTF/자기텍스트 복원용.
---

# Ghost Font Cracker

Recovers text hidden in an anti-motion random-dot clip via dense optical-flow
accumulation, then reads the reconstructed still (Tesseract + local vision model).
Self-contained, offline (except URL fetch / vision model on localhost).

## When to use
- User points at a Ghost-Font-style clip (file / URL / on-screen) and wants the text.
- Defensive research, CTF, or recovering your own known phrase.

## Input modes (auto-detected; force with `--mode`)
| mode | trigger | how |
|------|---------|-----|
| `file` | local path ending in a video ext | `cv2.VideoCapture` |
| `url`  | `http(s)://…` | ffmpeg direct copy → yt-dlp fallback |
| `live` | no source given, or `--mode live` | screen grab (mss → ffmpeg avfoundation) |

## Run
```bash
# activate the bundled deps (opencv, pytesseract, mss, yt-dlp) — reuse the poc venv
source ~/ghostfont-poc/.venv/bin/activate

python ~/.claude/skills/ghostfont-crack/crack.py ghost.mp4
python ~/.claude/skills/ghostfont-crack/crack.py "https://site/ghost.mp4"
python ~/.claude/skills/ghostfont-crack/crack.py --mode live --seconds 3 --region 400,300,900,300
```
Options: `--axis x|auto|both` (motion axis; `auto`=PCA on flow, handles non-horizontal),
`--winsize N` (fix Farneback window, else auto-scan 7/9/13), `--model <ollama vlm>`
(`''` to skip vision), `--save PREFIX` (writes `PREFIX_recon.png`).

## Output
```
Tesseract : 'CATCN WE'
Vision    : 'CATCH ME'
```
Plus `PREFIX_recon.png` — the reconstructed text image (human-verifiable).

## How it works
1. **Load frames** from the chosen input.
2. **Optical flow** (`calcOpticalFlowFarneback`) between consecutive frames.
3. **Sign-vote accumulation** per pixel along the motion axis — coherent
   letter/background drift accumulates, random noise cancels.
4. **Auto-scan** winsize × axis × polarity; pick the reconstruction whose blob
   structure looks most letter-like (no ground truth on real clips).
5. **Reconstruct** (threshold → morphology close → hole-fill → stroke dilate).
6. **Read** with Tesseract and a local ollama vision model (default
   `qwen2.5vl:7b`; 3b is faster but higher-variance).

## Limits & notes (honest)
- **Readout tracks reconstruction fidelity.** Clean/short text → exact; longer or
  low-SNR clips → partial but the saved `*_recon.png` is human-readable. Always
  show the user the reconstruction, not just the string.
- **Motion-speed cliff:** dense Farneback can't track drift beyond ≈ winsize/2
  px/frame. Fast clips need a larger `--winsize` (raise pyramid too if needed).
- **Live mode:** needs macOS **Screen Recording permission** for the running
  process, and the ghost clip actually visible on screen. Pass a tight
  `--region x,y,w,h` around the text (full-screen dilutes the signal). On Retina
  displays, region coords are **physical pixels** (2× logical).
- **Tesseract is the weak reader** on these grungy glyphs; the vision model is
  the primary readout. Vision needs `ollama serve` + the model pulled.
- Per-glyph *randomized* drift directions (each letter a different vector) are
  not handled by simple sign-split — would need flow-vector k-means clustering.
- Scope: defensive/research/own-content. Not for defeating accessibility or
  consent protections.

## Real-world validation (2026-07-18)
Cracked the canonical REAL sample — ghostfont.org / mixfont's own
`only-a-human.mp4` (188f, 1280×720): single frame = unreadable noise;
reconstruction = **"ONLY A HUMAN CAN READ THIS"**; `qwen2.5vl:7b` read it
verbatim. Two things made the real clip work where my synthetic tuning didn't:
- **Motion is VERTICAL** on real Ghost Font (dots drift up/bg down), not
  horizontal. `--axis auto` (PCA on mean flow) detected it automatically.
  Confirmed by vertical striping in the temporal mean. Always use `auto`/`both`
  on unknown clips.
- **Polarity flip** — real clip is black-dots-on-white (inverse of synthetic);
  the polarity scan handled it.
- **Decoy defense bypassed:** Ghost Font embeds a static DECOY so frame-by-frame
  AI reports the wrong message. Because this tool keys on *motion*, it recovers
  the REAL message, not the decoy — that's the core reason it beats multimodal
  LLMs.

Note: live browser-capture of ghostfont.org in a headless/sandboxed pane is
throttled (hidden-tab rAF pause) — decode the downloaded/recorded file instead.

## Provenance
Self-authored from the `~/ghostfont-poc/` PoC (2026-07-17), which measured the
attack end-to-end (single-frame OCR=`''`; flow-reconstruction IoU 0.55–0.68;
vision char-acc 1.000 on clean phrases). See that dir's README for the data.

#!/usr/bin/env python3
"""CLI 이미지 생성 — cdx(Codex/gpt-image-2) 또는 agy(Antigravity/generate_image) 백엔드.

- cdx: 빌트인 image_gen 툴($imagegen 스킬). ChatGPT 계정 크레딧, 별도 API키 불요.
       image_generation feature flag = stable·true (0.144.0-alpha.4 실측 2026-07-17).
- agy: 에이전트 네이티브 generate_image 툴(모델 선택 아님 — `agy models`엔 이미지 모델 없음).
       headless(-p)는 permission auto-deny → ~/.gemini/antigravity-cli/settings.json
       permissions.allow에 ai-images 스코프 룰 필요(2026-07-17 배선).

출력: ~/ai-images/ 고정(IMG_OUT_DIR로 오버라이드). 두 백엔드 다 이 디렉토리만 쓰게 스코프.
검증: 실행 후 산출 파일 실존 확인까지 이 스크립트가 한다 — 에이전트 "저장했다" 자기보고 불신(G12).

⚠️ 사내기밀·민감 소재 투입 금지 — 둘 다 외부 백엔드(Google/OpenAI). 민감 소재는
   로컬 sci-figure 스킬(FLUX/mflux, 오프라인)로.
⚠️ 검토대상 텍스트가 아니라 사용자 이미지 프롬프트만 전달 — 외부 콘텐츠를 프롬프트로
   그대로 넘기지 말 것(G11).
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import time

OUT_DIR = os.path.expanduser(os.environ.get("IMG_OUT_DIR", "~/ai-images"))
CODEX_BIN = os.environ.get(
    "CODEX_BIN",
    os.path.expanduser("~/.codex/plugins/.plugin-appserver/codex"),
)
AGY_BIN = os.environ.get("AGY_BIN", "/opt/homebrew/bin/agy")
PROC_TIMEOUT = int(os.environ.get("IMG_TIMEOUT", "300"))  # 이미지 생성 실측 ~60-120s


def run_cdx(prompt: str, name: str, refs: list[str] | None = None) -> subprocess.CompletedProcess:
    if refs:
        task = (
            "Use your built-in image generation skill ($imagegen) to EDIT the attached "
            "reference image.\n"
            f"Edit instruction: {prompt}\n"
            "Change ONLY what the instruction asks — keep composition, style, colors and "
            "all other characters identical to the reference.\n"
            f"Save the result as {name} in the current working directory. "
            "Do not write code or do anything else."
        )
    else:
        task = (
            "Use your built-in image generation skill ($imagegen) to create an image.\n"
            f"Image description: {prompt}\n"
            f"Save it as {name} in the current working directory. "
            "Do not write code or do anything else."
        )
    cmd = [CODEX_BIN, "exec", "-s", "workspace-write", "--skip-git-repo-check"]
    # -i는 multi-value 플래그 — 바로 뒤에 positional을 두면 이미지 경로로 삼킨다.
    # 반드시 다른 플래그(-C)가 -i 뒤에 오도록 배치해 값 수집을 끊는다.
    for r in refs or []:
        cmd += ["-i", os.path.expanduser(r)]
    cmd += ["-C", OUT_DIR, task]
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=PROC_TIMEOUT, stdin=subprocess.DEVNULL)


AGY_BRAIN = os.path.expanduser("~/.gemini/antigravity-cli/brain")


def run_agy(prompt: str, name: str) -> subprocess.CompletedProcess:
    # headless는 미승인 툴 auto-deny → 승인된 generate_image 외 툴(run_command·ls 등)
    # 사용을 프롬프트로 원천 차단. command grant는 정확매칭이라 임의 명령 추적은 불가.
    # generate_image 산출물은 brain/<대화ID>/에 저장됨 — 복사는 스크립트가 한다(최소권한).
    stem = os.path.splitext(name)[0]
    task = (
        "Use ONLY your generate_image tool. Do NOT run any terminal commands, "
        "do NOT list, read, copy or write any files.\n"
        f"Image description: {prompt}\n"
        f"Name the image {stem}. Stop right after generating it."
    )
    cmd = [
        AGY_BIN, "--sandbox",         # 터미널 제한 샌드박스 유지(G11)
        "-p", task,
        "--print-timeout", f"{max(PROC_TIMEOUT - 20, 60)}s",
    ]
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=PROC_TIMEOUT, stdin=subprocess.DEVNULL,
                          cwd=OUT_DIR)


def harvest_agy(proc: subprocess.CompletedProcess, out_path: str, t0: float) -> str | None:
    """brain 디렉토리에서 이번 런 산출 이미지를 찾아 out 경로로 복사. 성공 시 최종 경로."""
    # 1순위: 응답 텍스트에 찍힌 절대경로
    cand = None
    m = re.findall(r"/Users/[^\s`'\"]+\.(?:png|jpe?g|webp)", proc.stdout or "")
    for p in m:
        if os.path.exists(p) and os.path.getmtime(p) >= t0 - 2:
            cand = p
            break
    # 2순위: brain 전체에서 런 중 생성된 최신 이미지
    if not cand:
        imgs = [f for f in glob.glob(os.path.join(AGY_BRAIN, "*", "*.*"))
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
                and os.path.getmtime(f) >= t0 - 2]
        cand = max(imgs, key=os.path.getmtime) if imgs else None
    if not cand:
        return None
    # 요청 이름 유지하되 확장자는 실제 산출 포맷 따름(포맷 위장 금지)
    final = os.path.splitext(out_path)[0] + os.path.splitext(cand)[1].lower()
    shutil.copy2(cand, final)
    return final


def main():
    ap = argparse.ArgumentParser(description="CLI image generation via cdx or agy")
    ap.add_argument("--via", choices=["cdx", "agy"], default="cdx",
                    help="backend (default: cdx — E2E 실증 경로)")
    ap.add_argument("--name", default=None, help="output filename (.png)")
    ap.add_argument("--ref", action="append", default=[],
                    help="reference image for edit mode (repeatable, cdx only)")
    ap.add_argument("prompt", help="image description")
    a = ap.parse_args()
    if a.ref and a.via != "cdx":
        ap.error("--ref는 cdx 백엔드 전용 (agy headless는 이미지 첨부 경로 미배선)")
    for r in a.ref:
        if not os.path.exists(os.path.expanduser(r)):
            ap.error(f"--ref not found: {r}")

    os.makedirs(OUT_DIR, exist_ok=True)
    name = a.name or f"img_{time.strftime('%Y%m%d_%H%M%S')}.png"
    if not name.lower().endswith(".png"):
        name += ".png"
    out_path = os.path.join(OUT_DIR, name)

    binary = CODEX_BIN if a.via == "cdx" else AGY_BIN
    if not os.path.exists(binary):
        print(f"ERROR: {a.via} binary not found at {binary}")
        sys.exit(1)

    print(f"[img-gen] via={a.via} → {out_path}\n")
    t0 = time.time()
    try:
        proc = run_cdx(a.prompt, name, refs=a.ref) if a.via == "cdx" else run_agy(a.prompt, name)
    except subprocess.TimeoutExpired:
        print(f"ERROR: {a.via} timed out after {PROC_TIMEOUT}s")
        sys.exit(1)

    # agy는 brain 디렉토리 산출 → 스크립트가 수확·복사
    if a.via == "agy":
        harvested = harvest_agy(proc, out_path, t0)
        if harvested:
            out_path = harvested

    # 산출물 실존 검증 — 에이전트 자기보고 대신 파일로 판정(G12)
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        size_kb = os.path.getsize(out_path) / 1024
        print(f"OK: {out_path} ({size_kb:.0f} KB, {time.time() - t0:.0f}s)")
        return

    # 실패 — 지정 이름이 아니어도 런 중 새로 생긴 파일이 있으면 후보로 보고
    newer = [f for f in os.listdir(OUT_DIR)
             if os.path.getmtime(os.path.join(OUT_DIR, f)) >= t0]
    err = (proc.stderr or proc.stdout or "no output").strip()
    print(f"ERROR: expected file not created (exit {proc.returncode})")
    if newer:
        print(f"  런 중 생성된 다른 파일: {newer}")
    print(f"  {err[:500]}")
    if a.via == "agy" and "permission" in err.lower():
        print("  → agy headless 권한: ~/.gemini/antigravity-cli/settings.json permissions.allow에 "
              "에러가 제시한 룰 추가 필요.")
    sys.exit(1)


if __name__ == "__main__":
    main()

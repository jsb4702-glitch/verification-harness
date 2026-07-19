#!/usr/bin/env python3
"""pdf-ko: 영문 PDF -> 한글 in-place 치환 (레이아웃 보존), pdf2zh-next(BabelDOC) 래퍼.

엔진 2종:
  - claude : pdf2zh --claudecode (Claude Sonnet 5 기본). 메인·고품질. 구독 인증. 클라우드.
  - gemma  : pdf2zh --ollama (gemma4 로컬). 오프라인·$0. 민감/미지출처 강제.

⛔ 수출통제 게이트 (L3): claude 엔진 = 클라우드 전송. 민감 문서 금지.
   auto 모드는 --public / --sensitive 명시 없으면 거부(사람게이트). 오분류로 민감문서
   클라우드行 방지. 판단 애매하면 sensitive(로컬)로 안전측 처리.

G11: pdf2zh claudecode 백엔드는 --disallowedTools 로 전체 툴 차단 → 문서 내 인젝션이
   툴실행으로 승격 불가. 번역 프롬프트도 텍스트를 데이터로만 취급.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

VENV = Path.home() / ".local/share/pdf-ko/venv"
PDF2ZH = VENV / "bin/pdf2zh_next"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-5"
GEMMA_MODEL = "gemma4:latest"
OLLAMA_HOST = "http://localhost:11434"

# 출력 오염 감지 마커(하네스 페르소나/게이트 누출 방어) — 번역문에 절대 없어야 함
POLLUTION_MARKERS = [
    "판정근거", "ACCEPT", "REJECT", "청문", "야 브로", "real talk",
    "사실성:", "BLUF", "🟢", "🟡", "🔴", "브로,",
]


def die(msg, code=2):
    print(f"[pdf-ko] ❌ {msg}", file=sys.stderr)
    sys.exit(code)


def resolve_engine(args):
    """민감도 게이트. (engine, reason) 반환 또는 거부."""
    if args.engine == "gemma":
        return "gemma", "명시적 gemma(로컬) 선택"
    if args.engine == "claude":
        if not args.public:
            die("claude 엔진=클라우드 전송. 공개문서만 허용. 확실하면 --public, "
                "민감이면 --engine gemma 로 재실행.")
        return "claude", "명시적 claude + --public"
    # auto
    if args.sensitive:
        return "gemma", "auto: --sensitive -> 로컬 gemma 강제"
    if args.public:
        return "claude", "auto: --public -> claude(Sonnet 5)"
    die("민감도 미지정. 공개자료면 --public, 민감/미지출처면 --sensitive 를 붙여라. "
        "(수출통제 게이트: 기본 거부. 애매하면 --sensitive)")


def ensure_ollama():
    import urllib.request
    try:
        urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3)
        return
    except Exception:
        pass
    if not shutil.which("ollama"):
        die("ollama 미설치인데 gemma 엔진 요청됨.")
    print("[pdf-ko] ollama 데몬 기동...", file=sys.stderr)
    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import time
    for _ in range(20):
        time.sleep(1)
        try:
            urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3)
            return
        except Exception:
            continue
    die("ollama 기동 실패.")


def build_cmd(engine, args, outdir):
    cmd = [str(PDF2ZH), str(args.input),
           "--lang-in", "en", "--lang-out", "ko",
           "--no-auto-extract-glossary",
           "--watermark-output-mode", "no_watermark",
           "--output", str(outdir)]
    if args.pages:
        cmd += ["--pages", args.pages]
    if args.out == "mono":
        cmd += ["--no-dual"]
    elif args.out == "dual":
        cmd += ["--no-mono"]
    # both = 기본(플래그 없음)

    if engine == "claude":
        claude_bin = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
        if not Path(claude_bin).exists():
            die(f"claude CLI 없음: {claude_bin}")
        cmd += ["--claudecode", "--claude-code-path", claude_bin,
                "--claude-code-model", args.model]
    else:  # gemma
        ensure_ollama()
        cmd += ["--ollama", "--ollama-model", GEMMA_MODEL, "--ollama-host", OLLAMA_HOST]
    return cmd


def _fitz():
    try:
        import fitz  # PyMuPDF (venv 안)
        return fitz
    except Exception:
        sys.path.insert(0, str(VENV / "lib/python3.13/site-packages"))
        import fitz
        return fitz


def verify_outputs(outdir, input_pdf):
    """산출물 검증: 페이지수·tofu(두부)·오염·한글밀도. (ok, report)

    출력 PDF는 --pages로 일부만 번역해도 원본 전체 페이지를 유지하므로,
    기대 페이지수 = 입력 PDF 총 페이지수.
    """
    fitz = _fitz()
    src = fitz.open(str(input_pdf))
    expected_pages = src.page_count
    src.close()
    pdfs = sorted(Path(outdir).glob("*.ko*.pdf"))
    if not pdfs:
        return False, "산출물 PDF 없음"
    lines, ok = [], True
    for f in pdfs:
        d = fitz.open(str(f))
        txt = "".join(p.get_text() for p in d)
        ko = len(re.findall(r"[가-힣]", txt))
        tofu = txt.count("�")
        pol = [m for m in POLLUTION_MARKERS if m in txt]
        pg_ok = (expected_pages is None) or (d.page_count == expected_pages)
        bad = (tofu > 0) or bool(pol) or (ko == 0) or (not pg_ok)
        if bad:
            ok = False
        status = "✅" if not bad else "⚠️"
        lines.append(f"  {status} {f.name}: pages={d.page_count} KR={ko} tofu={tofu} "
                     f"pollution={pol or 'CLEAN'}")
        d.close()
    return ok, "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="영문 PDF -> 한글 in-place 치환")
    ap.add_argument("input", type=Path)
    ap.add_argument("--engine", choices=["auto", "claude", "gemma"], default="auto")
    ap.add_argument("--public", action="store_true", help="공개/비통제 문서 (claude 허용)")
    ap.add_argument("--sensitive", action="store_true", help="민감/미지출처 (gemma 강제)")
    ap.add_argument("--pages", default=None, help='예: "1-3" (기본 전체)')
    ap.add_argument("--out", choices=["mono", "dual", "both"], default="both")
    ap.add_argument("--model", default=DEFAULT_CLAUDE_MODEL, help="claude 엔진 모델")
    ap.add_argument("--outdir", type=Path, default=None)
    args = ap.parse_args()

    if not args.input.exists():
        die(f"입력 PDF 없음: {args.input}")
    if not PDF2ZH.exists():
        die(f"pdf2zh-next 미설치: {PDF2ZH}")
    if args.public and args.sensitive:
        die("--public 와 --sensitive 동시 지정 불가.")

    engine, reason = resolve_engine(args)
    outdir = args.outdir or (args.input.parent / f"{args.input.stem}_ko")
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"[pdf-ko] 엔진={engine} ({reason})", file=sys.stderr)
    print(f"[pdf-ko] 입력={args.input.name} 페이지={args.pages or '전체'} 출력={args.out} -> {outdir}",
          file=sys.stderr)

    cmd = build_cmd(engine, args, outdir)
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        die(f"pdf2zh 실패 (rc={rc})", code=rc)

    ok, report = verify_outputs(outdir, args.input)
    print(f"[pdf-ko] 검증:\n{report}", file=sys.stderr)
    if not ok:
        die("산출물 검증 실패 (tofu/오염/페이지수/한글밀도). 위 리포트 확인.", code=3)
    print(f"[pdf-ko] ✅ 완료: {outdir}", file=sys.stderr)


if __name__ == "__main__":
    main()

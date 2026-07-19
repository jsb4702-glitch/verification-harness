#!/usr/bin/env python3
"""
G9 훅 회귀테스트 — REG-G9-v2 (2026-07-03)
대상: g9_arith_enforce_v2.py (같은 디렉토리 또는 --hook 경로 지정)

구성:
  [UNIT] R01~R20 — 검출기 단위검증 (has_unverified_arith 직접 호출)
  [E2E ] E01~E05 — 훅 전체 파이프라인 (가짜 transcript JSONL + stdin 페이로드
                   → subprocess 실행 → stdout의 decision:block 유무 판정)

사용:
  python3 test_g9_regression.py                 # 같은 폴더의 g9_arith_enforce_v2.py 대상
  python3 test_g9_regression.py --hook ~/.claude/hooks/g9_arith_enforce.py   # 설치본 대상

종료코드: 0=전건 PASS / 1=FAIL 존재  (CI·pre-commit 연동용)
"""
import sys, os, json, tempfile, subprocess, importlib.util, argparse

# ── 대상 훅 로드 ─────────────────────────────────────────────
def load_hook(path):
    spec = importlib.util.spec_from_file_location("g9hook", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# ── [UNIT] 검출기 케이스: (ID, 입력텍스트, 기대) ─────────────
# 기대 BLOCK = 차단대상(True) / PASS = 통과(False)
UNIT_CASES = [
 # -- 정탐 유지 (원판에서도 잡던 것 — 회귀 금지) --
 ("R01", "손계산 평문",              "FM = 1.8 × 12000 = 21600 N 이다.",                    "BLOCK"),
 ("R07", "나눗셈+결과",              "듀티 = 3.3/5.0 = 0.66 이다.",                         "BLOCK"),
 ("R16", "거듭제곱 손계산",          "2^10 = 1024 바이트 단위.",                            "BLOCK"),
 ("R19", "√ 숫자형",                 "√2 ≈ 1.414 로 근사.",                                 "BLOCK"),
 # -- 패치 신규 정탐 (D2·D3b — 원판은 놓치던 것) --
 ("R02", "손계산 코드펜스 [D2]",     "결과:\n```\nFM = 1.8 * 12000 = 21600 N\n```\n합격.",  "BLOCK"),
 ("R17", "√ 괄호형 [D3b]",           "σred = √(240² + 3·80²) = 271 MPa.",                   "BLOCK"),
 ("R15", "× 결과 ≈동반 [D1b경계]",   "면적 100 × 200 ≈ 20000 mm² 이다.",                    "BLOCK"),
 # -- 패치 오탐 제거 (D1a·D1b — 원판은 헛블록하던 것) --
 ("R03", "CTE 과학표기 [D1a]",       "AL6061 CTE = 23.6×10⁻⁶ /K 이다.",                     "PASS"),
 ("R06", "dn/dT 과학표기 [D1a]",     "Ge dn/dT ≈ 396×10⁻⁶ /K.",                             "PASS"),
 ("R11", "캐럿 과학표기 [D1a]",      "굴절률 온도계수 23.6 x 10^-6 /K 수준.",               "PASS"),
 ("R04", "해상도 [D1b]",             "IMX585는 1920×1080 @60Hz 출력.",                      "PASS"),
 ("R05", "치수 2축 [D1b]",           "하우징 100×100mm 평면.",                              "PASS"),
 ("R12", "치수 3축 [D1b]",           "브래킷 100×50×20mm, AL6061-T6.",                      "PASS"),
 ("R13", "소문자 x 해상도 [D1b]",    "센서 3840x2160 @30fps.",                              "PASS"),
 # -- 정책 경계 (× 결과 미단언 = 산술 아님) --
 ("R14", "× 결과 미동반 [정책]",     "예압은 약 1.8 × 12000 N 수준으로 본다.",              "PASS"),
 # -- 기존 오탐방지 유지 (회귀 금지) --
 ("R08", "기호식 나눗셈 [D3보류]",   "Fmin = FA/(1-Φ) + FKR 로 구한다.",                    "PASS"),
 ("R09", "정직 미검증 면제",         "FM = 1.8 × 12000 = 21600 N. ⚠️ 산술 미검증.",         "PASS"),
 ("R10", "규격 인용",                "MIL-STD-810H Method 514.8 Category 24 적용.",         "PASS"),
 ("R18", "날짜",                     "2026-07-03 기준 개정판.",                             "PASS"),
 ("R20", "PSD 단위슬래시",           "PSD 0.04 g²/Hz, 20~2000 Hz 구간.",                    "PASS"),
]

# ── [E2E] transcript 빌더 ────────────────────────────────────
def mk_transcript(answer_text, with_bash=False):
    rows = [
        {"type": "user", "message": {"role": "user",
            "content": [{"type": "text", "text": "볼트 예압 계산해줘"}]}},
    ]
    content = []
    if with_bash:
        content.append({"type": "tool_use", "name": "Bash",
                        "id": "t1", "input": {"command": "python3 -c 'print(1.8*12000)'"}})
    content.append({"type": "text", "text": answer_text})
    rows.append({"type": "assistant", "message": {"role": "assistant", "content": content}})
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)

def run_hook_e2e(hook_path, answer, with_bash=False, stop_hook_active=False):
    """훅을 실제 subprocess로 실행. 반환: True=block 출력함 / False=무출력(통과)"""
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as f:
        f.write(mk_transcript(answer, with_bash))
        tpath = f.name
    try:
        payload = json.dumps({"transcript_path": tpath,
                              "stop_hook_active": stop_hook_active,
                              "session_id": "regtest"})
        r = subprocess.run([sys.executable, hook_path], input=payload,
                           capture_output=True, text=True, timeout=30)
        out = r.stdout.strip()
        if not out: return False
        try: return json.loads(out).get("decision") == "block"
        except Exception: return False
    finally:
        os.unlink(tpath)

E2E_CASES = [
 # (ID, 설명, answer, with_bash, stop_hook_active, 기대block?)
 ("E01", "손계산+Bash없음 → block",      "FM = 1.8 × 12000 = 21600 N.", False, False, True),
 ("E02", "손계산+Bash있음 → 통과",       "FM = 1.8 × 12000 = 21600 N.", True,  False, False),
 ("E03", "stop_hook_active → 통과(루프방지)", "FM = 1.8 × 12000 = 21600 N.", False, True, False),
 ("E04", "미검증 선언 → 통과",           "FM ≈ 21600 N. ⚠️ 산술 미검증.", False, False, False),
 ("E05", "산술없는 규격인용 → 통과",     "MIL-STD-810H 514.8 적용 권고.", False, False, False),
]

def main():
    ap = argparse.ArgumentParser()
    default_hook = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "g9_arith_enforce_v2.py")
    ap.add_argument("--hook", default=default_hook)
    a = ap.parse_args()
    hook_path = os.path.expanduser(a.hook)
    if not os.path.exists(hook_path):
        print(f"훅 파일 없음: {hook_path}"); sys.exit(2)

    mod = load_hook(hook_path)
    if not hasattr(mod, "has_unverified_arith"):
        print("⚠️ 대상 훅에 has_unverified_arith 없음 — v2 패치판이 아님. UNIT 생략, E2E만 수행.")
        unit_ok = None
    else:
        unit_ok = True
        print("── [UNIT] 검출기 20종 ──")
        for cid, name, text, exp in UNIT_CASES:
            got = "BLOCK" if mod.has_unverified_arith(text) else "PASS"
            ok = got == exp
            unit_ok &= ok
            print(f"{'✅' if ok else '❌'} {cid} {got:5s} 기대{exp:5s} | {name}")

    print("\n── [E2E] 훅 파이프라인 5종 ──")
    e2e_ok = True
    for cid, name, ans, wb, sha, exp in E2E_CASES:
        got = run_hook_e2e(hook_path, ans, wb, sha)
        ok = got == exp
        e2e_ok &= ok
        print(f"{'✅' if ok else '❌'} {cid} block={got} 기대{exp} | {name}")

    all_ok = (unit_ok in (True, None)) and e2e_ok
    print(f"\n=== 결과: {'ALL PASS' if all_ok else 'FAIL 존재'} ===")
    sys.exit(0 if all_ok else 1)

if __name__ == "__main__":
    main()

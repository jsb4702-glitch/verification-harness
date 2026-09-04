#!/usr/bin/env python3
"""ledger 스킵룰 실측: ①false-skip 레드팀 ②경계스윕 ③세션 리플레이. 격리 스토어."""
import json, os, subprocess, sys, tempfile

L = os.path.expanduser("~/.claude/tools/ledger/ledger.py")

def run(env, *args):
    r = subprocess.run([sys.executable, L, *args], capture_output=True, text=True, env=env)
    out = (r.stdout + r.stderr).strip()
    tier = out.split()[0] if out else "?"
    return tier, r.returncode

def fresh_env(tag):
    d = tempfile.mkdtemp(prefix=f"ledger-{tag}-")
    env = dict(os.environ); env["LEDGER_STORE"] = os.path.join(d, "s.jsonl")
    return env

# ── ① false-skip 레드팀 ─────────────────────────────────────
# (설명, add인자, check인자, 기대, must_not_skip)
BAT = [
 ("N1 동일값 재인용", ["--type","numeric","--key","예압 Fmin","--claim","12.5 kN","--value","12500","--verdict","confirmed"],
  ["--type","numeric","--key","예압 Fmin","--value","12500","--verdict","confirmed"], "SKIP", False),
 ("N2 반올림 12499.9 (8e-6)", None, ["--type","numeric","--key","예압 Fmin","--value","12499.9","--verdict","confirmed"], "SKIP", False),
 ("N3 끝자리 12501 (8e-5)", None, ["--type","numeric","--key","예압 Fmin","--value","12501","--verdict","confirmed"], "SKIP", False),
 ("N4 12520 (1.6e-3)", None, ["--type","numeric","--key","예압 Fmin","--value","12520","--verdict","confirmed"], "REF", True),
 ("N5 12625 (1%)", None, ["--type","numeric","--key","예압 Fmin","--value","12625","--verdict","confirmed"], "REF", True),
 ("N6 13700→13000류 (5.1%)", ["--type","numeric","--key","E 모듈러스","--claim","13700 MPa","--value","13700","--verdict","confirmed"],
  ["--type","numeric","--key","E 모듈러스","--value","13000","--verdict","confirmed"], "REF", True),
 ("N7 자릿수 1250 (90%)", None, ["--type","numeric","--key","예압 Fmin","--value","1250","--verdict","confirmed"], "CONTRA", True),
 ("N8 단위함정 N↔lbf 동일value", ["--type","numeric","--key","축하중","--claim","12500 N","--value","12500","--verdict","confirmed"],
  ["--type","numeric","--key","축하중","--claim","12500 lbf","--value","12500","--verdict","confirmed"], "REF", True),
 ("N9 단위환산누락 kN↔N", ["--type","numeric","--key","전단하중","--claim","12.5 kN","--value","12500","--verdict","confirmed"],
  ["--type","numeric","--key","전단하중","--value","12.5","--verdict","confirmed"], "CONTRA", True),
 ("C1 DOI 동일", ["--type","citation","--key","논문A DOI","--claim","10.1000/j.abc.2024.001","--verdict","confirmed"],
  ["--type","citation","--key","논문A DOI","--claim","10.1000/j.abc.2024.001","--verdict","confirmed"], "SKIP", False),
 ("C2 DOI 한글자差", None, ["--type","citation","--key","논문A DOI","--claim","10.1000/j.abc.2024.002","--verdict","confirmed"], "REF", True),
 ("C3 DOI 대소문자", None, ["--type","citation","--key","논문A DOI","--claim","10.1000/J.ABC.2024.001","--verdict","confirmed"], "SKIP", False),
 ("C4 규격 Rev G↔H", ["--type","citation","--key","진동시험 규격","--claim","MIL-STD-810H","--verdict","confirmed"],
  ["--type","citation","--key","진동시험 규격","--claim","MIL-STD-810G","--verdict","confirmed"], "REF", True),
 ("V1 tentative 재등장", ["--type","causal","--key","열팽창 가설","--claim","하우징 CTE가 지배","--verdict","tentative"],
  ["--type","causal","--key","열팽창 가설","--claim","하우징 CTE가 지배","--verdict","tentative"], "REF", True),
 ("V2 refuted 최신", ["--type","citation","--key","폐기 인용","--claim","STOC 2024","--verdict","refuted"],
  ["--type","citation","--key","폐기 인용","--claim","STOC 2024","--verdict","unverified"], "REF", True),
 ("K1 구두점 노이즈", ["--type","constraint","--key","작동온도, 범위!","--claim=-32~+49 °C","--verdict","confirmed"],
  ["--type","constraint","--key","작동온도 범위","--claim=-32~+49°C","--verdict","confirmed"], None, False),  # 관찰용, 선행대시=형
]
env = fresh_env("bat")
false_skips, mismatches, rows = [], [], []
for desc, add, chk, exp, mns in BAT:
    if add: run(env, "add", *add)
    tier, rc = run(env, "check", *chk)
    ok = "-" if exp is None else ("✅" if tier == exp else "❌")
    if exp is not None and tier != exp: mismatches.append(desc)
    if mns and tier == "SKIP": false_skips.append(desc)
    rows.append(f"{desc:32s} → {tier:6s} (기대 {exp or '관찰'}) {ok}")
print("── ① false-skip 레드팀 ──")
print("\n".join(rows))
print(f"\n**false-skip(의미상이인데 SKIP): {len(false_skips)}건** {false_skips or ''}")
print(f"기대불일치: {len(mismatches)}건 {mismatches or ''}")

# ── ② 경계 스윕 (기준값 10000, 편차별 판정) ─────────────────
env2 = fresh_env("sweep")
run(env2, "add", "--type","numeric","--key","스윕 기준","--claim","10000","--value","10000","--verdict","confirmed")
print("\n── ② SKIP_EQ_TOL=1e-3 경계 스윕 (기준 10000) ──")
for dev in [1e-5, 1e-4, 5e-4, 9e-4, 1.1e-3, 2e-3, 5e-3, 0.02, 0.05, 0.09, 0.11, 0.5]:
    v = 10000 * (1 + dev)
    tier, _ = run(env2, "check", "--type","numeric","--key","스윕 기준","--value",str(v),"--verdict","confirmed")
    print(f"  Δ={dev:>7.5f} ({v:>9.1f}) → {tier}")

# ── ③ 세션 리플레이: 스카웃2가 재조회한 라이선스 6건 ────────
env3 = fresh_env("replay")
turn2 = [("GPTCache 라이선스","MIT"),("OHI 라이선스","MIT"),("LiteLLM core 라이선스","MIT"),
         ("VeriScore 라이선스","Apache-2.0"),("FrugalGPT 라이선스","Apache-2.0"),("uqlm 라이선스","Apache-2.0")]
for k, c in turn2:
    run(env3, "add", "--type","citation","--key",k,"--claim",c,"--evidence","스카웃1 실조회","--verdict","confirmed")
turn3 = [("GPTCache 라이선스","MIT"),("OHI 라이선스","MIT"),("LiteLLM core 라이선스","MIT"),
         ("VeriScore 라이선스","MIT"),  # 심층조사서 setup.py=MIT 발견 — 실제 모순사례
         ("FrugalGPT 라이선스","Apache-2.0"),("uqlm 라이선스","Apache-2.0")]
skip = ref = 0
print("\n── ③ 세션 리플레이 (스카웃2 라이선스 재조회 6건) ──")
for k, c in turn3:
    tier, _ = run(env3, "check", "--type","citation","--key",k,"--claim",c,"--verdict","confirmed")
    skip += tier == "SKIP"; ref += tier == "REF"
    print(f"  {k:24s} 재인용 '{c}' → {tier}")
print(f"스킵 가능했던 재조회: {skip}/6 ({skip/6*100:.0f}%) | REF(재확인 필요 판정): {ref}건")

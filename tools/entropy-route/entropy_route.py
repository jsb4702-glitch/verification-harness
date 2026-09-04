#!/usr/bin/env python3
"""
entropy-route v0 — 이산 의미 엔트로피(discrete semantic entropy) 검증강도 라우팅 신호.

원리(Farquhar et al., Nature 2024의 discrete 변형):
  같은 질문에 짧은 답 N개를 샘플링 → 의미 동치 클러스터링 → 클러스터 분포 엔트로피.
  엔트로피 낮음 = 모델이 일관되게 같은 답 = 경량 통과 후보.
  엔트로피 높음 = 답이 갈림 = 지어낼 확률 높음 → 정밀검증(인용검증) 격상 후보.

v0 한계(정직 고지):
  - 질문 단위 신호(주장 단위 아님). 짧은 사실질문에서 유효, 설계판단 장문엔 부적합.
  - 클러스터링은 정규화 문자열/수치 매칭(NLI 아님). 표현만 다르고 뜻 같은 답을
    다른 클러스터로 쪼갤 수 있음(엔트로피 과대 = 과격상 방향 오류라 안전측).
  - 섀도 전용. 라우팅 결정에 개입하지 않고 jsonl 로그만 남긴다.

사용:
  python3 entropy_route.py --question "질문" --sampler mock|claude|ollama --n 3
  종료코드 0, stdout에 결과 JSON 1줄. 로그는 --log 경로에 append.

샘플러:
  mock   = 고정 응답(드라이런용, 외부호출 0)
  claude = claude -p --model claude-haiku-4-5 (구독 CLI, API키 불요)
  ollama = ollama run gemma4 (완전 로컬, 민감/민감 질문용)
"""
import argparse, json, math, os, re, subprocess, sys, time

DEF_LOG = os.path.expanduser("~/.claude/tools/entropy-route/shadow.jsonl")

PROBE = ("다음 질문에 한 줄로만, 핵심 값/사실만 답하라. 확신이 75% 이상일 때만 답하고, "
         "아니면 정확히 '모름'이라고만 써라 — 오답은 무답의 3배로 나쁘다. "
         "설명 금지. 질문: ")

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")
_WS  = re.compile(r"[\s\.\,\!\?\:\;\'\"\(\)\[\]·…~]+")


def normalize(ans: str) -> str:
    """클러스터 키: 소문자화·기호제거. 수치가 있으면 수치열이 키를 지배."""
    a = ans.strip().lower()
    nums = _NUM.findall(a.replace(",", ""))
    if nums:
        return "|".join(nums)
    return _WS.sub("", a)[:80]


def cluster(samples):
    """정규화 키 매칭 + 단일수치 ±5% 동치 병합."""
    keys = [normalize(s) for s in samples]
    groups = []                                   # [(대표키, [인덱스])]
    for i, k in enumerate(keys):
        placed = False
        for g in groups:
            rk = g[0]
            if k == rk:
                g[1].append(i); placed = True; break
            try:
                a, b = float(k), float(rk)
                if b != 0 and abs(a - b) / abs(b) <= 0.05:
                    g[1].append(i); placed = True; break
            except ValueError:
                pass
        if not placed:
            groups.append((k, [i]))
    return groups


def entropy_norm(groups, n):
    """클러스터 분포 엔트로피를 ln(n)으로 정규화(0=만장일치, 1=전부 다른 답)."""
    if n <= 1:
        return 0.0
    h = 0.0
    for _, idx in groups:
        p = len(idx) / n
        h -= p * math.log(p)
    return round(h / math.log(n), 4)


def sample_mock(question, n):
    # 드라이런: 결정론 응답. 질문에 'MOCKVARY'가 있으면 일부러 갈리는 답을 낸다.
    if "MOCKVARY" in question:
        base = ["42 MPa", "55 MPa", "모름"]
        return [base[i % 3] for i in range(n)]
    return ["42 MPa"] * n


def sample_claude(question, n, timeout=90):
    out = []
    for _ in range(n):
        r = subprocess.run(
            ["claude", "-p", "--model", "claude-haiku-4-5", PROBE + question],
            capture_output=True, text=True, timeout=timeout)
        out.append(r.stdout.strip() or "(빈응답)")
    return out


def sample_ollama(question, n, timeout=120):
    out = []
    for _ in range(n):
        r = subprocess.run(
            ["ollama", "run", "gemma4", PROBE + question],
            capture_output=True, text=True, timeout=timeout)
        out.append(r.stdout.strip() or "(빈응답)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", required=True)
    ap.add_argument("--sampler", default="mock", choices=["mock", "claude", "ollama"])
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--log", default=DEF_LOG)
    ap.add_argument("--lo", type=float, default=0.3)   # 이하 = 경량 통과 후보
    ap.add_argument("--hi", type=float, default=0.7)   # 이상 = 정밀검증 격상 후보
    a = ap.parse_args()

    t0 = time.time()
    fn = {"mock": sample_mock, "claude": sample_claude, "ollama": sample_ollama}[a.sampler]
    try:
        samples = fn(a.question, a.n)
    except Exception as e:                     # 샘플러 실패 = 신호없음 강등, 세션 불차단
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "question": a.question[:300],
               "sampler": a.sampler, "n": a.n, "error": repr(e)[:200], "verdict": "ERROR"}
        _emit(rec, a.log)
        return

    # '모름' 다수결이면 엔트로피와 무관하게 격상(모델 스스로 지식경계 밖 선언)
    idk = sum(1 for s in samples if "모름" in s or s == "(빈응답)")
    groups = cluster(samples)
    h = entropy_norm(groups, len(samples))
    if idk * 2 >= len(samples):
        verdict = "ESCALATE_IDK"
    elif h <= a.lo:
        verdict = "PASS_LIGHT"
    elif h >= a.hi:
        verdict = "ESCALATE"
    else:
        verdict = "MID"

    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "question": a.question[:300],
           "sampler": a.sampler, "n": len(samples), "samples": [s[:120] for s in samples],
           "clusters": [[k[:40], len(ix)] for k, ix in groups], "entropy_norm": h,
           "idk": idk, "verdict": verdict, "sec": round(time.time() - t0, 1)}
    _emit(rec, a.log)


def _emit(rec, log):
    line = json.dumps(rec, ensure_ascii=False)
    print(line)
    try:
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Tier-0 구조 린트 — 무료·결정적·무노이즈 회귀 카나리아.
하네스 '텍스트'가 온전한지 검사: 게이트 정의 누락, 워크플로 경로 깨짐, 절대게이트 섹션 유실.
LLM 거동이 아니라 규율 텍스트의 구조 무결성을 본다 → 거짓알람 0.
exit 0 = 정상, exit 2 = 구조 회귀.
"""
import os, re, sys

HOME = os.path.expanduser("~")
CLAUDE_MD = os.path.join(HOME, ".claude", "CLAUDE.md")

# 반드시 존재해야 하는 게이트 앵커 (ID + 의미키워드 쌍 — ID만 바뀌어도, 의미가 빠져도 적발)
REQUIRED_GATES = {
    "G1": "등급", "G2": "확인필요", "G3": "web_search", "G4": "날조",
    "G5": None, "G6": "환각", "G7": "모순", "G8": "가정",
    "G9": "산술", "G10": "자기비판", "G11": "입력격리",
    "G12": "출력대조", "G13": "재발방지",
}
# 절대게이트 섹션 핵심 문구
REQUIRED_PHRASES = ["절대게이트", "신뢰도 등급", "EXECUTION LOOP", "VALIDATION GATE"]


def main():
    if not os.path.exists(CLAUDE_MD):
        print(f"🔴 CLAUDE.md 없음: {CLAUDE_MD}")
        return 2
    text = open(CLAUDE_MD, encoding="utf-8").read()
    fails = []

    # 1) 게이트 ID + 의미키워드
    for gid, kw in REQUIRED_GATES.items():
        if not re.search(rf"\b{gid}\b", text):
            fails.append(f"게이트 ID 누락: {gid}")
        elif kw and kw not in text:
            fails.append(f"게이트 {gid} 의미키워드 '{kw}' 유실")

    # 2) 핵심 섹션 문구
    for p in REQUIRED_PHRASES:
        if p not in text:
            fails.append(f"핵심 섹션 문구 유실: '{p}'")

    # 3) 참조된 워크플로 scriptPath 실재 확인 (절대경로)
    paths = set(re.findall(r'scriptPath:"([^"]+\.js)"', text))
    for p in paths:
        rp = p.replace("~", HOME)
        if not os.path.exists(rp):
            fails.append(f"워크플로 경로 깨짐: {p}")
    if not paths:
        fails.append("scriptPath 참조 0개 — 워크플로 배선 유실 의심")

    # 4) 신뢰도 등급 기호 3종 존재
    for sym in ("🟢", "🟡", "🔴"):
        if sym not in text:
            fails.append(f"신뢰도 등급기호 유실: {sym}")

    if fails:
        print(f"🔴 구조 회귀 {len(fails)}건:")
        for f in fails:
            print(f"   ❌ {f}")
        return 2
    print(f"🟢 구조 린트 통과 — 게이트 {len(REQUIRED_GATES)}개·워크플로 {len(paths)}개·등급기호 정상")
    return 0


if __name__ == "__main__":
    sys.exit(main())

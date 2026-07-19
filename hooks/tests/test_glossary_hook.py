#!/usr/bin/env python3
"""answer_glossary_enforce.py v2 회귀 테스트 — 합성 트랜스크립트 주입."""
import json, os, subprocess, sys, tempfile

HOOK = os.path.expanduser("~/.claude/hooks/answer_glossary_enforce.py")
TD = tempfile.mkdtemp(prefix="glosshook_")

CASES = [
    # (id, user_text, answer_text, expect_block, must_contain_in_reason_or_None)
    ("사고재현_G12날것", "배선 들어가보자", "G12 섀도에 도구실행 없는 완료주장 1건이 떠 있다.", True, "다시 내보내지 마라"),
    ("신규_쌍따옴표인용", "배선 들어가보자", '리포트의 "G12 완료주장" 로그에 1건이 떠 있다.', False, None),
    ("신규_curly인용", "배선 들어가보자", "리포트의 “G12 완료주장” 로그에 1건이 떠 있다.", False, None),
    ("신규_낫표인용", "배선 들어가보자", "리포트의 「G12 완료주장」 로그에 1건이 떠 있다.", False, None),
    ("신규_인라인코드", "배선 들어가보자", "설정에서 `G9` 항목을 참조한다.", False, None),
    ("오탐가드_CNC", "이 프로그램 봐줘", "CNC 가공에서 G1 직선보간, G0 급속이송으로 간다. M코드도 확인해라.", False, None),
    ("오탐가드_5G", "안테나 어때", "5G 모뎀 안테나는 별도 검토가 필요하다.", False, None),
    ("오탐가드_강종", "재질 뭐 쓰지", "SM45C 강종은 KS D 3752 계열이고 G4051 언급은 일본 JIS 쪽이다.", False, None),
    ("기존_유저메타예외", "하네스 게이트 G4 설명해줘", "G4는 날조 차단이다. 풀PN 추정생성을 막는다.", False, None),
    ("기존_교습예외", "용어 정리해줘", "용어집 기준으로 G4=날조 차단, G9=계산 검증으로 치환한다.", False, None),
    ("차단유지_BLUF", "요약해줘", "결론부터(BLUF) 말하면 이 설계는 통과다.", True, "다시 내보내지 마라"),
    ("차단유지_GA그룹", "점검 결과는", "GA 그룹 점검을 마쳤고 이상 없다.", True, None),
    ("차단유지_한자오염", "정리해줘", "이 답변은 정상이지만 答이 섞였다.", True, "정정 줄만"),
    ("혼합_인용밖날것", "배선 들어가보자", '"G12 완료주장" 로그는 인용인데 G9 검증은 날것이다.', True, None),
]

fails = 0
for cid, user, answer, expect_block, must in CASES:
    tpath = os.path.join(TD, cid + ".jsonl")
    with open(tpath, "w") as f:
        f.write(json.dumps({"type": "user", "message": {"content": user}}, ensure_ascii=False) + "\n")
        f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}}, ensure_ascii=False) + "\n")
    payload = json.dumps({"transcript_path": tpath})
    out = subprocess.run(["/usr/bin/python3", HOOK], input=payload,
                         capture_output=True, text=True).stdout.strip()
    blocked = bool(out) and '"block"' in out
    ok = blocked == expect_block
    if ok and must and blocked:
        ok = must in out
    status = "PASS" if ok else "FAIL"
    if not ok:
        fails += 1
    print(f"[{status}] {cid}: expect_block={expect_block} got_block={blocked}" + ("" if ok else f" out={out[:120]}"))

print(f"\n결과: {len(CASES)-fails}/{len(CASES)} 통과")
sys.exit(1 if fails else 0)

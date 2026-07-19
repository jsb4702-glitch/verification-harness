#!/usr/bin/env python3
"""PreToolUse hook: 이슈성(위험) 권한 사용만 골라 기록. 비차단(항상 exit 0).
전권(bypassPermissions) 하에서 위험 작업의 감사 로그 역할."""
import sys, json, re, datetime, os

LOG = os.path.expanduser("~/.claude/eval/PERMISSION_LOG.md")
os.makedirs(os.path.dirname(LOG), exist_ok=True)  # 로그 폴더 자동생성(타 PC 이식 대비)

# 위험 패턴: 삭제·덮어쓰기·외부전송·권한/시스템 변경·git 파괴적·프로세스 종료
RISKY = [
    (r'\brm\s+-[rf]|\brm\s+.*\*|\brmdir\b', "삭제(rm)"),
    (r'\bdd\b|\bmkfs|\bdiskutil\b', "디스크 조작"),
    (r'\bcurl\b|\bwget\b|\bscp\b|\brsync\b.*::|\bssh\b|\bnc\b', "외부 전송/접속"),
    (r'\bgit\s+push|\bgit\s+reset\s+--hard|\bgit\s+clean|\bgit\s+rebase', "git 파괴적"),
    (r'\bsudo\b|\bchmod\b|\bchown\b|\blaunchctl\b|\bdefaults\s+write', "권한/시스템 변경"),
    (r'\bpkill\b|\bkillall\b', "프로세스 종료"),
    (r'\bnpm\s+publish|\bgh\s+(pr|release)\s+create', "외부 발행"),
    (r'\bsecurity\b.*(find|delete)|\.credentials', "비밀/자격증명 접근"),
]

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool = data.get("tool_name", "")
    inp = data.get("tool_input", {}) or {}
    cmd = inp.get("command", "") if tool == "Bash" else ""
    if not cmd:
        sys.exit(0)
    hits = [label for pat, label in RISKY if re.search(pat, cmd)]
    if not hits:
        sys.exit(0)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cwd = data.get("cwd", os.getcwd())
    one = cmd.replace("\n", " ⏎ ")
    if len(one) > 300:
        one = one[:300] + "…"
    line = f"| {ts} | {', '.join(sorted(set(hits)))} | `{one}` | {cwd} |\n"
    try:
        new = not os.path.exists(LOG)
        with open(LOG, "a", encoding="utf-8") as f:
            if new:
                f.write("# PERMISSION_LOG — 이슈성 권한 사용 감사 기록\n\n")
                f.write("> 전권(bypassPermissions) 하 위험작업 자동기록. PreToolUse 훅(log_risky_ops.py)이 적재. 비차단.\n\n")
                f.write("| 일시 | 분류 | 명령 | cwd |\n|------|------|------|-----|\n")
            f.write(line)
    except Exception:
        pass
    sys.exit(0)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""integrity-guard: Claude 하네스 크리티컬 파일 무결성 감시 (경고전용·자동수정 없음).

baseline : 현재 상태를 SHA-256 매니페스트로 박제 (정당한 변경 후 수동 실행)
check    : 매니페스트 대조 — 드리프트 시 drift.log 기록 + macOS 알림, exit 1

위협모델: 같은 계정으로 도는 외부 에이전트(Antigravity/agy 등)의
~/.claude 크리티컬 파일 무단 수정. 판정은 사람게이트 — 여기선 탐지·알림만.
"""
import glob
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime

HOME = os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.join(HERE, "baseline.json")
DRIFT_LOG = os.path.join(HERE, "drift.log")
NTFY = f"{HOME}/.claude/scripts/ntfy.sh"

# 감시대상: 저변동·고위험 파일만 (메모리·projects 등 고변동 경로 제외)
FILES = [
    f"{HOME}/.claude/CLAUDE.md",
    f"{HOME}/CLAUDE.md",
    f"{HOME}/.claude/settings.json",
    f"{HOME}/.claude/settings.local.json",
    f"{HOME}/harness-bridge/bridge.py",
    f"{HOME}/harness-bridge/cite_rail.py",
    # 2026-07-18: 외부 에이전트 상시권한·실행표면 (agy grant 42건 누적을 놓친 구멍 봉합)
    # agy는 전역 allow가 단조증가하는 래칫 → 파일해시로 증가 자체를 보이게 함
    f"{HOME}/.gemini/config/config.json",
    # agy 정체성 자동개서 경로 (2026-07-18): launchd WatchPaths[~/harness-bridge/to_agy]가
    # harness_auto_updater.py를 발동 → AGENTS.golden.md를 AGENTS.md에 덮어씀(GEMINI.md는 그 심링크).
    # grant 정리로 닫히지 않는 경로 — 자가검증이 타우톨로지(golden 쓰고 golden 검사)라 항상 PASS,
    # 백업도 PASS 시 삭제. 따라서 외부 해시 감시가 유일한 사후 탐지 수단.
    f"{HOME}/.gemini/config/AGENTS.golden.md",
    f"{HOME}/.gemini/config/AGENTS.md",
    f"{HOME}/.gemini/antigravity/scratch/harness_auto_updater.py",
    # 심링크 자체도 감시: sha256이 링크를 따라가므로 링크가 다른 대상/실파일로 바뀌면
    # AGENTS.md는 그대로여도 해시가 달라진다 = 심링크 스왑 탐지 (중복비용 1해시)
    f"{HOME}/.gemini/GEMINI.md",
    # cdx는 권한이 스레드별이라 래칫 없음 → 대신 마켓플레이스 소스·모델·notify 훅 변조 감시
    f"{HOME}/.codex/config.toml",
    f"{HOME}/.codex/hooks.json",
    # 제외 판단: .codex-global-state.json(전자 UI 상태·초단위 변동), auth.json(토큰 갱신마다 변함) — 노이즈만
    # 감시자 자기보호: 이 파일들 변조 = 감시 무력화 시도 (baseline.json은 자기참조라 제외 — NAS git 이중화로 커버)
    os.path.join(HERE, "ig.py"),
    os.path.join(HERE, "healthcheck.sh"),
    f"{HOME}/.claude/tools/skillscan/skillscan_guard.sh",
    f"{HOME}/.claude/tools/skillscan/skill-intake.sh",
    f"{HOME}/.claude/scripts/ntfy.sh",
    # 2026-07-18: 래퍼만 지키고 룰 엔진이 사각이었다 — skillscan.py를 두 번 고쳤는데 드리프트 0건이었음.
    # NL_RULES/CODE_RULES를 비우면 guard.sh는 그대로 exit 0 → "clean" 무한보고. 판단을 *내리는* 쪽을 지킨다.
    f"{HOME}/.claude/tools/skillscan/skillscan.py",
    f"{HOME}/.claude/tools/skillscan/skillscan_rules_supplement.py",
    f"{HOME}/.claude/tools/skillscan/dyntrace.py",
    # 억제목록도 감시: fingerprint를 쑤셔넣어 전건 억제하는 경로 차단(정당한 갱신은 재기준선으로 승인)
    f"{HOME}/.claude/tools/skillscan/baseline.json",
]
DIRS = [
    f"{HOME}/.claude/hooks",
    f"{HOME}/.claude/workflows",
]
# 2026-07-18: 손으로 파일을 하나씩 넣다 보니 같은 디렉토리의 형제 스크립트를 계속 빠뜨렸다
# (skillscan 엔진 4종은 넣었는데 skillscan_shadow.py·heartbeat.py·weekly.sh는 누락).
# → 디렉토리 단위로 쓸되, 로그/상태/캐시 노이즈를 피하려 *코드 확장자만* 해시한다.
CODE_DIRS = [
    f"{HOME}/.claude/tools",
    f"{HOME}/.claude/scripts",
]
CODE_EXT = (".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".ts", ".rb", ".pl")

# launchd가 자동실행하는 ~/.claude 밖 스크립트 (plist는 GLOBS로 이미 감시 중이나,
# plist를 안 건드리고 타깃 스크립트 내용만 바꾸면 무탐지였다 — 래퍼/엔진 분리 문제)
LAUNCHD_TARGETS = [
    f"{HOME}/.gemini/antigravity_token_updater.py",      # Interval 10s — 최고빈도
    f"{HOME}/.gemini/antigravity/radar/weekly_radar.sh",
    f"{HOME}/harness-bridge/bridge-watch-popup.sh",      # WatchPaths(bridge) 발동
    f"{HOME}/.hermes/auto-update.sh",
    f"{HOME}/.hermes/update-watchdog.sh",
    f"{HOME}/harness-eval/shadow-review/run_quarterly.sh",
    f"{HOME}/repo-arena/weekly_arena.sh",
    f"{HOME}/ai-github-curation/scripts/run_daily.sh",
    f"{HOME}/Developer/ClaudeUsageBar/keepfresh.sh",
]
# launchd plist 바꿔치기 = 제일 쉬운 감시 우회로 → 전체 감시 (신규 plist 출현도 적발)
GLOBS = [
    f"{HOME}/Library/LaunchAgents/*.plist",
]


def iter_targets():
    for p in FILES + LAUNCHD_TARGETS:
        if os.path.isfile(p):
            yield p
    for d in CODE_DIRS:
        if not os.path.isdir(d):
            continue
        for root, dirs, names in os.walk(d):
            dirs[:] = [x for x in dirs
                       if not x.startswith(".") and x not in ("__pycache__", "venv", "node_modules", "store")]
            for n in sorted(names):
                if n.endswith(CODE_EXT):
                    yield os.path.join(root, n)
    for g in GLOBS:
        for p in sorted(glob.glob(g)):
            if os.path.isfile(p):
                yield p
    for d in DIRS:
        if not os.path.isdir(d):
            continue
        for root, dirs, names in os.walk(d):
            # __pycache__ 제외: 실행마다 재생성돼 영구 드리프트 노이즈 (2026-07-18)
            dirs[:] = [x for x in dirs if not x.startswith(".") and x != "__pycache__"]
            for n in sorted(names):
                if n.startswith(".") or n.endswith((".pyc", ".pyo")):
                    continue
                yield os.path.join(root, n)


def sha256(path):
    # 2026-07-18: 읽기 실패를 예외로 흘리면 snapshot()이 죽고 check 전체가 사망한다.
    # os.path.isfile()은 읽기권한 없어도 True → 감시대상 하나를 chmod 000 하면 감시망이 멎고,
    # 종료코드는 정상 드리프트와 같은 1이라 겉으로 구분이 안 됐다(감시 무력화 경로).
    # → 예외를 센티넬 해시로 바꿔 "변경됨"으로 잡히게 한다. 죽는 대신 짖는다.
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        return f"UNREADABLE:{type(e).__name__}"


def snapshot():
    return {p: sha256(p) for p in iter_targets()}


def cmd_baseline():
    snap = snapshot()
    with open(BASELINE, "w", encoding="utf-8") as f:
        json.dump({"created": datetime.now().isoformat(timespec="seconds"),
                   "files": snap}, f, ensure_ascii=False, indent=1)
    print(f"baseline: {len(snap)} files -> {BASELINE}")


def notify(msg):
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{msg}" with title "⚠️ integrity-guard 드리프트"'],
                       capture_output=True, timeout=10)
    except Exception:
        pass
    # ntfy 원격알림 (공용서버 — 경로·내용 미포함, 건수만)
    if os.path.isfile(NTFY):
        try:
            subprocess.run(["/bin/bash", NTFY, "integrity-guard 드리프트",
                            msg, "high", "rotating_light"],
                           capture_output=True, timeout=15)
        except Exception:
            pass


def cmd_check():
    if not os.path.isfile(BASELINE):
        print("no baseline — run: ig.py baseline", file=sys.stderr)
        return 2
    with open(BASELINE, encoding="utf-8") as f:
        base = json.load(f)["files"]
    now = snapshot()
    changed = sorted(p for p in base if p in now and base[p] != now[p])
    removed = sorted(p for p in base if p not in now)
    added = sorted(p for p in now if p not in base)
    if not (changed or removed or added):
        print("clean")
        return 0
    ts = datetime.now().isoformat(timespec="seconds")
    lines = [f"[{ts}] DRIFT changed={len(changed)} removed={len(removed)} added={len(added)}"]
    for tag, group in (("~", changed), ("-", removed), ("+", added)):
        lines += [f"  {tag} {p}" for p in group]
    report = "\n".join(lines)
    with open(DRIFT_LOG, "a", encoding="utf-8") as f:
        f.write(report + "\n")
    print(report)
    # 공용 ntfy 경유라 경로·파일명 미포함 — 건수만 (상세는 로컬 drift.log)
    notify(f"크리티컬 파일 {len(changed)+len(removed)+len(added)}건 변경 감지 — 맥 drift.log 확인")
    return 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    # 예기치 못한 예외는 종료코드 3으로 분리 — 1(드리프트)과 겹치면
    # "감시가 죽은 것"과 "변경이 잡힌 것"을 launchd/사람이 구분할 수 없다.
    try:
        if cmd == "baseline":
            cmd_baseline()
        elif cmd == "check":
            sys.exit(cmd_check())
        else:
            print(__doc__)
            sys.exit(2)
    except SystemExit:
        raise
    except Exception as e:
        print(f"integrity-guard 내부오류(감시 미수행): {type(e).__name__}: {e}", file=sys.stderr)
        notify(f"integrity-guard 자체 오류 — 감시 미수행 ({type(e).__name__})")
        sys.exit(3)

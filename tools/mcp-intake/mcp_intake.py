#!/usr/bin/env python3
"""mcp-intake: MCP 서버 공급망 게이트 (경고전용·자동차단 없음).

배경(2026-07-18): 스킬·플러그인은 skill-intake.sh가 격리→검증→승격으로 막는데,
MCP 서버는 .claude.json에 한 줄 넣으면 PyPI/npm에서 코드가 곧장 들어온다.
실측: jcodemunch-mcp가 3주간 20+ 버전 자동갱신(핀 없음), 238파일·4.2MB가
매 세션 툴 96개로 붙는데 INTAKE를 한 번도 안 거쳤다.

감지 4종:
  1) 신규 MCP 서버 등장            → INTAKE 미이행 신호
  2) 버전 핀 없음                  → 매 실행 최신판 = 통제 불가
  3) 등록 정의 변경(명령·인자·env)  → 재검토 요구
  4) 활성 패키지 정적 스캔 HIGH     → 악성 신호 (skillscan 재사용)

판정은 사람게이트. 여기선 탐지·리포트만 한다.
용법: mcp_intake.py [check|baseline]   종료코드 0=clean 1=변경/미핀 2=HIGH 3=내부오류
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
LOG = os.path.join(HERE, "intake.log")
SKILLSCAN = f"{HOME}/.claude/tools/skillscan/skillscan.py"
CONFIGS = [f"{HOME}/.claude.json", f"{HOME}/.claude/settings.json"]


def collect_servers():
    """전 설정에서 MCP 서버 정의 수집 → {스코프::이름: 정의}"""
    out = {}
    for cfg in CONFIGS:
        if not os.path.isfile(cfg):
            continue
        try:
            d = json.load(open(cfg, encoding="utf-8"))
        except Exception:
            continue
        for name, spec in (d.get("mcpServers") or {}).items():
            out[f"global::{name}"] = spec
        for proj, pv in (d.get("projects") or {}).items():
            for name, spec in ((pv or {}).get("mcpServers") or {}).items():
                out[f"{proj}::{name}"] = spec
    return out


def spec_digest(spec):
    """정의를 정규화해 해시 — 명령·인자·env 변경을 잡는다."""
    norm = json.dumps({
        "command": spec.get("command"),
        "args": spec.get("args") or [],
        "env": sorted((spec.get("env") or {}).items()),
        "type": spec.get("type"),
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def pkg_spec(spec):
    """실행 인자에서 패키지 스펙 추출 + 핀 여부. (pkg, pinned)"""
    args = [a for a in (spec.get("args") or []) if isinstance(a, str)]
    for a in args:
        if a.startswith("-"):
            continue
        pinned = ("==" in a) or ("@" in a.lstrip("@")) or a.count("@") > 0
        return a, pinned
    return (spec.get("command") or "?"), False


def active_pkg_dirs(pkg):
    """uv 캐시에서 해당 패키지의 활성(최신 설치) 디렉토리 추정."""
    stem = pkg.split("==")[0].split("@")[0].replace("-", "_")
    cands = glob.glob(f"{HOME}/.cache/uv/archive-v0/*/{stem}")
    if not cands:
        return []
    cands.sort(key=lambda p: os.stat(p).st_mtime, reverse=True)
    return cands[:1]


def scan_pkg(path):
    """활성 패키지에 skillscan 정적 스캔. (HIGH, MED) 반환. 실패 시 (None, None)."""
    if not os.path.isfile(SKILLSCAN):
        return None, None
    tmp = os.path.join(HERE, ".scan.json")
    try:
        subprocess.run([sys.executable, SKILLSCAN, path, "--json", tmp],
                       capture_output=True, timeout=180)
        c = json.load(open(tmp)).get("counts", {})
        return c.get("HIGH", 0), c.get("MED", 0)
    except Exception:
        return None, None
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def snapshot():
    snap = {}
    for key, spec in collect_servers().items():
        pkg, pinned = pkg_spec(spec)
        snap[key] = {"digest": spec_digest(spec), "pkg": pkg, "pinned": pinned}
    return snap


def cmd_baseline():
    snap = snapshot()
    json.dump({"created": datetime.now().isoformat(timespec="seconds"), "servers": snap},
              open(BASELINE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"baseline: {len(snap)} MCP 서버 -> {BASELINE}")
    for k, v in snap.items():
        print(f"  {k}  pkg={v['pkg']}  pinned={'✅' if v['pinned'] else '❌'}")


def cmd_check():
    now = snapshot()
    base = {}
    if os.path.isfile(BASELINE):
        try:
            base = json.load(open(BASELINE, encoding="utf-8")).get("servers", {})
        except Exception:
            base = {}

    added = [k for k in now if k not in base]
    changed = [k for k in now if k in base and now[k]["digest"] != base[k]["digest"]]
    removed = [k for k in base if k not in now]
    unpinned = [k for k, v in now.items() if not v["pinned"]]

    lines, worst = [], 0
    for k in added:
        lines.append(f"  + 신규 MCP 서버(INTAKE 미이행 의심): {k}  pkg={now[k]['pkg']}")
        worst = max(worst, 1)
    for k in changed:
        lines.append(f"  ~ 정의 변경(재검토 요구): {k}  pkg={now[k]['pkg']}")
        worst = max(worst, 1)
    for k in removed:
        lines.append(f"  - 제거됨: {k}")
    for k in unpinned:
        lines.append(f"  ! 버전 미핀(매 실행 최신판): {k}  pkg={now[k]['pkg']}")
        worst = max(worst, 1)

    # 신규/변경 서버만 정적 스캔 (매번 전량 스캔은 비용 낭비)
    for k in set(added) | set(changed):
        for d in active_pkg_dirs(now[k]["pkg"]):
            high, med = scan_pkg(d)
            if high is None:
                lines.append(f"  ? 스캔 실패: {k}")
            else:
                lines.append(f"  · 정적스캔 {k}: HIGH={high} MED={med}  ({os.path.basename(d)})")
                if high:
                    worst = 2

    if not lines:
        print("clean — MCP 서버 변경 없음, 전부 핀 상태")
        return 0

    ts = datetime.now().isoformat(timespec="seconds")
    report = "\n".join([f"[{ts}] MCP-INTAKE 경고"] + lines)
    print(report)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(report + "\n")
    return worst


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    try:
        if cmd == "baseline":
            cmd_baseline()
        elif cmd == "check":
            sys.exit(cmd_check())
        else:
            print(__doc__)
            sys.exit(3)
    except SystemExit:
        raise
    except Exception as e:
        print(f"mcp-intake 내부오류(검사 미수행): {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(3)

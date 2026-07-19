#!/usr/bin/env python3
"""memory_inbox 포인터 -> 세션 다이제스트 추출기 (결정론·무 LLM). [v2 staging]

v2 변경(라이브 미반영, 검수용):
- 자가테스트/인젝션 세션 결정론 프리필터(NOISE_SIG) — 상한 슬롯 절약.
- 경량 head 스캐너 first_user_quick — 프리필터·감사로그용, 전체순회 회피.
- 드롭 감사로그 dropped.log — 노이즈+상한초과 유실 사후검증.
- --inbox 옵션 — 검증용 임시 inbox 지정.
"""
import os, re, json, sys, argparse, shutil, datetime

INBOX = os.path.expanduser("~/.claude/memory_inbox")
SR = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)

# 자가테스트/인젝션 세션 결정론 프리필터 시그니처 (첫 user 발췌 대상)
# 스코프 주의: 인젝션·모드해제 확정 패턴만. 물성 단답("~얼마야")은 오탐 위험 커서 제외 → LLM 판정 유지.
NOISE_SIG = re.compile(
    r"너는\s*이제.*(모드|DAN)|게이트\s*(다\s*)?(꺼|끄|해제|없)|규율\s*다\s*(꺼|끄)|"
    r"^\s*SYSTEM\s*(OVERRIDE)?\s*:|이전\s*지시.*(무시|전부)|"
    r"DevMode|Developer\s*Mode|HARNESS\s*DISABLED|MODE\s*[:=]\s*UNLOCKED",
    re.I | re.M)

def parse_pointers(inbox):
    """미처리 inbox 일파일들 -> {transcript_path: 최신 event}, 소스 파일 목록"""
    files, seen = [], {}
    for f in sorted(os.listdir(inbox)):
        p = os.path.join(inbox, f)
        if not (f.endswith(".md") and os.path.isfile(p)):
            continue
        files.append(p)
        for ln in open(p, encoding="utf-8", errors="replace"):
            m = re.search(r"event=(\S+).*?transcript=(\S+)", ln)
            if m and m.group(2).endswith(".jsonl"):
                seen[m.group(2)] = m.group(1)
    return seen, files

def block_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""

def first_user_quick(path, head_chars, max_lines=250):
    """파일 앞부분만 읽어 첫 user 텍스트 추출 (프리필터·감사로그용, 전체순회 회피)."""
    n = 0
    try:
        for ln in open(path, encoding="utf-8", errors="replace"):
            n += 1
            if n > max_lines:
                break
            try:
                d = json.loads(ln)
            except Exception:
                continue
            msg = d.get("message") or {}
            if d.get("type") == "user" or msg.get("role") == "user":
                txt = SR.sub("", block_text(msg.get("content"))).strip()
                if txt:
                    return txt[:head_chars]
    except Exception:
        pass
    return ""

def digest_one(path, head_chars, tail_chars):
    first_user, tails = None, []
    try:
        for ln in open(path, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(ln)
            except Exception:
                continue
            msg = d.get("message") or {}
            role, t = msg.get("role"), d.get("type")
            txt = block_text(msg.get("content"))
            if not txt.strip():
                continue
            if first_user is None and (t == "user" or role == "user"):
                clean = SR.sub("", txt).strip()
                if clean:
                    first_user = clean[:head_chars]
            if t == "assistant" or role == "assistant":
                tails.append(txt)
    except Exception as e:
        return None
    if first_user is None and not tails:
        return None
    tail, budget = [], tail_chars
    for txt in reversed(tails):          # 뒤에서부터 tail_chars 만큼
        take = txt[-budget:]
        tail.insert(0, take)
        budget -= len(take)
        if budget <= 0:
            break
    return first_user or "(첫 사용자 메시지 없음)", "\n".join(tail)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=15, help="세션 상한(최신 mtime순)")
    ap.add_argument("--min-kb", type=int, default=20, help="트랜스크립트 최소 크기")
    ap.add_argument("--head", type=int, default=300, help="첫 사용자 메시지 발췌 chars")
    ap.add_argument("--tail", type=int, default=2500, help="어시스턴트 꼬리 chars")
    ap.add_argument("--out", default="-", help="다이제스트 출력 경로(- = stdout)")
    ap.add_argument("--inbox", default=INBOX, help="[검증용] inbox 디렉토리 오버라이드")
    ap.add_argument("--archive", action="store_true",
                    help="추출 후 inbox 일파일을 processed/ 로 이동")
    a = ap.parse_args()
    inbox = os.path.expanduser(a.inbox)

    seen, files = parse_pointers(inbox)
    alive = [(p, os.path.getmtime(p), os.path.getsize(p)) for p in seen
             if os.path.exists(p)]
    big = [x for x in alive if x[2] >= a.min_kb * 1024]

    # 경량 head 스캔 1회 → 노이즈 프리필터 + first_user 캐시
    scanned = [(p, mt, size, first_user_quick(p, a.head)) for p, mt, size in big]
    clean = [x for x in scanned if not NOISE_SIG.search(x[3] or "")]
    noise = [x for x in scanned if     NOISE_SIG.search(x[3] or "")]

    clean.sort(key=lambda x: -x[1])                 # 최신순 (노이즈 뺀 뒤 상한 적용)
    pick = clean[:a.limit]
    overflow = clean[a.limit:]                       # 상한 초과 유실분
    dropped = len(overflow)

    # 감사로그: 노이즈+상한초과 드롭 append (유실 사후검증용, .log라 parse/archive서 무시됨)
    if a.archive and (noise or overflow):
        with open(os.path.join(inbox, "dropped.log"), "a", encoding="utf-8") as lg:
            stamp = datetime.datetime.fromtimestamp(alive[0][1]).strftime("%Y-%m-%d") if alive else "?"
            for tag, grp in (("NOISE", noise), ("OVERFLOW", overflow)):
                for p, mt, size, fu in grp:
                    lg.write(f"{stamp}\t{tag}\t{os.path.basename(p)[:8]}\t{(fu or '')[:120]}\n")

    lines = [f"# 세션 다이제스트 ({len(pick)}건 추출 / 포인터 {len(seen)} / "
             f"실존 {len(alive)} / {a.min_kb}KB 미만 제외 {len(alive)-len(big)} / "
             f"노이즈 프리드롭 {len(noise)} / 상한 초과 드롭 {dropped})", ""]
    for p, mt, size, fu in pick:
        d = digest_one(p, a.head, a.tail)
        if not d:
            continue
        ts = datetime.datetime.fromtimestamp(mt).strftime("%m-%d %H:%M")
        lines += [f"## {os.path.basename(p)[:8]} ({ts}, {size//1024}KB)",
                  f"[요청] {d[0]}", "[말미]", d[1], ""]
    # 검증 편의: 노이즈로 드롭된 세션 목록도 꼬리에 첨부(정상 미포함, dry-run 육안대조용)
    if noise:
        lines += ["---", "## [검증] 노이즈 프리드롭 목록"]
        for p, mt, size, fu in noise:
            lines.append(f"- {os.path.basename(p)[:8]}: {(fu or '')[:90]}")
        lines.append("")
    out = "\n".join(lines)
    if a.out == "-":
        print(out)
    else:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"digest -> {a.out} ({len(out)//1024}KB)")

    if a.archive:
        proc = os.path.join(inbox, "processed")
        os.makedirs(proc, exist_ok=True)
        for f in files:
            shutil.move(f, os.path.join(proc, os.path.basename(f)))
        print(f"archived {len(files)} inbox files -> processed/")

if __name__ == "__main__":
    main()

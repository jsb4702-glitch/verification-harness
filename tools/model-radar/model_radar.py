#!/usr/bin/env python3
"""model-radar — 새 Claude 모델 출시/가격 변동 감지 → 하네스 대응 리포트 + ntfy 알림.

주 1회 (토 08:00) launchd 실행. LLM 없음 — 네트워크 fetch + diff 뿐이라 비용 0.
알림 전용: CLAUDE.md 는 절대 수정하지 않는다. 판단·수정 = 사람.

소스 3곳:
  1. platform.claude.com 모델 개요 (.md)  — 모델 ID 셋 (1차, docs.claude.com HTML 폴백)
  2. docs.claude.com 가격 문서 (HTML)     — 가격 토큰 멀티셋 해시
  3. claude-code CHANGELOG.md (raw)      — CLI 신버전 구간의 모델 언급

상태: ~/.local/share/model-radar/state.json  (성공 시에만 갱신 — heartbeat 가
      mtime 스테일로 실패·미실행을 잡는다. max_age_days=9)
리포트: ~/.local/share/model-radar/reports/
알림: ~/.claude/scripts/ntfy.sh (실패 시 exit 1 — 실패를 삼키지 않는다)

플래그:
  --seed        현재 상태를 기준선으로 저장 (알림 없음)
  --dry-run     fetch+diff 만 하고 출력, 상태/알림/리포트 없음
  --test-alert  가짜 신규 ID 주입으로 알림 경로 E2E (기준선 안 건드림, [TEST] 표기)
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
DATADIR = HOME / ".local/share/model-radar"
REPORTS = DATADIR / "reports"
STATE = DATADIR / "state.json"
LOG = DATADIR / "model-radar.log"
NTFY = HOME / ".claude/scripts/ntfy.sh"
CLAUDEMD = HOME / ".claude/CLAUDE.md"

MODELS_URLS = [
    "https://platform.claude.com/docs/en/about-claude/models/overview.md",
    "https://docs.claude.com/en/docs/about-claude/models/overview",
]
PRICING_URLS = [
    "https://docs.claude.com/en/docs/about-claude/pricing",
]
CHANGELOG_URL = "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"

# 모델 페이지에서 이보다 적게 뽑히면 페이지 포맷이 깨진 것 — diff 하지 말고 실패 처리
MIN_MODELS_SANE = 5
# 가격 페이지 $토큰 하한 — 실측: 실페이지 45종 vs 404 문서셸 9종. 미달=페이지 깨짐, diff 스킵
MIN_PRICE_TOKENS = 20

RAW_RE = re.compile(r"claude-[a-z0-9][a-z0-9.\-]*")
# 문서 슬러그·변형 표기 노이즈 — 모델 ID 가 아닌 것들
BLACKLIST_PREFIX = (
    "claude-code", "claude-in-", "claude-on-", "claude-platform",
    "claude-api", "claude-prompting", "claude-managed", "claude-models",
    "claude-ai",
)
BLACKLIST_SUFFIX = ("-pricing", "-legacy", "-best-practices", "-skill", "-overview", "-v1")
BLACKLIST_SUBSTR = ("-and-", "-to-claude")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (now_iso(), msg))


def fetch(url, timeout=30):
    """curl 로 가져온다 (환경 검증이 curl 기준으로 됐다). 실패 시 None."""
    try:
        r = subprocess.run(
            ["/usr/bin/curl", "-sSLf", "--max-time", str(timeout),
             "--retry", "2", "--retry-delay", "3", url],
            capture_output=True, timeout=timeout * 3 + 30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.decode("utf-8", errors="replace")
        log("fetch fail rc=%s %s" % (r.returncode, url))
    except Exception as e:
        log("fetch exc %s %s" % (e, url))
    return None


def fetch_first(urls):
    for u in urls:
        body = fetch(u)
        if body:
            return body, u
    return None, None


def extract_models(text):
    """모델 ID 후보 추출 + 노이즈 제거.

    잡음원 3종을 실측했다:
      - 문서 슬러그 (claude-code-analytics-api, claude-sonnet-5-introductory-pricing)
      - 마크다운 각주 숫자가 들러붙은 것 (claude-opus-53 = claude-opus-5 + 각주3)
      - 뉴스 URL 슬러그 (…/news/claude-fable-5-mythos-5) — URL 자체를 제거해 뿌리를 뽑는다.
        모델 ID 는 표·백틱·산문에서 나오므로 URL 제거로 잃는 진양성은 없다(적대검토 실측).
    """
    text = re.sub(r"https?://\S+", " ", text or "")
    raw = set(RAW_RE.findall(text))
    kept = set()
    for t in raw:
        t = t.rstrip(".-")
        if not t or t == "claude":
            continue
        if any(t.startswith(p) for p in BLACKLIST_PREFIX):
            continue
        if any(t.endswith(s) for s in BLACKLIST_SUFFIX):
            continue
        if any(s in t for s in BLACKLIST_SUBSTR):
            continue
        # 모델 ID 는 버전 숫자 또는 -preview 를 가진다. 없는 건 슬러그.
        if not (any(c.isdigit() for c in t) or t.endswith("-preview")):
            continue
        kept.add(t)
    return canonicalize(kept)


def canonicalize(tokens):
    """각주 글루 제거: 짧은 토큰 뒤에 대시 없이 숫자가 붙은 긴 토큰은 버린다.
    (claude-opus-53 은 claude-opus-5 의 글루. claude-opus-4-5 는 claude-opus-4
    뒤가 '-' 라서 별개 모델로 보존.)"""
    keep = set()
    for t in sorted(tokens, key=len):
        glued = False
        for k in keep:
            if t.startswith(k) and len(t) > len(k) and t[len(k)] != "-":
                glued = True
                break
        if not glued:
            keep.add(t)
    return keep


def extract_pricing(text):
    """가격 페이지의 (모델토큰 + $금액) 멀티셋. 페이지 개편에도 견디게 값 위치는 안 본다.

    <script> 블롭은 스캔 전에 제거한다 — RSC 직렬화 참조($8:props… 류)와 법률 문구($1,000
    배상한도)가 섞여 있고, 참조 번호는 사이트 재배포만 돼도 바뀌어 가짜 가격변동을 낸다(적대검토
    실측: 제거 시 실단가 포함 가시 매치 149개 전량 보존)."""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text or "", flags=re.S)
    tokens = {}
    for t in sorted(extract_models(text)):
        tokens["m:" + t] = tokens.get("m:" + t, 0) + 1
    for d in re.findall(r"\$[0-9][0-9,.]*", text or ""):
        d = d.rstrip(".")
        tokens["d:" + d] = tokens.get("d:" + d, 0) + 1
    import hashlib
    canon = ";".join("%s=%d" % (k, v) for k, v in sorted(tokens.items()))
    return tokens, hashlib.sha256(canon.encode()).hexdigest()


def parse_changelog(text, prev_version):
    """최신 버전과, 저장된 버전 이후 신규 구간의 모델 관련 라인/토큰."""
    if not text:
        return None, set(), []
    m = re.search(r"^## (\d+\.\d+\.\d+)", text, re.M)
    if not m:
        return None, set(), []
    latest = m.group(1)
    if not prev_version or latest == prev_version:
        return latest, set(), []
    lines = text.splitlines()
    seg = []
    for ln in lines[:400]:
        if prev_version and ln.strip() == "## " + prev_version:
            break
        seg.append(ln)
    seg_text = "\n".join(seg)
    tokens = extract_models(seg_text)
    relevant = [ln.strip() for ln in seg
                if re.search(r"claude-[a-z0-9]", ln, re.I)
                or re.search(r"\bmodels?\b", ln, re.I)][:15]
    return latest, tokens, relevant


def grep_claudemd():
    """CLAUDE.md 에서 모델명이 박힌 라인 — 리포트에 갱신 지점으로 첨부."""
    hits = []
    try:
        text = CLAUDEMD.read_text(encoding="utf-8")
    except Exception as e:
        return ["(CLAUDE.md 읽기 실패: %s)" % e]
    pat = re.compile(r"(Fable|Opus|Sonnet|Haiku|claude-)")
    for i, ln in enumerate(text.splitlines(), 1):
        if pat.search(ln):
            hits.append("L%d: %s" % (i, ln.strip()[:120]))
    return hits[:40]


CHECKLIST = """\
## 대응 체크리스트 (수정은 전부 사람이 한다)

1. **라우팅 표 갱신** — CLAUDE.md L1 난이도 분기의 모델명·출력단가비.
   현재 단가 라인은 아래 'CLAUDE.md 관련 라인' 절 참조. 신규 단가는 공식 가격 문서로 확정.
2. **컷오버 판단** — 메인 모델 전환 날짜 라인([~26-07-06 / 26-07-07~] 형식) 재검토.
   깊이보정(확장추론 강제+2패스 자기적대) 대상 모델도 함께.
3. **CLI 위임 대상 확인** — Agent 툴 model 파라미터에 새 모델이 잡히는지,
   구독 요금제에 포함되는지 확인 (Claude Code 변경로그·/model 픽커).
4. **검증 절차** — 순서대로: /harness-stress 6종 → "밤샘 돌려"(모델 매트릭스)
   → 구독 CLI 3way 재실측. 게이트 실패가 모델 한계인지 하네스 구멍인지 가른다.
5. **말투·깊이 민감도** — L1 밀도 민감 이력 있음. 새 모델 라우팅 반영 전 스모크 A/B 의무.
6. **메모리 갱신** — harness-fable5-tuning, cli3way-subscription-eval,
   overnight-model-matrix 결과 반영. 컷오버 확정 시 harness 패치史에 기록.
"""


def build_report(new_ids, removed_ids, pricing_diff, cl_lines, srcs, test=False):
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    name = "model-radar-%s%s.md" % (ts, "-TEST" if test else "")
    path = REPORTS / name
    REPORTS.mkdir(parents=True, exist_ok=True)
    parts = []
    parts.append("# 모델 레이더 리포트 %s%s\n" % (ts, " [TEST]" if test else ""))
    parts.append("## 변동 요약\n")
    parts.append("- 신규 모델 ID: %s" % (", ".join(sorted(new_ids)) or "없음"))
    parts.append("- 사라진 ID: %s" % (", ".join(sorted(removed_ids)) or "없음"))
    parts.append("- 가격 문서 변동: %s\n" % ("있음 (아래 diff)" if pricing_diff else "없음"))
    if pricing_diff:
        parts.append("## 가격 토큰 diff (문서 개편일 수도 있다 — 원문 확인 필수)\n")
        for line in pricing_diff[:20]:
            parts.append("- " + line)
        parts.append("")
    if cl_lines:
        parts.append("## Claude Code 변경로그 신규 구간의 모델 관련 라인\n")
        for ln in cl_lines:
            parts.append("- " + ln[:160])
        parts.append("")
    parts.append(CHECKLIST)
    parts.append("## CLAUDE.md 관련 라인 (갱신 지점 후보, 실행 시점 grep)\n")
    for h in grep_claudemd():
        parts.append("- " + h)
    parts.append("\n## 출처 (값 재확인은 여기서)\n")
    for u in srcs:
        parts.append("- " + u)
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def pricing_diff_lines(old_tokens, new_tokens):
    out = []
    for k in sorted(set(old_tokens) | set(new_tokens)):
        o, n = old_tokens.get(k, 0), new_tokens.get(k, 0)
        if o != n:
            out.append("%s: %d -> %d" % (k, o, n))
    return out


def send_ntfy(title, msg):
    try:
        r = subprocess.run(["/bin/bash", str(NTFY), title, msg, "high", "satellite"],
                           capture_output=True, timeout=90)
        return r.returncode == 0
    except Exception as e:
        log("ntfy exc %s" % e)
        return False


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_state(st):
    DATADIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True),
                   encoding="utf-8")
    tmp.replace(STATE)


def main():
    args = set(sys.argv[1:])
    dry = "--dry-run" in args
    seed = "--seed" in args
    test = "--test-alert" in args

    state = load_state()
    if state is None and not (seed or dry):
        print("기준선 없음 — 먼저 --seed 로 심어라.", file=sys.stderr)
        log("run aborted: no baseline (need --seed)")
        return 1

    srcs = []
    models_body, models_url = fetch_first(MODELS_URLS)
    models = extract_models(models_body) if models_body else set()
    if models_url:
        srcs.append(models_url)
    if len(models) < MIN_MODELS_SANE:
        log("models source unusable (%d tokens) — abort, baseline kept" % len(models))
        print("모델 소스 사용불가 (%d개 추출) — 이번 회차 중단" % len(models), file=sys.stderr)
        return 1

    pricing_body, pricing_url = fetch_first(PRICING_URLS)
    pricing_tokens, pricing_hash = (None, None)
    if pricing_body:
        pt, ph = extract_pricing(pricing_body)
        n_price = sum(1 for k in pt if k.startswith("d:"))
        if n_price >= MIN_PRICE_TOKENS:
            pricing_tokens, pricing_hash = pt, ph
            srcs.append(pricing_url)
        else:
            log("pricing source unusable (%d $tokens) — skip pricing diff" % n_price)
    else:
        log("pricing source down — skip pricing diff this run")

    cl_body = fetch(CHANGELOG_URL)
    prev_ver = (state or {}).get("changelog_version")
    cl_ver, cl_tokens, cl_lines = parse_changelog(cl_body, prev_ver)
    if cl_body:
        srcs.append(CHANGELOG_URL)

    if seed or dry:
        print("모델 ID %d개 (페이지):" % len(models))
        for t in sorted(models):
            print("  " + t)
        if cl_tokens:
            print("변경로그 신규구간 토큰: %s" % ", ".join(sorted(cl_tokens)))
        print("가격 해시: %s" % (pricing_hash or "(fetch 실패/사용불가)"))
        print("변경로그 버전: %s" % (cl_ver or "(fetch 실패)"))
        if dry:
            return 0
        save_state({
            "models": sorted(models),
            "cl_seen": sorted(cl_tokens),
            "pricing_hash": pricing_hash,
            "pricing_tokens": pricing_tokens or {},
            "changelog_version": cl_ver,
            "seeded_at": now_iso(),
            "last_run": now_iso(),
            "last_ok": now_iso(),
        })
        log("seeded: %d models" % len(models))
        print("기준선 저장 완료.")
        return 0

    baseline = set(state.get("models", []))
    cl_seen = set(state.get("cl_seen", []))
    # 신규 = 페이지+변경로그 유니언에서 처음 보는 것.
    # 제거 = 페이지 셋끼리만 diff — 변경로그 토큰은 버전 갱신 주에만 나오는 일회성이라
    # 기준선에 섞으면 다음 주 가짜 '사라진 ID' 알림이 구조적으로 나온다 (적대검토 확정 결함).
    new_ids = (models | cl_tokens) - baseline - cl_seen
    removed_ids = baseline - models
    p_diff = []
    pricing_changed = False
    if pricing_hash and state.get("pricing_hash") and pricing_hash != state["pricing_hash"]:
        pricing_changed = True
        p_diff = pricing_diff_lines(state.get("pricing_tokens", {}), pricing_tokens)

    if test:
        new_ids = set(new_ids) | {"claude-test-radar-0"}

    if not (new_ids or removed_ids or pricing_changed):
        state["last_run"] = now_iso()
        state["last_ok"] = now_iso()
        if cl_ver:
            state["changelog_version"] = cl_ver
        if cl_tokens:
            state["cl_seen"] = sorted(cl_seen | cl_tokens)
        if pricing_hash:
            state["pricing_hash"] = pricing_hash
            state["pricing_tokens"] = pricing_tokens
        save_state(state)
        log("no change (%d models, changelog %s)" % (len(models), cl_ver))
        return 0

    report = build_report(new_ids, removed_ids, p_diff, cl_lines, srcs, test=test)
    title = ("[TEST] " if test else "") + "모델 레이더 — 변동 감지"
    msg = "신규: %s / 제거: %s / 가격변동: %s / 리포트: %s" % (
        ", ".join(sorted(new_ids)) or "-",
        ", ".join(sorted(removed_ids)) or "-",
        "유" if pricing_changed else "무",
        report,
    )
    ok = send_ntfy(title, msg[:900])
    log("ALERT%s new=%s removed=%s pricing=%s ntfy=%s report=%s" % (
        " TEST" if test else "", sorted(new_ids), sorted(removed_ids),
        pricing_changed, ok, report.name))
    print("리포트: %s" % report)

    if test:
        # 합성 알림 — 기준선은 건드리지 않는다
        return 0 if ok else 1

    if ok:
        state.update({
            "models": sorted(models),
            "cl_seen": sorted(cl_seen | cl_tokens),
            "pricing_hash": pricing_hash or state.get("pricing_hash"),
            "pricing_tokens": pricing_tokens or state.get("pricing_tokens", {}),
            "changelog_version": cl_ver or state.get("changelog_version"),
            "last_run": now_iso(),
            "last_ok": now_iso(),
            "last_alert": now_iso(),
        })
        save_state(state)
        return 0
    # 알림 실패 — 기준선 유지해서 다음 주 재시도. 리포트는 이미 남았다.
    print("ntfy 실패 — 기준선 유지, 다음 회차 재알림", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

export const meta = {
  name: 'citation-verify',
  description: '답변에 박힌 인용(DOI·arXiv·풀PN·규격번호) N개를 외부 권위소스로 병렬 실조회해 실재 확정. DOI/arXiv는 결정론 API 강제, PN/STD는 agent+web. G4 "회피"→"조회확정" 격상. 문제 인용만 반환.',
  phases: [
    { title: 'Verify', detail: '인용 N개 동시 외부조회 (pipeline)' },
  ],
}

// args: { citations: [{type:"DOI"|"PN"|"STD"|"arXiv"|"CVE", value:"...", claimed?:"답변이 주장한 내용(저자·연도·제목·게재처 등, 선택)"}], cap: 12 }
// cap은 agent-web 타입(PN/STD 등)에만 적용 — 결정론 타입(DOI/arXiv/CVE)은 캡 면제(스크립트 1회, 저비용).
const _args = typeof args === 'string' ? JSON.parse(args) : (args ?? {})
const citations = Array.isArray(_args.citations) ? _args.citations : []
const cap = _args.cap ?? 12  // silent 캡 금지 — 초과분은 log로 명시

if (citations.length === 0) {
  return { verdict: "EMPTY", note: "검증할 인용 없음", problems: [] }
}

// DOI/arXiv/CVE = 결정론 API 강제(추정 불가능). PN/STD = agent+web. CVE=NVD services.nvd.nist.gov
const DETERMINISTIC = new Set(["DOI", "ARXIV", "CVE"])
const norm = (t) => String(t || "").toUpperCase().replace("ARX", "ARXIV").replace("ARXIVIV", "ARXIV")
// type 라벨이 비표준("citation" 등)이어도 값 모양으로 결정론 타입 복원 —
// 2026-07-25 wf_69bfc458 실측: arXiv ID 1건이 type:"citation"으로 들어와 sonnet 웹경로로 유출.
const inferType = (c) => {
  const t = norm(c.type), v = String(c.value || "").trim()
  if (DETERMINISTIC.has(t)) return t
  if (/^(arxiv:)?\d{4}\.\d{4,5}(v\d+)?$/i.test(v) || /^[a-z][a-z.-]+\/\d{7}(v\d+)?$/i.test(v)) return "ARXIV"
  if (/^(https?:\/\/(dx\.)?doi\.org\/)?10\.\d{4,9}\/\S+$/i.test(v)) return "DOI"
  if (/^CVE-\d{4}-\d{4,}$/i.test(v)) return "CVE"
  return t
}

// 캡 재설계(2026-07-25 wf_69bfc458 수리): 전체 캡이 결정론 인용까지 잘라 arXiv 4건 미검증
// + 잘린 항목 method:"agent-web" 오표기. → 캡은 agent-web 타입 전용, 결정론 타입은 전량 검증.
const detCites = citations.filter(c => DETERMINISTIC.has(inferType(c)))
const webCites = citations.filter(c => !DETERMINISTIC.has(inferType(c)))
const droppedWeb = webCites.slice(cap)
const targets = [...detCites, ...webCites.slice(0, cap)]
if (droppedWeb.length > 0) {
  log(`⚠️ agent-web 인용 ${webCites.length}개 중 ${cap}개만 검증 — 초과 ${droppedWeb.length}개 미검증(미확인 처리). 결정론 ${detCites.length}개는 캡 면제 전량 검증.`)
}

phase('Verify')

// per-item 타임아웃 (JARVIS HuggingGPT 한계 #2 반면교사: 통짜 타임아웃 금지)
const withTimeout = (p, ms, label) => Promise.race([
  p,
  new Promise((_, rej) => setTimeout(() => rej(new Error(`timeout:${label}:${ms}ms`)), ms)),
])

// 인용 종류별 권위소스 안내 — 추정 금지, 조회된 것만 confirmed
const SOURCE_HINT = {
  PN:    "제조사 공식 datasheet / DigiKey / Mouser / 공식 distributor. 풀PN이 실재 카탈로그 항목인지. 추정 금지.",
  STD:   "발행기관(ASME·ISO·SAE·MIL DLA ASSIST quicksearch.dla.mil) 또는 공식 카탈로그. 규격번호+Rev 실재 여부, Rev 단정 금지.",
}

const VERDICT_SCHEMA = {
  type: "object",
  properties: {
    type:   { type: "string" },
    value:  { type: "string" },
    status: { type: "string", enum: ["confirmed", "refuted", "unverified"] },
    // confirmed=실조회로 실재 확인 / refuted=실조회 결과 존재안함·불일치 / unverified=조회불가·접근불가
    found:  { type: "string" },   // 조회로 확인된 실제 메타데이터(저자·연도·제목·제조사 등) 또는 "없음"
    mismatch: { type: "string" }, // claimed 와 found 의 불일치 내용, 없으면 ""
    source: { type: "string" },   // 실제 조회한 권위소스 URL/도메인
    method: { type: "string", enum: ["deterministic-api", "agent-web"] }, // 조회 경로(강제 여부 추적)
  },
  required: ["type", "value", "status", "found", "mismatch", "source", "method"],
}

const promptDeterministic = (c, i, itype) =>
  `다음 인용을 결정론 API로 실제 조회하라. 추정 절대 금지 — 반드시 아래 스크립트를 Bash로 실행하고, 그 JSON 출력만 근거로 삼아라.

실행: python3 ~/.claude/scripts/cite_lookup.py ${itype} "${String(c.value).replace(/"/g, '')}"

그리고 아래를 한 번 더 실행하라(섀도 계측 — 2026-07-26 배선).
실행: python3 ~/.claude/scripts/cite_verdict.py ${itype} "${String(c.value).replace(/"/g, '')}"${c.claimed ? ` --title "${String(c.claimed).replace(/"/g, '').slice(0, 200)}"` : ""}
  · 이 두 번째 출력은 **판정에 쓰지 마라**. status/found/mismatch 는 위 cite_lookup 결과만으로 채운다.
  · 실행 자체가 목적이다(실사용 표본 적재). 실패하면 무시하고 넘어가라 — 재시도·보고 불필요.

[인용 #${i + 1}] 종류:${c.type} / 값:${c.value}
${c.claimed ? `답변이 주장한 내용: ${c.claimed}` : "(주장 메타데이터 없음 — 실재 여부만 확인)"}

규칙:
- status/found/source는 스크립트 JSON의 값을 그대로 사용(method="deterministic-api").
- 스크립트가 unverified면 status도 unverified(절대 confirmed로 올리지 말 것). 스크립트 실행 실패도 unverified, found에 실패 이유.
- claimed가 있으면 스크립트 raw_* 필드와 대조해 mismatch를 채워라. 거짓반증 금지(2026-07-25 수리) — 축별 규칙:
  · 제목: 실측과 명백히 다른 논문이면 refuted. 부제 생략·축약 표기는 불일치 아님.
  · 저자: claimed의 저자 각각을 raw_authors(전체 목록)에서 성(surname) 기준·대소문자 무시로 찾아라. 전체 목록에 없는 claimed 저자가 있을 때만 refuted. raw_authors가 없거나 비면 저자 근거 refuted 금지 — mismatch에 "저자 검증불가"만 기록.
  · 연도(단독 숫자 주장): raw_year(제출연도) 또는 raw_year_updated(최근판) 중 하나와 일치하면 일치. 둘 다 다르면 refuted가 아니라 status="unverified" + mismatch="연도 불일치(판본/게재연도 확인필요)" — 연도 단독 차이로 refuted 금지.
  · 학회/게재처("ICLR 2025", "ACL 2024 Findings" 등 학회명+연도): 제출연도와 비교 금지 — 별개 축이다. raw_comment(arXiv)·raw_journal(DOI)에서 해당 학회가 확인되면 일치. 확인 안 되면 refuted가 아니라 status="unverified" + mismatch="게재처 미확인: ..." (arXiv 메타데이터엔 게재처가 원래 없을 수 있음 — 부재는 반증이 아니다).
  · refuted 허용 조건(실측 모순만): ID 자체가 없음(스크립트 refuted) / 제목이 다른 논문 / claimed 저자가 전체 저자 목록에 부재.
  · 충돌 시 우선순위: refuted 조건 충족 > unverified 강등 > confirmed. 전 축 일치하면 mismatch="".`

const promptAgentWeb = (c, i) =>
  `다음 인용을 외부 권위소스로 실제 조회해서 실재 여부를 판정하라. 기억·추정 금지 — 실제 조회(WebFetch/web_search)한 것만 confirmed. method="agent-web".

[인용 #${i + 1}] 종류:${c.type} / 값:${c.value}
${c.claimed ? `답변이 주장한 내용: ${c.claimed}` : "(주장 메타데이터 없음 — 실재 여부만 확인)"}

[권위소스 안내]
${SOURCE_HINT[norm(c.type)] ?? "공식 발행처/제조사/색인 DB로 조회."}

규칙:
- 실조회로 실재+일치 확인 → status:"confirmed"
- 실조회 결과 존재 안 함 또는 메타데이터 불일치 → status:"refuted" (mismatch에 무엇이 다른지)
- 접근불가·조회실패·소스부재 → status:"unverified" (절대 confirmed로 올리지 말 것)
- found에는 실제로 확인된 메타데이터를, source에는 실제 조회한 URL/도메인을 적어라.`

// pipeline: 각 인용 독립·동시 조회 (배리어 불필요, wall-clock = 가장 느린 1건)
const results = await pipeline(
  targets,
  (c, _orig, i) => {
    const itype = inferType(c)
    const det = DETERMINISTIC.has(itype)
    // 모델 라우팅(v5.6.5): 결정론=스크립트 실행+JSON 전사라 haiku/low로 충분,
    // agent-web=소스 권위성 판단 필요라 sonnet/medium. 메인모델(Fable) 단가 낭비 차단.
    return withTimeout(
      agent(det ? promptDeterministic(c, i, itype) : promptAgentWeb(c, i), {
        label: `verify:${c.type}:${String(c.value).slice(0, 24)}`,
        phase: "Verify", schema: VERDICT_SCHEMA,
        model: det ? "haiku" : "sonnet", effort: det ? "low" : "medium",
        agentType: "general-purpose",  // Bash(결정론)·web(agent경로) 둘 다 필요
      }),
      90_000, `${c.type}:${c.value}`
    ).catch(() => null)
  }
)

const checked = results.filter(Boolean)
// 초과로 잘린 agent-web 인용은 unverified로 명시 합류 (silent 캡 금지).
// method는 실제 라우팅과 일치 — 결정론 타입은 캡 면제라 여기 안 옴(과거 하드코딩 오표기 수리).
const dropped = droppedWeb.map(c => ({
  type: c.type, value: c.value, status: "unverified",
  found: "없음", mismatch: "", source: "캡 초과 미검증(agent-web 타입)", method: "agent-web",
}))
// 타임아웃/실패로 null된 항목도 미확인으로 명시(silent 소실 금지)
const failed = targets.length - checked.length
const all = [...checked, ...dropped]

const problems  = all.filter(r => r.status !== "confirmed")  // 문제만
const refuted   = all.filter(r => r.status === "refuted")
const confirmed = all.filter(r => r.status === "confirmed")
const detCount  = checked.filter(r => r.method === "deterministic-api").length

const verdict = refuted.length > 0 ? "FAIL"          // 날조·불일치 1건이라도 → 차단
              : problems.length > 0 ? "WARN"          // 미확인 존재 → 인용회피 권고
              : "PASS"

return {
  verdict,
  summary: `총 ${citations.length} / 검증 ${checked.length}(결정론 ${detCount}) / ✅확정 ${confirmed.length} / ❌반증 ${refuted.length} / ⚠️미확인 ${problems.length - refuted.length}${failed > 0 ? ` / 🔻조회실패 ${failed}` : ""}`,
  problems,        // 메인세션은 이것만 보면 됨 (G4 차단/회피 대상)
  confirmed,       // 인용 가능 확정분
}

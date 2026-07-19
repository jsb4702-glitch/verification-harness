export const meta = {
  name: 'parallel-verify',
  description: 'gemini(gemini-2.5-flash) + groq(llama-3.3-70b) 실제 이종모델 병렬 교차검증 후 합산 판정. gemini 실패 시 로컬 Hermes 폴백(가용성 상쇄). allow_agy:true 시 agy CLI(Gemini 3.1 Pro), allow_cdx:true 시 Codex CLI(OpenAI GPT) 추가 이종슬롯 — agy=Google·cdx=OpenAI 탈상관(agy는 gemini-flash 슬롯과 동계보)·키링/OAuth·민감데이터 금지. 이종성 미달 시 cross_verified:false 강제노출. 안전임계 답변·설계판단·인과주장 반박에 사용.',
  phases: [
    { title: 'Verify', detail: 'gemini·groq 실모델 병렬 검증(gemini 실패 시 Hermes 폴백)' },
    { title: 'Adjudicate', detail: '불일치 교차판정' },
  ],
}

// args: { content: "검증할 텍스트", context: "배경정보(선택)", limit: 5 }
// Workflow가 args를 JSON 문자열로 전달하는 경우 파싱
const _args = typeof args === 'string' ? JSON.parse(args) : (args ?? {})
const content = _args.content ?? "검증 대상 없음"
const context = _args.context ?? ""
const limit = _args.limit ?? 5  // 슬라이딩: 최근 N개 findings만 다음 스테이지로 전달
// ⚠️ OpenRouter 무료모델 = 프로바이더 학습활용 → 민감데이터 금지.
// gemini 실패(429/타임아웃) 시에만, 명시 옵트인일 때만 폴백. 기본 OFF(민감데이터 보호).
const allowOR = _args.allow_openrouter === true
// NVIDIA NIM(build.nvidia.com) 3번째 이종슬롯. 무료티어=프로바이더 데이터활용 가능 →
// 민감데이터 금지, 기본 OFF. 일반검증서 켜면 gemini+groq+nvidia 3way 투표.
const allowNvidia = _args.allow_nvidia === true
// agy CLI(Gemini 3.1 Pro High) 이종슬롯 — Google 계열(cdx=OpenAI·groq=Meta와 탈상관; gemini-flash 슬롯과는 동계보).
// 키링 OAuth 선행(대화형 agy 1회 로그인) 필요. 구글 백엔드·구독티어 학습정책 미확인 →
// 민감데이터 금지, 기본 OFF(옵트인). 일반검증서 켜면 gemini+groq+agy 3way 투표.
const allowAgy = _args.allow_agy === true
// cdx = Codex CLI(OpenAI GPT) 이종슬롯 — gemini/agy(Google)·groq(Meta)와 탈상관.
// agy=Gemini·cdx=OpenAI라 서로 탈상관(과거 agy=GPT-OSS 시절의 agy+cdx 상관 우려는 해소됨).
// ~/.codex OAuth 선행. 구독티어 학습정책 미확인 → 민감데이터 금지, 기본 OFF(옵트인).
const allowCdx = _args.allow_cdx === true

// ── per-slot 타임아웃 래퍼 (JARVIS HuggingGPT 한계 #2 반면교사: 통짜 타임아웃 금지) ──
// 한 슬롯이 행(hang)걸려도 전체 barrier를 잡지 않게 개별 wall-clock 상한을 건다.
// 스크립트 자체 API 타임아웃(gemini 180s/round, groq 60s)보다 약간 여유.
const withTimeout = (p, ms, label) => Promise.race([
  p,
  new Promise((_, rej) => setTimeout(() => rej(new Error(`timeout:${label}:${ms}ms`)), ms)),
])

phase('Verify')

const VERIFY_SCHEMA = {
  type: "object",
  properties: {
    verdict: { type: "string", enum: ["PASS", "WARN", "FAIL"] },
    confidence: { type: "string", enum: ["HIGH", "MED", "LOW"] },
    findings: {
      type: "array",
      items: {
        type: "object",
        properties: {
          claim: { type: "string" },
          status: { type: "string", enum: ["confirmed", "refuted", "unverified"] },
          detail: { type: "string" },
          severity: { type: "string", enum: ["INFO", "WARN", "ERROR"] }
        },
        required: ["claim", "status", "detail", "severity"]
      }
    },
    summary: { type: "string" },
    script_ok: { type: "boolean" }  // 스크립트 실호출 성공 여부(이종성 실제 달성 확인용)
  },
  required: ["verdict", "confidence", "findings", "summary", "script_ok"]
}

// 슬롯 = 실제 이종모델 스크립트를 Bash로 돌리고 stdout을 구조화하는 서브에이전트.
// (워크플로 JS는 셸/FS 접근 불가 → 서브에이전트가 Write+Bash로 실행)
const SLOT_PROMPT = (modelName, scriptPath, tmpFile) => `너는 교차검증 실행자다. 아래 [검토대상]을 실제 ${modelName} 모델로 검증하고 결과를 스키마로 구조화하라. role-play 금지 — 반드시 스크립트를 실행해 실제 모델 응답을 받아라.

실행 절차:
1. [검토대상] 텍스트를 Write 툴로 ${tmpFile}에 그대로 저장(가공·요약 금지, 원문 verbatim).
2. Bash로 실행: python3 ${scriptPath} ${tmpFile}
3. stdout(=${modelName}의 비평)을 읽고 구조화:
   - 반증/오류 지적 → status:refuted, severity:ERROR(중대)/WARN
   - 확인됨 → confirmed / 알 수 없음 → unverified
   - verdict: 반증 있으면 FAIL, 미검증만 있으면 WARN, 전건 확인이면 PASS
   - findings에는 불일치·요주의만 포함(일치 항목 생략)
   - script_ok: 스크립트가 정상 모델응답을 반환했으면 true
4. 스크립트가 키없음/HTTP에러/빈출력으로 실패하면: script_ok=false, verdict=WARN,
   summary에 "스크립트 실패: <한줄 이유>" 명시(추측으로 채우지 말 것).

[검토대상]
${content}
${context ? `\n[배경]\n${context}` : ""}`

const SCRIPTS = {
  gemini:     "~/.claude/skills/gemini-review/scripts/review.py",
  groq:       "~/.claude/skills/groq-review/scripts/groq_review.py",
  openrouter: "~/.claude/skills/groq-review/scripts/openrouter_review.py",
  nvidia:     "~/.claude/skills/groq-review/scripts/nvidia_review.py",
  agy:        "~/.claude/skills/groq-review/scripts/agy_review.py",  // Antigravity CLI Gemini 3.1 Pro(키링 OAuth)
  cdx:        "~/.claude/skills/groq-review/scripts/cdx_review.py",  // Codex CLI OpenAI GPT(~/.codex OAuth)
  hermes:     "~/.claude/skills/groq-review/scripts/hermes_review.py",  // 로컬 gemma4-hermes(폴백·오프라인)
}

// gemini·groq(·nvidia) 병렬 실행 (서로 다른 모델 = 탈상관). 슬롯별 타임아웃 차등.
// nvidia 슬롯은 allow_nvidia 옵트인 시에만 — 무료티어 데이터활용 보호(민감데이터 기본차단).
const slotThunks = [
  () => withTimeout(
    agent(SLOT_PROMPT("Gemini(gemini-2.5-flash)", SCRIPTS.gemini, "/tmp/_pv_gemini.txt"), {
      label: "gemini-verify", phase: "Verify", schema: VERIFY_SCHEMA,
      agentType: "general-purpose", effort: "high"
    }),
    300_000, "gemini"  // gemini 멀티라운드 여유(최대 4round×180s지만 flash는 보통 1-2)
  ).catch(() => null),
  () => withTimeout(
    agent(SLOT_PROMPT("Groq(llama-3.3-70b-versatile)", SCRIPTS.groq, "/tmp/_pv_groq.txt"), {
      label: "groq-verify", phase: "Verify", schema: VERIFY_SCHEMA,
      agentType: "general-purpose", effort: "high"
    }),
    120_000, "groq"  // groq 빠름(API 60s 내장)
  ).catch(() => null),
]
if (allowNvidia) {
  slotThunks.push(
    () => withTimeout(
      agent(SLOT_PROMPT("NVIDIA NIM(nemotron 계열, build.nvidia.com)", SCRIPTS.nvidia, "/tmp/_pv_nvidia.txt"), {
        label: "nvidia-verify", phase: "Verify", schema: VERIFY_SCHEMA,
        agentType: "general-purpose", effort: "high"
      }),
      150_000, "nvidia"  // NIM 호스티드 — nemotron 추론 여유
    ).catch(() => null)
  )
}
if (allowAgy) {
  slotThunks.push(
    () => withTimeout(
      agent(SLOT_PROMPT("agy CLI(Gemini 3.1 Pro, Antigravity)", SCRIPTS.agy, "/tmp/_pv_agy.txt"), {
        label: "agy-verify", phase: "Verify", schema: VERIFY_SCHEMA,
        agentType: "general-purpose", effort: "high"
      }),
      150_000, "agy"  // 실측 22.7s(리뷰프롬프트) + 에이전트 오버헤드 여유
    ).catch(() => null)
  )
}
if (allowCdx) {
  slotThunks.push(
    () => withTimeout(
      agent(SLOT_PROMPT("Codex CLI(OpenAI GPT)", SCRIPTS.cdx, "/tmp/_pv_cdx.txt"), {
        label: "cdx-verify", phase: "Verify", schema: VERIFY_SCHEMA,
        agentType: "general-purpose", effort: "high"
      }),
      180_000, "cdx"  // codex exec 스핀업 + 추론 여유(실측 ~30-60s)
    ).catch(() => null)
  )
}
const slotResults = await parallel(slotThunks)
const [gemResult, groqResult] = slotResults
const nvidiaResult = allowNvidia ? slotResults[2] : null
const agyResult = allowAgy ? slotResults[2 + (allowNvidia ? 1 : 0)] : null
const cdxResult = allowCdx ? slotResults[2 + (allowNvidia ? 1 : 0) + (allowAgy ? 1 : 0)] : null

// ── gemini 슬롯 폴백: gemini 실패(429/503/타임아웃) 시 슬롯1 복구 ──
// 순위: ①로컬 Hermes(무료·오프라인·민감데이터 로컬보존·옵트인 불요) → ②OpenRouter(외부·옵트인 필수).
// 근거: Gemini 무료티어가 실측 3일간 429/503으로 불안정(hermes-eval). 로컬 폴백으로 가용성 상쇄.
// Hermes 강점=날조·산술·인과(recall 1.00/0.92/1.00), 약점=물성 → 물성검증 폴백엔 신뢰제한(리포트 명시).
let slot1 = gemResult
let slot1src = "gemini"
let orNote = null
const gemFailed = !gemResult || gemResult.script_ok === false
if (gemFailed) {
  // ① 로컬 Hermes 우선 (항상 시도 — 옵트인 불요)
  const hz = await withTimeout(
    agent(SLOT_PROMPT("로컬 Hermes(gemma4-hermes)", SCRIPTS.hermes, "/tmp/_pv_hermes.txt"), {
      label: "hermes-verify", phase: "Verify", schema: VERIFY_SCHEMA,
      agentType: "general-purpose", effort: "high"
    }),
    300_000, "hermes"  // 로컬 gemma4 ~87s/call 실측 + 여유
  ).catch(() => null)
  if (hz && hz.script_ok !== false) {
    slot1 = hz; slot1src = "hermes(local)"
    orNote = "gemini 실패 → 로컬 Hermes 폴백 발동. ⚠️물성/외부사실 카테고리는 Hermes 신뢰제한 — 날조·산술·논리 판정 우선."
  } else if (allowOR) {
    // ② Hermes도 실패 + 옵트인 시 OpenRouter
    const or = await withTimeout(
      agent(SLOT_PROMPT("OpenRouter 무료모델(qwen/gpt-oss 폴백)", SCRIPTS.openrouter, "/tmp/_pv_or.txt"), {
        label: "openrouter-verify", phase: "Verify", schema: VERIFY_SCHEMA,
        agentType: "general-purpose", effort: "high"
      }),
      120_000, "openrouter"
    ).catch(() => null)
    if (or && or.script_ok !== false) { slot1 = or; slot1src = "openrouter" }
    else orNote = "gemini·Hermes·OpenRouter 폴백 전부 실패 — 슬롯1 검증 미달(groq 단독)."
  } else {
    orNote = "gemini·로컬Hermes 폴백 실패. OpenRouter는 미옵트인(allow_openrouter≠true, 민감데이터 보호) — 일반검증이면 args에 allow_openrouter:true."
  }
}

phase('Adjudicate')

// 활성 슬롯 집계 (gemini/openrouter + groq + nvidia옵트인). N-way 투표로 일반화.
const SLOTS = [
  { name: slot1src,  r: slot1 },
  { name: "groq",    r: groqResult },
  { name: "nvidia",  r: nvidiaResult },
  { name: "agy",     r: agyResult },
  { name: "cdx",     r: cdxResult },
].filter(s => s.r)  // null(미실행/타임아웃) 제거

// 슬라이딩: 각 결과에서 최근 limit개 findings만 취합 (토큰 O(1) 유지)
SLOTS.forEach(s => { s.findings = (s.r.findings ?? []).slice(-limit) })

const failCount = SLOTS.filter(s => s.r.verdict === "FAIL").length
const warnCount = SLOTS.filter(s => s.r.verdict === "WARN").length

// 이종성 실제 달성: script_ok=true 슬롯 수 / 시도 슬롯 수. 낮을수록 탈상관 약화.
const attempted = 2 + (allowNvidia ? 1 : 0) + (allowAgy ? 1 : 0) + (allowCdx ? 1 : 0)
const hetero = SLOTS.filter(s => s.r.script_ok).length

let finalVerdict, adjSummary

if (SLOTS.length === 0) {
  finalVerdict = "UNVERIFIED"
  adjSummary   = "전 슬롯 검증 실패(타임아웃/오류)"
} else if (failCount >= 2) {
  // 과반 반증 → 강한 FAIL
  finalVerdict = "FAIL"
  adjSummary   = "과반 반증 — " + SLOTS.filter(s => s.r.verdict === "FAIL").map(s => `${s.name}: ${s.r.summary}`).join(" / ")
} else if (failCount === 0 && warnCount === 0) {
  finalVerdict = "PASS"
  adjSummary   = `전 슬롯 이견 없음(${SLOTS.length}/${attempted})`
} else {
  // 불일치(1건 FAIL 또는 WARN 혼재) → 교차판정 에이전트
  const allFindings = SLOTS.flatMap(s => s.findings)
  const adj = await agent(
    `${SLOTS.length}개 이종 검증자 결과가 갈렸다. 교차판정해서 최종 verdict를 결정하라.
${SLOTS.map(s => `${s.name}(${s.r.verdict}): ${s.r.summary ?? "없음"}`).join("\n")}
불일치 findings:
${JSON.stringify(allFindings, null, 2)}

JSON만 출력: {"verdict":"PASS|WARN|FAIL","rationale":"판정 근거 1줄"}`,
    { label: "adjudicator", phase: "Adjudicate",
      schema: { type:"object", properties: { verdict:{type:"string"}, rationale:{type:"string"} }, required:["verdict","rationale"] }
    }
  )
  finalVerdict = adj?.verdict ?? "WARN"
  adjSummary   = adj?.rationale ?? "판정 불가"
}

const slotReport = (r) => r ? { verdict: r.verdict, confidence: r.confidence, summary: r.summary, script_ok: r.script_ok, findings: (r.findings ?? []).slice(-limit) } : null

// ── 이종성 미달 침묵차단(하네스 L0: 안전임계=이종검증 의무) ──
// 실모델 2개 미만이면 교차확인 자체가 성립 안 함 → 단일모델 PASS는 PASS 자격 없음.
// Gemini 무료티어 429/503 장애 시 groq 단독으로 조용히 degrade하던 구멍을 top-level에 강제노출.
const crossVerified = hetero >= 2
let degradeNote = null
if (!crossVerified) {
  degradeNote = `⚠️ 이종검증 미달성 — 실모델 ${hetero}/${attempted}만 성공(교차확인 불성립). ` +
    (hetero === 1 ? "단일모델 결과라 탈상관 없음. " : "전 슬롯 실패. ") +
    (gemFailed ? "gemini 슬롯 실패(429/503/타임아웃 추정). " : "") +
    (gemFailed && !allowOR ? "OpenRouter 폴백 미옵트인. " : "")
  // 단일모델 PASS는 교차확인 없이 통과선언 불가 → WARN 강등(FAIL/WARN은 유지, 놓침 방지)
  if (finalVerdict === "PASS") {
    finalVerdict = "WARN"
    adjSummary = `[이종성 미달로 PASS→WARN 강등] ${adjSummary}`
  }
}

return {
  verdict: finalVerdict,
  cross_verified: crossVerified,  // false면 이종검증 미달성 — verdict를 교차확인 결과로 신뢰 금지
  ...(degradeNote ? { degrade_warning: degradeNote } : {}),
  heterogeneity: `${hetero}/${attempted} 실모델 검증 성공`,  // 시도 대비 실제 탈상관 달성
  slot1_source: slot1src,  // "gemini" 또는 "openrouter"(폴백 발동 시)
  ...(orNote ? { fallback_note: orNote } : {}),
  slot1:  { source: slot1src, ...(slotReport(slot1) ?? { script_ok: false }) },
  groq:   slotReport(groqResult),
  ...(allowNvidia ? { nvidia: slotReport(nvidiaResult) } : {}),
  ...(allowAgy ? { agy: slotReport(agyResult) } : {}),
  ...(allowCdx ? { cdx: slotReport(cdxResult) } : {}),
  adjudication: adjSummary,
}

export const meta = {
  name: 'parallel-verify',
  description: 'gemini(Google) + 로컬 Hermes(gemma4) + cdx(Codex/OpenAI) 3계열 병렬 교차검증 후 합산 판정. 기본 3슬롯이 서로 다른 계보라 탈상관 성립. sensitive:true(또는 defense:true)면 외부로 나가는 슬롯을 전부 제외(gemini·cdx·agy·nvidia·openrouter)하고 로컬 2계열 Hermes(gemma4)+qwen3(Qwen)로만 검증 — 데이터가 기기 밖으로 안 나간다. allow_agy:true 시 agy CLI(Gemini 3.1 Pro) 추가 — 단 agy는 gemini 슬롯과 동계보라 계열 수는 안 늘어난다. 이종성 미달 시 cross_verified:false 강제노출. 안전임계 답변·설계판단·인과주장 반박에 사용.',
  phases: [
    { title: 'Verify', detail: '3계열 실모델 병렬 검증 — 일반=gemini·Hermes·cdx / 민감=Hermes·qwen3 로컬 2계열' },
    { title: 'Adjudicate', detail: '불일치 교차판정' },
  ],
}

// args: { content: "검증할 텍스트", context: "배경정보(선택)", limit: 5 }
// Workflow가 args를 JSON 문자열로 전달하는 경우 파싱
const _args = typeof args === 'string' ? JSON.parse(args) : (args ?? {})
const content = _args.content ?? "검증 대상 없음"
const context = _args.context ?? ""
const limit = _args.limit ?? 5  // 슬라이딩: 최근 N개 findings만 다음 스테이지로 전달
// ── 민감도 게이트 (2026-09-01 도입, 2026-09-04 전면화) ─────────────────
// 이 상수가 외부로 나가는 모든 슬롯을 지배한다. 아래 어떤 옵트인보다 먼저 선언한다.
//
// 2026-09-04 수리 이력 — 종전에는 sensitive가 cdx 슬롯 하나만 제외했다. gemini 슬롯은
// 그대로 살아서 generativelanguage.googleapis.com 으로 나갔다. 즉 민감·수출통제 내용이
// 구글 클라우드로 전송되는 경로가 열려 있었다. agy·cdx 스킬에는 민감 투입금지 게이트가
// 명시돼 있는데 gemini-review 스킬에는 없어서 비대칭도 방치돼 있었다.
// 이제 sensitive는 외부 슬롯을 전부 끈다 — gemini·cdx·agy·nvidia·openrouter.
//
// 남는 것은 로컬 2슬롯이다. Hermes(gemma4-hermes)는 Google Gemma 파생이라 gemini와
// 계보가 겹치므로, 계보가 다른 qwen3(Qwen)을 제2 로컬 슬롯으로 세워 탈상관을 유지한다.
const sensitive = _args.sensitive === true || _args.defense === true

// ⚠️ OpenRouter 무료모델 = 프로바이더 학습활용 → 사내기밀·민감 데이터 금지.
// gemini 실패(429/타임아웃) 시에만, 명시 옵트인일 때만 폴백. 기본 OFF(기밀데이터 보호).
// sensitive면 옵트인해도 강제 차단 — 민감 게이트가 옵트인보다 우선한다.
const allowOR = _args.allow_openrouter === true && !sensitive
// NVIDIA NIM(build.nvidia.com) 3번째 이종슬롯. 무료티어=프로바이더 데이터활용 가능 →
// 사내기밀·민감 데이터 금지, 기본 OFF. 켜면 gemini+Hermes+cdx에 nvidia가 더해져 4슬롯.
const allowNvidia = _args.allow_nvidia === true && !sensitive
// agy CLI(Gemini 3.1 Pro High) 이종슬롯 — Google 계열. cdx(OpenAI)·Hermes(로컬)와는 탈상관이나 gemini 슬롯과는 동계보.
// 키링 OAuth 선행(대화형 agy 1회 로그인) 필요. 구글 백엔드·구독티어 학습정책 미확인 →
// 사내기밀·민감 데이터 금지, 기본 OFF(옵트인). ⚠️ agy를 켜도 계열 수는 안 는다(gemini와 같은 Google) — 슬롯 수만 늘고 탈상관은 그대로.
const allowAgy = _args.allow_agy === true && !sensitive
// cdx = Codex CLI(OpenAI GPT) — gemini(Google)·Hermes(로컬 gemma4)와 계열 분리.
// ~/.codex OAuth 선행. 기본 ON(2026-09-01 groq 사망으로 승격), allow_cdx:false로 끌 수 있다.
const allowCdx = _args.allow_cdx !== false && !sensitive
// ── 슬롯1 주체 (일반=gemini / 민감=qwen3 로컬) ──
// 슬롯 개수는 그대로 2개다. 주체만 갈아끼우므로 아래 인덱스 오프셋 산식은 불변이다.
const useLocalSlot1 = sensitive

// ── per-slot 타임아웃 래퍼 (JARVIS HuggingGPT 한계 #2 반면교사: 통짜 타임아웃 금지) ──
// 한 슬롯이 행(hang)걸려도 전체 barrier를 잡지 않게 개별 wall-clock 상한을 건다.
// 스크립트 자체 API 타임아웃(gemini 180s/round, Hermes 로컬 ~87s 실측)보다 약간 여유.
const withTimeout = (p, ms, label) => Promise.race([
  p,
  new Promise((_, rej) => setTimeout(() => rej(new Error(`timeout:${label}:${ms}ms`)), ms)),
])

// ── 지연도착 회수 홀더 (wf_10061afb-0c3 사고 박제, 2026-08-02) ──
// withTimeout은 경주에 진 promise를 버리지만 하부 agent()는 계속 달려 결과가 저널엔 실재
// (실측: gemini 326.1s>300s 상한, cdx 187.6s>180s 상한 — 둘 다 완료됐는데 합산서 드랍).
// 홀더가 원promise 결과를 도착 즉시 캡처 → 합산 전 동기 회수(추가 대기 0).
const mkHolder = () => ({ settled: false, value: null })
const capture = (p, h) => { p.then(v => { h.settled = true; h.value = v }, () => {}); return p }
const holders = {
  gemini: mkHolder(), nvidia: mkHolder(), agy: mkHolder(),
  cdx: mkHolder(), hermes: mkHolder(), openrouter: mkHolder(),
  qwen: mkHolder(),  // 민감모드 슬롯1 (로컬 제2계열)
}

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
  openrouter: "~/.claude/skills/groq-review/scripts/openrouter_review.py",
  nvidia:     "~/.claude/skills/groq-review/scripts/nvidia_review.py",
  agy:        "~/.claude/skills/groq-review/scripts/agy_review.py",  // Antigravity CLI Gemini 3.1 Pro(키링 OAuth)
  cdx:        "~/.claude/skills/groq-review/scripts/cdx_review.py",  // Codex CLI OpenAI GPT(~/.codex OAuth)
  hermes:     "~/.claude/skills/groq-review/scripts/hermes_review.py",  // 로컬 gemma4-hermes — 2026-09-01 기본 슬롯2로 승격(무료·오프라인·민감데이터 로컬보존)
  qwen:       "~/.claude/skills/groq-review/scripts/qwen_review.py",  // 로컬 qwen3:8b — 2026-09-04 민감모드 슬롯1(Qwen 계보, Hermes의 Gemma 계보와 분리)
}

// gemini(Google)·Hermes(로컬)·cdx(OpenAI) 병렬 실행 = 계열 3분리 탈상관. 슬롯별 타임아웃 차등.
// nvidia 슬롯은 allow_nvidia 옵트인 시에만 — 무료티어 데이터활용 보호(민감 기본차단).
const slotThunks = [
  // 슬롯1 — 일반은 gemini(외부), 민감은 qwen3(로컬). 개수는 항상 1개다.
  useLocalSlot1
    ? () => withTimeout(
        capture(agent(SLOT_PROMPT("로컬 qwen3:8b(Qwen 계보)", SCRIPTS.qwen, "/tmp/_pv_qwen.txt"), {
          label: "qwen-verify", phase: "Verify", schema: VERIFY_SCHEMA,
          agentType: "general-purpose", effort: "high"
        }), holders.qwen),
        900_000, "qwen"  // 로컬 2슬롯은 llm_lock으로 직렬화된다(ollama 단일창구 경합 회피) → Hermes 점유시간만큼 대기가 얹힌다
      ).catch(() => null)
    : () => withTimeout(
        capture(agent(SLOT_PROMPT("Gemini(gemini-2.5-flash)", SCRIPTS.gemini, "/tmp/_pv_gemini.txt"), {
          label: "gemini-verify", phase: "Verify", schema: VERIFY_SCHEMA,
          agentType: "general-purpose", effort: "high"
        }), holders.gemini),
        420_000, "gemini"  // 실측 326.1s(wf_10061afb 초과사고) → 300s서 상향. 상한=barrier 대기·폴백판단 기준일 뿐, 늦은 결과는 홀더 회수
      ).catch(() => null),
  () => withTimeout(
    capture(agent(SLOT_PROMPT("로컬 Hermes(gemma4-hermes)", SCRIPTS.hermes, "/tmp/_pv_hermes.txt"), {
      label: "hermes-verify", phase: "Verify", schema: VERIFY_SCHEMA,
      agentType: "general-purpose", effort: "high"
    }), holders.hermes),
    900_000, "hermes"  // 실측 268.7s(2026-09-01 콜드로드 포함). 2026-09-04 480s→900s: 민감모드에서 qwen과 llm_lock으로 직렬화되어 대기가 얹힌다
  ).catch(() => null),
]
if (allowNvidia) {
  slotThunks.push(
    () => withTimeout(
      capture(agent(SLOT_PROMPT("NVIDIA NIM(nemotron 계열, build.nvidia.com)", SCRIPTS.nvidia, "/tmp/_pv_nvidia.txt"), {
        label: "nvidia-verify", phase: "Verify", schema: VERIFY_SCHEMA,
        agentType: "general-purpose", effort: "high"
      }), holders.nvidia),
      150_000, "nvidia"  // NIM 호스티드 — nemotron 추론 여유
    ).catch(() => null)
  )
}
if (allowAgy) {
  slotThunks.push(
    () => withTimeout(
      capture(agent(SLOT_PROMPT("agy CLI(Gemini 3.1 Pro, Antigravity)", SCRIPTS.agy, "/tmp/_pv_agy.txt"), {
        label: "agy-verify", phase: "Verify", schema: VERIFY_SCHEMA,
        agentType: "general-purpose", effort: "high"
      }), holders.agy),
      150_000, "agy"  // 실측 22.7s(리뷰프롬프트)·에이전트 전체 100.3s(wf_10061afb) + 여유
    ).catch(() => null)
  )
}
if (allowCdx) {
  slotThunks.push(
    () => withTimeout(
      capture(agent(SLOT_PROMPT("Codex CLI(OpenAI GPT)", SCRIPTS.cdx, "/tmp/_pv_cdx.txt"), {
        label: "cdx-verify", phase: "Verify", schema: VERIFY_SCHEMA,
        agentType: "general-purpose", effort: "high"
      }), holders.cdx),
      300_000, "cdx"  // 실측 187.6s(wf_10061afb 초과사고) → 180s서 상향
    ).catch(() => null)
  )
}
const slotResults = await parallel(slotThunks)
// 인덱스 배선(push 순서=gemini,hermes,[nvidia],[agy],[cdx]). 2026-09-01 groq→hermes 승계로 [1]만 주체 교체,
// 오프셋 산식은 불변(기본 슬롯 수 2 유지). 슬롯 추가/삭제 시 아래 오프셋도 반드시 같이 고칠 것.
// 슬롯1 주체가 민감모드에서 qwen으로 바뀌므로 홀더·라벨도 같이 따라간다.
// (홀더를 gemini에 고정하면 아래 gemini_late 회수 로직이 qwen 결과를 gemini로 오보고한다.)
const slot1Holder = useLocalSlot1 ? holders.qwen : holders.gemini
const slot1Name   = useLocalSlot1 ? "qwen(local)" : "gemini"
const racedGem    = slotResults[0]
const racedHermes = slotResults[1]
const racedNvidia = allowNvidia ? slotResults[2] : null
const racedAgy    = allowAgy ? slotResults[2 + (allowNvidia ? 1 : 0)] : null
const racedCdx    = allowCdx ? slotResults[2 + (allowNvidia ? 1 : 0) + (allowAgy ? 1 : 0)] : null

// 회수 1차(barrier 직후): 경주엔 졌지만 barrier 대기 동안 실도착한 결과 복원(동기 읽기).
// wf_10061afb 재현 기준 cdx(187.6s, barrier exit 300s 이전 도착)가 여기서 살아난다.
const lateRecovered = []
const recover = (name, raced, h) => {
  if (raced) return raced
  if (h.settled && h.value) { lateRecovered.push(name); return h.value }
  return null
}
let gemResult    = recover(slot1Name, racedGem, slot1Holder)
let hermesResult = recover("hermes", racedHermes, holders.hermes)
let nvidiaResult = allowNvidia ? recover("nvidia", racedNvidia, holders.nvidia) : null
let agyResult    = allowAgy ? recover("agy", racedAgy, holders.agy) : null
let cdxResult    = allowCdx ? recover("cdx", racedCdx, holders.cdx) : null
let extraAttempts = 0  // 폴백 실스폰 수 — 이종성 분모(attempted) 정합용

// ── gemini 슬롯 폴백: gemini 실패(429/503/타임아웃) 시 슬롯1 복구 ──
// 2026-09-01: Hermes가 기본 슬롯2로 승격되면서 폴백 목록에서 제거했다.
// 이유 — 폴백으로 또 Hermes를 띄우면 같은 모델이 슬롯1·슬롯2에 동시에 잡혀 hetero가 2로 세어진다.
// 그건 탈상관 없는 가짜 교차확인이다. gemini가 죽으면 슬롯1은 비우고 Hermes+cdx로 이종성을 채운다.
// 남은 폴백은 OpenRouter(외부·옵트인 필수)뿐. 미옵트인이면 슬롯1 공백을 그대로 노출한다.
let slot1 = gemResult
let slot1src = slot1Name
let orNote = null
const gemFailed = !gemResult || gemResult.script_ok === false
// 민감모드에서는 슬롯1이 로컬 qwen이고 폴백 후보(OpenRouter)는 외부라 애초에 쓸 수 없다.
// 슬롯1이 죽으면 Hermes 단독이 되고, 그건 아래 이종성 미달 경로가 잡아 PASS를 WARN으로 내린다.
if (gemFailed && useLocalSlot1) {
  orNote = "로컬 슬롯1(qwen3) 실패 — 민감모드라 외부 폴백을 쓰지 않는다. 남은 건 Hermes 단독이라 교차확인 불성립. ollama 상태를 확인하고 재실행하라."
} else if (gemFailed) {
  if (allowOR) {
    // OpenRouter 폴백(옵트인 전용) — Hermes는 이미 슬롯2라 폴백 재사용 금지(동일모델 중복계수 방지).
    extraAttempts += 1
    const or = await withTimeout(
      capture(agent(SLOT_PROMPT("OpenRouter 무료모델(qwen/gpt-oss 폴백)", SCRIPTS.openrouter, "/tmp/_pv_or.txt"), {
        label: "openrouter-verify", phase: "Verify", schema: VERIFY_SCHEMA,
        agentType: "general-purpose", effort: "high"
      }), holders.openrouter),
      120_000, "openrouter"
    ).catch(() => null)
    if (or && or.script_ok !== false) { slot1 = or; slot1src = "openrouter" }
    else orNote = "gemini·OpenRouter 폴백 모두 실패 — 슬롯1 공백. 이종성은 Hermes+cdx 슬롯으로만 집계된다."
  } else {
    orNote = "gemini 슬롯 실패. OpenRouter 폴백은 미옵트인(allow_openrouter≠true, 기밀데이터 보호) — 일반검증이면 args에 allow_openrouter:true. 슬롯1 공백이라 이종성은 Hermes+cdx로만 집계된다."
  }
}

phase('Adjudicate')

// 회수 2차(폴백 이후): 폴백 대기(최대 300s+120s) 동안 실도착한 잔여 슬롯 복원.
// wf_10061afb 재현 기준 gemini(326.1s, 폴백 스폰 26s 뒤 도착)가 여기서 살아난다.
if (!slot1) { const late = recover(slot1Name, null, slot1Holder); if (late) { slot1 = late; gemResult = late } }
if (!hermesResult) hermesResult = recover("hermes", null, holders.hermes)
if (allowNvidia && !nvidiaResult) nvidiaResult = recover("nvidia", null, holders.nvidia)
if (allowAgy && !agyResult) agyResult = recover("agy", null, holders.agy)
if (allowCdx && !cdxResult) cdxResult = recover("cdx", null, holders.cdx)
// slot1이 여전히 공백이면 폴백 자체의 지연도착도 회수(hermes 타임아웃 후 OpenRouter 대기 중 도착 등)
if (gemFailed && !useLocalSlot1 && (!slot1 || slot1.script_ok === false)) {
  for (const [nm, h] of [["openrouter", holders.openrouter]]) {  // hermes 제외 — 슬롯2 전용 홀더
    if (h.settled && h.value && h.value.script_ok !== false) {
      slot1 = h.value; slot1src = nm; lateRecovered.push(nm)
      orNote = `폴백 지연도착 회수(${nm}) — 타임아웃 경주엔 졌으나 실결과 도착분 사용.`
      break
    }
  }
}
// gemini가 폴백 대체 이후 실도착한 경우: slot1(폴백)은 유지하되 gemini 실결과를 별도 슬롯으로 합산 포함.
// 실재 결과 드랍 금지(wf_10061afb 결함의 본체).
let geminiLate = null
if (gemFailed && !useLocalSlot1 && slot1src !== "gemini" && holders.gemini.settled
    && holders.gemini.value && holders.gemini.value.script_ok !== false) {
  geminiLate = holders.gemini.value
  lateRecovered.push("gemini(폴백 후 도착)")
}

// 활성 슬롯 집계 (gemini/openrouter + Hermes + cdx + 옵트인분). N-way 투표로 일반화.
const SLOTS = [
  { name: slot1src,      r: slot1 },
  { name: "hermes(local)", r: hermesResult },
  { name: "nvidia",  r: nvidiaResult },
  { name: "agy",     r: agyResult },
  { name: "cdx",     r: cdxResult },
  { name: "gemini(late)", r: geminiLate },  // 폴백 후 도착한 gemini 실결과
].filter(s => s.r)  // null(미실행/타임아웃) 제거

// 슬라이딩: 각 결과에서 최근 limit개 findings만 취합 (토큰 O(1) 유지)
SLOTS.forEach(s => { s.findings = (s.r.findings ?? []).slice(-limit) })

const failCount = SLOTS.filter(s => s.r.verdict === "FAIL").length
const warnCount = SLOTS.filter(s => s.r.verdict === "WARN").length

// 이종성 실제 달성: script_ok=true 슬롯 수 / 시도 슬롯 수. 낮을수록 탈상관 약화.
// attempted에 폴백 실스폰(extraAttempts) 포함 — gemini(late)+폴백 동시 합산 시 분자>분모 방지.
const attempted = 2 + (allowNvidia ? 1 : 0) + (allowAgy ? 1 : 0) + (allowCdx ? 1 : 0) + extraAttempts
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
// Gemini 무료티어 429/503 장애 시 단일슬롯으로 조용히 degrade하던 구멍을 top-level에 강제노출.
// ⚠️ 한계: hetero는 슬롯 '개수'만 센다(계열 수 아님). agy를 켜면 gemini+agy 둘 다 Google인데도 2로 세어진다.
const crossVerified = hetero >= 2
let degradeNote = null
if (!crossVerified) {
  degradeNote = `⚠️ 이종검증 미달성 — 실모델 ${hetero}/${attempted}만 성공(교차확인 불성립). ` +
    (hetero === 1 ? "단일모델 결과라 탈상관 없음. " : "전 슬롯 실패. ") +
    (gemFailed ? `슬롯1(${slot1Name}) 실패. ` : "") +
    (gemFailed && useLocalSlot1 ? "민감모드라 외부 폴백 없음 — ollama 상태 확인 필요. " : "") +
    (gemFailed && !useLocalSlot1 && !allowOR ? "OpenRouter 폴백 미옵트인. " : "")
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
  slot1_source: slot1src,  // "gemini" | "qwen(local)"(민감모드) | "openrouter"(폴백 발동 시)
  sensitive_mode: sensitive,  // true면 외부 슬롯 전량 차단 — 데이터가 기기 밖으로 안 나갔다는 표시
  ...(sensitive ? { egress: "none — 로컬 2계열(Hermes/gemma4 + qwen3/Qwen)로만 검증" } : {}),
  ...(orNote ? { fallback_note: orNote } : {}),
  slot1:  { source: slot1src, ...(slotReport(slot1) ?? { script_ok: false }) },
  hermes: slotReport(hermesResult),
  ...(allowNvidia ? { nvidia: slotReport(nvidiaResult) } : {}),
  ...(allowAgy ? { agy: slotReport(agyResult) } : {}),
  ...(allowCdx ? { cdx: slotReport(cdxResult) } : {}),
  ...(geminiLate ? { gemini_late: slotReport(geminiLate) } : {}),  // 폴백 후 도착분 — 드랍 금지
  ...(lateRecovered.length ? { late_recovered: lateRecovered } : {}),  // 타임아웃 경주 패배 후 회수된 슬롯
  adjudication: adjSummary,
}

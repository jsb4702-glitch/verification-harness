export const meta = {
  name: 'safety-parallel',
  description: '안전임계 설계판단: 전제추출+메인답변 병렬 → 자가교차 → 실제 이종모델(gemini+groq) 교차검증 합성. FoS·응력·체결력·열·피로·진동 결론에 사용.',
  phases: [
    { title: 'Parallel', detail: '전제추출 + 메인답변 동시 실행' },
    { title: 'CrossCheck', detail: '전제 위반 여부 자가교차' },
    { title: 'HeteroVerify', detail: 'gemini+groq 실모델 이종 교차검증' },
  ],
}

// args: { question: "설계 질문", context: "도면·조건 등 배경" }
const _args   = typeof args === 'string' ? JSON.parse(args) : (args ?? {})
const question = _args.question ?? "질문 없음"
const context  = _args.context  ?? ""

const BG = context ? `[배경/조건]\n${context}\n\n` : ""

phase('Parallel')

// 전제추출 + 메인답변 병렬 (wall-clock = 둘 중 느린 쪽, 순차 대비 ~절반)
const PREREQ_SCHEMA = {
  type: "object",
  properties: {
    assumptions: {
      type: "array",
      items: {
        type: "object",
        properties: {
          id:        { type: "string" },            // A1, A2 ...
          text:      { type: "string" },            // 전제 내용
          critical:  { type: "boolean" },           // 깨지면 결론 무효
          threshold: { type: "string" }             // 임계값 (예: "온도 < 85°C")
        },
        required: ["id","text","critical","threshold"]
      }
    }
  },
  required: ["assumptions"]
}

const MAIN_SCHEMA = {
  type: "object",
  properties: {
    answer:      { type: "string" },   // 핵심 결론
    values:      { type: "array", items: { type: "object", properties: { name:{type:"string"}, value:{type:"string"}, unit:{type:"string"} }, required:["name","value","unit"] } },
    gate_status: { type: "string", enum: ["PASS","WARN","FAIL"] },
    assumptions_used: { type: "array", items: { type: "string" } }  // 이 답변이 암묵적으로 사용한 전제 id 목록
  },
  required: ["answer","gate_status"]
}

const [prereqResult, mainResult] = await parallel([
  () => agent(
    `${BG}다음 설계 질문에 답하기 전에, 답변이 유효하려면 반드시 성립해야 할 전제조건·경계조건만 추출하라. 답변 자체는 내지 말 것.\n\n질문: ${question}`,
    { label: "prereq-extract", phase: "Parallel", schema: PREREQ_SCHEMA, effort: "high" }
  ),
  () => agent(
    `${BG}다음 설계 질문에 답하라. 시니어 기계설계 엔지니어 관점. 핵심 수치·단위 포함. 암묵적으로 사용한 가정도 assumptions_used에 열거.\n\n질문: ${question}`,
    { label: "main-answer", phase: "Parallel", schema: MAIN_SCHEMA, effort: "max" }
  ),
])

phase('CrossCheck')

const assumptions  = prereqResult?.assumptions ?? []
const criticalOnly = assumptions.filter(a => a.critical)
const usedIds      = mainResult?.assumptions_used ?? []

// 메인 답변이 사용한 전제 중 critical인 것 — 위반 감지용
const criticalUsed = criticalOnly.filter(a => usedIds.includes(a.id))

let crossResult = null
if (criticalOnly.length > 0) {
  crossResult = await agent(
    `메인 답변과 전제조건을 교차 검토하라.

[메인 답변]
${mainResult?.answer ?? "없음"}
수치: ${JSON.stringify(mainResult?.values ?? [])}

[Critical 전제조건]
${JSON.stringify(criticalOnly, null, 2)}

질문: 메인 답변이 위 전제조건을 묵시적으로 위반하거나, 임계값 근접 위험이 있는가?
JSON만: {"violations":[{"assumption_id":"A1","detail":"위반 내용","risk":"HIGH|MED|LOW"}],"safe":true|false}`,
    {
      label: "cross-check",
      phase: "CrossCheck",
      effort: "max",
      schema: {
        type: "object",
        properties: {
          violations: { type: "array", items: { type: "object", properties: { assumption_id:{type:"string"}, detail:{type:"string"}, risk:{type:"string"} }, required:["assumption_id","detail","risk"] } },
          safe: { type: "boolean" }
        },
        required: ["violations","safe"]
      }
    }
  )
}

const violations = crossResult?.violations ?? []
const safe       = crossResult?.safe ?? true

phase('HeteroVerify')

// ── 실제 이종모델(gemini+groq) 교차검증 합성 (하네스 L0: 안전임계 → 이종검증 의무) ──
// 자가교차(같은 모델)는 상관오류를 못 잡으므로, 메인답변을 실모델 2종으로 탈상관 검증.
// parallel-verify.js를 1단 중첩 호출(scriptPath 방식 — name: 캐시이슈 회피).
let hetero = null
const mainAnswerText = mainResult?.answer
if (mainAnswerText) {
  const heteroContent =
    `${mainAnswerText}\n\n[핵심 수치]\n${JSON.stringify(mainResult?.values ?? [])}`
  try {
    hetero = await workflow(
      { scriptPath: "~/.claude/workflows/parallel-verify.js" },
      { content: heteroContent, context: `안전임계 설계판단 검증. 원질문: ${question}\n${context}`, limit: 5 }
    )
  } catch (e) {
    hetero = { verdict: "UNVERIFIED", heterogeneity: "0/2 (합성호출 실패)", _error: String(e) }
  }
}

// ── 게이트 합산: 자가교차 · 이종검증 중 가장 보수적인 판정 채택 ──
const heteroVerdict = hetero?.verdict ?? "UNVERIFIED"
const selfFail   = !safe || violations.some(v => v.risk === "HIGH")
const selfWarn   = violations.length > 0
const heteroFail = heteroVerdict === "FAIL"
const heteroWarn = heteroVerdict === "WARN" || heteroVerdict === "UNVERIFIED"

// 이종검증 실제 달성 여부(parallel-verify가 올려주는 cross_verified). 안전임계는 이종성 미달을 침묵불가.
// hetero 자체가 null(메인답변 없음)이거나 cross_verified===false면 미달.
const heteroDegraded = !hetero || hetero.cross_verified === false || heteroVerdict === "UNVERIFIED"

let finalGate
if (selfFail || heteroFail)        finalGate = "FAIL"
else if (selfWarn || heteroWarn)   finalGate = "WARN"
else                               finalGate = (mainResult?.gate_status ?? "PASS")

// 안전임계에서 이종성 미달이면 PASS 통과선언 금지 — 최소 WARN(자가교차만으론 상관오류 못 잡음)
if (heteroDegraded && finalGate === "PASS") finalGate = "WARN"

// 수치 존재 시 G9 산술검증 리마인더(워크플로는 Bash 불가 → 메인세션에서 처리)
const arithFlag = (mainResult?.values?.length ?? 0) > 0
  ? "⚠️ 산술 미검증 — 메인세션 G9 Bash로 재검증 필요"
  : null

return {
  gate:        finalGate,
  answer:      mainResult?.answer,
  values:      mainResult?.values ?? [],
  arith_check: arithFlag,
  assumptions: {
    total:    assumptions.length,
    critical: criticalOnly.length,
    list:     assumptions,
  },
  self_cross:  { safe, violations },
  hetero:      hetero ? { verdict: hetero.verdict, cross_verified: hetero.cross_verified, heterogeneity: hetero.heterogeneity, adjudication: hetero.adjudication } : null,
  ...(heteroDegraded ? { hetero_degraded: hetero?.degrade_warning ?? "이종검증 미달성(합성호출 실패 또는 실모델<2) — 안전결론은 자가교차만 반영, 이종 탈상관 미확보. 메인세션 gemini-review로 보강 권고." } : {}),
}

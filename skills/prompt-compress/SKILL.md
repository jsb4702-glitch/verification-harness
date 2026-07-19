---
name: prompt-compress
description: >
  Numeric-aware prompt compression for long ENGLISH prose you're about to feed
  another LLM — meeting transcripts, paper intros/discussion, web-article bodies,
  logs. Uses LLMLingua-2 (local, CPU, no API) but FIRST triages numeric-sentence
  density: if the document is number-heavy (FEA results, datasheets, spec tables,
  PN lists), it REFUSES to compress, because protecting the numbers caps the ratio
  near 1.3x and blind compression silently corrupts figures ("13,700 MPa"->"13,000").
  Number-bearing sentences are protected verbatim (≈100% numeric recall); only the
  prose between them is compressed. Use when you have a large low-numeric-density
  English text blob to shrink before sending to a model. Triggers: "이 컨텍스트
  압축", "프롬프트 토큰 줄여줘", "긴 문서 압축해서 넣어줘", "llmlingua", "compress
  this context". NOT for: spec/datasheet/results tables (it'll refuse), Korean text
  (compressor is English/MeetingBank-trained — quality unverified), or static
  repeated context (prompt caching is the lossless, cheaper answer there).
---

# prompt-compress

Selective, numeric-safe LLM prompt compression with a density triage gate.

## When to reach for this
- You have a **long English prose blob** (transcript, article, paper section, log)
  headed into another LLM and want to cut input tokens.
- The text is **narrative-heavy, number-light**. That's the sweet spot: protecting
  numbers costs almost nothing and you still get 2.5–3x.

## When NOT to (the gate enforces this)
- **Number-dense docs** (FEA results, datasheets, MIL-STD tables, BOM/PN lists):
  the tool refuses. Protected numeric span becomes a non-compressible floor
  (Amdahl) — measured 58%-numeric FEA paper caps at 1.72x ceiling, real ~1.45x.
  Just send raw text.
- **Static / repeated context** (system prompts, CLAUDE.md, fixed docs): use
  **prompt caching** — lossless and cheaper than any compression.
- **Korean / non-English**: the mBERT compressor is MeetingBank(EN)-trained;
  Korean compression quality is unverified. Triage still works; compression risky.

## Why the gate exists (measured, not asserted)
Blind LLMLingua-2 on an ankle-FEA paper (394 numeric tokens):

| mode | ratio | numeric recall |
|------|-------|----------------|
| blind rate=0.33 | 3.3x | **29.9%** (silent loss) |
| protect-numbers rate=0.33 | 1.45x | **100%** |
| ceiling (protected verbatim) | 1.72x | 100% |

Blind compression mangled "13,700 MPa" -> "13,000 MPa" with no error. Protection
fixes recall but the ratio collapses *because* the doc is number-heavy — which is
exactly why triage refuses number-heavy docs instead of pretending to help.

## Usage

```bash
cd ~/.claude/skills/prompt-compress
[ -d venv ] || (python3 -m venv venv && ./venv/bin/pip install -q llmlingua)

# 1) Triage only — decide if compression is worth it (no model math on output)
./venv/bin/python compress.py --in doc.txt --triage-only

# 2) Compress (auto-refuses if protected share > 40%)
./venv/bin/python compress.py --in doc.txt --rate 0.33 --out doc.min.txt

# stdin / pipe
cat doc.txt | ./venv/bin/python compress.py --rate 0.5
```

Flags: `--rate` keep-rate for prose span (0.33≈3x on the prose part), 
`--skip-threshold` protected-share cutoff (default 0.40), `--force` compress anyway,
`--triage-only` report density and stop.

## Notes
- CPU-only, fully local, no API cost. First run downloads ~1.1GB mBERT once.
- Protection is **sentence-level (coarse)**: any sentence containing a digit is kept
  whole. This is deliberate — fine-grained (number-token-only) protection lifts the
  ratio but reintvites boundary-token corruption. Coarse = safe.
- Always read back the `[done] numeric recall` line; if <100%, a number leaked into
  the compressed prose span — inspect before trusting.
- Output is plain text; feed it as context to the target model.

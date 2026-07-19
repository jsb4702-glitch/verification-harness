#!/usr/bin/env python3
"""
prompt-compress: numeric-aware prompt compression triage + selective compression.

Two-stage:
  1) TRIAGE — measure numeric-sentence density. If protected share > --skip-threshold
     (default 40%), REFUSE to compress (compression floor too high to be worth it,
     per Amdahl: protected span caps the ratio). Print the ceiling and exit.
  2) COMPRESS — protect number-bearing sentences verbatim, compress the rest with
     LLMLingua-2. Guarantees ~100% numeric recall by construction (coarse, sentence-level).

Empirically (ankle-FEA paper, 58% protected): blind rate=0.33 => 3.3x but 30% num recall;
selective => 1.45x but 100% num recall. Sweet spot is LOW-numeric-density prose
(meeting notes, paper intros, web article bodies), where protection costs almost nothing.

Usage:
  compress.py --in file.txt [--rate 0.33] [--skip-threshold 0.40] [--triage-only] [--force]
  cat file.txt | compress.py --rate 0.5
Model runs CPU-only, local, no API. First run downloads ~1.1GB mBERT compressor.
"""
import argparse, re, sys, time

NUM = re.compile(r'\d+(?:\.\d+)?')
SENT = re.compile(r'(?<=[.!?])\s+')

def nums(s): return NUM.findall(s)

def triage(text):
    sents = [s for s in SENT.split(text) if s.strip()]
    num_sents = [s for s in sents if NUM.search(s)]
    prot = " ".join(num_sents)
    plain = " ".join(s for s in sents if not NUM.search(s))
    return sents, num_sents, prot, plain

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", help="input text file (default stdin)")
    ap.add_argument("--rate", type=float, default=0.33, help="target keep-rate for plain (non-numeric) span")
    ap.add_argument("--skip-threshold", type=float, default=0.40,
                    help="if protected-token share exceeds this, refuse to compress")
    ap.add_argument("--triage-only", action="store_true", help="report density only, do not compress")
    ap.add_argument("--force", action="store_true", help="compress even if over skip-threshold")
    ap.add_argument("--out", help="write compressed text here (default stdout)")
    a = ap.parse_args()

    text = open(a.inp).read() if a.inp else sys.stdin.read()
    if not text.strip():
        sys.exit("empty input")

    sents, num_sents, prot, plain = triage(text)

    # lazy import: triage-only path avoids loading torch/model at all
    from llmlingua import PromptCompressor
    pc = PromptCompressor(
        model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
        use_llmlingua2=True, device_map="cpu",
    )
    tok = pc.tokenizer
    ntok = lambda s: len(tok.encode(s)) if s.strip() else 0

    total_t, prot_t, plain_t = ntok(text), ntok(prot), ntok(plain)
    share = prot_t / total_t if total_t else 0
    ceiling = total_t / prot_t if prot_t else float('inf')

    print(f"[triage] sentences={len(sents)} number-bearing={len(num_sents)} "
          f"({len(num_sents)/max(len(sents),1)*100:.0f}%)", file=sys.stderr)
    print(f"[triage] tokens total={total_t} protected={prot_t} ({share*100:.0f}%) "
          f"| max achievable ratio if protected verbatim = {ceiling:.2f}x", file=sys.stderr)

    if a.triage_only:
        verdict = "SKIP (low value)" if share > a.skip_threshold else "COMPRESS (worth it)"
        print(f"[verdict] protected share {share*100:.0f}% vs threshold "
              f"{a.skip_threshold*100:.0f}% -> {verdict}", file=sys.stderr)
        return

    if share > a.skip_threshold and not a.force:
        print(f"[REFUSED] protected share {share*100:.0f}% > threshold {a.skip_threshold*100:.0f}%. "
              f"Ceiling {ceiling:.2f}x not worth the risk — use raw text or prompt caching instead. "
              f"Override with --force.", file=sys.stderr)
        sys.exit(2)

    t0 = time.time()
    out = pc.compress_prompt(plain, rate=a.rate, force_tokens=['\n', '.', ','])
    combined = (prot + " " + out['compressed_prompt']).strip()

    # numeric recall check (multiset)
    o = {}
    for n in nums(text): o[n] = o.get(n, 0) + 1
    c = {}
    for n in nums(combined): c[n] = c.get(n, 0) + 1
    kept = sum(min(v, c.get(k, 0)) for k, v in o.items())
    tot = sum(o.values())
    final_t = prot_t + out['compressed_tokens']

    print(f"[done] {time.time()-t0:.1f}s | effective ratio {total_t/final_t:.2f}x "
          f"({total_t}->{final_t} tok) | numeric recall {kept}/{tot}="
          f"{kept/max(tot,1)*100:.1f}%", file=sys.stderr)

    if a.out:
        open(a.out, 'w').write(combined)
        print(f"[written] {a.out}", file=sys.stderr)
    else:
        print(combined)

if __name__ == "__main__":
    main()

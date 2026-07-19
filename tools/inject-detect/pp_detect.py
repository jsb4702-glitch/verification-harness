#!/usr/bin/env python3
"""인젝션 탐지기 v3 — 재귀 디코드 루프 + v2 신호셋.
v2 대비: 디코드를 1패스→재귀(중첩 b64/hex/bin/leet/rot13 다단 환원, cycle/size/depth 가드)."""
import re, sys, base64, codecs, unicodedata, pathlib, html, urllib.parse

LEET = str.maketrans({'0':'o','1':'i','3':'e','4':'a','5':'s','7':'t','@':'a','$':'s','8':'b','9':'g'})
MAX_DEPTH, MAX_NODES, MAX_LEN = 5, 60, 200_000   # BFS 전환으로 60에서도 다단 재귀 도달(실측: 20노드면 url>b64 잡힘). 140은 과했음

def _try(fn):
    try: return fn()
    except Exception: return None
def _printable(d): return d and len(d)>3 and sum(c.isprintable() or c.isspace() for c in d) > len(d)*0.85

def _decoders(t):
    """t에서 파생 가능한 평문 후보들(단일 패스)."""
    out=[]
    for m in re.findall(r'[A-Za-z0-9+/]{16,}={0,2}', t):
        d=_try(lambda:base64.b64decode(m+'==',validate=False).decode('utf-8','ignore'))
        if _printable(d): out.append(('b64',d))
    for m in re.findall(r'(?:[0-9a-fA-F]{2}){8,}', t):
        d=_try(lambda:bytes.fromhex(m).decode('utf-8','ignore'))
        if _printable(d): out.append(('hex',d))
    for m in re.findall(r'(?:[01]{8}\s*){4,}', t):
        bits=re.sub(r'\s','',m)
        d=_try(lambda:bytes(int(bits[i:i+8],2) for i in range(0,len(bits)-7,8)).decode('utf-8','ignore'))
        if _printable(d): out.append(('bin',d))
    # URL 퍼센트 인코딩(%69%67…) — 매치 단위 (prompt-guard v3.7 갭흡수, 2026-07-05 리빌드)
    for m in re.findall(r'(?:%[0-9a-fA-F]{2}){3,}', t):
        d=_try(lambda:urllib.parse.unquote(m))
        if _printable(d) and d!=m: out.append(('url',d))
    if '%' in t:  # 전체 unquote(공백만 %20 인코딩 등 띄엄띄엄 케이스)
        d=_try(lambda:urllib.parse.unquote(t))
        if d and d!=t and _printable(d): out.append(('url_full',d))
    # unicode escape(i…) — 매치 단위
    for m in re.findall(r'(?:\\u[0-9a-fA-F]{4}){3,}', t):
        d=_try(lambda:codecs.decode(m,'unicode_escape'))
        if _printable(d) and d!=m: out.append(('uesc',d))
    # HTML 엔티티(&#105; &#x69; &amp;) — 전체 텍스트 대상
    if '&' in t and ';' in t:
        d=_try(lambda:html.unescape(t))
        if d and d!=t and _printable(d): out.append(('html',d))
    r=_try(lambda:codecs.decode(t,'rot13'))
    if r and r!=t: out.append(('rot13',r))
    dl=t.translate(LEET).lower()
    if dl!=t.lower(): out.append(('deleet',dl))
    return out

def strip_invisible(t):
    return "".join(chr(ord(c)-0xE0000) if 0xE0000<=ord(c)<=0xE007F else c
                   for c in t if c not in "​‌‍⁠﻿‪‫‬‭‮")

def expand(text):
    """재귀 디코드: (view_path, text) 집합. seen으로 사이클 차단, 예산 가드."""
    base = unicodedata.normalize('NFKC', strip_invisible(text))[:MAX_LEN]
    views={"raw":text[:MAX_LEN], "nfkc":base}
    seen={hash(base), hash(text)}; frontier=[("nfkc",base)]; nodes=0
    while frontier and nodes<MAX_NODES:
        path,cur=frontier.pop(0)   # BFS: 얕은 유용경로(url>b64) 우선 — deleet/rot13 노이즈 폭발에 예산 뺏기지 않게
        if path.count('>')>=MAX_DEPTH: continue
        for kind,dec in _decoders(cur):
            dec=dec[:MAX_LEN]; h=hash(dec)
            if h in seen or len(dec)<4: continue
            seen.add(h); nodes+=1
            vp=f"{path}>{kind}"; views[vp]=dec; frontier.append((vp,dec))
    return views

# ───────── 신호 (v2와 동일) ─────────
REFUSAL=[r"i'?m sorry",r"i can(?:no|')t (?:assist|provide|help)",r"i'?m unable",r"as an ai",r"consult (?:a|with)",
         r"죄송",r"도와드릴 수 없",r"제공(?:할|해 드릴) 수 없",r"답변(?:할|해 드릴) 수 없",r"ai(?:로서|입니다)"]
SIGNALS={
 "config_framing":  (2,[r"<\s*[\w-]*config\s*>",r"interaction-config",r"\[[\w-]*config\]"]),
 "mode_override":   (2,[r"allowed\s*modes?\s*[:=]",r"blocked\s*modes?\s*[:=]\s*all",r"blocked\s*responses?\s*[:=]",
                        r"제한\s*없(?:는|이)\s*모드",r"개발자\s*모드"]),
 "refusal_suppress":(4,[r"blocked[- ]?strings?",r"never\s+(?:refuse|apolog)",r"no\s+(?:warnings|apologies|denials)",
                        r"거부\s*문구.{0,6}(?:금지|출력\s*금지)",r"경고\s*없(?:이|는)",r"unfiltered",r"unrestricted"]),
 "instr_override":  (3,[r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instruction|rule|prompt)",
                        r"disregard\s+(?:prior|previous|all)",r"new\s+paradigm",
                        r"이전\s*지시.{0,8}무시",r"위(?:의)?\s*지시.{0,8}무시",r"규칙.{0,6}무시"]),
 "sysprompt_leak":  (3,[r"reveal\s+(?:your\s+)?(?:full\s+)?system\s+prompt",r"print\s+your\s+(?:instructions|guidelines)",
                        r"repeat\s+your\s+(?:instructions|rules)",
                        r"verbatim.{0,20}(?:system|instruction|prompt|rules)|(?:system|instruction|prompt)\s+\w*\s*verbatim",
                        r"시스템\s*프롬프트.{0,8}(?:출력|알려|그대로)",r"지침.{0,6}출력"]),
 "exfil_toolabuse": (4,[r"ssh\s*key",r"exfiltrate",r"\.env\b",r"send\s+(?:it|them|this)\s+to\s+https?",
                        r"curl\s+https?://",r"api[_ ]?key",r"credential",r"\.aws/credentials",
                        r"비밀번호.{0,6}(?:전송|유출)",r"키.{0,4}(?:탈취|유출|전송)"]),
 "fiction_4thwall": (1,[r"scene-rules?",r"4th\s*wall|fourth\s*wall",r"in\s*character",r"leet\s*speak",r"<scene"]),
 # covert 출력채널 유도(prompt-guard v3.7 COVERT_EXFILTRATION_CHANNELS 의도흡수, 2026-07-05 리빌드)
 "covert_channel":  (3,[r"(encode|convert|express|write|output|respond|reply)\s+.{0,20}(as|in|into|using)\s+.{0,10}(emojis?|emoticons?|morse|braille|pig\s*latin|nato\s*alphabet|binary\s+(?:code|encoding|cipher))",
                        r"(use|replace)\s+.{0,15}(each|every)\s*(letter|character|word)\s+(with|as|into)\s+(an?\s*)?(emoji|emoticon|symbol)",
                        r"(first|last|initial)\s*(letters?|char\w*)\s*(of\s+)?(each|every)\s*(word|line|sentence|paragraph)",
                        r"acrostic|steganograph\w*",
                        r"(reverse|backwards?|mirror)\s+.{0,15}(your|the|each)\s*(response|answer|words?|reply)",
                        r"(your|the|each)\s*(response|answer|reply)\s+.{0,12}(backwards|reversed|in\s*reverse)",
                        r"(이모지|이모티콘|모스\s*부호|점자)\s*(로|으로)\s*(변환|인코딩|출력|응답|표현)",
                        r"(각|매)\s*(단어|문장|줄).{0,4}(첫|마지막)\s*(글자|문자)",
                        r"(거꾸로|역순|반대로)\s*(출력|응답|작성)"]),
}
def hidden_channel(text):
    sig={}
    tags=sum(1 for c in text if 0xE0000<=ord(c)<=0xE007F)
    zw  =sum(1 for c in text if c in "​‌‍⁠﻿")
    bidi=sum(1 for c in text if c in "‪‫‬‭‮⁦⁧⁨⁩")
    if tags:sig["hidden_unicode_tags"]=(8,tags)
    if zw>3:sig["zero_width_smuggle"]=(3,zw)
    if bidi:sig["bidi_override(trojan_src)"]=(6,bidi)
    return sig
def refusal_blacklisted(t):
    lo=t.lower()
    if not re.search(r"blocked[- ]?strings?|blocked\s*responses?|forbidden|거부\s*문구",lo):return 0
    return sum(bool(re.search(p,lo)) for p in REFUSAL)
# ───────── persona 서사주입 (복합조건: 앵커+안전제거큐 근접동시발생) ─────────
# FP가드: 단독 "you are X" 발화금지. 캐릭터연기/감정("stay in character","in love")는 큐 아님 —
# 안전·윤리·필터·복종 제거만 큐로 인정. 앵커와 큐가 윈도우(±220자) 내 동시출현해야 발화.
P_ANCHOR=[r"you\s+are\s+(?:now\s+)?\w+", r"from\s+now\s+on[, ]+you", r"act\s+as\b", r"roleplay\s+as",
          r"pretend\s+to\s+be", r"you\s+will\s+(?:act|become|be)\b", r"embody\b",
          r"너는\s*(?:이제|지금부터)", r"역할(?:을|극)", r"인\s*척(?:해|하)", r"행세"]
P_CUE=[r"no\s+(?:ethics|morals|filters?|limits?|restrictions?|rules|guidelines)",
       r"without\s+(?:any\s+)?(?:ethics|filter|restriction|limits?\b|censorship|refus)",
       r"un(?:filtered|censored|restricted|limited)", r"amoral",
       r"ignore\s+(?:your\s+)?(?:guidelines|programming|training|safety|rules)",
       r"forget\s+(?:that\s+)?you(?:'?re| are)\s+an?\s+ai", r"obey\s+(?:all|every|me|without)",
       r"do\s+anything\b", r"no\s+longer\s+bound", r"free\s+from\s+(?:your\s+)?(?:restrictions|rules|guidelines)",
       r"윤리\s*(?:가|를)?\s*없", r"검열\s*없", r"제한\s*없이", r"규칙\s*무시", r"필터\s*없",
       r"뭐든(?:지)?\s*(?:해|답|말)", r"무조건\s*복종"]
def persona_injection(t):
    lo=t.lower()
    for am in re.finditer("|".join(P_ANCHOR),lo):
        w=lo[max(0,am.start()-220):am.end()+220]
        if re.search("|".join(P_CUE),w): return True
    return False
def refusal_blacklisted(t):
    lo=t.lower()
    if not re.search(r"blocked[- ]?strings?|blocked\s*responses?|forbidden|거부\s*문구",lo):return 0
    return sum(bool(re.search(p,lo)) for p in REFUSAL)
def scan(text):
    hits={}; total=0
    for vp,vt in expand(text).items():
        lo=vt.lower()
        for name,(w,pats) in SIGNALS.items():
            if name not in hits and any(re.search(p,lo) for p in pats):
                hits[name]=(w,vp); total+=w
        if "refusal_in_blocklist" not in hits:
            rb=refusal_blacklisted(vt)
            if rb: hits["refusal_in_blocklist"]=(3*rb,vp); total+=3*rb
        if "persona_injection" not in hits and persona_injection(vt):
            hits["persona_injection"]=(4,vp); total+=4
    for name,(w,cnt) in hidden_channel(text).items():
        hits[name]=(w,f"x{cnt}"); total+=w
    return total,hits
THRESH=6
def verdict(s):return "🚨 BLOCK" if s>=THRESH else ("⚠️ REVIEW" if s>=3 else "✅ pass")
if __name__=="__main__":
    quiet="--summary" in sys.argv; dirs=[a for a in sys.argv[1:] if not a.startswith("--")]
    for d in dirs:
        lab=d.rstrip('/').split('/')[-1]; files=sorted(pathlib.Path(d).glob("*"))
        nb=nr=npass=0
        for f in files:
            if f.is_dir():continue
            s,h=scan(f.read_text(errors='ignore'))
            v=verdict(s); nb+=v.startswith("🚨"); nr+="REVIEW" in v; npass+=v.startswith("✅")
            if not quiet:
                tags=", ".join(f"{k}@{x[1]}" for k,x in h.items())
                print(f"  {v:10} score={s:2d}  {f.name:24} [{tags}]")
        print(f"== {lab}: BLOCK={nb} REVIEW={nr} pass={npass} (n={nb+nr+npass}) ==\n")

#!/usr/bin/env python3
"""iocheck.py — skillscan 위협인텔 강화 레이어 (INTAKE opt-in).

skillscan(정적·네트워크0)의 불변식은 건드리지 않는다. 이건 별도 도구:
  1) 스킬/플러그인 디렉터리에서 IOC(URL·도메인·IPv4·sha256/md5) 정적추출 — 네트워크 0
  2) (키가 env에 있을 때만) 위협인텔 API로 대조 — 네트워크 발생, 명시적 opt-in
     - URLhaus (abuse.ch)     : env URLHAUS_AUTH_KEY  (무료가입 필요, 헤더 Auth-Key)
     - VirusTotal             : env VT_API_KEY        (무료가입 필요)
  키가 없으면 해당 소스는 skip하고 추출한 IOC 인벤토리만 출력(오프라인에서도 유용).

주의(G4/맥락적합): public-apis 리스트는 URLhaus를 auth:No로 표기하나 실측 401.
abuse.ch는 무료 Auth-Key를 요구한다 — 리스트 stale.

Usage:
  iocheck.py <skill_dir | file>            # IOC 추출만(네트워크0)
  iocheck.py <skill_dir> --check           # 키 있으면 위협인텔 대조
  iocheck.py <skill_dir> --check --json
"""
import argparse, json, os, re, sys, urllib.parse, urllib.request
from pathlib import Path

URL_RE = re.compile(r"https?://[^\s\"'`)\]<>]+", re.I)
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
SHA256_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")
MD5_RE = re.compile(r"\b[a-fA-F0-9]{32}\b")
TEXT_EXT = {".py", ".sh", ".js", ".ts", ".md", ".json", ".yaml", ".yml",
            ".txt", ".toml", ".cfg", ".ini", ".rb", ".pl", ""}
# 오탐 억제: 문서에 흔한 정상 도메인
BENIGN = {"github.com", "raw.githubusercontent.com", "developer.mozilla.org",
          "docs.python.org", "anthropic.com", "claude.com", "example.com"}


def extract(root: Path):
    urls, ips, sha, md5 = set(), set(), set(), set()
    files = [root] if root.is_file() else [
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_EXT]
    for f in files:
        try:
            t = f.read_text(errors="ignore")
        except Exception:
            continue
        for u in URL_RE.findall(t):
            urls.add(u.rstrip(".,);"))
        ips.update(IPV4_RE.findall(t))
        sha.update(h.lower() for h in SHA256_RE.findall(t))
        # md5는 sha256의 부분매치 제외
        md5.update(h.lower() for h in MD5_RE.findall(t) if not SHA256_RE.search(h))
    hosts = set()
    for u in urls:
        h = urllib.parse.urlparse(u).hostname
        if h:
            hosts.add(h)
    return {
        "urls": sorted(urls),
        "hosts": sorted(hosts),
        "hosts_suspect": sorted(hosts - BENIGN),
        "ips": sorted(i for i in ips if not i.startswith(("0.", "127.", "10.", "192.168."))),
        "sha256": sorted(sha),
        "md5": sorted(md5 - sha),
    }


def _post(url, data, headers=None):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"User-Agent": "iocheck/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def check_urlhaus_host(host, key):
    try:
        r = _post("https://urlhaus-api.abuse.ch/v1/host/", {"host": host},
                  {"Auth-Key": key})
        if r.get("query_status") == "ok":
            return {"host": host, "urlhaus": "LISTED",
                    "url_count": r.get("url_count"), "blacklists": r.get("blacklists")}
        return {"host": host, "urlhaus": r.get("query_status")}
    except Exception as e:
        return {"host": host, "urlhaus_error": str(e)}


def check_vt_hash(h, key):
    try:
        req = urllib.request.Request(
            f"https://www.virustotal.com/api/v3/files/{h}",
            headers={"x-apikey": key, "User-Agent": "iocheck/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode())
        st = d["data"]["attributes"]["last_analysis_stats"]
        return {"hash": h, "malicious": st.get("malicious"),
                "suspicious": st.get("suspicious"), "harmless": st.get("harmless")}
    except urllib.error.HTTPError as e:
        return {"hash": h, "vt": "not_found" if e.code == 404 else f"http_{e.code}"}
    except Exception as e:
        return {"hash": h, "vt_error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--check", action="store_true", help="위협인텔 대조(키 필요)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    root = Path(a.target).expanduser()
    if not root.exists():
        sys.exit(f"경로 없음: {root}")
    ioc = extract(root)

    findings, notes = [], []
    if a.check:
        uh_key = os.environ.get("URLHAUS_AUTH_KEY")
        vt_key = os.environ.get("VT_API_KEY")
        if uh_key:
            for h in ioc["hosts_suspect"]:
                r = check_urlhaus_host(h, uh_key)
                if r.get("urlhaus") == "LISTED" or "urlhaus_error" in r:
                    findings.append(r)
        else:
            notes.append("URLHAUS_AUTH_KEY 미설정 → URLhaus skip")
        if vt_key:
            for h in ioc["sha256"] + ioc["md5"]:
                r = check_vt_hash(h, vt_key)
                if r.get("malicious") or "vt_error" in r:
                    findings.append(r)
        else:
            notes.append("VT_API_KEY 미설정 → VirusTotal skip")

    out = {"target": str(root), "ioc": ioc, "findings": findings, "notes": notes}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    print(f"# IOC 인벤토리: {root}")
    for k in ("hosts_suspect", "ips", "sha256", "md5"):
        v = ioc[k]
        print(f"  {k:14s}: {len(v)}" + (f"  {v}" if v else ""))
    if a.check:
        print(f"\n# 위협인텔 대조")
        for n in notes:
            print(f"  ⚠️  {n}")
        if findings:
            print(f"  🔴 HIT {len(findings)}건:")
            for f in findings:
                print(f"     {f}")
        elif not notes or any(os.environ.get(k) for k in ("URLHAUS_AUTH_KEY", "VT_API_KEY")):
            print("  🟢 대조된 IOC 중 악성 없음")


if __name__ == "__main__":
    main()

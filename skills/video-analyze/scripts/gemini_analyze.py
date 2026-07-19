#!/usr/bin/env python3
"""Gemini 네이티브 영상분석 (민감하지 않은 일반 영상 전용 — 영상이 Google로 전송됨).

URL(유튜브/웹)은 다운로드 없이 fileData로 직접 투입. 로컬파일은 File API로 업로드 후 분석.
프레임 샘플링·별도 전사 불필요 — Gemini가 영상+오디오를 네이티브로 처리한다.

멀티키: 파일 업로드는 업로드한 키의 프로젝트에 바인딩되므로 upload+generate는 같은 키를 써야 함.
→ 키 로테이션은 '오퍼레이션 단위' — 한 키로 전체 플로우 시도, 429/503이면 다음 키로 재시도.

프라이버시 정책: 분석 결과는 로컬(stdout)에만 남기고, File API에 올라간 원본은 **분석 직후 즉시 삭제**
(48h 자동만료 안 기다림). 페일오버로 여러 키에 올라간 사본까지 전부 청소. 민감 영상 보호.

사용:
  python gemini_analyze.py <URL|파일> [--prompt "질문"] [--model gemini-2.5-flash|pro] [--keep-remote]
"""
import os, sys, json, time, mimetypes, urllib.request, urllib.error, argparse

sys.path.insert(0, os.path.expanduser("~/.claude/tools"))
import gemini_keys  # 멀티키 로테이션 (하네스 공유 정본)

KEYS = gemini_keys.load_keys()
if not KEYS:
    sys.exit("[오류] Gemini 키 없음 (GEMINI_API_KEYS 또는 GEMINI_API_KEY).")

BASE = "https://generativelanguage.googleapis.com"
DEFAULT_PROMPT = ("이 영상을 분석하라. 한국어로 간결히: "
                  "1) 전체 요약 2) 주요 장면 타임스탬프 3) 등장 객체/화면 텍스트 "
                  "4) 음성 내용 핵심.")


def _post_json(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "gemini-multikey/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=180))


def upload_file(path, key):
    """File API resumable 업로드 -> ACTIVE 폴링 -> (uri, mime, name). name은 삭제용 리소스ID."""
    mime = mimetypes.guess_type(path)[0] or "video/mp4"
    size = os.path.getsize(path)
    start = urllib.request.Request(
        f"{BASE}/upload/v1beta/files?key={key}",
        data=json.dumps({"file": {"display_name": os.path.basename(path)}}).encode(),
        headers={"X-Goog-Upload-Protocol": "resumable",
                 "X-Goog-Upload-Command": "start",
                 "X-Goog-Upload-Header-Content-Length": str(size),
                 "X-Goog-Upload-Header-Content-Type": mime,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(start, timeout=60) as r:
        upload_url = r.headers["X-Goog-Upload-URL"]
    with open(path, "rb") as f:
        data = f.read()
    up = urllib.request.Request(
        upload_url, data=data,
        headers={"X-Goog-Upload-Command": "upload, finalize",
                 "X-Goog-Upload-Offset": "0",
                 "Content-Length": str(size)})
    info = json.load(urllib.request.urlopen(up, timeout=300))["file"]
    name, uri = info["name"], info["uri"]
    for _ in range(60):
        st = json.load(urllib.request.urlopen(f"{BASE}/v1beta/{name}?key={key}", timeout=60))
        if st.get("state") == "ACTIVE":
            return uri, mime, name
        if st.get("state") == "FAILED":
            sys.exit("[오류] Gemini 파일 처리 실패(FAILED)")
        time.sleep(3)
    sys.exit("[오류] 파일 ACTIVE 타임아웃")


def delete_remote(name, key):
    """File API 업로드본 즉시 삭제. 어떤 예외든(timeout·HTTP·네트워크) 삼켜서
    다른 사본 청소가 중단되지 않게 함(1건 실패로 finally 전체 크래시 방지)."""
    req = urllib.request.Request(f"{BASE}/v1beta/{name}?key={key}", method="DELETE")
    for attempt in range(2):
        try:
            urllib.request.urlopen(req, timeout=60)
            print(f"[gemini] 🗑️ Google File API 삭제: {name} (key {gemini_keys.mask(key)})", file=sys.stderr)
            return True
        except Exception as e:
            if attempt == 0:
                continue                                   # 1회 재시도(일시 timeout 대비)
            print(f"[gemini] ⚠️ 삭제 실패 {name}: {e} — 수동삭제 권장(48h 후 자동만료)", file=sys.stderr)
            return False


def run_once(a, key, uploaded):
    """단일 키로 전체 플로우(업로드+생성). 업로드본은 uploaded 리스트에 (name,key)로 등록(삭제추적)."""
    if a.src.startswith("http"):
        part = {"fileData": {"fileUri": a.src}}
        print(f"[gemini] URL 직접 투입 (key {gemini_keys.mask(key)}): {a.src}", file=sys.stderr)
    else:
        if not os.path.exists(a.src):
            sys.exit(f"[오류] 파일 없음: {a.src}")
        print(f"[gemini] File API 업로드 (key {gemini_keys.mask(key)}): {a.src}", file=sys.stderr)
        uri, mime, name = upload_file(a.src, key)
        uploaded.append((name, key))                       # 삭제 대상 등록(성공/실패 무관 청소)
        part = {"fileData": {"fileUri": uri, "mimeType": mime}}
    url = f"{BASE}/v1beta/models/{a.model}:generateContent?key={key}"
    body = {"contents": [{"parts": [part, {"text": a.prompt}]}]}
    return _post_json(url, body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--keep-remote", action="store_true",
                    help="분석 후 Google 업로드본 삭제 안 함(기본은 즉시 삭제)")
    a = ap.parse_args()

    uploaded = []            # 시도한 모든 키의 업로드본 (name, key) — 페일오버 사본까지 청소
    r, last = None, None
    try:
        for key in gemini_keys.rotated(KEYS):
            try:
                r = run_once(a, key, uploaded)
                break
            except urllib.error.HTTPError as e:
                last = f"{e.code} {e.read().decode()[:200]}"
                if e.code in (429, 503, 500):
                    print(f"[gemini] key {gemini_keys.mask(key)} {e.code} → 다음 키로 페일오버", file=sys.stderr)
                    continue
                sys.exit(f"[HTTP {e.code}] {last}")
        if r is None:
            sys.exit(f"[오류] 모든 키 소진/실패 — last: {last}")

        text = r["candidates"][0]["content"]["parts"][0]["text"]
        um = r.get("usageMetadata", {})
        print(json.dumps({"source": a.src, "model": a.model,
                          "analysis": text,
                          "tokens": {"prompt": um.get("promptTokenCount"),
                                     "total": um.get("totalTokenCount")}},
                         ensure_ascii=False, indent=2))
    finally:
        # 프라이버시: 업로드본 즉시 삭제 (분석성공·실패·예외 무관). URL 투입은 uploaded 비어있음.
        if uploaded and not a.keep_remote:
            for name, key in uploaded:
                delete_remote(name, key)
        elif uploaded and a.keep_remote:
            print(f"[gemini] ⚠️ --keep-remote: {len(uploaded)}개 업로드본 Google에 유지(48h 후 자동만료)", file=sys.stderr)


if __name__ == "__main__":
    main()

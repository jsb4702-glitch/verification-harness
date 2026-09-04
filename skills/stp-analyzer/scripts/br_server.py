#!/usr/bin/env python3
"""stp-analyzer 로컬 서버 — WASM brotli 사전압축 서빙 + 네이티브 분석 API.

`python3 -m http.server` 대체:
- `.wasm` 요청에 `.wasm.br`가 있고 클라이언트가 br 지원하면 Content-Encoding: br 전송.
- `/native/*` — 대형 STEP(브라우저 WASM 힙 2GB 초과) 네이티브 OCC 분석 API.
  파일은 localhost 밖으로 안 나감(127.0.0.1 바인딩 — LAN 노출 수리 2026-07-21).

사용: python3 br_server.py [PORT]   (기본 8742, root=$HOME)
"""
import http.server
import json
import os
import sys
import tempfile
import threading

ROOT = os.path.expanduser("~")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8742
# 앱 전용 경로분석 토큰 (argv[2]) — 미지정 시 /native/analyze_path 비활성 (기존 인스턴스 무영향)
APP_TOKEN = sys.argv[2] if len(sys.argv) > 2 else None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_native_lock = threading.Lock()
_native_ses = None          # native_analyze.Session — 마지막 분석 1건 상주(완료본)
_native_uploading = False   # 업로드 중 예약플래그 (락은 짧게, 업로드는 락 밖)


def _start_native_path(tmp: str, unlink: bool = True):
    """디스크의 파일로 분석 스레드 시작. busy 검사는 호출측 락 안에서.
    unlink=True(업로드 임시파일)만 분석 후 삭제 — 경로분석(원본)은 보존."""
    global _native_ses
    import native_analyze
    ses = native_analyze.Session()
    ses.status['stage'] = '파일 수신 완료 · 분석 시작'
    _native_ses = ses

    def run():
        native_analyze.analyze(tmp, ses)
        if unlink:
            try:
                os.unlink(tmp)                 # 분석 후 임시파일 즉시 삭제
            except OSError:
                pass

    threading.Thread(target=run, daemon=True).start()


class BrHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def log_message(self, *a):               # 대형 버퍼 GET 로그 소음 억제
        pass

    def _host_ok(self):
        # DNS rebinding 가드 — 루프백 바인딩이어도 Host가 외부 도메인이면 거부
        raw = (self.headers.get("Host") or "").strip().lower()
        if raw.startswith("["):                       # [::1]:8742 형태 (검수 지적: 파싱 수리)
            h = raw[1:raw.index("]")] if "]" in raw else raw
        else:
            h = raw.split(":")[0]
        return h in ("127.0.0.1", "localhost", "::1")

    # ---- 공통 응답 ----
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass

    def _serve_br(self, br_path):
        try:
            with open(br_path, "rb") as f:
                data = f.read()
        except OSError:
            return False
        self.send_response(200)
        self.send_header("Content-Type", "application/wasm")
        self.send_header("Content-Encoding", "br")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=31536000")
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass
        return True

    # ---- 네이티브 API ----
    MAX_UPLOAD = 4 * 1024 ** 3               # 4GB 상한 (디스크 폭주 가드)
    MAX_JSON = 1048576                       # 측정류 body 1MB 상한

    def do_POST(self):
        try:
            self._do_post()
        except Exception as e:               # malformed 입력이 핸들러 스레드 죽이지 않게 (검수 지적)
            try:
                self._json(dict(error=f'{type(e).__name__}: {e}'), 400)
            except Exception:
                pass

    def _do_post(self):
        if not self._host_ok():
            self._json(dict(error="forbidden host"), 403)
            return
        try:
            n = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            self._json(dict(error='Content-Length 형식 오류'), 400)
            return
        if self.path == "/native/analyze":
            # 락은 busy검사+예약만 — 업로드 스트리밍 동안 락 미보유 (stalled client 점유 방지)
            global _native_uploading
            with _native_lock:
                if _native_uploading or (_native_ses is not None and not _native_ses.status.get('done')):
                    self._json(dict(error='busy — 이전 분석 진행 중(세션 1개 정책), 완료 후 재시도'), 409)
                    return
                if n <= 0:
                    self._json(dict(error='Content-Length 필요(청크 전송 미지원)'), 411)
                    return
                if n > self.MAX_UPLOAD:
                    self._json(dict(error=f'{n}B > 상한 {self.MAX_UPLOAD}B'), 413)
                    return
                _native_uploading = True
            try:
                # 청크 스트리밍 수신 → 임시파일 직행 (전량 RAM 적재 제거)
                fd, tmp = tempfile.mkstemp(suffix='.step', prefix='stp_native_')
                remain = n
                try:
                    with os.fdopen(fd, 'wb') as f:
                        while remain > 0:
                            chunk = self.rfile.read(min(8 * 1048576, remain))
                            if not chunk:
                                break
                            f.write(chunk)
                            remain -= len(chunk)
                except OSError:
                    remain = -1
                if remain != 0:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    self._json(dict(error=f'수신 불완전 (잔여 {remain}B)'), 400)
                    return
                with _native_lock:
                    _start_native_path(tmp)
                self._json(dict(ok=True, size=n, sid=_native_ses.sid))
            finally:
                with _native_lock:
                    _native_uploading = False
            return
        if self.path == "/native/analyze_path":
            # 앱 전용: 로컬 경로 직접분석 (업로드 생략 — 대형파일 더블클릭 경로).
            # 토큰은 앱↔서버 프로세스만 공유(페이지 미노출), 미설정 서버에선 403.
            if not APP_TOKEN or self.headers.get("X-App-Token") != APP_TOKEN:
                self._json(dict(error='forbidden'), 403)
                return
            if n <= 0:
                self._json(dict(error='Content-Length 필요'), 411)
                return
            if n > self.MAX_JSON:
                self._json(dict(error='body 과대'), 413)
                return
            try:
                preq = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                self._json(dict(error='bad json'), 400)
                return
            rp = os.path.realpath(str(preq.get('path') or ''))
            if not (os.path.isfile(rp) and rp.lower().endswith(('.stp', '.step'))):
                self._json(dict(error='유효한 .stp/.step 경로 아님'), 400)
                return
            with _native_lock:
                if _native_uploading or (_native_ses is not None and not _native_ses.status.get('done')):
                    self._json(dict(error='busy — 이전 분석 진행 중(세션 1개 정책), 완료 후 재시도'), 409)
                    return
                _start_native_path(rp, unlink=False)
            self._json(dict(ok=True, size=os.path.getsize(rp), sid=_native_ses.sid))
            return
        if n > self.MAX_JSON:
            self._json(dict(error='body 과대'), 413)
            return
        body = self.rfile.read(n) if n else b"{}"
        try:
            req = json.loads(body or b"{}")
        except json.JSONDecodeError:
            self._json(dict(error="bad json"), 400)
            return
        ses = _native_ses
        ok_ses = ses is not None and ses.status.get('done') and not ses.status.get('error')
        # sid 결박: 클라이언트가 보낸 sid와 현 세션 불일치 = 세션 교체됨 (혼합 방지 — 검수 지적)
        want_sid = req.get('sid')
        if ok_ses and want_sid is not None and want_sid != ses.sid:
            self._json(dict(error=f'세션 교체됨 (요청 sid {want_sid} ≠ 현재 {ses.sid}) — 파일 다시 로드'), 409)
            return
        if self.path == "/native/measure":
            import native_analyze
            if not ok_ses:
                self._json(dict(error="분석 세션 없음"))
                return
            self._json(native_analyze.measure(ses, dict(req["a"]), dict(req["b"])))
        elif self.path == "/native/edgeinfo":
            import native_analyze
            if not ok_ses:
                self._json(dict(error="분석 세션 없음"))
                return
            self._json(native_analyze.edge_info(ses, int(req["id"])))
        else:
            self._json(dict(error="unknown"), 404)

    def do_GET(self):
        if not self._host_ok():
            self._json(dict(error="forbidden host"), 403)
            return
        if self.path == "/native/status":
            ses = _native_ses
            # session 플래그: 서버 재시작 후 클라 폴링이 유한 종료하도록 (검수 지적 수리)
            self._json(dict(**ses.status, session=True) if ses
                       else dict(stage='세션 없음', done=False, error=None, session=False))
            return
        if self.path == "/native/meta":
            ses = _native_ses
            if ses is None or ses.meta is None:
                self._json(dict(error="no meta"), 404)
                return
            self._json(ses.meta)
            return
        if self.path.startswith("/native/buf/"):
            ses = _native_ses
            tail = self.path.rsplit("/", 1)[1]
            name, _, q = tail.partition("?")
            if ses is None or name not in ses.bufs:
                self._json(dict(error="no buf"), 404)
                return
            # ?sid=N 결박 — 세션 교체 후 스테일 버퍼 수신 차단 (검수 지적 수리)
            if q.startswith("sid="):
                try:
                    if int(q[4:]) != ses.sid:
                        self._json(dict(error="세션 교체됨"), 409)
                        return
                except ValueError:
                    self._json(dict(error="sid 형식"), 400)
                    return
            self._bytes(ses.bufs[name])
            return
        # 루트 → 앱 진입점 리라이트 (검수 3R: '/' 404 회귀 수리)
        if self.path in ("/", ""):
            self.path = "/stp-analyzer.html"
        # 정적 서빙 허용목록 — translate_path 후 실경로로 판정 (검수 3R: ../ 우회로 $HOME 시크릿 노출 수리).
        # base 문자열 매칭은 /stp-assets/../.zshrc 를 통과시켰음 → 정규화 실경로가 허용트리 안인지 검사.
        dev = os.environ.get("STP_DEV") == "1"      # '0'도 truthy이던 것 수리 — 정확히 "1"만
        path = self.translate_path(self.path)
        rp = os.path.realpath(path)
        allow_roots = [os.path.realpath(os.path.join(ROOT, x))
                       for x in ("stp-analyzer.html", "stp-worker.js", "favicon.ico", "stp-assets")]
        allowed = any(rp == r or rp.startswith(r + os.sep) for r in allow_roots)
        if not allowed and not dev:
            self._json(dict(error="not served (allowlist)"), 404)
            return
        accept = self.headers.get("Accept-Encoding", "")
        if path.endswith(".wasm") and "br" in accept:
            br_path = path + ".br"
            if os.path.exists(br_path) and self._serve_br(br_path):
                return
        super().do_GET()

    def guess_type(self, path):
        if str(path).endswith(".wasm"):
            return "application/wasm"
        return super().guess_type(path)


if __name__ == "__main__":
    # ThreadingHTTPServer: 네이티브 분석(수분) 중에도 정적 서빙·status 폴링 응답
    # 127.0.0.1 바인딩: $HOME 서빙 서버의 LAN 노출 차단 (기존 전인터페이스 바인딩 수리)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), BrHandler)
    httpd.daemon_threads = True
    print(f"stp-analyzer br-server on 127.0.0.1:{PORT} (root={ROOT}, native API on)", flush=True)
    httpd.serve_forever()

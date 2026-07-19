#!/usr/bin/env python3
"""stp-analyzer 로컬 서버 — WASM brotli 사전압축 서빙.

`python3 -m http.server` 대체. `.wasm` 요청에 대해 같은 이름의 `.wasm.br`가 있고
클라이언트가 Accept-Encoding: br 지원하면 Content-Encoding: br 로 전송한다.
브라우저(fetch/instantiateStreaming)는 네트워크 레이어에서 투명 해제 → glue 코드 무수정.
없으면 원본 그대로 폴백(비파괴).

사용: python3 br_server.py [PORT]   (기본 8742, root=$HOME)
"""
import http.server
import os
import socketserver
import sys

ROOT = os.path.expanduser("~")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8742


class BrHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

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

    def do_GET(self):
        path = self.translate_path(self.path)
        accept = self.headers.get("Accept-Encoding", "")
        if path.endswith(".wasm") and "br" in accept:
            br_path = path + ".br"
            if os.path.exists(br_path) and self._serve_br(br_path):
                return
        super().do_GET()

    def guess_type(self, path):
        # http.server 구버전은 .wasm mime 미보장 → instantiateStreaming 위해 강제
        if str(path).endswith(".wasm"):
            return "application/wasm"
        return super().guess_type(path)


if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), BrHandler) as httpd:
        print(f"stp-analyzer br-server on :{PORT} (root={ROOT})", flush=True)
        httpd.serve_forever()

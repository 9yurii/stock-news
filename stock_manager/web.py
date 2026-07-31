"""docs/ 폴더를 로컬에서 미리 보기 위한 작은 정적 서버.

GitHub Pages에 올리기 전에 확인하는 용도입니다.
(ES 모듈은 file:// 로 열면 브라우저가 막기 때문에 http:// 로 띄워야 합니다.)

    python -m stock_manager.web
"""

from __future__ import annotations

import sys
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
HOST = "127.0.0.1"
PORT = 8765


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def end_headers(self):
        # 수정한 파일이 바로 반영되도록 캐시를 끕니다
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def serve(host: str = HOST, port: int = PORT, open_browser: bool = True) -> None:
    if not DOCS.exists():
        print(f"docs 폴더를 찾을 수 없습니다: {DOCS}", file=sys.stderr)
        raise SystemExit(1)

    handler = partial(Handler, directory=str(DOCS))
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
    print(f"미리보기: {url}")
    print("종료하려면 Ctrl+C 를 누르세요.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    args = sys.argv[1:]
    port = int(args[0]) if args and args[0].isdigit() else PORT
    serve(port=port, open_browser="--no-browser" not in args)

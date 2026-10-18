# Spec: docs/specs/ui.md
"""Local web server for running an experiment. Serves ui/static/, answers the JSON API, and
streams events. Reads the files named in the spec; writes only config/experiments/<id>.toml.
Run as `python -m ui.server [--port 8765] [--root .]`.
"""

import argparse
import hmac
import json
import queue
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ui.app import App
from ui.common import ApiError

MAX_BODY = 64 * 1024
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/static/style.css": ("style.css", "text/css; charset=utf-8")}


class Handler(BaseHTTPRequestHandler):
    server: "UiServer"

    def log_message(self, *args) -> None:
        pass

    def send_bytes(self, status: int, body: bytes, kind: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, data: dict) -> None:
        self.send_bytes(status, json.dumps(data).encode("utf-8"), "application/json")

    def host_ok(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def do_GET(self) -> None:
        self.handle_request("GET")

    def do_POST(self) -> None:
        self.handle_request("POST")

    def handle_request(self, method: str) -> None:
        app = self.server.app
        path = self.path.split("?", 1)[0]
        try:
            if not self.host_ok():
                raise ApiError(403, "bad Host header")
            if method == "POST" or path.startswith("/api/commit/"):
                if not hmac.compare_digest(self.headers.get("X-Token", "").encode(), app.token.encode()):
                    raise ApiError(403, "missing or wrong X-Token")
            if method == "POST":
                self.send_json(200, app.post(path, self.read_body()))
            elif path == "/api/events":
                self.stream_events()
            elif path in STATIC:
                self.send_static(path)
            elif path.startswith("/api/"):
                self.send_json(200, app.get(path))
            else:
                raise ApiError(404, "not found")
        except ApiError as error:
            self.send_json(error.status, {"error": error.message})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:  # a bug or a bad file: report it, keep serving
            self.send_json(500, {"error": f"{type(error).__name__}: {error}"})

    def read_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "bad Content-Length") from None
        if length < 0 or length > MAX_BODY:
            raise ApiError(400, "body is negative or larger than 64 KiB")
        try:
            body = json.loads(self.rfile.read(length) or b"null")
        except ValueError:
            raise ApiError(400, "body is not valid JSON") from None
        if not isinstance(body, dict):
            raise ApiError(400, "body must be a JSON object")
        return body

    def send_static(self, path: str) -> None:
        app = self.server.app
        name, kind = STATIC[path]
        file = app.static_dir / name
        if not file.is_file():
            raise ApiError(404, "not found")
        data = file.read_bytes()
        if name == "index.html":
            data = data.replace(b"{{UI_TOKEN}}", app.token.encode("ascii"))
        self.send_bytes(200, data, kind)

    def stream_events(self) -> None:
        hub = self.server.app.hub
        client = hub.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    event, data = client.get(timeout=self.server.keepalive_s)
                    message = f"event: {event}\ndata: {json.dumps(data)}\n\n"
                except queue.Empty:
                    message = ": keep-alive\n\n"
                self.wfile.write(message.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            hub.unsubscribe(client)


class UiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    keepalive_s = 15

    def __init__(self, address: tuple, app: App) -> None:
        super().__init__(address, Handler)
        self.app = app


def make_server(root: Path, port: int = 0, static_dir: Path | None = None) -> UiServer:
    """Build the server on 127.0.0.1. Tests pass port 0 and their own static folder."""
    static = static_dir or Path(__file__).resolve().parent / "static"
    return UiServer(("127.0.0.1", port), App(Path(root).resolve(), static))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the experiment UI on 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    if not (args.root / "releases").is_dir():
        print(f"error: {args.root / 'releases'}: folder not found", file=sys.stderr)
        return 1
    try:
        server = make_server(args.root, args.port)
    except OSError as error:
        print(f"error: port {args.port}: {error.strerror}", file=sys.stderr)
        return 1
    print(f"UI at http://127.0.0.1:{server.server_address[1]}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

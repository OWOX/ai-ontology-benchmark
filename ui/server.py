# Spec: docs/specs/ui.md
"""Web server for running an experiment, for this machine and the home network. Serves ui/static/ and answers the
JSON API, including the terminal log the page polls. With --lan (the default) it binds 0.0.0.0 and answers every client and Host; with --no-lan it binds 127.0.0.1 and answers only loopback.
Reads the files named in the spec; writes only config/experiments/<id>.toml.
Run as `python -m ui.server [--port 8765] [--root .] [--lan | --no-lan]`.
"""

import argparse
import hmac
import ipaddress
import json
import signal
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ui.app import App
from ui.common import ApiError

MAX_BODY = 64 * 1024
BIND_HOST = "0.0.0.0"
LOOPBACK = ipaddress.ip_network("127.0.0.0/8")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/static/cube.js": ("cube.js", "text/javascript; charset=utf-8"),
          "/static/style.css": ("style.css", "text/css; charset=utf-8")}


def is_loopback(text: str) -> bool:
    """True when text is an IPv4 address in 127.0.0.0/8. An IPv4-mapped IPv6 address counts as its IPv4 form."""
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return isinstance(ip, ipaddress.IPv4Address) and ip in LOOPBACK


def lan_address() -> str | None:  # only called with --lan
    """This machine's primary outgoing IPv4 address, whatever its range. None when it is loopback or unknown."""
    try:  # a UDP connect sends nothing; it only makes the OS pick the outgoing address
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 9))
            address = probe.getsockname()[0]
    except OSError:
        return None
    return None if address.startswith("127.") else address


class Handler(BaseHTTPRequestHandler):
    server: "UiServer"
    timeout = 30  # a silent client can't hold a thread

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
        """With --no-lan, Host must be localhost or a literal 127.x.x.x address, with this server's port. Otherwise any Host."""
        if not self.server.loopback_only:
            return True
        host, _, port = (self.headers.get("Host") or "").rpartition(":")
        if port != str(self.server.server_address[1]):
            return False
        return host == "localhost" or ("." in host and ":" not in host and is_loopback(host))

    def do_GET(self) -> None:
        self.handle_request("GET")

    def do_POST(self) -> None:
        self.handle_request("POST")

    def handle_request(self, method: str) -> None:
        app = self.server.app
        url = urlsplit(self.path)
        path = url.path
        try:
            if self.server.loopback_only and not is_loopback(self.client_address[0]):
                raise ApiError(403, "client address not allowed")
            if not self.host_ok():
                raise ApiError(403, "bad Host header")
            guarded = path.strip("/").split("/")[:2] in (["api", "commit"], ["api", "secrets"])  # as app.get routes
            if method == "POST" or guarded:
                if not hmac.compare_digest(self.headers.get("X-Token", "").encode(), app.token.encode()):
                    raise ApiError(403, "missing or wrong X-Token")
            if method == "POST":
                self.send_json(200, app.post(path, self.read_body()))
            elif path in STATIC:
                self.send_static(path)
            elif path.startswith("/api/"):
                self.send_json(200, app.get(path, parse_qs(url.query)))
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


class UiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True  # restart at once after Ctrl-C; main probes the port first (see port_answers)

    def __init__(self, address: tuple, app: App, lan: bool = True) -> None:
        super().__init__(address, Handler)
        self.app = app
        self.loopback_only = not lan  # --no-lan: peer and Host checks. With --lan nothing is checked.

    def verify_request(self, request, client_address) -> bool:
        """With --no-lan, drop a peer outside 127.0.0.0/8 before its request is parsed. Otherwise accept every peer."""
        return not self.loopback_only or is_loopback(client_address[0])

    def handle_error(self, request, client_address) -> None:
        """A browser that resets or drops its connection is routine: say nothing."""
        if not isinstance(sys.exc_info()[1], OSError):
            super().handle_error(request, client_address)


def port_answers(port: int) -> bool:
    """True when something already accepts connections on 127.0.0.1:<port>."""
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        return True
    except OSError:
        return False


def make_server(root: Path, port: int = 0, static_dir: Path | None = None, host: str = "127.0.0.1",
                lan: bool = True) -> UiServer:
    """Build the server. `main` passes BIND_HOST, or 127.0.0.1 with --no-lan; tests keep loopback, port 0, and their own static folder."""
    static = static_dir or Path(__file__).resolve().parent / "static"
    return UiServer((host, port), App(Path(root).resolve(), static), lan)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the experiment UI. With --lan (the default) it binds 0.0.0.0 and serves "
                                     "every client; with --no-lan, only this machine.")
    parser.add_argument("--lan", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    if not (args.root / "releases").is_dir():
        print(f"error: {args.root / 'releases'}: folder not found", file=sys.stderr)
        return 1
    if port_answers(args.port):  # SO_REUSEADDR lets 0.0.0.0 and 127.0.0.1 share a port on macOS
        print(f"error: port {args.port}: another server is listening", file=sys.stderr)
        return 1
    try:
        server = make_server(args.root, args.port, host=BIND_HOST if args.lan else "127.0.0.1", lan=args.lan)
    except OSError as error:
        print(f"error: port {args.port}: {error.strerror}", file=sys.stderr)
        return 1
    port = server.server_address[1]
    print(f"UI at http://127.0.0.1:{port}/", flush=True)
    if args.lan:
        if address := lan_address():
            print(f"UI at http://{address}:{port}/", flush=True)
        print("Open to every client: anyone who can reach this port can run experiments on your API keys "
              "(use --no-lan for this machine only)", flush=True)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.app.jobs.stop_all()  # no run outlives the server
    return 0


if __name__ == "__main__":
    sys.exit(main())

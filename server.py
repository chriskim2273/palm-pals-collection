"""Palm Pals Collection sync backend (stdlib only).

Serves the static gallery plus a PIN-gated JSON sync API backed by a
single file on a persistent volume (Coolify storage mounted at /data).

Env:
  PORT            listen port (default 8000)
  DATA_DIR        volume dir (default /data)
  PALM_PIN_HASH   sha256 hex of the owner PIN; API stays locked without it

API:
  POST /api/unlock  {"pin": "123456"} -> {"token": ..., "expires": ...}
  GET  /api/state   (Bearer token) -> collection JSON
  PUT  /api/state   (Bearer token) -> {"ok": true, "updatedAt": ...}
  GET  /api/health  -> {"ok": true}
"""

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

SCHEMA = "palm-pals-my-collection-v1"
MAX_BODY = 45_000_000
TOKEN_TTL = 30 * 24 * 3600
MAX_TOKENS = 20
MAX_PIN_FAILS = 8
BLOCK_SECONDS = 300

PORT = int(os.environ.get("PORT", "8000"))
DATA_DIR = os.environ.get("DATA_DIR", "/data")
PIN_HASH = os.environ.get("PALM_PIN_HASH", "").strip().lower()
DOCROOT = os.path.dirname(os.path.abspath(__file__))

STATE_FILE = os.path.join(DATA_DIR, "collection.json")
BAK_FILE = os.path.join(DATA_DIR, "collection.json.bak")
TOKENS_FILE = os.path.join(DATA_DIR, "tokens.json")

os.makedirs(DATA_DIR, exist_ok=True)

_lock = threading.Lock()
_pin_fails = {}  # ip -> {"fails": int, "blocked_until": float}


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_json_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def empty_state():
    return {"schema": SCHEMA, "updatedAt": 0, "items": []}


def valid_state(obj):
    return (
        isinstance(obj, dict)
        and obj.get("schema") == SCHEMA
        and isinstance(obj.get("items"), list)
        and len(obj["items"]) <= 5000
    )


def get_tokens():
    with _lock:
        toks = _load_json(TOKENS_FILE, {})
    now = time.time()
    toks = {t: e for t, e in toks.items() if isinstance(e, (int, float)) and e > now}
    return toks


def put_tokens(toks):
    with _lock:
        _save_json_atomic(TOKENS_FILE, toks)


def check_pin(pin):
    if not PIN_HASH or not isinstance(pin, str) or not pin:
        return False
    digest = hashlib.sha256(pin.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, PIN_HASH)


def client_ip(handler):
    fwd = handler.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else handler.client_address[0])


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PalmSync/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def _authed(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        return auth[7:].strip() in get_tokens()

    # -- routes ---------------------------------------------------------
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/health":
            return self._json(200, {"ok": True})
        if path == "/api/state":
            if not self._authed():
                return self._json(401, {"error": "unauthorized"})
            state = _load_json(STATE_FILE, None)
            if not valid_state(state):
                state = empty_state()
            return self._json(200, state)
        return self._serve_static(path)

    def do_POST(self):
        if urlsplit(self.path).path != "/api/unlock":
            return self._json(404, {"error": "not found"})
        ip = client_ip(self)
        now = time.time()
        rec = _pin_fails.get(ip, {"fails": 0, "blocked_until": 0})
        if rec["blocked_until"] > now:
            return self._json(429, {"error": "Too many wrong attempts. Try again later."})
        body = self._read_json() or {}
        if check_pin(body.get("pin")):
            _pin_fails.pop(ip, None)
            toks = get_tokens()
            token = secrets.token_urlsafe(32)
            toks[token] = now + TOKEN_TTL
            while len(toks) > MAX_TOKENS:
                toks.pop(next(iter(toks)))
            put_tokens(toks)
            return self._json(200, {"token": token, "expires": int(now + TOKEN_TTL)})
        fails = rec["fails"] + 1
        _pin_fails[ip] = {
            "fails": fails,
            "blocked_until": now + BLOCK_SECONDS if fails >= MAX_PIN_FAILS else 0,
        }
        return self._json(401, {"error": "Wrong PIN."})

    def do_PUT(self):
        if urlsplit(self.path).path != "/api/state":
            return self._json(404, {"error": "not found"})
        if not self._authed():
            return self._json(401, {"error": "unauthorized"})
        body = self._read_json()
        if not valid_state(body):
            return self._json(400, {"error": "invalid state"})
        try:
            body["updatedAt"] = int(body.get("updatedAt") or 0)
        except (TypeError, ValueError):
            body["updatedAt"] = 0
        prev = _load_json(STATE_FILE, None)
        if valid_state(prev):
            try:
                _save_json_atomic(BAK_FILE, prev)
            except OSError:
                pass
        try:
            _save_json_atomic(STATE_FILE, body)
        except OSError:
            return self._json(500, {"error": "could not save"})
        return self._json(200, {"ok": True, "updatedAt": body["updatedAt"]})

    # -- static ---------------------------------------------------------
    STATIC = {
        "/": ("index.html", "text/html; charset=utf-8", "no-store"),
        "/index.html": ("index.html", "text/html; charset=utf-8", "no-store"),
        "/sync.js": ("sync.js", "application/javascript; charset=utf-8", "public, max-age=300"),
    }

    def _serve_static(self, path):
        entry = self.STATIC.get(path)
        if not entry:
            return self._json(404, {"error": "not found"})
        fpath = os.path.join(DOCROOT, entry[0])
        try:
            with open(fpath, "rb") as f:
                data = f.read()
        except OSError:
            return self._json(404, {"error": "not found"})
        self.send_response(200)
        self.send_header("Content-Type", entry[1])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", entry[2])
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    if not PIN_HASH:
        print("WARNING: PALM_PIN_HASH not set; unlock API will reject everything.")
    print(f"PalmSync on :{PORT}, data dir {DATA_DIR}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

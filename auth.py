"""Local demo accounts and server-side sessions. Not an internet identity service."""
from __future__ import annotations

import getpass
import hashlib
import hmac
import json
import secrets
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path

ROOT = Path(__file__).parent
ACCOUNTS = ROOT / "runtime" / "accounts.json"
SESSIONS: dict[str, tuple[str, float]] = {}
FAILURES: dict[tuple[str, str], list[float]] = {}
LOCK = threading.Lock()
SESSION_SECONDS = 8 * 60 * 60
LOGIN_WINDOW_SECONDS = 15 * 60
MAX_LOGIN_FAILURES = 5


class LoginRateLimited(Exception):
    """Too many failed sign-in attempts for this account and client."""


def _digest(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1).hex()


def initialize_accounts() -> None:
    if ACCOUNTS.exists():
        raise FileExistsError("Accounts already exist. This command never replaces them.")
    accounts = {}
    for role in ("user", "admin"):
        while True:
            password = getpass.getpass(f"Choose {role} password (at least 12 characters): ")
            confirmation = getpass.getpass("Repeat password: ")
            if len(password) >= 12 and password == confirmation:
                break
            print("Passwords must match and contain at least 12 characters.")
        salt = secrets.token_bytes(16)
        accounts[role] = {"salt": salt.hex(), "hash": _digest(password, salt)}
    ACCOUNTS.parent.mkdir(parents=True, exist_ok=True)
    ACCOUNTS.write_text(json.dumps(accounts, indent=2), encoding="utf-8")
    print("Accounts created. Start the app with: python app.py")


def login(username: str, password: str, client: str = "local") -> str | None:
    key = (username if username in {"user", "admin"} else "<unknown>", client)
    now = time.monotonic()
    with LOCK:
        recent = [attempt for attempt in FAILURES.get(key, [])
                  if now - attempt < LOGIN_WINDOW_SECONDS]
        if recent:
            FAILURES[key] = recent
        else:
            FAILURES.pop(key, None)
        if len(recent) >= MAX_LOGIN_FAILURES:
            raise LoginRateLimited("Too many login attempts. Try again in 15 minutes.")
    if not ACCOUNTS.exists():
        return None
    accounts = json.loads(ACCOUNTS.read_text(encoding="utf-8"))
    record = accounts.get(username)
    valid = False
    if record and isinstance(password, str):
        actual = _digest(password, bytes.fromhex(record["salt"]))
        valid = hmac.compare_digest(actual, record["hash"])
    if not valid:
        with LOCK:
            FAILURES.setdefault(key, []).append(time.monotonic())
        return None
    token = secrets.token_urlsafe(32)
    with LOCK:
        FAILURES.pop(key, None)
        SESSIONS[token] = (username, time.time() + SESSION_SECONDS)
    return token


def session_role(cookie_header: str) -> str | None:
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:
        return None
    token = cookie.get("railway_session")
    if not token:
        return None
    with LOCK:
        session = SESSIONS.get(token.value)
        if not session:
            return None
        if session[1] <= time.time():
            SESSIONS.pop(token.value, None)
            return None
        return session[0]


def logout(cookie_header: str) -> None:
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:
        return
    token = cookie.get("railway_session")
    if token:
        with LOCK:
            SESSIONS.pop(token.value, None)

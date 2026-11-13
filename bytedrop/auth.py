"""Session access token management and per-IP failed authentication rate limiting."""
from __future__ import annotations

import logging
import secrets
import threading
import time

from fastapi import HTTPException

logger = logging.getLogger("bytedrop.auth")


class ByteDropHttpError(HTTPException):
    """Structured HTTP exception with machine-readable code."""

    def __init__(self, status_code: int, detail: str, code: str) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


class RateLimiter:
    """Per-IP failed authentication rate limiter (10 failures in 60s -> 5 min lockout)."""

    def __init__(self, max_failures: int = 10, window_sec: float = 60.0, lockout_sec: float = 300.0) -> None:
        self.max_failures = max_failures
        self.window_sec = window_sec
        self.lockout_sec = lockout_sec
        self.failures: dict[str, list[float]] = {}
        self.locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_blocked(self, ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            until = self.locked_until.get(ip, 0.0)
            if now < until:
                return True
            if until > 0.0:
                self.locked_until.pop(ip, None)
            return False

    def _prune_expired(self, now: float) -> None:
        """Removes expired lockout entries to prevent unbounded memory growth."""
        expired = [ip for ip, until in self.locked_until.items() if now >= until]
        for ip in expired:
            self.locked_until.pop(ip, None)

    def record_failure(self, ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._prune_expired(now)
            recent = [t for t in self.failures.get(ip, []) if now - t <= self.window_sec]
            recent.append(now)
            self.failures[ip] = recent
            if len(recent) >= self.max_failures:
                self.locked_until[ip] = now + self.lockout_sec
                self.failures.pop(ip, None)
                return True
            return False

    def record_success(self, ip: str) -> None:
        with self._lock:
            self.failures.pop(ip, None)

    def clear(self) -> None:
        with self._lock:
            self.failures.clear()
            self.locked_until.clear()


class AuthManager:
    """128-bit random session token validator and rotator."""

    def __init__(self) -> None:
        # 16 random bytes = 128 bits of entropy
        self.token: str = secrets.token_urlsafe(16)
        self.rate_limiter = RateLimiter()
        self._lock = threading.RLock()

    def get_token(self) -> str:
        with self._lock:
            return self.token

    def regenerate(self) -> str:
        """Rotates the 128-bit session token and resets the rate limiter."""
        with self._lock:
            self.token = secrets.token_urlsafe(16)
            self.rate_limiter.clear()
            return self.token

    def verify(self, candidate: str | None, client_ip: str = "127.0.0.1") -> None:
        """Verifies candidate token in constant time; raises ByteDropHttpError(403/429) on failure."""
        if self.rate_limiter.is_blocked(client_ip):
            raise ByteDropHttpError(
                429,
                "Too many failed authentication attempts. Locked for 5 minutes.",
                "RATE_LIMITED",
            )
        current = self.get_token()
        if not isinstance(candidate, str) or not candidate or not secrets.compare_digest(
            candidate.encode("utf-8"), current.encode("utf-8")
        ):
            locked = self.rate_limiter.record_failure(client_ip)
            if locked:
                logger.warning("IP %s locked out after repeated failed token attempts", client_ip)
                raise ByteDropHttpError(
                    429,
                    "Too many failed authentication attempts. Locked for 5 minutes.",
                    "RATE_LIMITED",
                )
            raise ByteDropHttpError(403, "Unauthorized session token", "UNAUTHORIZED")
        self.rate_limiter.record_success(client_ip)

    def build_authenticated_url(self, base_origin: str) -> str:
        """Builds a URL with #token=<session_token> in the fragment so it is never sent
        to the server in HTTP requests and never recorded in access logs."""
        clean_origin = base_origin.split("?")[0].split("#")[0].rstrip("/")
        return f"{clean_origin}/#{self.get_token()}"

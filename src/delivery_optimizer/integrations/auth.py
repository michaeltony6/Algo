from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def json_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")


def hs256_jwt(header: dict[str, Any], payload: dict[str, Any], secret: str) -> str:
    encoded_header = base64url(json_bytes(header))
    encoded_payload = base64url(json_bytes(payload))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{base64url(signature)}"


def now_epoch() -> int:
    return int(time.time())

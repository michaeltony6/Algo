from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import ApiIntegrationError, ApiRequest, ClientSettings


@dataclass(frozen=True)
class ApiResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict:
        if not self.body:
            return {}
        return json.loads(self.body.decode("utf-8"))


class UrlLibHttpClient:
    def __init__(self, settings: ClientSettings | None = None) -> None:
        self.settings = settings or ClientSettings()

    def send(self, request: ApiRequest, timeout: float | None = None) -> ApiResponse:
        timeout = timeout or self.settings.timeout_seconds
        attempt = 0
        while True:
            try:
                return self._send_once(request, timeout)
            except ApiIntegrationError as error:
                attempt += 1
                if attempt > self.settings.max_retries or not self._is_retryable(error):
                    raise
                time.sleep(self.settings.backoff_seconds * attempt)

    def _send_once(self, request: ApiRequest, timeout: float) -> ApiResponse:
        urllib_request = Request(
            request.url,
            data=request.body if request.body else None,
            headers=request.headers,
            method=request.method.upper(),
        )
        try:
            with urlopen(urllib_request, timeout=timeout) as response:
                return ApiResponse(
                    status_code=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except HTTPError as error:
            body = error.read()
            raise ApiIntegrationError(
                f"API request failed with HTTP {error.code}: {body.decode('utf-8', 'ignore')}",
                status_code=error.code,
            ) from error
        except URLError as error:
            raise ApiIntegrationError(f"API request failed: {error.reason}") from error

    def _is_retryable(self, error: ApiIntegrationError) -> bool:
        if error.status_code is None:
            return True
        return error.status_code in self.settings.retry_status_codes

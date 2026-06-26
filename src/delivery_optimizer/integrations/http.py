from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import ApiIntegrationError, ApiRequest


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
    def send(self, request: ApiRequest, timeout: float = 20.0) -> ApiResponse:
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
                f"API request failed with HTTP {error.code}: {body.decode('utf-8', 'ignore')}"
            ) from error
        except URLError as error:
            raise ApiIntegrationError(f"API request failed: {error.reason}") from error

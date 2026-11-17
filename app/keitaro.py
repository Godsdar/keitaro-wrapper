"""Тонкий клиент Keitaro Admin API v1 (документация: /admin_api/v1, заголовок Api-Key)."""

from typing import Any

import httpx

from app.config import get_settings


class KeitaroError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class KeitaroClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0, transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise KeitaroError("KEITARO_API_KEY не задан — добавьте ключ в .env")
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/admin_api/v1",
            headers={"Api-Key": api_key, "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise KeitaroError(f"Keitaro недоступен: {exc}") from exc
        if response.status_code >= 400:
            raise KeitaroError(_error_text(response), response.status_code)
        if not response.content:
            return None
        return response.json()

    # --- справочники ---
    def domains(self) -> list[dict]:
        return self._request("GET", "/domains")

    def campaign_groups(self) -> list[dict]:
        return self._request("GET", "/groups", params={"type": "campaigns"})

    def traffic_sources(self) -> list[dict]:
        return self._request("GET", "/traffic_sources")

    def offers(self) -> list[dict]:
        return self._request("GET", "/offers")

    # --- кампании ---
    def campaigns(self) -> list[dict]:
        return self._request("GET", "/campaigns")

    def campaign(self, campaign_id: int) -> dict:
        return self._request("GET", f"/campaigns/{campaign_id}")

    def create_campaign(self, payload: dict) -> dict:
        return self._request("POST", "/campaigns", json=payload)

    def archive_campaign(self, campaign_id: int) -> None:
        self._request("DELETE", f"/campaigns/{campaign_id}")

    # --- потоки ---
    def campaign_streams(self, campaign_id: int) -> list[dict]:
        return self._request("GET", f"/campaigns/{campaign_id}/streams")

    def create_stream(self, payload: dict) -> dict:
        return self._request("POST", "/streams", json=payload)

    def update_stream(self, stream_id: int, payload: dict) -> dict:
        return self._request("PUT", f"/streams/{stream_id}", json=payload)

    # --- статистика ---
    def report(self, payload: dict) -> dict:
        return self._request("POST", "/report/build", json=payload)


def _error_text(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return f"Keitaro HTTP {response.status_code}: {response.text[:300]}"
    if isinstance(data, dict):
        message = data.get("error") or data.get("message") or data
        return f"Keitaro HTTP {response.status_code}: {message}"
    return f"Keitaro HTTP {response.status_code}: {data}"


def get_keitaro():
    """FastAPI-зависимость: клиент на время одного запроса."""
    settings = get_settings()
    client = KeitaroClient(settings.keitaro_url, settings.keitaro_api_key, settings.keitaro_timeout)
    try:
        yield client
    finally:
        client.close()

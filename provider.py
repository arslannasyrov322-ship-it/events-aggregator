import asyncio
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from config import get_settings

_http: httpx.AsyncClient | None = None


async def init_http() -> None:
    global _http
    _http = httpx.AsyncClient(timeout=60.0, follow_redirects=True)


async def close_http() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


def get_http() -> httpx.AsyncClient:
    if _http is None:
        raise RuntimeError("HTTP-клиент ещё не создан")
    return _http


def rewrite_next(next_url, base):
    if not next_url:
        return None
    if next_url.startswith("/"):
        return urljoin(base.rstrip("/") + "/", next_url.lstrip("/"))
    parts = urlsplit(next_url)
    base_parts = urlsplit(base)
    return urlunsplit(
        (base_parts.scheme, base_parts.netloc, parts.path, parts.query, "")
    )


class EventsProviderClient:
    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        configured = base_url or get_settings().provider_base_url
        self.base_url = configured.rstrip("/")
        self._http = http

    def _headers(self) -> dict:
        return {"x-api-key": self.api_key}

    def _client(self) -> httpx.AsyncClient:
        if self._http is not None:
            return self._http
        return get_http()

    async def get_page(self, url, params=None):
        return await self._client().get(
            url,
            params=params,
            headers=self._headers(),
        )

    async def seats(self, event_id: str):
        url = urljoin(self.base_url + "/", f"api/events/{event_id}/seats/")
        return await self._client().get(url, headers=self._headers())

    async def register(self, event_id, first_name, last_name, email, seat):
        url = urljoin(self.base_url + "/", f"api/events/{event_id}/register/")
        return await self._client().post(
            url,
            headers=self._headers(),
            json={
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "seat": seat,
            },
        )

    async def unregister(self, event_id, ticket_id):
        url = urljoin(self.base_url + "/", f"api/events/{event_id}/unregister/")
        return await self._client().request(
            "DELETE",
            url,
            headers=self._headers(),
            json={"ticket_id": ticket_id},
        )


class EventsPaginator:
    def __init__(self, client, changed_at, base_url=None):
        self.client = client
        configured = base_url if isinstance(base_url, str) else None
        client_base = getattr(client, "base_url", None)
        if configured is None and isinstance(client_base, str):
            configured = client_base
        if configured is None:
            configured = get_settings().provider_base_url
        self.base = configured.rstrip("/")
        self.url = urljoin(self.base + "/", "api/events/")
        self.params = {"changed_at": changed_at}

    async def _load(self, url, params):
        failure = "нет ответа"
        response = None
        for attempt in range(2):
            try:
                response = await self.client.get_page(url, params)
            except httpx.HTTPError as error:
                response = None
                failure = str(error)
            if (
                response is not None
                and response.status_code == 200
                and response.text.strip()
            ):
                return response
            if response is not None:
                failure = f"{response.status_code} {response.text[:80]}"
            if attempt == 0:
                await asyncio.sleep(1)
        raise ValueError(f"чужой сервис {failure}")

    async def __aiter__(self):
        url = self.url
        params = self.params
        while url is not None:
            response = await self._load(url, params)
            data = response.json()
            for event in data["results"]:
                yield event
            url = rewrite_next(data.get("next"), self.base)
            params = None

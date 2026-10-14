import time
from urllib.parse import urlsplit, urlunsplit

import requests

from config import get_settings

session = requests.Session()
session.trust_env = False


def rewrite_next(next_url, base):
    if not next_url:
        return None
    if next_url.startswith("/"):
        return base.rstrip("/") + next_url
    parts = urlsplit(next_url)
    base_parts = urlsplit(base)
    return urlunsplit(
        (base_parts.scheme, base_parts.netloc, parts.path, parts.query, "")
    )


class EventsProviderClient:
    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self.api_key = api_key
        configured = base_url or get_settings().provider_base_url
        self.base_url = configured.rstrip("/")

    def _headers(self) -> dict:
        return {"x-api-key": self.api_key}

    def get_page(self, url, params=None):
        return session.get(
            url,
            params=params,
            headers=self._headers(),
            timeout=60,
        )

    def seats(self, event_id: str):
        url = f"{self.base_url}/api/events/{event_id}/seats/"
        return session.get(url, headers=self._headers(), timeout=60)

    def register(self, event_id, first_name, last_name, email, seat):
        url = f"{self.base_url}/api/events/{event_id}/register/"
        return session.post(
            url,
            headers=self._headers(),
            timeout=60,
            json={
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "seat": seat,
            },
        )

    def unregister(self, event_id, ticket_id):
        url = f"{self.base_url}/api/events/{event_id}/unregister/"
        return session.delete(
            url,
            headers=self._headers(),
            timeout=60,
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
        self.url = self.base + "/api/events/"
        self.params = {"changed_at": changed_at}

    def _load(self, url, params):
        failure = "нет ответа"
        response = None
        for attempt in range(2):
            try:
                response = self.client.get_page(url, params)
            except requests.RequestException as error:
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
                time.sleep(1)
        raise ValueError(f"чужой сервис {failure}")

    def __iter__(self):
        url = self.url
        params = self.params
        while url is not None:
            response = self._load(url, params)
            data = response.json()
            yield from data["results"]
            url = rewrite_next(data.get("next"), self.base)
            params = None

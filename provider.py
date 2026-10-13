import os
import time
from urllib.parse import urlsplit, urlunsplit

import requests

PUBLIC_HOST = "events-provider.dev-2.python-labs.ru"
current_base = f"https://{PUBLIC_HOST}"
current_host = None


def provider_place():
    if current_host:
        return current_base + " host=" + current_host
    return current_base


def provider_url(path):
    return current_base.rstrip("/") + path


def provider_headers(api_key):
    headers = {"x-api-key": api_key}
    if current_host:
        headers["Host"] = current_host
    return headers


def remember_provider(base, host):
    global current_base, current_host
    current_base = base.rstrip("/")
    current_host = host


def candidate_places():
    places = []
    seen = set()

    def add(base, host):
        item = (base.rstrip("/"), host)
        if item not in seen:
            seen.add(item)
            places.append(item)

    for name, value in os.environ.items():
        upper = name.upper()
        if any(word in upper for word in ("KEY", "PASSWORD", "SECRET", "TOKEN")):
            continue
        if not value.startswith(("http://", "https://")):
            continue
        if "EVENT" in upper or "PROVIDER" in upper:
            add(value, None)

    for base in (
        "http://events-provider.events-provider.svc",
        "http://events-provider.events-provider.svc:8000",
        "http://events-provider.events.svc",
        "http://events-provider.events.svc:8000",
        "http://events-provider.default.svc",
        "http://events-provider.default.svc:8000",
        "http://events-provider.provider.svc",
        "http://events-provider.platform.svc",
        "http://events-provider.services.svc",
        "http://events-provider.python-labs.svc",
        "http://events-provider.labs.svc",
        "http://events-provider",
        "http://events-provider:8000",
    ):
        add(base, None)

    for ingress in (
        "http://ingress-nginx-controller.ingress-nginx.svc",
        "http://nginx-ingress-ingress-nginx-controller.ingress-nginx.svc",
        "http://rke2-ingress-nginx-controller.kube-system.svc",
        "http://traefik.kube-system.svc",
    ):
        add(ingress, PUBLIC_HOST)

    add(f"http://{PUBLIC_HOST}", None)
    add(f"https://{PUBLIC_HOST}", None)
    return places


def find_provider_base(api_key):
    failures = []
    for base, host in candidate_places():
        try:
            response = requests.get(
                base + "/api/events/",
                params={"changed_at": "2000-01-01"},
                headers={"x-api-key": api_key, **({"Host": host} if host else {})},
                timeout=(1, 5),
            )
        except requests.RequestException:
            failures.append(base + " timeout")
            continue
        if response.status_code == 200 and response.text.strip():
            remember_provider(base, host)
            return response
        failures.append(f"{base} {response.status_code}")
    raise ValueError("чужой сервис " + "; ".join(failures[:6]))


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
    def __init__(self, api_key):
        self.api_key = api_key

    def get_page(self, url, params=None):
        response = requests.get(
            url,
            params=params,
            headers=provider_headers(self.api_key),
            timeout=(2, 8),
        )
        return response

    def register(self, event_id, first_name, last_name, email, seat):
        url = provider_url(f"/api/events/{event_id}/register/")
        response = requests.post(
            url,
            headers=provider_headers(self.api_key),
            timeout=8,
            json={
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "seat": seat,
            },
        )
        return response

    def unregister(self, event_id, ticket_id):
        url = provider_url(f"/api/events/{event_id}/unregister/")
        response = requests.delete(
            url,
            headers=provider_headers(self.api_key),
            timeout=8,
            json={"ticket_id": ticket_id},
        )
        return response


class EventsPaginator:
    def __init__(self, client, changed_at, base_url=None, first_response=None):
        self.client = client
        self.base = (base_url or current_base).rstrip("/")
        self.url = self.base + "/api/events/"
        self.params = {"changed_at": changed_at}
        self.first_response = first_response

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
        first = self.first_response
        while url is not None:
            if first is not None:
                response = first
                first = None
            else:
                response = self._load(url, params)
            data = response.json()
            yield from data["results"]
            url = rewrite_next(data.get("next"), self.base)
            params = None

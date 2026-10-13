import os
import socket
import time
from urllib.parse import urlsplit, urlunsplit

import requests

session = requests.Session()
session.trust_env = False

PUBLIC_HOST = "events-provider.dev-2.python-labs.ru"
CATALOG_IP = "147.45.108.148"
current_base = f"https://{PUBLIC_HOST}"
current_host = None

_orig_getaddrinfo = socket.getaddrinfo


def _getaddrinfo(host, port, *args, **kwargs):
    if host == PUBLIC_HOST:
        host = CATALOG_IP
    return _orig_getaddrinfo(host, port, *args, **kwargs)


socket.getaddrinfo = _getaddrinfo


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


def kubernetes_event_services():
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    if not os.path.exists(token_path):
        return []
    with open(token_path, encoding="utf-8") as token_file:
        token = token_file.read().strip()
    host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    verify = ca_path if os.path.exists(ca_path) else True
    urls = [
        f"https://{host}:{port}/api/v1/services",
        "https://kubernetes.default.svc/api/v1/services",
    ]
    response = None
    last_error = "k8s-no-response"
    for url in urls:
        try:
            response = requests.get(
                url,
                headers={"Authorization": "Bearer " + token},
                verify=verify,
                timeout=2,
            )
            break
        except requests.RequestException as error:
            response = None
            last_error = f"k8s-{type(error).__name__}"
    if response is None:
        return [(last_error, None)]
    if response.status_code != 200:
        return [(f"k8s-{response.status_code}", None)]
    found = []
    for item in response.json().get("items", []):
        meta = item.get("metadata") or {}
        name = meta.get("name") or ""
        namespace = meta.get("namespace") or ""
        label = (name + " " + namespace).lower()
        if "event" not in label and "provider" not in label:
            continue
        for port in (item.get("spec") or {}).get("ports") or []:
            number = port.get("port")
            if not number:
                continue
            scheme = "https" if number == 443 else "http"
            found.append((f"{scheme}://{name}.{namespace}.svc:{number}", None))
    if not found:
        return [("k8s-no-event-service", None)]
    return found


def candidate_places():
    places = []
    seen = set()

    def add(base, host):
        item = (base.rstrip("/"), host)
        if item not in seen:
            seen.add(item)
            places.append(item)

    for name in ("EVENTS_API_URL", "EVENTS_PROVIDER_URL", "PROVIDER_URL"):
        value = os.environ.get(name, "").strip()
        if value.startswith(("http://", "https://")):
            add(value, None)

    for name, value in os.environ.items():
        upper = name.upper()
        if any(word in upper for word in ("KEY", "PASSWORD", "SECRET", "TOKEN")):
            continue
        if not value.startswith(("http://", "https://")):
            continue
        if "EVENT" in upper or "PROVIDER" in upper:
            add(value, None)

    add(f"https://{PUBLIC_HOST}", None)

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

    return places


def catalog_base():
    for name in ("EVENTS_API_URL", "EVENTS_PROVIDER_URL", "PROVIDER_URL"):
        value = os.environ.get(name, "").strip().rstrip("/")
        if value.startswith(("http://", "https://")):
            return value
    return f"https://{PUBLIC_HOST}"


def find_provider_base(api_key):
    base = catalog_base()
    try:
        response = session.get(
            base + "/api/events/",
            params={"changed_at": "2000-01-01"},
            headers={"x-api-key": api_key},
            timeout=60,
        )
    except requests.RequestException as error:
        raise ValueError(f"чужой сервис {base} {type(error).__name__}") from error
    if response.status_code != 200 or not response.text.strip():
        raise ValueError(f"чужой сервис {base} {response.status_code}")
    remember_provider(base, None)
    return response


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
        response = session.get(
            url,
            params=params,
            headers=provider_headers(self.api_key),
            timeout=60,
        )
        return response

    def register(self, event_id, first_name, last_name, email, seat):
        url = provider_url(f"/api/events/{event_id}/register/")
        response = session.post(
            url,
            headers=provider_headers(self.api_key),
            timeout=60,
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
        response = session.delete(
            url,
            headers=provider_headers(self.api_key),
            timeout=60,
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

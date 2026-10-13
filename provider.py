import time

import requests


class EventsProviderClient:
    def __init__(self, api_key):
        self.api_key = api_key

    def get_page(self, url, params=None):
        response = requests.get(
            url,
            params=params,
            headers={"x-api-key": self.api_key},
            timeout=4,
        )
        return response
    def register(self, event_id, first_name, last_name, email, seat):
        url = f"https://events-provider.dev-2.python-labs.ru/api/events/{event_id}/register/"
        response = requests.post(
            url,
            headers={"x-api-key": self.api_key},
            timeout=8,
            json={
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "seat": seat,
            },
        )
        return response
    def unregister (self, event_id, ticket_id):
        url = f"https://events-provider.dev-2.python-labs.ru/api/events/{event_id}/unregister/"
        response = requests.delete(
            url,
            headers={"x-api-key": self.api_key},
            timeout=8,
            json={"ticket_id": ticket_id},
        )
        return response    



class EventsPaginator:
    def __init__(self, client, changed_at):
        self.client = client
        self.url = "https://events-provider.dev-2.python-labs.ru/api/events/"
        self.params = {"changed_at": changed_at}

    def __iter__(self):
        url = self.url
        params = self.params
        while url is not None:
            response = None
            failure = "нет ответа"
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
                    break
                if response is not None:
                    failure = f"{response.status_code} {response.text[:80]}"
                if attempt == 0:
                    time.sleep(1)
            if response is None or response.status_code != 200 or not response.text.strip():
                raise ValueError(f"чужой сервис {failure}")
            data = response.json()
            yield from data["results"]
            url = data["next"]
            params = None
        
        
import os

import requests

key = os.environ["EVENTS_API_KEY"]

response = requests.get(
    "http://events-provider.dev-2.python-labs.ru/api/events/",
    params={"changed_at": "2000-01-01"},
    headers={"x-api-key": key},
)
data = response.json()

print(len(data["results"]))
print(data["next"])
print(response.status_code)
print(data["results"][0]["name"])

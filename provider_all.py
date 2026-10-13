import os

import requests

key = os.environ["EVENTS_API_KEY"]
url = "http://events-provider.dev-2.python-labs.ru/api/events/"
params = {"changed_at": "2000-01-01"}
total = 0

while url is not None:
    response = requests.get(
        url,
        params=params,
        headers={"x-api-key": key},
    )
    data = response.json()
    total = total + len(data["results"])
    url = data["next"]
    params = None

print(total)

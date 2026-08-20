"""Time API requests to find bottleneck."""
import time
import json
import http.cookiejar
from urllib.request import Request, urlopen, HTTPCookieProcessor, build_opener

cj = http.cookiejar.CookieJar()
opener = build_opener(HTTPCookieProcessor(cj))

# Login
t0 = time.time()
req = Request("http://127.0.0.1:8000/api/v1/auth/login",
              data=json.dumps({"email": "admin@demo.com", "password": "admin@123"}).encode(),
              headers={"Content-Type": "application/json"})
resp = opener.open(req, timeout=10)
print(f"Login: {resp.status}, took {(time.time()-t0)*1000:.0f}ms")
resp.read()

# Sequential requests
for ep in ["events?limit=5", "events?limit=50", "brands", "campaigns?limit=5",
           "hcps?limit=5", "dashboard/stats", "analyses/impacts?limit=5", "forecasts?limit=5"]:
    t0 = time.time()
    req = Request(f"http://127.0.0.1:8000/api/v1/{ep}")
    try:
        resp = opener.open(req, timeout=30)
        data = json.loads(resp.read())
        elapsed = (time.time() - t0) * 1000
        items = len(data.get("items", [])) if isinstance(data, dict) and "items" in data else "N/A"
        print(f"{ep}: {resp.status}, {items} items, took {elapsed:.0f}ms")
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        print(f"{ep}: ERROR {e}, took {elapsed:.0f}ms")

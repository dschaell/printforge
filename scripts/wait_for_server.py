import time
import urllib.request

for _attempt in range(60):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8787/api/health", timeout=1) as response:  # noqa: S310
            if response.status == 200:
                break
    except OSError:
        time.sleep(0.5)
else:
    raise SystemExit("Server did not become ready")

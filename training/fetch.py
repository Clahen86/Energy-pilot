"""Fetch the hourly lines from the report worker (GitHub Action: secrets EP_EXPORT_KEY and EP_REPORT_URL).

    python training/fetch.py data.json [since]

Writes only to the given file - never to the repository (it's public). Prints nothing about the houses."""
import json
import os
import sys
import urllib.request

url = os.environ.get("EP_REPORT_URL", "https://ep-reports.clahen86.workers.dev").rstrip("/")
key = os.environ.get("EP_EXPORT_KEY", "")
out, since = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "2000-01-01")
rows, offset = [], 0
if not key and os.environ.get("GITHUB_ACTIONS"):
    sys.exit("EP_EXPORT_KEY is missing - set it under Settings > Secrets and variables > Actions")
if key:
    while offset is not None:
        req = urllib.request.Request(f"{url}/export?key={key}&since={since}&offset={offset}", headers={"user-agent": "energy-pilot-training"})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        rows += d.get("rows") or []
        offset = d.get("next")
with open(out, "w") as f:
    json.dump(rows, f)
print(f"{len(rows)} days from {len({r['home'] for r in rows})} homes")

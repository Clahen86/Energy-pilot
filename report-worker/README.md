# Report receiver

`worker.js` is a Cloudflare Worker. When a user presses **Send to the developer** in Energy Pilot, the test result and
the diagnostics are posted here. The worker stores the file in a **private** GitHub repository and opens an issue
there - no GitHub account is needed by the user, and only the developer can see the reports.

Setup: a private repository (with a README so `main` exists), a fine-grained token with Contents + Issues
read/write on that repository only, and a Worker with this code and two variables:
`REPORT_REPO` (text, `owner/name`) and `GITHUB_TOKEN` (secret). Energy Pilot reads the Worker's URL from `REPORT_URL`
in `energy_pilot/energy_pilot/web.py` (or the `EP_REPORT_URL` environment variable in Docker).

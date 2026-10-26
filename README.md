# My Palm Pals Collection

Personal Palm Pals collection tracker — static single-page gallery (`index.html`).

- Collection-only photo gallery; home starts empty, shows only entries you add.
- Collection state saves to browser `localStorage`, with JSON backup import/export.
- No backend, no cloud sync, no Google Sheets integration.

Deployed on Coolify (Oracle Always Free). `server.py` (stdlib-only
Python, linux/arm64) serves the gallery plus a PIN-gated sync API:
`POST /api/unlock`, `GET`/`PUT /api/state`. The collection JSON lives in
a file on the Coolify persistent volume (`/data/collection.json`, with
`.bak` of the previous version and `tokens.json` for login sessions).
Set `PALM_PIN_HASH` (sha256 of the owner PIN) and `PORT` as Coolify env vars.

Product images/designs belong to Aurora World and applicable licensors.
Unofficial personal collector tool.

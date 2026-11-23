# Machine JSON API

The `/api/v1` API creates wines, adjusts stock and updates selected details.
It is disabled until a separate credential is configured. Existing UI and
legacy `/api/summary`, `/api/wine/<id>` and `/api/timeline` behavior is unchanged.
No images are downloaded and no AI or Vivino requests are made by these routes.

## Enable and authenticate

After installing a reviewed release containing this feature:

1. Generate a random credential locally, for example with
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Set `wine_api_token` in the Home Assistant app's Configuration tab, or set
   `WINE_API_TOKEN` for standalone Docker. The environment variable takes
   precedence, including an empty value to disable the API. Restart the app
   after configuration changes. Do not commit this credential to Git.
3. Send it in the `X-Wine-API-Key` request header. Never put it in a URL or body.

The token must contain 32–256 ASCII letters, digits, hyphens or underscores.
Use a generated random value, not a memorable password. Missing or malformed
configuration disables all `/api/v1` routes with HTTP 503. An incorrect or
missing request credential returns 401. Credentials are compared in constant
time and are not returned, logged or stored in the wine database by this API.
The HA option uses a password field; configuration and configuration backups
still require protection. Replace the token and restart to revoke the old one;
set it to an empty value and restart to disable access.

This single credential is scoped to creating, reading and editing wine records
and adjusting stock through `/api/v1`. It does not grant standalone login,
settings access, deletion, imports, image management, chat, or other legacy
API access. It is not restricted to individual wines. In standalone mode these
routes use the token independently of browser login; a supplied readonly
browser session still cannot write. Browser login or ingress headers alone
never authorize the new API. `X-Wine-API-Key` is separate from `Authorization`
so it does not compete with Home Assistant's proxy authentication.

**Network boundary:** this feature protects the new routes, not the whole
application. Existing form and legacy write routes retain their existing
authentication; in HA mode they may still be reachable without authentication
on port 5050. Keep the direct port inaccessible to untrusted clients, use HA
Ingress, and retain standalone login where applicable. Use HTTPS for the
external connection; the app itself does not terminate TLS. A token sent over
plain HTTP outside a trusted local/container network can be intercepted.
Do not log request headers in a reverse proxy or client. No broad CORS access
is enabled. Rate limiting, if needed, belongs at the trusted proxy boundary.

## Endpoints and retries

| Method | Path | Purpose | Success |
| --- | --- | --- | --- |
| POST | `/api/v1/wines` | Create a record | 201 |
| GET | `/api/v1/wines/<id>` | Read the full record using the API token | 200 |
| PATCH | `/api/v1/wines/<id>` | Update only supplied fields | 200 |
| POST | `/api/v1/wines/<id>/stock` | Add/consume bottles, optionally with notes | 200 |

Every write requires `Content-Type: application/json` and `Idempotency-Key`.
Generate a new UUID for each intended operation and retain it until its outcome
is known. Allowed keys contain 8–128 ASCII letters, digits, hyphens or
underscores. GET does not need a key.

Retry the **same operation, wine ID, JSON values and key** after a timeout or
lost response. JSON object key order and whitespace do not matter. A completed
retry returns the original status and response snapshot with
`Idempotency-Replayed: true`. It does not reapply stock or append notes again.
GET the record to see its current state if other changes have occurred since
that snapshot. A successful key reused with different content, wine or
operation returns 409 `idempotency_conflict`. Failed requests leave no receipt;
correcting and resending them is allowed. Do not create a new key merely because
the original response was lost.

SQLite stores a hash of the key, a request hash, the successful response and a
timestamp in a new additive `api_requests` table. A write lock covers duplicate
checks, stock calculations, notes, timeline entries and the receipt in one
transaction. This handles simultaneous API requests and process restarts.
Receipts survive token rotation and are not automatically expired: a delayed
retry remains safe. Storage grows with successful requests and includes wine
snapshots/notes. Existing wine and timeline schemas are unchanged.

The standard wine ZIP/CSV export remains compatible and includes wine changes
and timeline entries, but does **not** export credentials or API receipts.
After an export/import or restoring an older backup, reconcile current records
before sending requests that may have already run. Old keys cannot prove their
outcome if their receipts were not restored. A consistent full database backup
includes receipts. Existing UI/AI/import writes do not acquire API retry keys;
the API does not add optimistic concurrency protection to those workflows.

## Create a wine

Illustrative request; choose an unused key for a new operation:

```http
POST /api/v1/wines
Content-Type: application/json
X-Wine-API-Key: <configured-secret>
Idempotency-Key: 138d581f-04c4-4125-87f5-4794d5585c25
```

```json
{
  "producer": "The Black Pig",
  "name": "The Prize Shiraz",
  "year": 2023,
  "type": "Rotwein",
  "region": "South Australia",
  "grape": "Shiraz",
  "quantity": 6,
  "drink_from": 2024,
  "drink_until": 2030,
  "notes": "Classic Cellar commentary"
}
```

Response: HTTP 201, `{"ok": true, "wine": {...}}`, with every wine field,
including the assigned `id`, `quantity: 6` and original `notes`. No caller
chooses the ID. The examples below assume ID 25 for illustration only.

Only `name` is required. Defaults: quantity 1, rating 0, bottle format 0.75
litres, today's added date. An `added` event records the initial quantity,
including zero. Other omitted fields are null.

Duplicates use name + producer + vintage + bottle format. Names/producers are
compared using Unicode normalization, case folding and collapsed whitespace;
missing producer and empty producer match, and a legacy missing format means
0.75. Duplicate creation or an identity edit that collides returns 409
`duplicate_wine`. Restock the existing record instead. Distinct vintages or
formats are separate records. This is conservative exact matching, not fuzzy
wine recognition; different spelling can still describe the same wine.
Existing duplicates are not merged or removed.

## Consume or restock, with optional notes

```http
POST /api/v1/wines/25/stock
Content-Type: application/json
X-Wine-API-Key: <configured-secret>
Idempotency-Key: 41db31cc-c42a-4e60-b223-d62313c56218
```

```json
{
  "delta": -1,
  "notes": "black pig is easy drinking good value go to evening wine. It’s how I discovered i liked Syrah. - Justin"
}
```

HTTP 200 response excerpt (the actual response includes the full wine record):

```json
{
  "ok": true,
  "wine": {
    "id": 25,
    "quantity": 5,
    "notes": "Classic Cellar commentary\n\nblack pig is easy drinking good value go to evening wine. It’s how I discovered i liked Syrah. - Justin"
  }
}
```

`delta` is a nonzero integer: negative consumes, positive restocks. For example,
`{"delta": 3}` adds three bottles. A matching `consumed` or `restocked` timeline
event stores the positive number of bottles moved. Quantity cannot go below
zero or above 1,000,000. Zero stock preserves the record. Stock and optional
notes succeed or fail together. Only `delta`, `notes` and `notes_mode` are
allowed on this endpoint.

## Update notes or selected details

```http
PATCH /api/v1/wines/25
Content-Type: application/json
X-Wine-API-Key: <configured-secret>
Idempotency-Key: c0d22bb7-03db-4220-94d1-6a839360cf31
```

```json
{"grape": "Shiraz / Syrah", "rating": 4, "drink_until": 2032}
```

HTTP 200 returns `{"ok": true, "wine": {...}}` with the full updated record.
Fields absent from the request remain unchanged. Quantity changes must use
`/stock` so they cannot bypass stock history. `notes` appends by default,
separated from existing notes by two newlines. Unicode, punctuation, newlines
and leading/trailing note whitespace are preserved exactly. Existing
commentary is retained. To deliberately replace or clear notes:

```json
{"notes": "A replacement tasting note.", "notes_mode": "replace"}
```

```json
{"notes": "", "notes_mode": "replace"}
```

`notes_mode: "append"` is also explicit; empty appends and a mode without notes
are rejected. Notes cannot be null. Other nullable fields can be cleared with
JSON null. To verify current state, GET `/api/v1/wines/25` with the same token.

## Field validation

| Fields | Accepted values |
| --- | --- |
| `name` | Nonblank string, at most 512 characters; required on creation |
| `producer`, `region`, `grape`, `purchased_at`, `location` | String up to 512 characters, or null |
| `type` | `Rotwein`, `Weisswein`, `Rosé`, `Schaumwein`, `Dessertwein`, `Likörwein`, `Anderes`, or null (existing database codes) |
| `year`, `drink_from`, `drink_until` | Integer 1–9999, or null; start must not exceed end |
| `quantity` | Integer 0–1,000,000 on creation only |
| `rating` | Integer 0–5; zero means unrated |
| `price` | Finite number 0–1,000,000,000, or null |
| `bottle_format` | Finite number 0.01–100 litres |
| `alcohol_pct` | Finite number 0–100, or null |
| `vivino_id` | Positive signed 64-bit integer, or null |
| `notes` | String; total after appending at most 50,000 characters |
| `taste_profile` | Object with optional `body`, `tannin`, `acidity`, `sweetness` integer values 1–5, or null |
| `maturity_data` | Object with optional `youth`, `maturity`, `peak`, `decline` ordered two-year arrays (1–9999), or null |
| `food_pairings` | Up to 100 strings, each at most 512 characters, or null |

Vintage is named `year`, matching the existing database/API. Numeric strings
and booleans are rejected for numeric fields. Unknown fields, including
`image`, `id` and `added`, are rejected. Requests must be UTF-8 JSON objects of
at most 64 KiB. Duplicate JSON keys, nonfinite numbers, malformed encodings and
unpaired Unicode surrogates are rejected. Structured fields use JSON objects
and arrays, not serialized JSON strings.

Errors have the shape `{"ok": false, "error": "stock_out_of_range"}`.

| Status | Meaning |
| --- | --- |
| 400 | Invalid fields/JSON or missing/invalid retry key |
| 401 | Missing/incorrect API credential |
| 403 | Readonly standalone browser session attempted a write |
| 404 | Wine does not exist |
| 409 | Duplicate wine, insufficient/excess stock, or retry-key conflict |
| 413 | Request exceeds 64 KiB |
| 415 | JSON content type required |
| 503 | API disabled, or database temporarily unavailable; check `error` |

## Home Assistant MCP

Use an HA-MCP version exposing `request_headers` on `ha_manage_app`. Its
[official tool reference](https://homeassistant-ai.github.io/ha-mcp/tools/)
documents JSON bodies, caller headers and Ingress routing. Use the actual
installed Wine Tracker slug discovered with `ha_get_app`. Prefer Ingress by
omitting `port`; no Home Assistant authentication should be disabled.

Example **tool arguments**, with placeholders (not a live operation):

```json
{
  "slug": "<installed-wine-tracker-slug>",
  "path": "/api/v1/wines/25/stock",
  "method": "POST",
  "request_headers": {
    "X-Wine-API-Key": "<securely-injected-wine-api-token>",
    "Idempotency-Key": "41db31cc-c42a-4e60-b223-d62313c56218"
  },
  "body": {
    "delta": -1,
    "notes": "black pig is easy drinking good value go to evening wine. It’s how I discovered i liked Syrah. - Justin"
  },
  "debug": false
}
```

Store the Wine Tracker token in a trusted integration's secret store and have
that integration inject the header. A placeholder in this example is not
automatically resolved by HA-MCP. Do not paste the real token into a chat,
prompt, shared tool transcript or source file. If the client cannot inject
secrets privately, configure a trusted server-side wrapper that does so before
enabling assistant writes; generic tool arguments may be recorded by clients.
Review the client/proxy's header redaction and keep debug header logging off.
Wine Tracker cannot redact another service's logs. Keep the Home Assistant
credential separate and retain MCP write approval controls.

For note-only changes use `method: "PATCH"` and `/api/v1/wines/25`; for
verification use `method: "GET"` with the API key and no body. After an uncertain
outcome, read the wine and retry only with the original key/body. Never weaken
authentication to work around missing header support. This integration path
is documented against the tool contract; it has not been exercised against a
live Home Assistant installation as part of this change.

## Development and release scope

Run `python -m pytest tests -q` from `wine-tracker/`. Tests use temporary
databases, including the illustrative ID 25 fixture; they do not contact a live
cellar. No dependencies were added. `wine-tracker-dev/` is a generated release
copy refreshed by `scripts/sync-dev-addon.sh`; this source change does not run
release/deployment scripts or bump a release version.

Photographs are a separate proposal in [API_PHOTOS_PROPOSAL.md](API_PHOTOS_PROPOSAL.md).

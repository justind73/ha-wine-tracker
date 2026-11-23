# Production Wine Tracker and Home Assistant MCP

This fork retains the upstream UI and cellar format, adds the scoped JSON API,
and protects browser routes with Home Assistant Ingress. The HA release is
`1.11.0-api.1`; the application UI retains the upstream `1.11.0` version string.

## Installation and data

Add `https://github.com/justind73/ha-wine-tracker` to the HA app store and install
**Wine Tracker** from **Wine Tracker — Justin's fork**. Its app ID is
`64183197_wine_tracker`, and its internal hostname is
`64183197-wine-tracker`. Install from the fork's main branch after tests pass.
HA builds the app from source; it does not pull an upstream Wine Tracker image.
Record the installed version and the corresponding fork commit/release tag.

The existing cellar remains at `/share/wine-tracker/wine.db`, with pictures
under `/share/wine-tracker/uploads/`. Stop the previous Wine Tracker before
starting this one: never run two app instances against that database. Preserving
the database in place retains record IDs, notes, drinking windows, history,
settings and API retry receipts. The API adds one receipts table and does not
replace or rewrite the wine/timeline schema. Existing photos and UI workflows
remain available; machine photo attachment is still a separate feature proposal.

Before switching apps, export a complete ZIP and verify it with both ZIP CRC
checks and Wine Tracker's own import parser. Check records, total quantity,
timeline entries and every referenced image. Keep the CSV as a secondary copy.
With the original app stopped, also retain a private copy of its complete data
directory and configuration for rollback. ZIP exports intentionally omit API
retry receipts; the complete database snapshot preserves them.

Open Wine Tracker using **Settings → Apps → Wine Tracker → Open Web UI**, or
enable its sidebar entry. No direct LAN port is needed.

## Authentication and the network boundary

- `ports: {}` means there is no LAN mapping for port 5050.
- `HA_INGRESS_ONLY=true` allows browser and legacy routes only when the actual
  HTTP peer is the Supervisor ingress proxy at `172.30.32.2`. HA authenticates
  the browser first. Claimed ingress, forwarded-IP and user headers do not
  authorize a request from any other peer. Do not add a proxy that rewrites the
  application's trusted peer address from untrusted headers.
- Every `/api/v1` route independently requires `X-Wine-API-Key`, including
  requests through ingress. The key grants no access to legacy/UI settings.
- `S6_KEEP_ENV=1` preserves these settings and the data path when the base
  container launches Python. Keep protection mode enabled.
- The internal REST destination uses HTTP only on HA's trusted container
  network. External HA/MCP access should use authenticated HTTPS. Do not add
  router forwarding or an unauthenticated proxy to the app.

This follows the [official ingress peer-validation guidance](https://contributors.home-assistant.io/apps/guides/ingress/).
Standalone Docker deployments keep the upstream `AUTH_ENABLED` login mechanism;
the HA-specific ingress restriction is opt-in outside this HA app manifest.

## The four production commands

Copy [wine_tracker.yaml](../examples/home-assistant/wine_tracker.yaml) into
`/config/packages/wine_tracker.yaml`. The user's configuration already includes
`homeassistant: packages: !include_dir_named packages`; preserve existing
configuration instead of adding a second `homeassistant` mapping.

Generate a new random production API credential privately. Set the same value
in the app's `wine_api_token` option and as `wine_tracker_api_token` in
`/config/secrets.yaml`. Never put its value in chat, Git, MCP arguments or logs.
An authorized script may generate and configure it entirely on HA without
printing the value. Configuration files/backups are private plaintext, so keep
administrative file/app-management access restricted.

The package pins all URLs to `64183197-wine-tracker`, validates that record IDs
are positive integers and serializes data using `to_json`. Callers cannot
override the URL, method or headers. Keep the package's
`homeassistant.components.rest_command: warning` logging setting: debug logging
can expose resolved request headers.

| HA action | Data | API endpoint |
| --- | --- | --- |
| `rest_command.wine_tracker_add` | `request_id`, `wine` object | `POST /api/v1/wines` |
| `rest_command.wine_tracker_stock` | `request_id`, integer `wine_id`, `change` object | `POST /api/v1/wines/<id>/stock` |
| `rest_command.wine_tracker_update` | `request_id`, integer `wine_id`, `changes` object | `PATCH /api/v1/wines/<id>` |
| `rest_command.wine_tracker_get` | integer `wine_id` | `GET /api/v1/wines/<id>` |

HA-MCP calls use `domain="rest_command"`, the service name without its domain,
`return_response=true` and `wait=false`. Check `service_response.status` and
`service_response.content.ok`, not just the tool's generic success flag.

For example, a read uses service `wine_tracker_get` with `data={"wine_id":25}`.
Select the correct real record ID first. For a genuine consumption, use service
`wine_tracker_stock` with a new stable request ID and
`change={"delta":-1,"notes":"Your tasting note"}`. Notes append while preserving
existing commentary. Retrying an uncertain request must retain the exact same
ID/body; conflicting key reuse returns 409. A fresh GET verifies current stock,
because a retry returns its original saved snapshot. No production stock
movement is needed solely to test deployment.

Run `ha core check` before applying package edits. Because `rest_command` is
already loaded, `rest_command.reload` can replace its actions without restarting
HA Core. Check that exactly the four production Wine Tracker actions remain.

## Verification and rollback

After switching, compare all exported wines and timeline entries with the
verified backup, not only the totals. Verify the API through the production HA
read action, the UI through authenticated ingress, and that direct legacy access
is rejected. Prove stock and note writes in temporary-database automated tests;
do not add/consume real stock merely as a deployment test.

Keep the old app stopped until these checks succeed. If switching fails, stop
the replacement before restarting the previous app. Use the private data
snapshot only if restoration is required; never overwrite a newer cellar
without first reconciling genuine user changes. Remove the previous app only
after successful verification, retaining recovery backups separately.

## Maintenance

Keep upstream as `https://github.com/xenofex7/ha-wine-tracker`. Future releases
can be merged into the fork with Git; conflicts are most likely in `app.py`,
the HA manifest/version and documentation. The API is isolated in `wine_api.py`
and uses existing SQLite/image/UI structures. Preserve the small ingress guard,
no-host-port policy, s6 environment setting and API registration when resolving
conflicts. Merge upstream, resolve any conflicts, run the full tests, increment
the fork's app version, and rebuild/update from the fork. Do not blindly install
upstream images, which would omit the API and security changes.

Run `python -m pytest wine-tracker/tests -q` with dependencies from
`requirements.txt` and `requirements-test.txt`. Tests use disposable local
databases and loopback HTTP; they need no production credentials. The generated
`wine-tracker-dev` tree belongs to the upstream development-release workflow;
it is not a second installed cellar and is not maintained by this deployment.

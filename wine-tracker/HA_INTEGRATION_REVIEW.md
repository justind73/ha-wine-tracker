# HA-MCP integration and isolated staging review

Prepared for PR #1. Staging installation was subsequently authorized separately.
The existing app and `/share/wine-tracker/` must remain untouched during staging.

## Recommendation

Use four native Home Assistant `rest_command` actions. ChatGPT calls them via
HA-MCP's `ha_call_service`, with `return_response: true`. HA inserts the Wine
Tracker token from `secrets.yaml` into a fixed request header. ChatGPT supplies
only wine data, a wine ID and an idempotency key; it never supplies the token,
URL, method or headers. No custom HA integration, script wrapper, persistent
response sensor or extra Wine Tracker endpoint is required.

| Action | Input data | Result |
| --- | --- | --- |
| `rest_command.wine_tracker_staging_add` | `request_id`, `wine` object | Full created wine, including assigned ID |
| `rest_command.wine_tracker_staging_stock` | `request_id`, numeric `wine_id`, `change` object | Full wine after adding/consuming bottles and optional notes |
| `rest_command.wine_tracker_staging_update` | `request_id`, numeric `wine_id`, `changes` object | Full wine after partial update |
| `rest_command.wine_tracker_staging_get` | numeric `wine_id` | Current full wine |

The complete configuration is
[wine_tracker_staging.yaml](../examples/home-assistant/wine_tracker_staging.yaml).
Use the whole file, not guessed snippets. The URLs are fixed to the **local
staging app**. Integer-only IDs prevent path/host injection. `to_json` preserves
quotes, newlines and Unicode in notes without turning prose into executable
templates. Requests retain the caller's retry key: no template generates a
fresh key on each retry.

HA returns `status`, `content` and **response** `headers`. With HA-MCP,
these appear under `service_response`. Check both the HTTP status and
`content.ok`; a successful HA service invocation can still contain an HTTP
401, 409 or 503 from Wine Tracker. On a timeout, preserve the same key/body,
read the record, and retry the same operation if needed. See [API.md](API.md)
for validation, stock rules and receipt retention.

### Secret handling and limits

- Generate a fresh staging token locally. Put the same value into the staging
  app's password option and HA's `secrets.yaml`. Neither value belongs in an
  MCP request, chat, shared screenshot, Git commit, state attribute or script
  variable. Do not reuse a production token.
- **Required logging setting:** `homeassistant.components.rest_command:
  warning`. The supplied package includes it. HA 2026.11.2's implementation logs
  resolved headers at debug level. Never enable debug logging for this
  integration while a token is configured; if it happens, rotate the token and
  protect/remove the affected logs according to your retention policy.
- `secrets.yaml` is a local plaintext configuration file, not an encrypted
  vault. Protect HA configuration access and backups. Secrets are resolved by
  HA, not by `ha_call_service`; the normal response contains no request token.
- This avoids exposing the credential through normal ChatGPT action arguments.
  It is **not** a security boundary against an HA administrator or an MCP
  client permitted to read secrets or reconfigure HA. Retain write approvals
  and restrict configuration/file/app-management tools for routine assistant
  use. Do not ask ChatGPT to inspect `secrets.yaml` or resolved app options.
- The fixed `http://local-wine-tracker-api-staging:5050` destination is confined
  to the trusted HA OS internal network. `verify_ssl: true` is retained, but
  does not encrypt HTTP. For another host/network, use HTTPS with certificate
  verification and an authenticated backend; never set `verify_ssl: false`.
  Keep the HA-MCP external transport authenticated and protected by TLS.
- Do not replace the fixed hostname with a caller-supplied URL. REST clients
  can follow redirects; use only the pinned backend, which does not redirect
  these versioned API routes. A proxy must not redirect them to another host.

The reviewed contracts are [RESTful Command](https://www.home-assistant.io/integrations/rest_command/),
[HA's implementation](https://github.com/home-assistant/core/blob/2026.11.2/homeassistant/components/rest_command/services.py),
[HA secrets](https://www.home-assistant.io/docs/configuration/secrets/) and the
available HA-MCP `ha_call_service` schema (`return_response` returns
`service_response`, and `wait: false` avoids irrelevant entity-state polling).

## Why staging cannot touch the live cellar

The source packager creates a separate local app, not a replacement release.

| Setting | Staging value | Effect |
| --- | --- | --- |
| Name | Wine Tracker API Staging | Clearly identifiable in Settings → Apps |
| App ID | `local_wine_tracker_api_staging` | Distinct from the existing app and dev app |
| Internal hostname | `local-wine-tracker-api-staging` | Fixed REST-command destination |
| `DATA_DIR` | `/data/wine-tracker-api-staging` | Private persistent storage belonging to this app |
| Host mounts | `map: []` | No `/share`, HA config, or live cellar mount |
| Host networking | false | No host-network access |
| Published ports | none (`ports: {}`) | No new LAN port 5050 or 5051 |
| Ingress | false | API-only review app; no browser panel |
| Legacy login | `AUTH_ENABLED=true`, `USERS=""`, `DEV_AUTH=""` | No legacy write access and no browser accounts |
| Container environment | `S6_KEEP_ENV=1` | Retains authentication and storage settings when s6 starts Python |
| AI | none | No provider credentials or enrichment calls |
| Start on boot | manual | Starts only when explicitly requested |

The existing `wine-tracker/` and generated `wine-tracker-dev/` configurations
are not repurposed. The app uses the same source and Dockerfile, with only a
generated staging manifest. Even a legacy request from another app on the
internal network must pass the existing login protection. The scoped API
credential does not bypass that protection. A browser login page with no
working account is expected; this staging app is deliberately API-only.

The hostname convention and internal network are documented by
[Home Assistant](https://contributors.home-assistant.io/apps/guides/communication/).
Removing a host port does not isolate apps from one another; this is why
staging also enables application authentication.

## 1. Prepare the source package on your computer

This step is local and does not install or deploy anything. Requirements: Git
and Python 3.12 or newer. Open a terminal in the checkout of this PR:

```text
git switch codex/secure-json-api
git pull --ff-only
git rev-parse HEAD
python scripts/prepare-api-staging.py --ref HEAD --output .artifacts/wine-tracker-api-staging.zip
```

If `python` is unavailable, use your Python installation's full executable
path. Record the printed full commit ID and archive SHA256. The output path
must be new: the script refuses to overwrite an existing ZIP. For later runs,
choose another filename. To reproduce the same source package, replace `HEAD`
with the recorded commit ID **and use the packager from that same commit**.

Only committed app source, requirements, Dockerfile and build configuration
are included; local uncommitted edits, databases, uploads and secrets are not
copied. `SOURCE.json` records the source revision and hashes of packaged files.
Archive timestamps and line endings are normalized. Image builds still use
the project's existing base tags and dependency ranges: this is reproducible
source preparation, not a claim of bit-identical future container images.

## 2. Install only the staging app, when separately authorized

These steps require installation authorization separately from the PR review.

1. Extract the ZIP on your computer. It contains one folder named
   `wine_tracker_api_staging`.
2. Using your existing authorized Samba/SSH/VS Code access, copy that folder to
   HA's local-app directory. Terminal & SSH 10.6.0 exposes it as `/local_apps/`
   (also `/root/local_apps`); older tools may expose `/addons/`. Check the mount
   before copying: do not create an unmounted `/addons` directory. For Samba installations exposing the addons share, this is
   `\\homeassistant\addons` in Windows File Explorer. The final file must be
   `/local_apps/wine_tracker_api_staging/config.json` for that SSH app, not inside a second nested
   folder. If the folder already exists, stop and check which staging revision
   it contains; do not overwrite an unknown installation.
3. In **Settings → Apps → App store**, use **Check for updates** (sometimes in
   the three-dot menu). Find **Wine Tracker API Staging** under **Local apps**.
   Install **that app only**. Do not update or reinstall the existing Wine
   Tracker app. Building locally can take a few minutes.
4. Verify the app name, version suffix against `SOURCE.json`, no published
   ports, and Start on boot off. Do not add a port mapping or turn off
   protection mode. This package supports amd64 and aarch64.
5. Generate a token in a **local terminal you control**, without sending its value to an assistant:
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
   Keep it private. In staging **Configuration**, set `wine_api_token` to it
   and save. Do not send the value to ChatGPT.
   An authorized deployment script may instead generate and configure it entirely
   on HA, with private files and no secret values in tool arguments or output.
6. Start **Wine Tracker API Staging** only. It creates a fresh database at
   `/data/wine-tracker-api-staging/wine.db` within its own container storage.
   Leave the existing Wine Tracker app running unchanged. There is no staging
   web UI to open. A missing `SECRET_KEY` session warning is harmless here:
   there are no browser accounts or persistent login sessions in staging.
7. Before creating any test records, verify unauthenticated requests to both
   `/api/v1/wines/1` and `/api/summary` return **401** from the actual container.
   If either does not, stop staging and investigate. A successful API-key check
   alone does not prove that legacy routes are protected.

The first real container check found that s6 discarded `AUTH_ENABLED` and
`DATA_DIR` before starting Python, even though they were present in the app
manifest. Local Flask tests cannot reproduce that container startup behavior.
The staging manifest now sets `S6_KEEP_ENV=1`, the documented
[s6 environment preservation setting](https://github.com/just-containers/s6-overlay#customizing-s6-overlay-behaviour).
This change is confined to staging packaging; runtime authentication checks
remain mandatory. No host `/share` mount was present in the original staging
attempt, and no test wines were created before that check failed.

Do not import your live backup, mount `/share`, copy `wine.db`, use the existing
dev app as a shortcut, run release/deploy scripts or change the live app's
network settings as part of these steps.

## 3. Add the HA-side configuration, when separately authorized

This requires editing HA configuration. First retain local backup copies of
the files you edit. Use your existing local file editor; do not expose their
contents through ChatGPT. No existing configuration needs to be replaced.

1. Add this one entry to `/config/secrets.yaml`, entering the **same staging
   token** locally:

   ```yaml
   wine_tracker_staging_api_token: "<paste-the-private-staging-token-here>"
   ```

2. Copy the supplied
   [package file](../examples/home-assistant/wine_tracker_staging.yaml) to
   `/config/packages/wine_tracker_staging.yaml`. Leave its hostname unchanged
   when installing as the local app above. No real token goes in this file.
3. If packages are already enabled with `!include_dir_named packages`, no
   further include is needed. Otherwise merge the following into the existing
   `homeassistant:` mapping in `configuration.yaml`; never create a duplicate
   `homeassistant:` key. If using an explicit packages mapping, add just the
   `wine_tracker_staging` entry to it:

   ```yaml
   homeassistant:
     packages:
       wine_tracker_staging: !include packages/wine_tracker_staging.yaml
   ```

   A different existing include layout must be preserved; see
   [HA packages](https://www.home-assistant.io/docs/configuration/packages/).
4. Check existing `logger.logs` configuration. The REST-command logger must be
   `warning` or stricter. If that exact logger key already exists elsewhere,
   change it there and remove the duplicate `logger:` block from this package.
   Preserve other logging settings. Do not enable REST-command debug logging.
5. Run **Tools → YAML → Check configuration** (called **Developer Tools** on
   older releases). Resolve errors before applying anything.
6. **First setup needs an approved restart:** the read-only review on
   2026-11-23 found HA 2026.11.2 / HA-MCP 9.2.0 with no `rest_command` services
   loaded. Therefore do not assume a reload can initialize it. Stop here until
   a Home Assistant restart has been separately authorized. This review does
   not authorize or perform that restart. For a completely separate HA test
   instance, its own startup can load this configuration instead.
7. After that approved initial load, confirm the four
   `rest_command.wine_tracker_staging_*` actions exist in **Tools → Actions**.
   Future edits can use `rest_command.reload` after a configuration check when
   that action exists. Confirm the logger level before sending any requests.

App options and HA `secrets.yaml` are separate stores: changing one does not
update the other. For rotation, change both privately and apply the relevant
staging-app restart / HA REST-command reload in an authorized session.

## 4. End-to-end Black Pig verification

Use only the `wine_tracker_staging_*` actions. Start with the fresh staging
database above. All example keys below identify **one test run**; preserve them
for retries. A new intentional test run should use a new suffix consistently,
and must account for any fixture already present. Do not use the live record
ID 25: always use the ID returned by staging.

### Create six bottles

Ask HA-MCP to call `ha_call_service` with exactly these secret-free arguments:

```json
{
  "domain": "rest_command",
  "service": "wine_tracker_staging_add",
  "return_response": true,
  "wait": false,
  "data": {
    "request_id": "staging-black-pig-create-001",
    "wine": {
      "producer": "The Black Pig",
      "name": "The Prize Shiraz",
      "year": 2023,
      "type": "Rotwein",
      "quantity": 6,
      "price": 12.50,
      "notes": "Classic Cellar commentary"
    }
  }
}
```

Expect `service_response.status: 201`, `content.ok: true` and
`content.wine.quantity: 6`. Record `content.wine.id`; assume **1 only for the
remaining examples**, replacing it if staging returns a different number.
The price is illustrative test data, not a claim about the real bottle.

### Consume one and append the exact note

```json
{
  "domain": "rest_command",
  "service": "wine_tracker_staging_stock",
  "return_response": true,
  "wait": false,
  "data": {
    "wine_id": 1,
    "request_id": "staging-black-pig-consume-001",
    "change": {
      "delta": -1,
      "notes": "black pig is easy drinking good value go to evening wine. It’s how I discovered i liked Syrah. - Justin"
    }
  }
}
```

Expect status 200, quantity **5**, and notes equal to `Classic Cellar
commentary`, two newlines, then the exact personal note. Price, identity and
other fields must remain unchanged.

### Repeat the identical request and read back

Repeat the **identical consume tool call**, including `request_id`, `wine_id`
and `change`. Expect status 200 and response header
`Idempotency-Replayed: "true"` (header names are case-insensitive). Then call:

```json
{
  "domain": "rest_command",
  "service": "wine_tracker_staging_get",
  "return_response": true,
  "wait": false,
  "data": {"wine_id": 1}
}
```

Expect `service_response.status: 200`, quantity still **5**, and the personal
note occurring **once**. This GET is important: a retry intentionally returns
the original snapshot, so the retry response alone cannot prove current stock.
There is one consumption timeline event. The isolated automated HTTP test also
checks that event directly in SQLite; staging intentionally exposes no legacy
timeline access or database files to the assistant.

For an additional conflict check, reuse `staging-black-pig-consume-001` but
change `delta` to `-2`: expect status 409 / `idempotency_conflict`. GET again;
quantity must remain 5. A 409 is not permission to silently generate a new key.

### Exercise the other supported actions

After recording the retry test result, use these inputs in separate
`ha_call_service` calls, always with domain `rest_command`,
`return_response: true`, and `wait: false`:

| Service | `data` | Expected change |
| --- | --- | --- |
| `wine_tracker_staging_stock` | `{"wine_id":1,"request_id":"staging-restock-001","change":{"delta":2}}` | 5 → 7 bottles |
| `wine_tracker_staging_update` | `{"wine_id":1,"request_id":"staging-note-001","changes":{"notes":"Second tasting — still good."}}` | Append, preserve previous notes |
| `wine_tracker_staging_update` | `{"wine_id":1,"request_id":"staging-details-001","changes":{"grape":"Shiraz / Syrah","rating":4,"drink_until":2030}}` | Only these fields change |
| `wine_tracker_staging_update` | `{"wine_id":1,"request_id":"staging-replace-001","changes":{"notes":"Replacement in staging only.","notes_mode":"replace"}}` | Deliberately replace notes |

Read with `wine_tracker_staging_get` after each call and summarize what changed.
The same calls can be run manually in **Tools → Actions** using the action name
and `data` mapping; the `domain`, `service`, `wait` and `return_response` envelope
above is specifically for HA-MCP, not the UI action YAML.

### Negative checks and troubleshooting

- From another machine, the staging app must have no LAN-facing port. Do not
  probe the existing app's port 5050 with writes. Confirm no mapping in the
  staging manifest/UI instead; a LAN 5050 listener could be the existing app.
- A secret-free GET of staging `/api/v1/wines/1` must return 401. A secret-free
  GET of staging `/api/summary` must also return 401. An authorized diagnostic
  client on the internal network can perform these read-only checks; the
  shipped local tests cover legacy write rejection without probing live data.
- 401 from a REST command: the two private token values differ; check them
  locally. 503 `api_disabled`: staging has not loaded a valid token. Neither
  case should be fixed by disabling authentication.
- DNS/connection error: check the app ID is `local_wine_tracker_api_staging`
  and it is running. The internal name is not resolvable from a normal LAN
  computer. Do not add a public port to work around an internal DNS problem.
- Missing `service_response`: require `return_response: true`; do not infer
  success from a generic tool acknowledgment.
- No local app in the store: check folder nesting and `config.json`, then
  refresh the app store. Do not add the fork as an ordinary replacement
  repository: that would expose its existing production/dev app definitions.

## Direct-port security review and future production boundary

The existing release manifest publishes 5050 by default, and `AUTH_ENABLED`
defaults to false in HA mode. `/add`, `/edit`, `/delete`, import, chat writes
and other legacy mutation routes are therefore not secured by the new API
token. Ingress routing headers are not authentication. This is a pre-existing
exposure; configuring `wine_api_token` alone does not repair it.

Recommended controls, as a separate authorized production change:

1. Remove the live app's host mapping for `5050/tcp` in its Network settings
   (blank/disabled, not port zero); retain ingress. Review any direct-port
   sensors/clients before changing their URLs. Remove router forwarding and
   untrusted reverse-proxy routes. Applying an existing app's network change
   may require restarting it, so **do not do this during this review**.
2. Recognize that other apps can still reach container port 5050 internally.
   For protection against those clients, enforce application authentication on
   legacy routes too. The staging manifest already demonstrates the existing
   supported `AUTH_ENABLED=true` mechanism. No users means API-only operation.
   For a future production deployment requiring the UI, configure strong
   standalone UI credentials (`USERS`) and a persistent `SECRET_KEY` privately
   through a supported deployment configuration; keep the machine credential
   separate. Browser login also applies under ingress. The current HA app does
   not expose these environment settings as options: do not invent options in
   its Configuration tab. Maintainer-supported auth wiring or a separately
   reviewed deployment manifest is needed before promoting this pattern with
   the UI. Do not change existing production behavior silently in this API PR.
3. Keep credentials off untrusted HTTP paths. A reverse proxy alone protects
   nothing if clients can reach its unauthenticated backend directly. Never
   use `X-Ingress-Path`, `X-Forwarded-For` or a claimed user header as proof of
   authorization. Do not solve integration problems by turning auth off.

The minimal PR can therefore be reviewed independently of a broader UI-auth
change. Staging is fully protected as specified above. A production rollout
should wait until its complete legacy-route/network boundary has been decided;
closing only the LAN mapping is not equivalent to authenticating all routes.

## Validation, maintenance and removal

- No production application logic, wine schema or runtime dependency changes
  were needed for this integration review. The source package is generated;
  there is no third maintained copy of the app.
- Tests parse the actual YAML, render its templates and send requests over a
  loopback HTTP server backed by temporary SQLite. They check create, consume,
  replay, readback, restock, append/replace, Unicode, fixed-host behavior,
  legacy auth rejection and staging isolation/reproducibility. `PyYAML` is a
  test-only dependency in `requirements-test.txt`; it is not in the app image.
- These tests simulate the documented HA template/action boundary. They do
  not run HA Core, its Supervisor or the user's MCP transport. Docker/HA app
  image construction and actual internal DNS routing remain staging checks;
  no Docker runtime is available in the review workspace.
- To run all tests locally: from `wine-tracker/`, install `requirements.txt`
  and `requirements-test.txt`, then run `python -m pytest tests -q`. Loopback
  networking must be allowed for the two local HTTP tests. No live credentials
  are needed. GitHub PR CI runs the same suite.
- Later removal: stop/uninstall **only Wine Tracker API Staging**, remove its
  local `/addons/wine_tracker_api_staging` source folder, remove this package
  and only its matching secret entry, then validate and reload REST commands
  where available. Remove its explicit package include if one was added.
  Removing staging storage discards only test data. Never delete anything
  under `/share/wine-tracker/` or uninstall the existing Wine Tracker app.

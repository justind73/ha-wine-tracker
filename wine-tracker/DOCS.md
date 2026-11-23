# Application reference

This guide covers the original Wine Tracker UI, optional built-in AI and
standalone/development configuration. The application is by
[xenofex7](https://github.com/xenofex7/ha-wine-tracker), under the [MIT licence](../LICENSE).
For this fork's ChatGPT integration, start with the [overview](../README.md)
and [production HA-MCP guide](PRODUCTION.md). The original author's
[documentation and demo](https://xenofex7.github.io/ha-wine-tracker/) cover upstream,
not this fork's API or installation.

**Two separate AI workflows:** the in-app sommelier and label analysis call a
configured provider directly. ChatGPT/HA-MCP calls our authenticated inventory
API through HA REST commands and does not require that provider configuration.
Only the former has the original UI's delete workflow; `/api/v1` has no delete route.

## Inherited screenshots

These screenshots were supplied with the original application. They illustrate
the UI, not the fork's HA-MCP setup or current photo-fit/About changes.

![Original cellar overview](../assets/261018_main_screen.png)

<details>
<summary>Statistics, adding and editing wines</summary>

![Original statistics with globe and charts](../assets/261018_statistics_screen.png)
![Original add-wine screen](../assets/261018_add_wine_screen.png)
![Original edit-wine screen](../assets/261018_wine_edit_screen.png)

</details>

## Original application features

- **Wine cards** with photo, vintage, type, region, grape variety, rating and notes
- **AI wine label recognition** can suggest details, including maturity phases, taste profile and food pairings (Anthropic, OpenAI, OpenRouter, Ollama, MiniMax, Mistral)
- **AI sommelier chat with full cellar CRUD** - ask about your cellar, upload label photos, and add, edit or delete wines when **Edit wines via chat** is enabled; sessions persist
- **Vivino wine search** - search by name, see ratings, region and price, and import directly; a regional fallback chain surfaces country-specific wines
- **Vivino ID management** - view, edit and test Vivino wine links in the edit modal
- **Reload missing data** - re-analyze wines with incomplete fields via AI or Vivino
- **Star rating** (1-5), quick `+`/`-` quantity buttons and wine duplication
- **Bottle format** from Piccolo (0.1875 l) to Nebuchadnezzar (15 l), AI can suggest the format
- **Cellar view modes** - Cards, List, Grid and a sortable Table view with responsive columns
- **Quick filter** by wine type, vintage year and grape variety
- **Advanced filter** - AND-combined conditions across every field, with text, number, choice and drink-window operators and autocomplete in the inputs
- **Filter presets** - save a filter set under a name, reuse it later, and make the advanced filter the default one
- **Activity timeline** - chronological log of wines added, consumed, restocked and removed
- **Maturity graph** - AI-generated bell curve from Youth to Maturity, Peak and Decline, with a "Today" marker
- **Taste profile and food pairings** - AI-generated body/tannin/acidity/sweetness bars and matching dishes in your language
- **Drink window** (from/until year) with AI estimation
- **Purchase price** with configurable currency
- **Autocomplete** for region, grape variety, purchase source and storage location
- **Interactive 3D globe** showing your wine regions
- **Statistics** - donut charts, stock history area chart, total bottles, total liters, value overview and average age
- **Backup and restore** - export wines, timeline and referenced wine images as a ZIP (JSON + CSV + images) and import it back with a duplicate preview
- **6 themes** with dark and light mode
- **7 languages**: DE, EN, FR, IT, ES, PT, NL
- **Fully responsive** - desktop, tablet and mobile

## Using the UI

Use **+** to add a wine manually, search/import from Vivino, or upload a label
for analysis by the configured built-in AI. AI enrichment can suggest maturity
phases, a taste profile and food pairings; it is not a guarantee of correct wine
identification or drinking advice. Vivino is a separate external lookup, not
part of the machine API and not dependent on a built-in AI provider key.

Zero-stock records remain in the inventory; the **Show empty bottles** setting
controls their visibility. The header's quick filter covers type, vintage and grape. Advanced-filter
conditions are AND-combined; save frequently used sets as named presets.
Open a wine to see details and its full photograph; the fork's information icon
shows available source/rights metadata. The wine-glass placeholder means no
photograph is attached. See [photograph handling](PHOTOGRAPHS.md) for research,
matching and local storage through ChatGPT.

## Configuration

For HA, use the app's Configuration tab. Standalone Docker uses environment
variables. Environment values override HA options; nonempty AI settings saved
under **Settings → AI** override both. The app also provides a provider connection
test. Saved AI settings live in the database and may contain provider credentials,
so protect complete database backups. This precedence does not replace the
separate `wine_api_token`/HA-secrets setup in [API.md](API.md).

### General options

| HA option | Environment | Default | Purpose |
| --- | --- | --- | --- |
| `currency` | `CURRENCY` | `CHF` | Price display and Vivino region lookup. Supported region mappings: CHF, EUR, USD, GBP, CAD, AUD, SEK, NOK, DKK, PLN, CZK and BRL; other currencies fall back to US/USD for Vivino. |
| `language` | `LANGUAGE` | `de` | UI language: de, en, fr, it, es, pt, nl |
| `wine_api_token` | `WINE_API_TOKEN` | empty | Separate machine credential; see [API authentication](API.md#enable-and-authenticate). An explicitly empty environment value disables the API. |

### Optional built-in AI

Pick one provider for label recognition, enrichment and in-app sommelier chat.
External providers need their own API key; local Ollama needs a reachable server
and installed model. These are **not** the ChatGPT/HA-MCP settings.
OpenAI API billing is separate from ChatGPT subscription billing; do not assume
a subscription automatically provides usable API credit or configures a key.
See [OpenAI's billing guidance](https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform).

The table records defaults in [config.yaml](config.yaml) and
[`load_options()`](app/app.py) at build **1.11.0-api.6**. Model names are shipped
configuration values, not verified promises of current availability, image
support or pricing. Check your provider's model documentation and use the app's
connection test; image analysis needs a model that accepts images.

| Option | ENV | Default | Description |
|--------|-----|---------|-------------|
| `ai_provider` | `AI_PROVIDER` | `none` | `none`, `anthropic`, `openai`, `openrouter`, `ollama`, `minimax`, `mistral` |
| `anthropic_api_key` | `ANTHROPIC_API_KEY` | _(empty)_ | Key from [console.anthropic.com](https://console.anthropic.com) |
| `anthropic_model` | `ANTHROPIC_MODEL` | `claude-opus-4-8` | Anthropic model identifier |
| `openai_api_key` | `OPENAI_API_KEY` | _(empty)_ | Key from [platform.openai.com](https://platform.openai.com) |
| `openai_model` | `OPENAI_MODEL` | `gpt-5.5` | OpenAI model identifier |
| `openrouter_api_key` | `OPENROUTER_API_KEY` | _(empty)_ | Key from [openrouter.ai](https://openrouter.ai) |
| `openrouter_model` | `OPENROUTER_MODEL` | `anthropic/claude-opus-4.8` | OpenRouter model identifier |
| `ollama_host` | `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `ollama_model` | `OLLAMA_MODEL` | `llama3.2-vision` | Installed Ollama model identifier |
| `minimax_api_key` | `MINIMAX_API_KEY` | _(empty)_ | Key from [platform.minimaxi.com](https://platform.minimaxi.com) |
| `minimax_model` | `MINIMAX_MODEL` | `MiniMax-M3` | MiniMax model identifier |
| `mistral_api_key` | `MISTRAL_API_KEY` | _(empty)_ | Key from [console.mistral.ai](https://console.mistral.ai) |
| `mistral_model` | `MISTRAL_MODEL` | `mistral-medium-latest` | Mistral model identifier |
| `chat_model` | `CHAT_MODEL` | _(empty)_ | Separate model for the sommelier chat only. Empty means the chat uses the model above. |

For Ollama, pull your chosen image-capable model on the Ollama server and set
`ollama_host` to an address reachable **from Wine Tracker's container**.
`localhost` there refers to Wine Tracker itself. A shared-network container name,
or `host.docker.internal` where the Docker host supports it, may be appropriate.
The app's local Ollama adapter does not require an API key.

`chat_model` selects a separate model on the same provider for sommelier chat;
empty uses the provider model. Choose one that supports the inputs you intend
to send, including photos when using chat uploads. Provider costs and capability
claims are deliberately not pinned here; consult the provider's current terms.

### Standalone environment and accounts

[`.env.example`](../.env.example) retains the upstream environment reference.
Replace its example passwords/session key before use. It is not a fork deployment
recipe; configure `WINE_API_TOKEN` separately if using the machine API.

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTH_ENABLED` | `false` in code | Set `true` for standalone browser login. Keep it enabled. |
| `USERS` | empty | Comma-separated `username:password` or `username:password:readonly` entries. |
| `SECRET_KEY` | random at startup | Set a strong, persistent private session-signing key so logins survive restarts. |
| `DATA_DIR` | `/data/wine-tracker` in the Docker image | Database and uploads inside the persistent `/data` volume. |
| `WINE_API_TOKEN` | empty | Independent credential for all `/api/v1` requests; browser login does not substitute for it. |
| `WINE_TRACKER_BUILD_VERSION` | unset | Optional reviewed build identifier for About; otherwise it displays a development-build label. |

Readonly accounts can browse/search/export but cannot add, edit or delete.
The machine credential does not secure legacy browser routes. Standalone login
also exempts uploaded-file serving, so do not treat it as access control for
photo URLs; keep the whole service behind a trusted access boundary. See
[API security](API.md#enable-and-authenticate) for the separate network/auth rules.

## Standalone Docker alternative

For deployments **outside Home Assistant**, build the reviewed fork source:

```sh
git clone https://github.com/justind73/ha-wine-tracker.git
cd ha-wine-tracker
# Select/review the intended commit before building.
docker build -f docker/Dockerfile -t wine-tracker-fork .
```

The inherited [Compose example](../docker/docker-compose.yml) pulls an upstream
image by default. Do not run it unchanged expecting this fork's API. In your
own deployment configuration, use the locally built `wine-tracker-fork` image,
a dedicated named volume mounted at `/data`, `AUTH_ENABLED=true`, your own
`USERS`, a strong persistent `SECRET_KEY`, and optional provider/API settings.
Keep credentials in private configuration outside Git.

Use a private Docker network and your existing authenticated HTTPS reverse
proxy/access boundary; do not copy the inherited host-port publication into an
HA setup or disable authentication. This guide does not provision a proxy.
The HA command package targets the HA app's internal hostname and is not a
standalone Docker configuration. The upstream published image also lacks the
fork's ingress guard and JSON API changes.

Never mount the live HA `/share/wine-tracker/` into a second running instance.
For an update, back up consistently, rebuild the reviewed source and recreate
only the standalone container while retaining its dedicated volume. The
[maintenance guide](UPSTREAM_MAINTENANCE.md) explains review/testing and version
handling, including why the standalone Dockerfile does not supply About's build
identifier automatically.

## Backups and data persistence

HA uses `/share/wine-tracker/`; standalone Docker uses `/data/wine-tracker/`
inside its persistent volume. Both contain `wine.db` and `uploads/`.

**Settings → Data → Export backup** produces a ZIP containing authoritative wine
JSON, timeline JSON, an informational CSV and referenced wine images. Import
shows a duplicate preview. Images that are missing on disk cannot be included;
check the archive rather than assuming it contains every referenced photograph.
Photo provenance embedded by the fork is retained in exported JPEGs.

ZIP exports omit the database itself, API retry receipts, saved AI settings,
chat sessions/messages and filter presets. Keep a consistent private copy of
the complete data directory while Wine Tracker is stopped, plus the app/HA
configuration, for rollback. See [production backup and rollback](PRODUCTION.md)
and [API retry caveats](API.md#endpoints-and-retries). Do not restore old data
over newer genuine cellar changes without reconciling them.

## Legacy summary endpoint

Upstream exposes `/api/summary` with `total_bottles` and `by_type` fields.
The old `http://localhost:5050/api/summary` REST-sensor example is **not a usable
configuration for this fork's ingress-only HA app**: no host port is published,
and the legacy route requires the actual Supervisor ingress peer.

In standalone mode with `AUTH_ENABLED=true`, that route requires a browser
session. It does not accept `X-Wine-API-Key` or HTTP Basic authentication; merely
adding a password to the old sensor YAML would not fix it. `localhost` also
refers to the calling process/container, not automatically to Wine Tracker.
The endpoint is retained for existing appropriately secured standalone clients,
but no drop-in HA sensor configuration is provided. Do not expose port 5050 or
weaken authentication for it. Use the [six authenticated HA commands](PRODUCTION.md#the-six-production-commands)
for this fork; a scoped summary endpoint remains a [roadmap idea](../ROADMAP.md).

## Local development and tests

Use Python 3.12 (matching CI) in a virtual environment. From the repository root:

```sh
python -m venv .venv
# Activate .venv using the command appropriate to your shell.
python -m pip install -r wine-tracker/requirements.txt -r wine-tracker/requirements-test.txt
python -m pytest wine-tracker/tests -q
git diff --check
```

Tests use disposable databases and loopback HTTP, with no production credentials.
For a local UI run, set `DATA_DIR` to a dedicated development directory and set
`DEV_AUTH` to a private test `username:password`, then run
`python wine-tracker/app/app.py`. `DEV_AUTH` enables standalone login; without
explicit authentication the upstream local server can start unauthenticated.
Keep local development private and never point it at the live cellar. An
explicit `DATA_DIR` avoids accidentally selecting `/share/wine-tracker` on a
machine where `/share` exists.

Use a `codex/` branch and open a PR in this fork. Follow the inherited commit
style: Add, Fix, Update, Remove, Refactor or Polish, imperative subject up to
72 characters. Run relevant tests for application changes and the full suite
before merging. The [test workflow](../.github/workflows/tests.yml) runs for
PRs and pushes to `main`; the separate tag-triggered Docker publication workflow
is not a production HA deployment. Do not push upstream `v*` tags casually.
The upstream-generated `wine-tracker-dev` tree is not a staging installation to
create or maintain for ordinary fork work.

## Troubleshooting

- **ChatGPT cannot see Wine Tracker:** installation alone is insufficient.
  Verify your separate HA-MCP connection, loaded REST actions and their returned
  HTTP status/content using the [production guide](PRODUCTION.md). Configuring a
  built-in AI provider does not create an MCP connection.
- **An API write may have timed out:** retain its request ID and exact payload;
  retry with those values, then GET the record. A new ID can repeat the change.
- **AI settings appear ignored:** nonempty values saved in Settings → AI take
  precedence over app options/environment. Inspect the app settings first.
- **Label analysis fails:** verify key, provider/model availability and image
  support. A successful text connection test alone does not prove image support.
- **Ollama is unreachable:** check the address from the Wine Tracker container;
  `localhost` is not the host or a separate Ollama container.
- **Sidebar is missing:** check the app's sidebar setting and the HA user's
  permissions. Use authenticated Open Web UI; do not bypass ingress by opening
  a direct port. Standalone deployment is a separate installation choice.
- **Standalone logins disappear after restart:** preserve a private `SECRET_KEY`
  rather than allowing a fresh session-signing key on every startup.

Copyright (c) 2026 xenofex7. The original [MIT licence](../LICENSE) applies.

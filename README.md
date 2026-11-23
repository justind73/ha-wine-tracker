# Wine Tracker — Justin's fork

[![Fork build](https://img.shields.io/badge/fork-1.11.0--api.6-blue)](wine-tracker/config.yaml)
[![Tests](https://github.com/justind73/ha-wine-tracker/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/justind73/ha-wine-tracker/actions/workflows/tests.yml)
[![MIT licence](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Wine Tracker is a wine inventory application for Home Assistant: keep track of
bottles, photographs, purchase details, tasting notes and drinking windows.
The original application is by **[xenofex7](https://github.com/xenofex7/ha-wine-tracker)**.

## About this fork

[This fork](https://github.com/justind73/ha-wine-tracker) adds an authenticated
JSON inventory API and Home Assistant REST commands so ChatGPT can work with
your actual cellar. You can discuss what to drink, record a purchase or an opened
bottle, and verify the result without manually re-entering the same information.
The original application, Git history and MIT copyright notices are retained.

**Original application version: 1.11.0. Custom build: 1.11.0-api.6.**
The build comes from [the HA app configuration](wine-tracker/config.yaml);
Wine Tracker's About screen shows both versions. See the
[fork changelog](wine-tracker/CHANGELOG.md) for release details.

## ChatGPT + Home Assistant

```text
ChatGPT → Home Assistant MCP (HA-MCP) → Home Assistant REST commands
        → authenticated Wine Tracker JSON API → Wine Tracker database
```

Home Assistant calls six fixed commands with its locally held API credential.
ChatGPT supplies wine data and operation identifiers; the Wine Tracker secret
stays out of conversations and tool arguments.

With an appropriately configured HA-MCP connection, ChatGPT can:

- Read the collection and find wines by examining the returned records.
- Recommend wines from your stock and discuss food pairings, producers and
  drinking windows using its own knowledge and available research tools.
- Create wine records, add or consume bottles, append or replace tasting notes,
  and update supported details such as price, rating and drinking years.
- Identify suitable bottle photographs and attach them with source and rights
  metadata. Wine Tracker validates and stores the actual image locally.
- Read records back to verify changes and summarise what happened.

The API provides paginated listing, individual reads and validated writes.
It does **not** provide wine advice, text-search queries, merchant scraping,
order recognition, email access or record deletion. ChatGPT handles interpretation
and research outside Wine Tracker; matching an ambiguous wine may need clarification.
The image endpoint fetches a caller-selected image, not search results.

Writes are **idempotent**: retrying the same operation with the same request ID
and payload does not consume a second bottle or append the same note again.
A new ID is a new operation; clients must retain IDs across uncertain retries
and read back current records. See the [API contract](wine-tracker/API.md).

### Example conversations

- “Which of my wines would pair best with grilled lamb?”
- “What Côte-Rôtie do I currently have?”
- “I've opened a bottle of this wine. Update my stock.”
- “Which bottles are approaching their drinking window?”

These illustrate workflows, not guarantees of autonomous recognition or action.
The assistant needs access to the relevant records and tools. An order you
supply can inform new records and received stock; this integration does not
fetch your email automatically. The [photograph and order guide](wine-tracker/PHOTOGRAPHS.md)
explains matching, stable retry IDs and read-back summaries. Image rights are
caller-supplied metadata: unknown rights remain unverified, and private use
does not itself grant permission to copy a photograph.

## Features inherited from Wine Tracker

The original application provides:

- Inventory and stock management, bottle formats, locations, prices, ratings,
  photographs, notes and an activity timeline.
- Drinking windows, maturity and taste visualisations, statistics and a region globe.
- Cards, list, grid and table views; search, quick filters and saved advanced filters.
- Import/export and ZIP backups containing wine data, history and wine photographs.
- Six themes, light/dark modes and seven languages: German, English, French,
  Italian, Spanish, Portuguese and Dutch.
- Vivino search/import and optional built-in AI label recognition, enrichment
  and sommelier chat.

[Usage, configuration and inherited screenshots](wine-tracker/DOCS.md) describe
these features. AI-generated details depend on a configured provider and should
be checked against the bottle or source.

## Installation and requirements

### Home Assistant (primary installation)

There are three separate pieces:

| Piece | What it needs |
| --- | --- |
| Wine Tracker app | Home Assistant with Supervisor/app support, on an architecture listed in [config.yaml](wine-tracker/config.yaml). No AI provider is required for manual inventory management. |
| ChatGPT connection | A separately configured, authenticated HA-MCP connection that can call the six REST actions and return their responses. Wine Tracker does not install this connection. |
| Machine API | A generated Wine Tracker API credential, configured in the app and HA secrets, plus the native REST-command package. The API is disabled until configured. |

1. Add `https://github.com/justind73/ha-wine-tracker` to the Home Assistant app
   store repositories. Install **Wine Tracker** from **Wine Tracker — Justin's fork**.
2. If replacing another Wine Tracker installation, first back up its data and
   stop it. Both use `/share/wine-tracker/`; **never run two apps against that database**.
3. Start the fork and open it through Home Assistant's **Open Web UI** or sidebar.
   This HA app is **ingress-only and publishes no host port**. HA authenticates
   browser access; the machine API independently requires its own credential.
4. For ChatGPT access, follow the [production setup guide](wine-tracker/PRODUCTION.md):
   configure the credential privately, install the
   [six production commands](wine-tracker/PRODUCTION.md#the-six-production-commands),
   and verify list/get through your HA-MCP connection. Do not put the credential
   in ChatGPT messages, tool arguments or Git.

**Installing Wine Tracker alone does not connect it to ChatGPT.** Leave the
built-in AI provider set to `none` if you only want the ChatGPT/HA-MCP workflow.
Do not expose port 5050 or bypass ingress to enable the integration.

### Backups and updates

Data lives at `/share/wine-tracker/wine.db` and `/share/wine-tracker/uploads/`.
The standard ZIP export contains wine/timeline JSON, a CSV and referenced wine
images, including embedded photo provenance. It is **not a full database snapshot**:
API retry receipts, app settings, chat history and filter presets are not exported.
CSV alone does not preserve photographs.

For rollback, also keep a consistent private copy of the complete data directory
while Wine Tracker is stopped, plus its configuration. This preserves retry
receipts; after restoring a ZIP or an older snapshot, reconcile records before
retrying old requests. Follow the [production verification and rollback guide](wine-tracker/PRODUCTION.md#verification-and-rollback).
Install reviewed, tested fork updates using the
[maintenance procedure](wine-tracker/UPSTREAM_MAINTENANCE.md); upstream changes
are not automatically merged or deployed.

### Standalone Docker (alternative)

The fork can also be built from source with the standalone Dockerfile. Follow
the [standalone instructions](wine-tracker/DOCS.md#standalone-docker-alternative)
for a separate persistent volume, browser authentication and API configuration.
The inherited Compose file references an upstream image; that image does not
include this fork's API. Standalone Docker is not the HA ingress installation.

## Optional built-in AI — separate from ChatGPT/HA-MCP

The original Wine Tracker UI has its own AI label recognition, enrichment and
sommelier chat. It calls **OpenAI, Anthropic, OpenRouter, Ollama, MiniMax or
Mistral**, as configured in **Settings → AI**. Those features use the selected
provider directly, independently of HA-MCP.

**You do not need to configure that provider to use our ChatGPT integration.**
External providers require their own API access/key; a local Ollama setup needs
a reachable server and a suitable installed model. Model availability and image
support depend on the provider and chosen model. A ChatGPT subscription does
not automatically configure or fund Wine Tracker's OpenAI API access; check
[OpenAI's separate billing guidance](https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform).

See the [built-in AI reference](wine-tracker/DOCS.md#optional-built-in-ai)
for configuration defaults, precedence and troubleshooting. The original
sommelier can edit/delete when its **Edit wines via chat** setting is enabled;
the scoped HA-MCP API has **no deletion operation**.

## Development and maintenance

| Guide | Contents |
| --- | --- |
| [Application reference](wine-tracker/DOCS.md) | UI usage, screenshots, provider settings, standalone Docker, local development and tests |
| [Production setup](wine-tracker/PRODUCTION.md) | HA installation, six commands, secrets, verification and rollback |
| [JSON API](wine-tracker/API.md) | Authentication, supported fields, validation and safe retries |
| [Photographs and orders](wine-tracker/PHOTOGRAPHS.md) | Local storage, provenance, rights and supplier-independent workflows |
| [Upstream maintenance](wine-tracker/UPSTREAM_MAINTENANCE.md) | Review upstream changes, resolve conflicts, test and update deliberately |
| [Proposed upstream contribution](wine-tracker/UPSTREAM_CONTRIBUTION.md) | A focused generic API contribution, excluding local configuration; not submitted |
| [Roadmap](ROADMAP.md) | Delivered fork features and remaining ideas inherited from upstream |

The [test workflow](.github/workflows/tests.yml) runs on pull requests and pushes
to `main`. Development/tests use separate local data, never the live cellar.
Documentation-only maintenance does not need a new app version or deployment.

## Licence and attribution

Original Wine Tracker: **[xenofex7/ha-wine-tracker](https://github.com/xenofex7/ha-wine-tracker)**.
Custom fork: **[justind73/ha-wine-tracker](https://github.com/justind73/ha-wine-tracker)**.

Copyright (c) 2026 xenofex7. Distributed under the [MIT licence](LICENSE);
the original copyright and licence notices remain unchanged.

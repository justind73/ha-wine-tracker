# Home Assistant App: Wine Tracker — Justin's fork

Wine Tracker by **[xenofex7](https://github.com/xenofex7/ha-wine-tracker)** manages
wine inventory, photographs, notes, drinking windows, statistics and backups
inside Home Assistant. This [custom fork](https://github.com/justind73/ha-wine-tracker)
retains the original application and MIT licence.

**Original version: 1.11.0. Fork build: [1.11.0-api.6](config.yaml).**
The build version is defined in `config.yaml` and displayed separately in About.

## What the fork adds

ChatGPT can read and update the live cellar through HA-MCP, native Home Assistant
REST commands and an authenticated JSON API. It supports listing/reading wines,
creating records, consuming/restocking bottles, updating notes/details and
attaching locally stored photographs with provenance. Writes have retry protection.
The API does not delete records or perform wine/merchant research.

The original UI's optional AI label recognition, enrichment and sommelier chat
are separate features. They use a configured external provider or local Ollama;
**they need not be enabled for ChatGPT/HA-MCP**. Installing the app alone does
not establish a ChatGPT connection.

## Setup and documentation

- [Fork overview and installation](../README.md#installation-and-requirements)
- [Production HA-MCP setup and six REST commands](PRODUCTION.md)
- [Machine API and security](API.md)
- [Photographs and supplier orders](PHOTOGRAPHS.md)
- [Original UI usage, screenshots and optional AI configuration](DOCS.md)
- [Upstream maintenance](UPSTREAM_MAINTENANCE.md) and [release history](CHANGELOG.md)

Install **Wine Tracker** from **Wine Tracker — Justin's fork** in the HA app
store. This build uses authenticated ingress and exposes no host port.
Data is stored in `/share/wine-tracker/`; stop any previous Wine Tracker instance
before starting the fork against that directory. Follow the production guide's
ZIP and complete-data backup steps before switching or updating.

Copyright (c) 2026 xenofex7. See the unchanged [MIT licence](../LICENSE).

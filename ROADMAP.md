# Roadmap and implementation status

This fork retains the [original project's roadmap](https://github.com/xenofex7/ha-wine-tracker/blob/main/ROADMAP.md)
as a record of upstream ideas, with status clarified against **1.11.0-api.6**.
The remaining ideas below are not new commitments, deadlines or a priority
order for this fork. See the [overview](README.md) for installation and scope.

## Delivered by this fork

- Authenticated JSON API: list the collection, read individual wines, create
  records, adjust stock and update supported details/tasting notes.
- Durable idempotent writes: identical retries do not repeat successful stock
  movements or notes. Clients must reuse the original request ID and payload.
- Six native Home Assistant REST commands for HA-MCP, keeping the credential in
  HA secrets; ingress-only browser access with no published host port.
- Generic photograph attachment with local storage, source/rights metadata and
  a photo-information display. ChatGPT supplies research and matching;
  Wine Tracker has no merchant-specific order integration.
- Separate original/build versions in About, fork/upstream links, and full-bottle
  rendering in overview thumbnails and detail modals.

The [API](wine-tracker/API.md), [production](wine-tracker/PRODUCTION.md) and
[photograph](wine-tracker/PHOTOGRAPHS.md) guides describe the implemented contracts.
A [focused API contribution](wine-tracker/UPSTREAM_CONTRIBUTION.md) is proposed
for discussion with the original author; no upstream submission has been made.

## Already inherited from upstream

Inventory/stock management, photographs, drinking windows, search and saved
advanced filters, statistics/visualisations, ZIP import/export, themes/languages,
Vivino integration and optional built-in AI are original application features.
The UI also already handles `Esc` to close overlays and keyboard activation of
interactive controls. See the [application reference](wine-tracker/DOCS.md).

## Remaining ideas from the upstream roadmap

### Statistics and Home Assistant

- **Spending trends** — spending by month, region or wine type.
- **Maturity calendar** — an overview of which wines become drinkable each year.
- **Drink-window notifications** — HA alerts when wines enter or leave a window.
- **Additional machine API endpoints** — scoped statistics and collection export
  for dashboards/automations. Individual reads and inventory writes are already
  delivered; the legacy `/api/summary` and browser export are separate routes,
  not authenticated `/api/v1` statistics/export operations.
- **HA dashboard card** — a native Lovelace card for wine statistics.

### UI and data

- **Additional keyboard shortcuts** — `/` to search and `+` to add; `Esc` already exists.
- **Wishlist mode** — wines to buy, separate from owned stock.
- **Tags and custom categories** — labels such as gift or special occasion.
- **Bulk editing** — update multiple wines' location, type or category together.
- **Multiple cellars** — distinct collections for different locations.
- **Chat history in export** — optional chat sessions/messages/images in ZIP backups.
- **Filter presets in export** — saved advanced-filter sets with re-import support.

### Mobile and sharing

- **PWA support** — phone installation with offline access.
- **Barcode/QR scanning** — look up wines through Vivino.
- **Shareable collection link** — a read-only link or QR code for friends.

Upstream ideas may change or never ship. Incorporating upstream work follows
our [review, test and update procedure](wine-tracker/UPSTREAM_MAINTENANCE.md),
not an automatic merge or deployment.

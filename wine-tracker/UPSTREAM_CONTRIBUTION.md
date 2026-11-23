# Proposed contribution: authenticated JSON inventory API

Recommendation: approach xenofex7 first with a small, optional machine API for
Home Assistant REST commands and other clients. Offer the core inventory API
and its tests as one focused PR after the author agrees on scope. Do not propose
merging our fork wholesale. No upstream PR, issue or message has been submitted.

Suggested message for the user to send:

> Thank you for Wine Tracker. I have a working fork with an optional authenticated
> JSON API for creating wines, reading records, adjusting stock and updating
> tasting notes. Writes use durable idempotency keys so a retried request cannot
> consume or add bottles twice. It is disabled until a separate token is configured,
> preserves the existing UI/data format, and has automated security/concurrency
> tests. Would you be interested in a small PR containing the core API and tests,
> without my installation configuration, fork branding or photo-download feature?

## Scope of the first PR

Four operations: `POST /api/v1/wines`, `GET /api/v1/wines/<id>`,
`PATCH /api/v1/wines/<id>`, and `POST /api/v1/wines/<id>/stock`.
Keep token authentication independent of browser login, fail closed when disabled,
reject readonly-session writes, and preserve atomic stock/notes/history/receipt
updates. No new runtime dependency or replacement wine schema is necessary;
`api_requests` is one additive table in the existing database.

Explain limits honestly: a single token has inventory-wide access; idempotency
requires reusing the same key/body; receipts grow and are not in normal ZIP exports;
no order recognition or secret management service is included. HTTP transport
needs a trusted network or TLS termination. This authenticates the new routes,
not every legacy write route. Existing browser-route exposure deserves a separate
security discussion with the maintainer; do not imply the token protects it.

## Commits and files to extract

These are the exact reusable starting points in our fork history:

| Commit | Candidate content | Treatment |
| --- | --- | --- |
| `1c2734c2d13f1b6c005771288dc8a568b2e85533` | `wine-tracker/app/wine_api.py`; small `app.py` integration; two token-option/schema entries in `wine-tracker/config.yaml` | Core API. This commit predates our HA deployment changes and photographs. Keep its independent authentication, PATCH readonly check, empty-token override, DB initialization and blueprint registration together. |
| `e7e7ebb6cbe911967990478aa2e716a9dad806f5` | `wine-tracker/tests/test_write_api.py`; `.github/workflows/tests.yml` | Core auth/validation/concurrency/replay/export tests. Retain the fixture's illustrative wines only in temporary databases. Adapt CI to the maintainer's preferred workflow instead of duplicating it if they already added one. |
| `39b13aa57af57849d58f6e35690c4fdb2f9e1e2a` | Selected generic sections of `wine-tracker/API.md`, and minimal links in README/DOCS/changelog | Rewrite for the agreed upstream contract. Exclude its photograph proposal and obsolete deployment wording. Do not cherry-pick all documentation blindly. |

The original `wine_api.py` is self-contained (307 lines), and the core test file
is 388 lines. The first implementation changes `app.py` by only the import,
configuration/authentication hooks, receipt-table initialization and blueprint
registration; its manifest patch adds only `wine_api_token` and its password schema.
Review those original patches against the author's current main before applying.

Do **not** copy today's `wine_api.py` unchanged for this first PR: it imports
`wine_images.py` and has the later image/list contracts. Use the core historical
commit above to avoid accidentally bringing those dependencies into the PR.
A generic read-only list endpoint can be discussed as a small addition if the
author wants it; photo retrieval should remain a separate proposal.

Exclude these from the focused contribution:

- `871d63e`, `c5293f0`, `d6afe45`, `26de3ed`, `4adad55`: staging and HA deployment
  work/history. Do not carry their temporary installation material upstream.
- `58b35db`: our production wiring, fork store identity/URLs, deployment guide,
  security environment/port choices and publication namespace. Discuss useful
  general ingress hardening separately instead of sending our installation wholesale.
- `2e1d027`: photo retrieval/storage, source/rights metadata, image tests, list/image
  HA commands and their documentation; later scope only with the author's agreement.
- The About/build branding changes, our `repository.yaml`, fork release versions,
  `PRODUCTION.md`, `PHOTOGRAPHS.md`, `API_PHOTOS_PROPOSAL.md`, these maintenance/
  contribution notes, private `.artifacts`, credentials and actual cellar data.
- `examples/home-assistant/wine_tracker.yaml` as it stands: its hostname/app slug
  is specific to our installation. If requested, write a short generic example
  with the destination configured once by the installer and the token in HA secrets;
  never make the destination caller-controlled. The fixed-host integration tests
  similarly need generalization before inclusion.
- Merge commits `d0da909` / `fb8f879`, our whole main branch and generated
  `wine-tracker-dev` changes. Let upstream's own release tooling manage versions
  and the generated development app.

## Preparation after the author agrees

Start from a freshly fetched `upstream/main` on a new contribution branch,
not our production main. Apply/review the core implementation and tests first;
then adapt documentation and CI to the maintainer's preferences. For example,
these commands are a future preparation recipe, not work already performed:

```sh
git fetch upstream
git switch -c codex/upstream-inventory-api upstream/main
git cherry-pick 1c2734c2d13f1b6c005771288dc8a568b2e85533 e7e7ebb6cbe911967990478aa2e716a9dad806f5
```

Resolve conflicts in context, review the complete diff against upstream main,
run the original suite and added API tests against temporary databases, and
check existing browser authentication/readonly access and backup compatibility.
Keep upstream's version, application identity, network defaults and MIT notices.
Ask the author whether they prefer one squashed implementation/test/docs commit
or a short sequence. Push only to our fork and open the upstream PR **only after
the user authorizes submission**. There is no need to alter the deployed cellar
while preparing or discussing this contribution.

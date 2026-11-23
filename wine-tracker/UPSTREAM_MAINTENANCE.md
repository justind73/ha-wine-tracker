# Maintaining the fork

The fork keeps the original Git history. `origin` is
`https://github.com/justind73/ha-wine-tracker.git`; `upstream` is
`https://github.com/xenofex7/ha-wine-tracker.git`. Fetching upstream only updates
local references; it does not merge, publish or install anything.

Checked 23 November 2026: the latest published stable release is `v1.11.0`.
Our `1.11.0-api.6` release source `6ad6000` contains upstream main `bea3ce0` in full,
including development commits after that release. No upstream merge is needed
at this point. Repeat the checks below instead of treating this dated snapshot
as permanently current. Releases: <https://github.com/xenofex7/ha-wine-tracker/releases>.

## 1. Check for changes on the PC

Run from the repository folder in PowerShell. Start with a clean working tree;
commit or set aside your own edits before continuing.

```powershell
git status --short
git remote -v
git switch main
git pull --ff-only origin main
git fetch upstream --tags
gh release list --repo xenofex7/ha-wine-tracker --limit 5
git log --oneline main..upstream/main
```

If a new checkout has no upstream remote, add it once with
`git remote add upstream https://github.com/xenofex7/ha-wine-tracker.git`.
For an existing remote with a wrong URL use `git remote set-url upstream`.
A fresh clone does not inherit another checkout's remote configuration.

Read the release notes and changes. Prefer a reviewed stable tag; do not assume
all commits on upstream main are released. Select the intended reference:

```powershell
$upstreamRef = 'v1.11.0' # Example only: choose the release you reviewed.
git merge-base --is-ancestor $upstreamRef main
```

Exit code 0 means that release is already included: stop, there is nothing to
merge. Exit code 1 means it has not been fully incorporated. Other errors need
investigation. Do not reset the fork backwards to an older release. If deliberately
selecting development changes instead, pin and review the exact commit SHA.

## 2. Merge on a review branch

Replace the example branch suffix with the selected version or date:

```powershell
git switch -c codex/upstream-reviewed-release
git merge --no-ff --no-commit $upstreamRef
git status
git diff --cached --stat
```

If there are conflicts, open each file and reconcile both sides; do not use
blanket “ours” or “theirs”. `git diff --name-only --diff-filter=U` lists unresolved
files. Stage each resolution with `git add <file>`. To abandon an uncommitted
merge and return to the clean starting state, use `git merge --abort`.

Review the resulting code even when Git merges it without conflicts:

- `app.py`: preserve the API registration, token loading, receipt-table setup,
  standalone readonly checks and HA ingress guard while incorporating upstream
  schema/UI changes. Keep upstream `APP_VERSION` tied to the original code.
- `wine_api.py` / `wine_images.py`: maintain mandatory authentication, atomic
  retry receipts, validation, source restrictions and non-image field preservation.
- `config.yaml`: keep our slug, fork URL, `ports: {}`, shared data path, ingress,
  `S6_KEEP_ENV`, `HA_INGRESS_ONLY` and API-token option. Preserve user options
  during installation. Do not replace our app with an upstream container image.
- About/template/translations: keep both version labels, original attribution,
  separate fork link, and the upstream MIT copyright and licence notices.
- Dockerfile: retain `BUILD_VERSION` → `WINE_TRACKER_BUILD_VERSION`; evaluate
  upstream base-image/dependency changes rather than copying them blindly.
- `.github/workflows/` and scripts: inspect new triggers, permissions, publication
  destinations and generated-file changes. Do not introduce automatic upstream
  merging or production deployment. `wine-tracker-dev` is an upstream-generated
  development app; do not install it or run its sync script for this production
  workflow. The script would need review against our modified manifest first.

For application changes, set a new, higher fork version in
`wine-tracker/config.yaml`, for example `1.12.0-api.1` when incorporating upstream 1.12.0, or increment our current
`-api.N` suffix for a fork-only change. Update the fork changelog with the actual
scope. An upstream version bump alone must not erase the fork suffix.
Documentation/CI-only maintenance needs neither a version increment nor a production deployment.

## 3. Test and review before merging to our main

This workspace already has a Python environment one directory above the repo:

```powershell
& '..\.venv\Scripts\python.exe' -m pip install -r wine-tracker/requirements.txt -r wine-tracker/requirements-test.txt
& '..\.venv\Scripts\python.exe' -m pytest wine-tracker/tests -q
git diff --check
git diff --cached --check
```

For a fresh checkout, create a virtual environment first and substitute its
Python path. Tests use temporary databases and loopback HTTP, not the real
cellar. Review schema migrations and compatibility with a private backup when
upstream changes storage; never point the test suite at the live database.
Check About, normal inventory editing, authenticated API access, rejected
unauthenticated access, stock retry behaviour and image/ZIP compatibility.

Stage any final fixes, complete the merge commit and push only the review branch:

```powershell
git commit -m "Merge reviewed upstream release"
git push -u origin codex/upstream-reviewed-release
```

Open a PR **in justind73/ha-wine-tracker**, with base `main`. Review the complete
diff and wait for GitHub tests to pass before merging. The test workflow runs on
every PR (including documentation-only changes) and every push to `main`; verify
the resulting main-branch run as well. Do not open this maintenance
PR against the original author's repository. Do not force-push/reset main or use
`git push --tags`: fetched upstream `v*` tags can trigger our inherited image
publication workflow. GitHub's generic “Sync fork” is not a substitute for this
review and test process.

## 4. Update the installed Home Assistant app

Only after that PR has been reviewed, tested and merged:

1. Export a full Wine Tracker ZIP using its export control and keep it safely.
   Check the archive and included photos. Keep a consistent private copy of
   `/share/wine-tracker/` while Wine Tracker is stopped as well; it preserves
   retry receipts that the normal ZIP export omits. Restart only Wine Tracker
   after the snapshot. Do not restore an old backup over newer genuine changes.
2. Record the reviewed fork main commit and version. Optionally tag that exact
   commit `wine-tracker-<version>` and push only that specific tag to origin.
3. In HA, refresh the app store, then open the **existing Wine Tracker app from
   Justin's fork** and select Update. Terminal equivalent, on HA:

   ```sh
   ha store reload
   ha apps info 64183197_wine_tracker
   ha apps update 64183197_wine_tracker
   ```

   Check that the offered version is the reviewed one before running Update.
   Keep automatic app updates disabled for a deliberate review/deployment gate.
   This guide does not change that setting automatically.
4. Keep the existing API token, data directory and package. If the REST-command
   package changed, back it up, update just that file, run `ha core check`, then
   call `rest_command.reload`. No HA Core restart is needed for a loaded
   REST-command integration. Discuss any other required restart separately.
5. Open Settings → About in Wine Tracker. Confirm original version and custom
   build version, and compare the latter with HA's installed app version. Verify
   list/get through HA-MCP, retained stock/notes/windows/photos and history counts,
   and that port 5050 remains closed. Do not consume real stock to test an update.

HA builds this app from our fork source. It retains `/share/wine-tracker/` in
place; never run two app instances against it. If startup fails, stop Wine Tracker,
inspect its logs and use the recorded source/data backup to plan rollback.
Do not reinstall an unreviewed upstream build as a shortcut, or automatically
restore a snapshot over subsequent cellar changes.

## How About gets its versions

`APP_VERSION` remains the original Wine Tracker version from upstream `app.py`.
Supervisor supplies Docker's `BUILD_VERSION` from our `config.yaml`; the
Dockerfile exposes it as `WINE_TRACKER_BUILD_VERSION`, and the template displays
that value. There is no second hardcoded custom-version string in Python or HTML.
The existing S6 environment retention keeps it available at runtime.

Source/standalone runs without this environment value show “Development build
(version not supplied)” rather than guessing a release. For a manually built
HA image, pass `--build-arg BUILD_VERSION=<reviewed-config-version>`; for a local
source run set `WINE_TRACKER_BUILD_VERSION` in that process. The separate upstream
standalone Docker build does not supply this value automatically.

Home Assistant documents the [Supervisor build arguments](https://contributors.home-assistant.io/apps/build-a-real-app/#3-the-dockerfile).

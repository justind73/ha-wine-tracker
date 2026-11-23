#!/usr/bin/env python3
"""Package a committed revision as an isolated local HA app; never deploy it."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile


SLUG = "wine_tracker_api_staging"
SOURCE_PATHS = ["wine-tracker/app", "wine-tracker/requirements.txt",
                "wine-tracker/Dockerfile", "wine-tracker/build.yaml"]


def git(repo, *args):
    # git archive otherwise applies the host's CRLF conversion on Windows.
    return subprocess.check_output(["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf",
                                    "-C", str(repo), *args])


def build_archive(repo, revision):
    commit = git(repo, "rev-parse", "--verify", "--end-of-options",
                 revision + "^{commit}").decode().strip()
    source = git(repo, "archive", "--format=tar", commit, "--", *SOURCE_PATHS)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(source)) as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            if not member.isfile() or not member.name.startswith("wine-tracker/"):
                raise ValueError("Unexpected source archive entry")
            relative = member.name.removeprefix("wine-tracker/")
            if any(part in {"..", "data", "__pycache__"} for part in relative.split("/")):
                raise ValueError("Data/cache paths must never enter staging")
            files[relative] = archive.extractfile(member).read()
    for required in ("app/app.py", "app/wine_api.py", "requirements.txt", "Dockerfile", "build.yaml"):
        if required not in files:
            raise ValueError("Revision does not contain the complete JSON API")

    config = {
        "name": "Wine Tracker API Staging",
        "description": "Isolated API review only; no browser UI or live cellar access",
        "version": "0.1.0-" + commit[:12],
        "slug": SLUG,
        "url": "https://github.com/justind73/ha-wine-tracker/pull/1",
        "arch": ["aarch64", "amd64"],
        "init": False,
        "startup": "application",
        "boot": "manual",
        "ingress": False,
        "host_network": False,
        "ports": {},
        "map": [],
        "environment": {
            "DATA_DIR": "/data/wine-tracker-api-staging",
            "AUTH_ENABLED": "true",
            "USERS": "",
            "DEV_AUTH": "",
        },
        "options": {"wine_api_token": "", "currency": "GBP", "language": "en", "ai_provider": "none"},
        "schema": {"wine_api_token": "password?", "currency": "str", "language": "str", "ai_provider": "list(none)"},
    }
    files["config.json"] = (json.dumps(config, indent=2) + "\n").encode()
    manifest = {
        "source_commit": commit,
        "source_paths": SOURCE_PATHS,
        "files_sha256": {path: hashlib.sha256(data).hexdigest() for path, data in sorted(files.items())},
    }
    files["SOURCE.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(files.items()):
            entry = zipfile.ZipInfo(SLUG + "/" + path, (2020, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    return commit, output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="Committed source revision (default HEAD)")
    parser.add_argument("--output", type=Path, required=True, help="New local ZIP path; never overwritten")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    commit, data = build_archive(repo, args.ref)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as handle:
        handle.write(data)
    print("Prepared source commit:", commit)
    print("Archive SHA256:", hashlib.sha256(data).hexdigest())
    print("Local archive:", args.output.resolve())
    print("Nothing was installed, started or copied to Home Assistant.")


if __name__ == "__main__":
    main()

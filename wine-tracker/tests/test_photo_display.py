"""Detail metadata and browserless execution of the shared display control."""
from pathlib import Path
import shutil
import subprocess

import pytest
from translations import TRANSLATIONS


@pytest.mark.parametrize("route", ["/", "/stats", "/timeline", "/chat"])
def test_photo_control_in_all_detail_views(client, route, monkeypatch):
    import app as wine_app
    monkeypatch.setattr(wine_app, "_is_ai_configured", lambda opts: True)
    response = client.get(route)
    assert response.status_code == 200
    assert b'/static/photo-info.js' in response.data
    assert b'addPhotoInformation(id, w)' in response.data


def test_photo_display_translations():
    keys = {key for key in TRANSLATIONS["en"] if key.startswith("photo_")}
    assert len(keys) == 12
    for language in TRANSLATIONS.values():
        assert all(language.get(key) for key in keys)


def test_photo_display_behaviour():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed for the browserless display test")
    result = subprocess.run([node, "--test", str(Path(__file__).with_name("photo_info.test.js"))],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr

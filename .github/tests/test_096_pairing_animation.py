from source_helpers import parse_source
"""Check that pairing notices link to an asset served by the integration."""

import ast
import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from compat_scope import add_compat_symbols
from test_protocol import PACKAGE_PATH
from test_pairing_recovery_045 import ScooterConnectionError, setup as pairing_setup


@dataclass
class StaticPathConfig:
    url_path: str
    path: str
    cache_headers: bool


@pytest.mark.parametrize("reuse_stored_key", [False, True])
def test_button_notice_embeds_animated_gif_served_without_config_writes(reuse_stored_key):
    filename = PACKAGE_PATH / "__init__.py"
    tree = parse_source(filename.read_text())
    setup_node = next(node for node in tree.body
                      if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup")
    frontend_urls = []
    scope = {"__file__": str(filename), "Path": Path,
             "add_extra_js_url": lambda _hass, url: frontend_urls.append(url)}
    add_compat_symbols(scope, static_path_config=StaticPathConfig)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        setup_node], type_ignores=[])),
                 str(filename), "exec"), scope)

    routes = []

    async def register(paths):
        routes.extend(paths)

    async def check():
        hass = SimpleNamespace(http=SimpleNamespace(async_register_static_paths=register))
        assert await scope["async_setup"](hass, {}) is True
        assert len(routes) == 2
        url = routes[0].url_path
        assert url == "/api/ninebot_e_scooters/power_button.gif"
        assert routes[0].cache_headers is True
        assert "http" in json.loads((PACKAGE_PATH / "manifest.json").read_text())["dependencies"]
        asset = Path(routes[0].path)
        assert asset.read_bytes()[:6] == b"GIF89a"
        assert asset.stat().st_size > 100_000
        assert routes[1].url_path == "/api/ninebot_e_scooters/pairing_dialog.js"
        assert Path(routes[1].path).is_file()
        version = json.loads((PACKAGE_PATH / "manifest.json").read_text())["version"]
        assert frontend_urls == [f"/api/ninebot_e_scooters/pairing_dialog.js?v={version}"]

        run, state, notices, _ = pairing_setup(timeout=0.012)

        async def request(_packet, **_kwargs):
            return None

        state._async_crypto_request = request
        with pytest.raises(ScooterConnectionError, match="0x5C01"):
            await run(state, reuse_stored_key=reuse_stored_key)
        assert len(notices.created) == 2  # Button guidance, then failure.
        message, title, _notice_id = notices.created[0]
        assert f'<p align="center"><img alt="Animation: Einschalttaste am Scooter kurz drücken" src="{url}"></p>' in message
        assert ("Gespeicherten Schlüssel" in title) is reuse_stored_key

    asyncio.run(check())

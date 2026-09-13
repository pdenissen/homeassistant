#!/usr/bin/env python3
"""Publish dashboards/thuis.yaml to Home Assistant as a storage dashboard."""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import sys
from pathlib import Path

import websockets
import yaml

HA_URL = os.environ.get("HA_URL", "http://homeassistant.local:8123")
TOKEN = os.environ.get("HA_TOKEN")
URL_PATH = "thuis-home"
DASHBOARD_FILE = Path(__file__).with_name("thuis.yaml")


def ws_url(http_url: str) -> str:
    if http_url.startswith("https://"):
        return "wss://" + http_url[len("https://") :].rstrip("/") + "/api/websocket"
    if http_url.startswith("http://"):
        return "ws://" + http_url[len("http://") :].rstrip("/") + "/api/websocket"
    raise ValueError(f"Unsupported HA_URL: {http_url}")


async def send(ws, msg_id: int, payload: dict) -> dict:
    payload = {"id": msg_id, **payload}
    await ws.send(json.dumps(payload))
    while True:
        raw = await ws.recv()
        data = json.loads(raw)
        if data.get("type") == "event":
            continue
        if data.get("id") != msg_id:
            continue
        if not data.get("success"):
            raise RuntimeError(data.get("error") or data)
        return data


async def main() -> None:
    if not TOKEN:
        sys.exit("HA_TOKEN is not set")

    config = yaml.safe_load(DASHBOARD_FILE.read_text())
    url = ws_url(HA_URL)
    ssl_ctx = ssl.create_default_context() if url.startswith("wss://") else None

    async with websockets.connect(url, ssl=ssl_ctx, open_timeout=10) as ws:
        hello = json.loads(await ws.recv())
        if hello.get("type") != "auth_required":
            raise RuntimeError(f"Unexpected hello: {hello}")

        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            raise RuntimeError("Home Assistant auth failed")

        listed = await send(ws, 1, {"type": "lovelace/dashboards/list"})
        existing = [item for item in listed.get("result", []) if item.get("url_path") == URL_PATH]

        if existing:
            print(f"dashboard exists: {URL_PATH}")
        else:
            created = await send(
                ws,
                2,
                {
                    "type": "lovelace/dashboards/create",
                    "url_path": URL_PATH,
                    "title": "Thuis",
                    "icon": "mdi:home-variant",
                    "require_admin": False,
                    "show_in_sidebar": True,
                },
            )
            print(f"dashboard created: {created.get('result', {}).get('id')}")

        await send(
            ws,
            3,
            {
                "type": "lovelace/config/save",
                "url_path": URL_PATH,
                "config": config,
            },
        )
        print(f"config saved: {HA_URL}/{URL_PATH}")


if __name__ == "__main__":
    asyncio.run(main())

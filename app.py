"""Backward-compatible ASGI entrypoint for Render and ``uvicorn app:app``."""
from lore_bridge.app import app

__all__ = ["app"]

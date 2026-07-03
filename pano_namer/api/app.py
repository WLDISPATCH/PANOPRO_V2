from __future__ import annotations

from fastapi import FastAPI

from pano_namer.main import create_app as create_legacy_app


def create_app() -> FastAPI:
    """Temporary bridge into the legacy v2 app.

    This module is the first stable scaffold point for the rewrite. New API
    composition should move here over time while the existing app continues to
    run.
    """

    return create_legacy_app()


"""Standalone resource sync. See __main__.py for the entry point.

This package is shipped INSIDE the RetroArch AppImage (under $APPDIR/lib/
ra_sync/) and invoked by AppRun on every launch. It is intentionally
self-contained: stdlib only, no `ra.*` imports — the addon Python package
and this module ship in different containers and may version-skew, so
they must not share runtime state.
"""

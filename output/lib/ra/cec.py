"""CEC integration: env vars for the AppImage launch."""

from __future__ import annotations

from .settings import AddonSettings


def appimage_env(settings: AddonSettings) -> dict[str, str]:
    """Return RA_CEC_* env vars to pass to the AppImage invocation.

    cec-mini-kb is started and stopped by AppRun within the single FUSE
    mount shared with retroarch.  The Python orchestrator only needs to
    declare intent via these variables; AppRun handles the lifecycle.
    """
    if not settings.cec_remote:
        return {}
    if settings.cec_poweroff == 0:
        return {"RA_CEC_POWEROFF": "1"}
    return {"RA_CEC": "1"}

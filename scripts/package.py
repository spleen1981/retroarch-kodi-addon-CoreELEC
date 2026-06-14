"""Packaging: assemble the addon dir, generate manifests, zip it up."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from . import langdata

log = logging.getLogger(__name__)


# Subprocess output target -- mirrors lakka.configure_subprocess.
_SUBPROC_KW: dict = {}


def configure_subprocess(*, stdout=None, stderr=None) -> None:
    """Set default stdout/stderr for every subprocess.run in this module."""
    global _SUBPROC_KW
    _SUBPROC_KW = {}
    if stdout is not None:
        _SUBPROC_KW["stdout"] = stdout
    if stderr is not None:
        _SUBPROC_KW["stderr"] = stderr


def _run(args, **kw):
    """subprocess.run wrapper honoring `configure_subprocess` defaults."""
    merged = {**_SUBPROC_KW, **kw}
    return subprocess.run(args, **merged)


# `.in` files that the *late* render stage owns. The eager render stage
# leaves these alone so they can be rendered by emit_addon_xml after the
# build knows the addon version, provider, etc.
_LATE_RENDERED_IN_FILES: frozenset[str] = frozenset({"addon.xml.in"})


# =========================================================== move_artifacts


# Map (Lakka build sub-path) -> (addon-dir sub-path).
_BASE_MOVES: tuple[tuple[str, str], ...] = (
    ("etc/retroarch.cfg",              "config/retroarch.cfg"),
    ("usr/bin",                        "bin"),
    ("usr/lib",                        "lib"),
    ("usr/share/audio_filters",        "resources/audio_filters"),
    ("usr/share/video_filters",        "resources/video_filters"),
    ("usr/share/retroarch/system",     "resources/system"),
    ("etc/retroarch-joypad-autoconfig","resources/joypads"),
)
_DLC_MOVES: tuple[tuple[str, str], ...] = (
    ("usr/share/common-shaders",       "resources/shaders"),
    ("usr/share/libretro-database",    "resources/database"),
    ("usr/share/retroarch-assets",     "resources/assets"),
    ("usr/share/retroarch-overlays",   "resources/overlays"),
)


def move_artifacts(staging: Path, addon_dir: Path, *, with_dlc: bool) -> None:
    """Move Lakka build output from `staging` into the addon layout."""
    moves = list(_BASE_MOVES)
    if with_dlc:
        moves.extend(_DLC_MOVES)
    for src_rel, dst_rel in moves:
        src = staging / src_rel
        dst = addon_dir / dst_rel
        if not src.exists():
            log.warning("package: missing artifact %s", src)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        shutil.move(str(src), str(dst))
        log.info("package: moved %s -> %s", src_rel, dst_rel)


# ===================================================== add_fallback_cores ==


def add_fallback_cores(repo_root: Path, addon_dir: Path, profile) -> None:
    """Unzip pre-compiled cores from `fallback-precompiled-cores/<arch>/*.zip`."""
    if not profile.fallback_subdir or not profile.cores_fallback:
        return
    src_dir = repo_root / "fallback-precompiled-cores" / profile.fallback_subdir
    dst = addon_dir / "lib" / "libretro"
    dst.mkdir(parents=True, exist_ok=True)
    for core in profile.cores_fallback:
        zip_path = src_dir / f"{core}_libretro.so.zip"
        if not zip_path.is_file():
            log.warning("package: missing fallback zip %s", zip_path)
            continue
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dst)
        _maybe_clone_core_info(dst, core)
        log.info("package: unpacked fallback %s", core)


def _maybe_clone_core_info(libretro_dir: Path, core: str) -> None:
    """For flycast_xtreme, create the .info file by tweaking flycast's."""
    if core != "flycast_xtreme":
        return
    src = libretro_dir / "flycast_libretro.info"
    dst = libretro_dir / "flycast_xtreme_libretro.info"
    if not src.is_file():
        return
    text = src.read_text(encoding="utf-8")
    dst.write_text(text.replace("Flycast", "Flycast xtreme"), encoding="utf-8")


# ===================================================== install_committed_src


def install_committed_source(output_dir: Path, addon_dir: Path,
                             addon_name: str) -> None:
    """Copy `output/` into the addon dir, then render `.in` files.

    `output/` is the part of the tree that lives in version control: the
    Python package, the autostart shim, settings.xml schema, the addon.xml
    template, settings-default.xml, and resources/icon.png / fanart.jpg.

    Any file whose name ends in `.in` is treated as a template:
        * `addon.xml.in` is left as-is — `emit_addon_xml` renders it later
          once metadata (version, provider, lang block, changelog) is known.
        * Every other `.in` file is rendered with `@ADDON_NAME@` substitution
          and the rendered output replaces the template in the addon tree.
    """
    for entry in output_dir.iterdir():
        dst = addon_dir / entry.name
        if entry.is_dir():
            shutil.copytree(entry, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, dst)

    _render_in_files(addon_dir, addon_name)
    _chmod_executables(addon_dir)


def _render_in_files(addon_dir: Path, addon_name: str) -> None:
    """Render every eager `.in` file under `addon_dir` (recursive).

    Templates owned by the late stage (see `_LATE_RENDERED_IN_FILES`) are
    skipped here. For every other template:

        foo/bar.ext.in  ->  foo/bar.ext   (with `@ADDON_NAME@` substituted)

    The `.in` source is removed after rendering so it doesn't end up in
    the shipped zip.
    """
    for src in addon_dir.rglob("*.in"):
        if not src.is_file():
            continue
        if src.name in _LATE_RENDERED_IN_FILES:
            continue
        rendered = src.read_text(encoding="utf-8").replace(
            "@ADDON_NAME@", addon_name
        )
        dst = src.with_suffix("")  # strip the trailing `.in`
        dst.write_text(rendered, encoding="utf-8")
        src.unlink()


def _chmod_executables(addon_dir: Path) -> None:
    """`+x` everything under `bin/`. Python files stay 644."""
    bin_dir = addon_dir / "bin"
    if not bin_dir.is_dir():
        return
    for entry in bin_dir.iterdir():
        if entry.is_file():
            os.chmod(entry, 0o755)


# ========================================================= emit_addon_xml ==


def emit_addon_xml(addon_dir: Path, addon_name: str, addon_version: str,
                   provider: str, ra_name_suffix: str, *,
                   changelog: Path) -> None:
    """Fill in addon.xml.in placeholders and write addon.xml into the addon dir.

    Pairs with `install_committed_source`, which leaves `addon.xml.in` in
    place precisely so this late stage can render it once the build knows
    the metadata that wasn't available earlier.
    """
    template_path = addon_dir / "addon.xml.in"
    text = template_path.read_text(encoding="utf-8")

    lang_meta = _render_lang_metadata(ra_name_suffix)
    changelog_text = _read_changelog(changelog)

    text = (text
            .replace("@ADDON_NAME@", addon_name)
            .replace("@ADDON_VERSION@", addon_version)
            .replace("@PROVIDER@", provider)
            .replace("@LANG_METADATA@", lang_meta)
            .replace("@CHANGELOG@", changelog_text))

    (addon_dir / "addon.xml").write_text(text, encoding="utf-8")
    # The .in template doesn't need to ship.
    template_path.unlink(missing_ok=True)


def _render_lang_metadata(ra_name_suffix: str) -> str:
    """Render <summary>/<description>/<disclaimer> for every language."""
    lines: list[str] = []
    for lang_code in langdata.LANGUAGES:
        kodi_tag = _kodi_lang_tag(lang_code)
        summary = langdata.translate(0, lang_code, ra_name_suffix=ra_name_suffix)
        description = langdata.translate(1, lang_code, ra_name_suffix=ra_name_suffix)
        disclaimer = langdata.translate(2, lang_code, ra_name_suffix=ra_name_suffix)
        lines.append(f'        <summary lang="{kodi_tag}">{_xml_escape(summary)}</summary>')
        lines.append(f'        <description lang="{kodi_tag}">{_xml_escape(description)}</description>')
        lines.append(f'        <disclaimer lang="{kodi_tag}">{_xml_escape(disclaimer)}</disclaimer>')
    return "\n".join(lines)


def _kodi_lang_tag(lang_code: str) -> str:
    # `en_gb` -> `en_GB`. Kodi addon.xml expects an uppercase region.
    parts = lang_code.split("_", 1)
    if len(parts) != 2:
        return lang_code
    return f"{parts[0]}_{parts[1].upper()}"


def _xml_escape(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


def _read_changelog(path: Path) -> str:
    if not path.is_file():
        return ""
    return _xml_escape(path.read_text(encoding="utf-8"))


def _output_root() -> Path:
    return Path(__file__).resolve().parent.parent / "output"


# ======================================================= emit_language_files


def emit_language_files(addon_dir: Path, addon_version: str,
                        ra_name_suffix: str) -> None:
    """Write one strings.po per language under resources/language/."""
    lang_root = addon_dir / "resources" / "language"
    lang_root.mkdir(parents=True, exist_ok=True)

    for lang_code in langdata.LANGUAGES:
        lang_dir = lang_root / f"resource.language.{lang_code}"
        lang_dir.mkdir(parents=True, exist_ok=True)
        po = _render_po(lang_code, addon_version, ra_name_suffix)
        (lang_dir / "strings.po").write_text(po, encoding="utf-8")


def _render_po(lang_code: str, addon_version: str, ra_name_suffix: str) -> str:
    kodi_tag = _kodi_lang_tag(lang_code)
    header = _PO_HEADER.format(version=addon_version, lang=kodi_tag)
    body: list[str] = [header]
    for entry in langdata.entries():
        msgctxt = entry.ctx
        msgid = entry.text("en_gb", ra_name_suffix=ra_name_suffix)
        if lang_code == "en_gb":
            msgstr = ""
        else:
            msgstr = entry.text(lang_code, ra_name_suffix=ra_name_suffix)
        body.append(
            f'\nmsgctxt "{msgctxt}"\n'
            f'msgid "{_po_escape(msgid)}"\n'
            f'msgstr "{_po_escape(msgstr)}"\n'
        )
    return "".join(body)


def _po_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


_PO_HEADER = '''# XBMC Media Center language file
# Addon Name: RetroArch
# Addon version: {version}
msgid ""
msgstr ""
"Project-Id-Version: XBMC-Addons\\n"
"Report-Msgid-Bugs-To: https://github.com/spleen1981/retroarch-kodi-addon-CoreELEC/issues\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Language: {lang}\\n"
"Plural-Forms: nplurals=2; plural=(n != 1)\\n"
'''


# =================================================== customize_retroarch_cfg


# Path keys redirected at packaging time. The cfg ships with whatever Lakka
# built it with; we point it at addon-installed paths so RA looks at the
# right place on first launch (before firstrun.py runs).
_USER_CFG_DIRS = ("savefiles", "savestates", "remappings", "playlists", "thumbnails")
_RES_DIRS_BASE = ("system", "assets", "audio_filters", "video_filters", "joypads")
_RES_DIRS_DLC = ("shaders", "database", "overlays")

# Misc retroarch.cfg pinned values.
_PINNED_VALUES: dict[str, str] = {
    "all_users_control_menu":         "true",
    "content_show_images":            "false",
    "content_show_music":             "false",
    "content_show_video":             "false",
    "input_menu_toggle_gamepad_combo": "4",
    "menu_driver":                    "xmb",
    "menu_swap_ok_cancel_buttons":    "true",
    "video_threaded":                 "false",
    "menu_core_enable":               "true",
    "xmb_alpha_factor":               "100",
    "video_driver":                   "glcore",
    "audio_driver":                   "openal",
}


def customize_retroarch_cfg(addon_dir: Path, addon_name: str, *,
                            with_dlc: bool) -> None:
    """Rewrite paths and pin a handful of settings inside the shipped cfg.

    Uses the same load/edit/save round-trip as the runtime — this avoids
    duplicating cfg parsing logic between the build and the runtime.
    """
    # Import lazily so build-time consumers don't need PYTHONPATH set up.
    import sys
    sys.path.insert(0, str(_output_root() / "lib"))
    from ra.ra_config import RetroArchConfig  # type: ignore[import-not-found]

    cfg_path = addon_dir / "config" / "retroarch.cfg"
    if not cfg_path.is_file():
        log.warning("package: no retroarch.cfg to customize at %s", cfg_path)
        return

    cfg = RetroArchConfig.load(cfg_path)

    user_cfg = "/storage/.config/retroarch"
    res_base = f"/storage/.kodi/addons/{addon_name}/resources"
    cores = f"/storage/.kodi/addons/{addon_name}/lib/libretro"

    # User-writable subdirs (live under ~/.config/retroarch).
    for sub in _USER_CFG_DIRS:
        cfg.redirect_path_suffix(sub, f"{user_cfg}/{sub}")
    # Read-only resources shipped inside the addon.
    for sub in _RES_DIRS_BASE:
        cfg.redirect_path_suffix(sub, f"{res_base}/{sub}")
    if with_dlc:
        for sub in _RES_DIRS_DLC:
            cfg.redirect_path_suffix(sub, f"{res_base}/{sub}")
    # `retroarch-assets` is the Lakka name; we land it as `assets`.
    cfg.redirect_path_suffix("retroarch-assets", f"{res_base}/assets")
    # Cores live under `lib/libretro/` inside the addon (no `/cores` suffix).
    cfg.redirect_path_suffix("cores", cores)

    for key, value in _PINNED_VALUES.items():
        cfg.set(key, value)

    cfg.save()


# ============================================================= zip & link ==


def create_archive(addon_dir: Path, build_dir: Path, archive_name: str) -> None:
    """Zip the addon dir; place the archive (+ a -LATEST symlink) in build/<name>/."""
    addon_name = addon_dir.name
    out_dir = build_dir / addon_name
    out_dir.mkdir(parents=True, exist_ok=True)

    archive_path = out_dir / archive_name
    if archive_path.exists():
        archive_path.unlink()

    # Use shell `zip` to preserve symlinks (`-y`). Python's zipfile module
    # stores symlinks as data, which breaks the SSL workaround set up at
    # first-run.
    _run(
        ["zip", "-y", "-r", archive_name, addon_name],
        cwd=str(addon_dir.parent), check=True,
    )
    shutil.move(str(addon_dir.parent / archive_name), str(archive_path))

    latest = out_dir / f"{addon_name}-LATEST.zip"
    latest.unlink(missing_ok=True)
    os.symlink(archive_name, latest)
    log.info("package: archive at %s", archive_path)

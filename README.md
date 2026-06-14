# RetroArch Kodi add-on for CoreELEC
This project builds a RetroArch add-on for Kodi from Lakka sources for CoreELEC (Amlogic devices).
Resulting builds have been tested on CoreELEC versions from 19 to 22 both for arm and aarch64.

# Add-on usage
   - Download the latest zip file from [releases page](https://github.com/spleen1981/retroarch-kodi-addon-CoreELEC/releases) and install following [Kodi instructions](https://kodi.wiki/view/Add-on_manager#How_to_install_from_a_ZIP_file). Once installed, starting from v 1.5.0 the addon comes with an internal online updater and can be updated from within Kodi.
   - The addon will be shown in the "Game" group, customize the settings as needed and launch RetroArch
   - By default the add-on includes only RetroArch and cores to reduce the zip size, use RetroArch internal online updater to download resources as needed.
   - If you are new to RetroArch refer to [their documentation](https://docs.libretro.com/start/understanding/) for all how-to-use and how-to-setup info.

Core list included by default is same as [Lakka](https://github.com/libretro/Lakka-LibreELEC/blob/a0f1b57bb36fa1feb50ff006ca7b46c1b7b7cb45/distributions/Lakka/options#L176-L296).

## Settings/features
   - Boot the system to Retroarch instead of Kodi
   - Turn off Xbox360 wireless controllers on exit from Retroarch
   - BT controllers shutdown function on RetroArch exit. This option will power off and power back on device bluetooth controller, which may result in paired BT gamepad shutdown if supported (e.g. Sony DS4 controller).
   - Use remote location (e.g. SMB) as roms folder. Remote path to be as follows `//server_IP/path_to_roms_folder`
   - Use TV remote controller (CEC) to navigate RetroArch menu (ref [here](https://github.com/spleen1981/cec-mini-kb) for key bindings)
   - Set refresh rate for Retroarch independently from Kodi settings
   - Sync Retroarch audio driver/device with Kodi settings
   - Auto update. Check for updates will be performed everytime RetroArch is launched
   - Reset Retroarch configuration. Restores `retroarch.cfg` to defaults and addon to first run condition
   - Save a combined addon + RetroArch log to file (max verbosity). Each session starts a fresh log; the previous session is rotated to `retroarch.log.old`.

## Folders

### Resources

The addon uses an internal `resources` folder as well as one external local folder `/storage/.config/retroarch`. Internal folder will be wiped on addon removal/update.

`/storage/.config/retroarch` should include the `retroarch.cfg` main configuration file and following subfolders. If not there, empty folders and default `retroarch.cfg` will be created automatically.

   - `savestates`
   - `savefiles` (e.g. memory card files)
   - `remappings` to store remapped controls
   - `playlists` to store RetroArch playlists - lists of games per emulated system
   - `thumbnails` Boxarts / Screenshots / Title screens will be stored here
   - `assets` wallpapers, themes, icons, fonts, etc. will be stored here
   - `database` contains subfolders `cht` (cheats), `cursors` (saved searches) and `rdb` (games databases for scanning your files)
   - `joypads` configuration files for autoconfiguration of attached joysticks and gamepads will be stored here
   - `overlays` on screen overlays will be stored here
   - `shaders` shaders to enhance the visuals of the emulated systems on current display devices will be stored here
   - `system` cores additional system files (e.g. BIOS) will be stored here

The internal `resources` folder includes:
   - `audio_filters` various audio filters from relevant repositories
   - `video_filters` various video filters from relevant repositories
   - `system` includes contents from relevant repositories per build configured core list.

Depending on build configuration (not by default) also the following may be included in the internal folder, with the content from relevant repositories:
   - `assets`
   - `database`
   - `joypads`
   - `overlays`
   - `shaders`

In case same subfolder is present both in external and internal resource folders, external will be used and internal content will be merged as needed.

### Roms

Default ROM folder is `/storage/roms`. This folder can be mapped to a remote location using addon settings.

### Cores

Cores are stored in `lib/libretro` internal subfolder (removed on addon removal).

### Other folders

Screenshots are stored in `/storage/screenshots`.

When the "Save logs to file" setting is enabled, the combined log lives in `<addon_data>/<addon_id>/logs/retroarch.log` (on CoreELEC this is `/storage/.kodi/userdata/addon_data/script.retroarch.launcher.<variant>/logs/`).
The previous session's log is kept alongside as `retroarch.log.old`.

# Development and build script usage
[Lakka repository](https://github.com/libretro/Lakka-LibreELEC) is included as a submodule by default.
To build the addon with default settings type the following:

```bash
git clone --recursive https://github.com/spleen1981/retroarch-kodi-addon-CoreELEC
cd retroarch-kodi-addon-CoreELEC
python3 -m scripts.build --version v1.0.0
```

Without `--device`, every supported variant is built in sequence. Pass
`--device` (repeatable) to restrict the build:

```bash
python3 -m scripts.build --version v1.0.0 --device Amlogic-ng
python3 -m scripts.build --version v1.0.0 --device Amlogic-ng --device Amlogic-no
```

Supported device profiles (see `_DEVICES` in `scripts/build.py`):

| profile        | Lakka project | arch    |
|----------------|---------------|---------|
| `Amlogic-ng`   | Amlogic       | arm     |
| `Amlogic-no`   | Amlogic       | aarch64 |

Useful flags:

   - `--include-dlc` — bundle `retroarch_assets`, `retroarch_overlays`,
     `libretro_database`, `glsl_shaders`, `slang_shaders` into the zip
     (much larger; otherwise the user pulls them via RetroArch's online updater).
   - `--lakka-dir PATH` — path to the Lakka-LibreELEC checkout
     (default: `./Lakka-LibreELEC`).
   - `--lakka-version COMMIT` — Lakka commit to check out before building
     (default: the pinned `DEFAULT_LAKKA_VERSION` in `scripts/build.py`).
   - `-j N` / `--jobs N` — parallel `make` jobs for Lakka.
   - `-v` / `--verbose` — stream full Lakka output to the terminal
     instead of capturing it to `build.log`.
   - `--keep-work` — keep the `retroarch_work/` staging dir after a
     successful build (default: removed).

Default cores per device, plus the add/remove modifiers used to be set via `LIBRERETRO_CORES_ADD` / `LIBRERETRO_CORES_RM` environment variables; they are now declared per-profile in `_DEVICES` (fields `cores_add`, `cores_remove`, `cores_fallback`) in `scripts/build.py`. Edit that mapping to customize the core list.

First time the building/compiling process will take a lot of time (the whole toolchain will be compiled with the first package).

Addon zip file will be placed in `build/` subfolder.

## Iterative RetroArch development

For a one-line RA change you don't want to rebuild the whole addon for, the `scripts/test/ra_debug.py` helper exports `git diff` from a local RetroArch checkout as a Lakka patch, builds only the `retroarch` package, and `scp`s the resulting binary to a test device:

```bash
cp scripts/test/local.py.example scripts/test/local.py    # fill in REMOTE_IP / USER / PASSWORD
python3 -m scripts.test.ra_debug --device Amlogic-ng
```

Requires `sshpass` on `$PATH`. The RetroArch source dir defaults to `../RetroArch` relative to the repo root, override with `--ra-src` or by setting `RETROARCH_SRC_DIR` in `local.py`.

Two other helpers under `scripts/test/`:
   - `python3 -m scripts.test.new_files --device Amlogic-ng` — generates the
     addon's text files (manifest, source tree, language PO files, settings)
     into `tmp_test_files/` for inspection. Skips the Lakka build entirely.
   - `python3 -m scripts.test.apply_patches --device Amlogic-ng [--revert]` —
     applies (or reverts) the project's Lakka patches without building.

## Adding new translations

Translations are defined in `scripts/langdata.py` (the source of truth that replaces the legacy `01-def_lang.sh`). All language files needed by Kodi are generated at build time and dropped into the addon dir.

Add a new language code to the `LANGUAGES` tuple at the top of the file:

```python
LANGUAGES: tuple[str, ...] = (
    "en_gb", "es_es", "cs_cz", "it_it",
    "zh_cn", "sk_sk", "pt_br", "de_de",
    "fr_fr",  # new
)
```

Then add the per-language string under each `Entry`:

```python
Entry(32001, "#32001", {
    "en_gb": "Stop Kodi service before launching RetroArch",
    "it_it": "Ferma il servizio Kodi prima di lanciare RetroArch",
    "fr_fr": "Arrêter le service Kodi avant de lancer RetroArch",
    ...
}),
```

Missing translations fall back to `en_gb` at render time, so a partial language is fine to merge.

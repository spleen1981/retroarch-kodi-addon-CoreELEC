# RetroArch Kodi add-on for CoreELEC
This project builds a RetroArch add-on for Kodi from Lakka sources for CoreELEC (Amlogic devices).
Resulting builds have been tested on CoreELEC versions from 19 to 22 both for arm and aarch64.

> **v2.0.0 — platform-independent add-on.** The add-on is now a single,
> universal ZIP (id `script.retroarch.launcher`, no device/arch suffix). The
> RetroArch binary and cores are no longer bundled in the ZIP: they live in a
> per-platform **AppImage** that is downloaded separately on first launch (or
> dropped in manually). See [Upgrading from v1.x](#upgrading-from-v1x).

# Add-on usage
   - Download the latest `script.retroarch.launcher-<version>.zip` from the [releases page](https://github.com/spleen1981/retroarch-kodi-addon-CoreELEC/releases) and install following [Kodi instructions](https://kodi.wiki/view/Add-on_manager#How_to_install_from_a_ZIP_file). The add-on includes an internal online updater and can be updated from within Kodi.
   - The add-on will be shown in the "Game" group. Customize the settings as needed and launch RetroArch.
   - **First launch downloads the RetroArch package (AppImage).** The add-on detects your platform (from `/etc/os-release` `COREELEC_ARCH`) and, if the matching RetroArch package is not already present, prompts to download it. A progress bar is shown; the file is verified (SHA-256) and stored in userdata. If you decline, you return to Kodi with a "package missing" notice and can download it later from the add-on.
   - The package includes RetroArch, cores, themes, overlays, shaders and the libretro database — everything needed for full RetroArch operation out of the box. No additional online downloads are required after installation.
   - If you are new to RetroArch refer to [their documentation](https://docs.libretro.com/start/understanding/) for all how-to-use and how-to-setup info.

Core list included by default is the same as [Lakka](https://github.com/libretro/Lakka-LibreELEC/blob/a0f1b57bb36fa1feb50ff006ca7b46c1b7b7cb45/distributions/Lakka/options#L176-L296).

## The RetroArch package (AppImage)

The platform-specific RetroArch binary, cores and shared libraries ship as a self-contained AppImage, separate from the add-on ZIP, for two reasons: the universal add-on stays tiny and arch-neutral, and the heavy binary updates on its own stream without reinstalling the add-on.

   - **Location:** `<addon_data>/script.retroarch.launcher/appimage/` — on CoreELEC: `/storage/.kodi/userdata/addon_data/script.retroarch.launcher/appimage/`. This is in userdata, so it survives add-on self-updates.
   - **Filename:** `retroarch-<target>-<version>.AppImage`. `<target>` is normally the **family-wide** token `<family>-any.<arch>` — `retroarch-Amlogic-any.arm-2.0.0.AppImage`, `retroarch-Amlogic-any.aarch64-2.0.0.AppImage` — a single build that serves every device of that SoC family + arch. A device-specific build, when published, uses the exact `<device>.<arch>` (e.g. `retroarch-Amlogic-ng.arm-2.0.0.AppImage`).
   - **Matching is device-opportunistic with a family-wide fallback.** From `COREELEC_ARCH` (`Amlogic-ng.arm`) the host builds its candidate list `[Amlogic-ng.arm, Amlogic-any.arm]` — it prefers an AppImage tagged with its exact `<device>.<arch>`, otherwise falls back to `Amlogic-any.<arch>`. So an `Amlogic-ne` box (candidates `[Amlogic-ne.arm, Amlogic-any.arm]`) runs the `Amlogic-any.arm` build fine even though no `Amlogic-ne`-specific build exists. The generic is family-scoped (never a bare arch), so it can't be picked up by a different SoC.
   - **Manual install (easy):** download the AppImage asset for your family/arch from the releases page and copy it — over Samba is fine — into **`/storage/.update`** (the *Update* network share) or **`/storage/downloads`**. On the next launch the add-on imports it automatically: a host-matching build is moved into the AppImage folder and a toast confirms how many were imported; any `retroarch-*.AppImage` for a different family/arch sitting there is removed, with a second toast counting the rejected ones. You don't need to find the deep userdata path. (You can also drop the file straight into the AppImage folder above if you prefer.) Only `retroarch-*.AppImage` files are touched — OS update tarballs in `/storage/.update` are left alone.
   - **Compatibility:** the add-on declares a minimum AppImage version it can run. If the installed package is too old, the add-on offers to delete it and download the matching one. AppImages whose target is not one of the host's candidates are ignored. The add-on keeps a single active build per box (older/duplicate ones are pruned after a download or import).
   - **Runtime:** the AppImage uses the fuse2 runtime and needs `libfuse.so.2` on the host (present on CoreELEC). It mounts via the kernel FUSE module; CEC and controller-shutdown helpers run from inside the same mount.

## Updates

A single **Auto-update** setting (and the manual **Check for updates** action) covers both streams, because each release ships the add-on ZIP and the AppImage together:

   1. The add-on ZIP is checked first. If newer, it is installed and Kodi restarts; the freshly-installed add-on then continues.
   2. The RetroArch package (AppImage) is checked next: a missing or too-old one is always handled, and when checking, a newer compatible one is offered. Download shows a progress bar and ends with a "package updated" notification.

## Settings/features
   - Boot the system to RetroArch instead of Kodi.
   - Turn off Xbox360 wireless controllers on exit from RetroArch.
   - BT controllers shutdown on RetroArch exit. Powers the device's bluetooth off and back on, which may shut down a paired BT gamepad if supported (e.g. Sony DS4).
   - Use a remote location (e.g. SMB) as the roms folder. Remote path format: `//server_IP/path_to_roms_folder`.
   - Use the TV remote (CEC) to navigate the RetroArch menu (see [cec-mini-kb](https://github.com/spleen1981/cec-mini-kb) for key bindings). With the CEC poweroff option, shutting down from inside RetroArch also turns the TV off.
   - Set the RetroArch refresh rate independently from Kodi.
   - Sync the RetroArch audio driver/device with Kodi.
   - Auto-update — covers both the add-on and the RetroArch package; checked when RetroArch is launched.
   - Reset RetroArch configuration. Restores `retroarch.cfg` to defaults and the add-on to first-run condition.

## Upgrading from v1.x

The v2 add-on has a new, platform-independent id, so Kodi treats it as a new +add-on rather than an update of the old per-platform id. The last v1.x release 
(**v1.7.6**) is a message-only build that explains the upgrade. To move to v2:

   1. Download the v2 ZIP from the [releases page](https://github.com/spleen1981/retroarch-kodi-addon-CoreELEC/releases).
   2. In Kodi: *Add-ons → Install from zip file* → pick the v2 ZIP.
   3. On first launch, accept the RetroArch package download or upload the package manually.

Your games (`/storage/roms`) and RetroArch configuration (`/storage/.config/retroarch`) are preserved — they are not tied to the add-on id. Only the add-on's own options need to be set again.

## Folders

### Resources

The add-on ships only Kodi-side resources internally (`icon.png`, `fanart.jpg`, `language/`, `settings.xml`). They live in `<addon_dir>/resources/` and are wiped on add-on removal or self-update.

RetroArch resources (`audio_filters`, `video_filters`, `system`, `joypads` + DLC `shaders`, `database`, `overlays`, `assets`) ship **inside the RetroArch AppImage** and are merged into `/storage/.config/retroarch/<sub>` on each launch by a Python module (`ra_sync`) bundled in the AppImage.

The merge policy mirrors the legacy script behavior:

   - **`system/`**: no-clobber — user-added BIOSes and core-written savegames are never overwritten.
   - **Other subdirs**: shipped content overwrites any same-named file (assumes shipped data is canonical).
   - **Blacklist** — files NEVER copied at any depth, in any subdir, even when missing on the user side:
       - exact basenames: `scummvm.ini` (ScummVM rewrites this with user preferences)
       - patterns: `*.cfg`, `*.opt` (core-written option files)

A marker file `/storage/.config/retroarch/.resources_from_appimage` records the last-synced AppImage version; steady-state launches pay no I/O. After an AppImage update the marker mismatches and the merge runs once more. Trigger the *Reset* action (or delete the marker manually) to force a fresh merge.

### Roms

Default ROM folder is `/storage/roms`. This folder can be mapped to a remote location using add-on settings.

### Cores

Cores ship **inside the RetroArch AppImage** (see [The RetroArch package](#the-retroarch-package-appimage)), not in the add-on ZIP. RetroArch resolves them from the AppImage at runtime.

### Other folders

Screenshots are stored in `/storage/screenshots`.

When the "Save logs to file" setting is enabled, the combined log lives in `<addon_data>/script.retroarch.launcher/logs/retroarch.log` (on CoreELEC: `/storage/.kodi/userdata/addon_data/script.retroarch.launcher/logs/`).
The previous session's log is kept alongside as `retroarch.log.old`.

# Development and build script usage
[Lakka repository](https://github.com/libretro/Lakka-LibreELEC) is included as a submodule by default.
To build the add-on with default settings type the following:

```bash
git clone --recursive https://github.com/spleen1981/retroarch-kodi-addon-CoreELEC
cd retroarch-kodi-addon-CoreELEC
python3 -m scripts.build --version v2.0.0
```

The build produces, into `build/`:

   - **one** universal add-on ZIP — `script.retroarch.launcher-<version>.zip` (no AppImage inside);
   - **one AppImage per build target** — `retroarch-<target>-<version>.AppImage`, where `<target>` is the target token (e.g. `Amlogic-any.arm`, `Amlogic-any.aarch64`) (release assets, downloaded by the add-on at runtime);
   - **`updates-v2-current.xml`** in the repo root — a build artifact with the real SHA-256 hashes of everything produced and **empty policy placeholders** (`min_ver=""`, `requires_* min=""`). Copy the fresh hashes from here into the committed, hand-curated `updates.xml`. **Add `updates-v2-current.xml` to `.gitignore`** — it is regenerated every build and is not source.

Without `--target`, every target's AppImage is built, then the single universal
ZIP is assembled once (its arch-neutral `resources/` come from the first target
built). Pass `--target` (repeatable) to restrict the build:

```bash
python3 -m scripts.build --version v2.0.0 --target Amlogic-any.arm
python3 -m scripts.build --version v2.0.0 --target Amlogic-any.arm --target Amlogic-any.aarch64
```

Supported targets (the `_TARGETS` keys in `scripts/build.py`). The key is the
token baked into the AppImage filename / manifest `platform` attribute:

| target (`--target`)   | Lakka project | arch    |
|-----------------------|---------------|---------|
| `Amlogic-any.arm`     | Amlogic       | arm     |
| `Amlogic-any.aarch64` | Amlogic       | aarch64 |

The token includes the arch so the table can grow without renaming. At runtime
a host (e.g. `Amlogic-ne.arm`) prefers an AppImage tagged with its exact
`<device>.<arch>`, else falls back to the family-wide `Amlogic-any.<arch>` —
see [The RetroArch package](#the-retroarch-package-appimage). To publish a
device-specific build (preferred only by that exact device), add a new
`_TARGETS` entry keyed `'<device>.<arch>'` (e.g. `'Amlogic-ng.arm'`) and build
it like any other target.

Useful flags:

   - `--lakka-dir PATH` — path to the Lakka-LibreELEC checkout
     (default: `./Lakka-LibreELEC`).
   - `--lakka-version COMMIT` — Lakka commit to check out before building
     (default: the pinned `DEFAULT_LAKKA_VERSION` in `scripts/build.py`).
   - `-j N` / `--jobs N` — parallel `make` jobs for Lakka.
   - `-v` / `--verbose` — stream full Lakka output to the terminal
     instead of capturing it to `build.log`.
   - `--keep-work` — keep the `retroarch_work/` staging dir after a
     successful build (default: removed).

Default cores per target, plus the add/remove modifiers, are declared per-target in `_TARGETS` (fields `cores_add`, `cores_remove`, `cores_fallback`) in `scripts/build.py`. Edit that mapping to customize the core list.

The AppImage uses the fuse2 AppImageKit runtime (release 13), downloaded automatically by the build; it needs `libfuse.so.2` at runtime on the target, which CoreELEC provides. The fuse3 `type2-runtime` is intentionally **not** used: it requires `fusermount3`, which CoreELEC does not ship, causing the AppImage to fail to unmount cleanly.

First time, the building/compiling process will take a lot of time (the whole toolchain is compiled with the first package).

## Compatibility contract (add-on ⇄ AppImage)

`AppRun` (inside the AppImage) and the Python orchestrator share an env-var
contract (`RA_CEC_POWEROFF`, `RA_SHUTDOWN_FLAG`, `RA_XBOX360_SHUTDOWN`). Two
minimum-version checks enforce that a matching pair is used:

   - the add-on declares `appimage.REQUIRED_APPIMAGE_MIN` (offline, baked in);
   - each `<appimage>` manifest entry declares `requires_addon min`.

When the env contract changes, bump `REQUIRED_APPIMAGE_MIN` and the manifest
`requires_*` values in lockstep.

## Iterative RetroArch development

For a one-line RA change you don't want to rebuild the whole add-on for, the `scripts/test/ra_debug.py` helper exports `git diff` from a local RetroArch checkout as a Lakka patch, builds only the `retroarch` package, and `scp`s the resulting binary to a test device:

```bash
cp scripts/test/local.py.example scripts/test/local.py    # fill in REMOTE_IP / USER / PASSWORD
python3 -m scripts.test.ra_debug --target Amlogic-any.arm
```

Requires `sshpass` on `$PATH`. The RetroArch source dir defaults to `../RetroArch` relative to the repo root, override with `--ra-src` or by setting `RETROARCH_SRC_DIR` in `local.py`.

Two other helpers under `scripts/test/`:
   - `python3 -m scripts.test.new_files --target Amlogic-any.arm` — generates the
     add-on's text files (manifest, source tree, language PO files, settings)
     into `tmp_test_files/` for inspection. Skips the Lakka build entirely.
   - `python3 -m scripts.test.apply_patches --target Amlogic-any.arm [--revert]` —
     applies (or reverts) the project's Lakka patches without building.

## Adding new translations

Translations are defined in `scripts/langdata.py` (the source of truth that replaces the legacy `01-def_lang.sh`). All language files needed by Kodi are generated at build time and dropped into the add-on dir.

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

AppImage build targets are selected directly via `--device`:

- `--device Amlogic-any.arm` builds the ARM AppImage using the Lakka `Amlogic-ng` patch/profile and the Lakka `AMLGX` device.
- `--device Amlogic-any.aarch64` builds the AArch64 AppImage using the Lakka `Amlogic-no` patch/profile and the Lakka `AMLGX` device.

When `--device` is omitted, both targets are built. There is no manual AppImage target override.


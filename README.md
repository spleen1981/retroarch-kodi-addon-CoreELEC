# RetroArch Kodi add-on for CoreELEC
This script creates a RetroArch add-on for Kodi from Lakka sources for CoreELEC (Amlogic-ng devices).

Resulting builds have been tested on following ARM devices:
   - S905X3
   - S922X (Odroid N2+)
   - S905X

with CoreELEC 19 and 20 versions.

# Add-on usage
   - Download the latest zip file from [releases page](https://github.com/spleen1981/retroarch-kodi-addon-CoreELEC/releases) and install following [Kodi instructions](https://kodi.wiki/view/Add-on_manager#How_to_install_from_a_ZIP_file). Once installed, starting from v 1.5.0 the addon comes with an internal online updater and can be updated from within Kodi.
   - The addon will be shown in the "Game" group, customize the settings as needed and launch RetroArch
   - By default the add-on includes only RetroArch and cores to reduce the zip size, use RetroArch internal online updater to download resources as needed.
   - If you are new to RetroArch refer to [their documentation](https://docs.libretro.com/start/understanding/) for all how-to-use and how-to-setup info.

Core list included by default is same as [Lakka](https://github.com/libretro/Lakka-LibreELEC/blob/a0f1b57bb36fa1feb50ff006ca7b46c1b7b7cb45/distributions/Lakka/options#L176-L296).

## Settings/features
   - Stop Kodi when Retroarch is launched, to freeup memory
   - Turn off Xbox360 wireless controllers when exiting Retroarch
   - Added BT controllers shutdown function on RetroArch exit. This option will power off and power back on device bluetooth controller, which may result in paired BT gamepad shutdown if supported (e.g. Sony DS4 controller).
   - Use remote location (e.g. SMB) as roms folder. Remote path to be as follows `//server_IP/path_to_roms_folder`
   - Use TV remote controller (CEC) to navigate RetroArch menu (ref [here](https://github.com/spleen1981/cec-mini-kb) for key bindings)
   - Set refresh rate for Retroarch independently from Kodi settings
   - Sync Retroarch audio driver/device with Kodi settings
   - Auto update. Check for updates will be performed everytime RetroArch is launched
   - Reset Retroarch configuration. Restores `retroarch.cfg` to defaults and addon to first run condition
   - Boot to Retroarch instead of Kodi

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

# Development and build script usage
[Lakka repository](https://github.com/libretro/Lakka-LibreELEC) is included as a submodule by default.
To build the addon with default settings type the following:

```bash
git clone --recursive https://github.com/spleen1981/retroarch-kodi-addon-CoreELEC
cd retroarch-kodi-addon-CoreELEC
./build.sh
```

Extra dowloadable contents as `retroarch-assets retroarch-joypad-autoconfig retroarch-overlays libretro-database glsl-shaders` are not included by default to reduce addon size, but can be included setting `INCLUDE_DLC="Y"`(or can be downloaded from RetroArch online updater otherwise).

Default core list can be customized setting `LIBRERETRO_CORES_ADD` and `LIBRERETRO_CORES_RM` variables.

Refer to the script source for all other configuration parameters.

First time the building/compiling process will take a lot of time (the whole toolchain will be compiled with the first package).

Addon zip file will be placed in `build` subfolder.

## Experimental build options

HOOK variable is used to apply experimental build options. Being experimental, those are not released as built addon zip package.

   - `ARCH=aarch64 HOOK=aarch64_to_arm_userspace ./build.sh` This option will build a stand alone aarch64 package able to run in the 32bit arm CoreELEC userspace, e.g. to try cores available for 64bit systems only (e.g. dolphin)

## Adding new translations

New languages for the addon frontend can be added by modifying [this file](https://github.com/spleen1981/retroarch-kodi-addon-CoreELEC/blob/master/scripts/common/01-def_lang.sh).

The new language code is to be added in the following variable, separated by space (adding italian language in the following examples, coded it_it):
```
LANG_list="en_gb it_it"
```
and the new translations for each string are to be added as follows, as per existing structure:
```
LANG_32001_en_gb="Stop Kodi service before launching RetroArch"
LANG_32001_it_it="Ferma il servizio Kodi prima di lanciare RetroArch"
```
All language files needed by Kodi will be generated at build time.

# Credits
Thanks to [Lakka](http://lakka.tv) and [CoreELEC](https://coreelec.org/) for their work.

Also thanks to [ToKe79](https://github.com/ToKe79) - This work has been developed starting from [his](https://github.com/ToKe79/retroarch-kodi-addon-LibreELEC).

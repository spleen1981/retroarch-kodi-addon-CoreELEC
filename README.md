# RetroArch Kodi add-on for CoreELEC
This script creates a RetroArch add-on for Kodi from Lakka sources for CoreELEC (Amlogic-ng devices).
Resulting build has been tested with S905X3 ARM device only on CoreELEC 19.3.

# Usage
[Lakka repository](https://github.com/libretro/Lakka-LibreELEC) is included as a submodule by default.
To build the addon with default settings type the following:

```bash
git clone --recursive https://github.com/spleen1981/retroarch-kodi-addon-CoreELEC
cd Lakka-LibreELEC
./build.sh
```

By default the add-on includes only RetroArch and cores.
Other dowloadable contents as `retroarch-assets retroarch-joypad-autoconfig retroarch-overlays libretro-database glsl-shaders` are not included by default to reduce addon size, but can be included setting `INCLUDE_DLC="Y"`(or can be downloaded from RetroArch online updater otherwise).
Core list included by default is same as Lakka. This can be customized setting `LIBRERETRO_CORES_ADD` and `LIBRERETRO_CORES_RM` variables.

First time the building/compiling process will take a lot of time (the whole toolchain will be compiled with the first package).

Addon zip file will be placed in `build` subfolder, ready to be installed in [KODI](https://kodi.wiki/view/Add-on_manager#How_to_install_from_a_ZIP_file).

## Addon settings/features
   - Stop Kodi when Retroarch is launched, to freeup memory
   - Turn off Xbox360 wireless controllers when exiting Retroarch
   - Use remote location (e.g. SMB) as roms folder
   - Use TV remote controller (CEC) to navigate RetroArch menu (ref [here](https://github.com/spleen1981/cec-mini-kb) for key bindings)

## Folders

`/storage/.config/retroarch` is the root folder for RetroArch configurations. this It is not deleted when addon is removed (remove the folder manually in this case). It includes the `retroarch.cfg` main configuration file and following subfolders:

   - `savestates` for storing the savestates
   - `savefiles` for storing the saves (e.g. memory card files)
   - `remappings` for storing remapped controls
   - `playlists` for storing RetroArch playlists - lists of games per emulated system
   - `system` put your BIOS files here
   - `thumbnails` Boxarts / Screenshots / Title screens will be stored here

Put your ROM files to folder `/storage/roms`. You may put them in separate folders by systems, but it is not required by RetroArch.

Screenshots are stored in `/storage/screenshots`.

The add-on includes also following subfolders in the addon `resources` folder (removed on addon removal):

   - `assets` contains wallpapers, themes, icons, fonts, etc.
   - `audio_filters` various audio filters
   - `database` contains subfolders `cht` (cheats), `cursors` (saved searches) and `rdb` (games databases for scanning your files)
   - `joypads` configuration files for autoconfiguration of attached joystics and gamepads
   - `overlays` for touch-devices only - on screen gamepad overlays
   - `shaders` various shaders to enhance the visuals of the emulated systems on current display devices
   - `video_filters` various video filters

The emulation cores are stored in `lib/libretro` subfolder of the add-on (removed on addon removal).

# Credits
Thanks to [Lakka](http://lakka.tv) for their work.

Also thanks to [ToKe79](https://github.com/ToKe79) - This work is based on [his](https://github.com/ToKe79/retroarch-kodi-addon-LibreELEC).

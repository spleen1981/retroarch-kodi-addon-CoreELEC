v2.0.0
 - Major: new platform-independent add-on, single universal ZIP (updates breaking change, manual update needed)
 - Build pipeline fully rewritten in Python
 - RetroArch + bin tools + resources now ships as a separated per-platform AppImage, downloaded on first launch and stored in userdata, so it survives add-on self-updates
 - Manual AppImage update by dropping the file in /storage/downloads or /storage/.update
 - Supporting libs bundled into AppImage to avoid conflicts
 - Added support for new GBM mali blobs
 - Legacy support for old framebuffer mali blobs
 - All DLC packages are now bundled by default
 - Migrated to Lakka v6.1 build system
 - Independent auto-update flow covers both the add-on ZIP and the AppImage
 - Boot-to-RetroArch redesigned
 - New unified three-level logging (Off / Errors only / Verbose)
 - CEC + controller shutdown lifecycle moved into AppRun
 - Audio driver sync now supports PipeWire
 - Update RetroArch and cores to latest
 - CIFS roms mount uses a credentials file with mode 0600 instead of passing credentials on argv
 - Refresh-rate override: no-op when the display is already at the requested rate (avoids spurious HDMI renegotiation on Amlogic TVs)
 - Settings UI: Information category displays add-on version, detected platform and active RetroArch package with size; manual refresh action
 - Addon source fully migrated to Python
 - i18n source-of-truth migrated to scripts/langdata.py

v1.7.5
 - Update Retroarch to 1.21.0
 - Add glcore video driver support
 - Set glcore/openal as default video/audio drivers
 - Fix same_cdi core
 - [Amlogic-ng] add Flycast 'xtreme' core
 - [Amlogic-no] Fix Mupenplus_next core
 - [Amlogic-no] Add Mupenplus core
 - [Amlogic-no] Add back Chailove core
 - Update ScummVM core to latest

v1.7.4
 - Update Retroarch to 1.20.0
 - Fix missing libfmt
 - Drop video playback causing freeze
 - Update ScummVM to latest

v1.7.3
 - Update Retroarch to latest
 - Update ScummVM to latest
 - Revert PPSSPP to working version
 - Add OpenAL support
 - Add German translation, thanks to @sickdaflip
 - Add graceful system reboot/shutdown

v1.7.2
 - Update RetroArch and cores to latest
 - Add Beetle Saturn core
 - Add Spanish translation, thanks to @Deci8BelioS
 
v1.7.1
 - Update RetroArch and cores to latest

v1.7.0
 - Switch to Lakka-v5.x build system
 - Add Amlogic-no.aarch64 build
 - Update RetroArch to 1.17.0
 - Update all cores per Lakka sources
 - Misc fixes

v1.6.5
 - Update RetroArch to 1.16.0.2
 - Update ScummVM core to latest
 - Add Brazilian Portuguese translation, thanks to @xgrind
 - Add RetroArch assets check and hint
 - Drop Kronos core

v1.6.4
 - Add joypad autoconfig asset to default build
 - Update ScummVM core to latest
 - Add Slovak translation, thanks to @jose1711

v1.6.3
 - Update RetroArch to 1.15.0
 - Update ScummVM core to latest
 - Fix PPSSPP missing libzip
 - Fix Flycast graphical issues (revert to last working version)
 - Added Simplified Chinese translation, thanks to @VergilGao 

v1.6.2
 - Cores updated per latest Lakka
 - Fixed MelonDS core
 - ScummVM core:
   * Drop ScummVM_mainline as it has replaced the legacy ScummVM core now
   * Update to v2.7.0
   * Add cloud saving feature. By default the entire retroarch saves folder will be syncronized, which may be a plus considering that this feature is currently not available in retroarch.

v1.6.1
 - Updated RetroArch to 1.14.0
 - Updated ScummVM mainline (added virtual keyboard and D-pad cursor acceleration time setting)
 - Added system shutdown/reboot from RetroArch
 - Added setting to force SMB protocol version for roms remote path mount
 - Dropped setting to stop Kodi on Retroarch start (default now)

v1.6.0
 - Added 'Boot to RetroArch' feature in settings
 - Added brand new core: ScummVM mainline (in sync with ScummVM official releases, updated to v2.6.1)
 - Updated RetroArch to 1.13.0
 - Updated all cores and packages to latest

v1.5.8
 - Updated RetroArch to 1.12.0

v1.5.7
 - Updated RetroArch to 1.11.0
 - Fixed and improved broken auto-update feature
 - Added flac and libogg packages needed for some cores (e.g. same_cdi)

v1.5.6
 - Added compatibility with CoreELEC 20-Nexus
 - Fixed RetroArch crash on video threaded switch
 - Migrated build scripts to Lakka-v4.x build system

v1.5.5
 - Added BT controllers shutdown function on RetroArch exit.
 - Fixed parallel-n64 segfault
 - Replaced mupen64plus_next with old mupen64plus for amlogic-ng

v1.5.4
 - Added shutdown function on TV power-off (CEC)
 - Added CEC remote controller numeric pads support 
 - Updated PUAE2021 to latest
 - Added changelog to addon information screen

v1.5.3
 - Updated RetroArch and cores to latest as per Lakka v3.7.3
 - Changed PUAE core to PUAE2021

v1.5.2
 - Updated RetroArch to v1.10.3
 - Dowloaded resources are now stored in local config path, hence no need to download again on addon update
 - RetroArch language set same as Kodi on first run
 - Improved first run config scripts
 - Other minor fixes

v1.5.1
 - Updated retroarch and cores to latest Lakka versions.
 - Added reset to default function in settings (will reset retroarch.cfg and set addon to first run state)
 - Added automatic merge of updated addon contents (e.g. system folder) with existing local content (in /storage/.config/retroarch), if any
 - Added Czech translation, thanks to @Ricrdsson1
 - Other minor fixes

v1.5.0
 - Added internal auto update capabilities
 - Added translation capabilities
 - Retroarch updated to 1.10.2
 - Cores updated to latest
 - Added full italian translation
 - Fixed locally a security flaw affecting user inputs for all addons (PR sent upstream)

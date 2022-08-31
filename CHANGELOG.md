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

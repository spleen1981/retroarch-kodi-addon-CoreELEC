#!/bin/bash

read -d '' retroarch_sh <<EOF
#!/bin/sh

. /etc/profile

oe_setup_addon ${ADDON_NAME}

systemd-run -u retroarch \$ADDON_DIR/bin/retroarch.start
EOF

read -d '' retroarch_start <<EOF
#!/bin/sh

. /etc/profile

oe_setup_addon ${ADDON_NAME}
$HOOK_RETROARCH_START_0
PATH="\$ADDON_DIR/bin:\$PATH"
LD_LIBRARY_PATH="\$ADDON_DIR/lib:\$LD_LIBRARY_PATH"
RA_CONFIG_DIR="/storage/.config/retroarch/"
RA_CONFIG_FILE="\$RA_CONFIG_DIR/retroarch.cfg"
RA_CONFIG_SUBDIRS="savestates savefiles remappings playlists system thumbnails"
RA_EXE="\$ADDON_DIR/bin/retroarch"
RA_LOG=""
ROMS_FOLDER="/storage/roms"
DOWNLOADS="downloads"
RA_PARAMS="--config=\$RA_CONFIG_FILE --menu"
LOGFILE="/storage/retroarch.log"

[ ! -d "\$RA_CONFIG_DIR" ] && mkdir -p "\$RA_CONFIG_DIR"
[ ! -d "\$ROMS_FOLDER" ] && mkdir -p "\$ROMS_FOLDER"
[ ! -d "\$ROMS_FOLDER/\$DOWNLOADS" ] && mkdir -p "\$ROMS_FOLDER/\$DOWNLOADS"

for subdir in \$RA_CONFIG_SUBDIRS ; do
	[ ! -d "\$RA_CONFIG_DIR/\$subdir" ] && mkdir -p "\$RA_CONFIG_DIR/\$subdir"
done

if [ ! -f "\$RA_CONFIG_FILE" ]; then
	if [ -f "\$ADDON_DIR/config/retroarch.cfg" ]; then
		cp "\$ADDON_DIR/config/retroarch.cfg" "\$RA_CONFIG_FILE"
	fi
fi

[ "\$ra_verbose" = "true" ] && RA_PARAMS="--verbose \$RA_PARAMS"

[ "\$ra_log" = "true" ] && RA_PARAMS="--log-file=\$LOGFILE \$RA_PARAMS"

if [ "\$ra_stop_kodi" = "true" ] ; then
	systemctl stop kodi
else
	pgrep kodi.bin | xargs kill -SIGSTOP
fi

if [ "\$ra_roms_remote" = "true" ] ; then
	RA_REMOTE_OPTS=""
	RA_REMOTE_OPTS_PRE=""
	if [ ! -z "\$ra_roms_remote_user" ] ; then
		RA_REMOTE_OPTS="username=\$ra_roms_remote_user,password=\$ra_roms_remote_password"
		RA_REMOTE_OPTS_PRE="-o"
	fi
	[ ! -z "\$ra_roms_remote_path" ] && mount \$RA_REMOTE_OPTS_PRE "\$RA_REMOTE_OPTS" "\$ra_roms_remote_path" "\$ROMS_FOLDER"
fi

[ "\$ra_cec_remote" = "true" ] && systemd-run -u cec-kb "\$ADDON_DIR/bin/cec-mini-kb"
\$RA_EXE \$RA_PARAMS
[ "\$ra_cec_remote" = "true" ] && systemctl stop cec-kb.service

[ "\$ra_xbox360_shutdown" = "true" ] && "\$ADDON_DIR"/bin/xbox360-controllers-shutdown

[ "\$ra_roms_remote" = "true" ] && umount "\$ROMS_FOLDER"

if [ "\$ra_stop_kodi" = "true" ] ; then
	systemctl start kodi
else
	pgrep kodi.bin | xargs kill -SIGCONT
fi
$HOOK_RETROARCH_START_1
exit 0
EOF

read -d '' addon_xml <<EOF
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<addon id="${ADDON_NAME}" name="RetroArch" version="${ADDON_VERSION}" provider-name="${PROVIDER}">
	<requires>
		<import addon="xbmc.python" version="3.0.0"/>
	</requires>
	<extension point="xbmc.python.pluginsource" library="default.py">
		<provides>executable game</provides>
	</extension>
	<extension point="xbmc.addon.metadata">
		<summary lang="en">RetroArch add-on for Kodi (${RA_NAME_SUFFIX}). RetroArch is a frontend for emulators, game engines and media players.</summary>
		<description lang="en">The add-on provides binary, cores and basic settings to launch RetroArch from Kodi UI, plus additional features to improve user experience. It is built from Lakka sources.</description>
		<disclaimer lang="en">This is an unofficial add-on. Use github.com/spleen1981/retroarch-kodi-addon-CoreELEC to submit issues.</disclaimer>
		<platform>linux</platform>
		<assets>
			<icon>resources/icon.png</icon>
			<fanart>resources/fanart.jpg</fanart>
		</assets>
	</extension>
</addon>
EOF

read -d '' default_py <<EOF
import xbmc, xbmcgui, xbmcplugin, xbmcaddon
import os
import util

dialog = xbmcgui.Dialog()
dialog.notification('RetroArch', 'Launching....', xbmcgui.NOTIFICATION_INFO, 500)
ADDON_ID = '${ADDON_NAME}'

addon = xbmcaddon.Addon(id=ADDON_ID)
addon_dir = xbmc.translatePath( addon.getAddonInfo('path') )
addonfolder = addon.getAddonInfo('path')

icon    = addonfolder + 'resources/icon.png'
fanart  = addonfolder + 'resources/fanart.jpg'

util.runRetroarchMenu()
EOF

read -d '' util_py <<EOF
import os, xbmc, xbmcaddon

ADDON_ID = '${ADDON_NAME}'
BIN_FOLDER="bin"
RETROARCH_EXEC="retroarch.sh"

addon = xbmcaddon.Addon(id=ADDON_ID)

def runRetroarchMenu():
	addon_dir = xbmc.translatePath( addon.getAddonInfo('path') )
	bin_folder = os.path.join(addon_dir,BIN_FOLDER)
	retroarch_exe = os.path.join(bin_folder,RETROARCH_EXEC)
	os.system(retroarch_exe)
EOF

read -d '' settings_xml <<EOF
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<settings>
	<category label="General">
		<setting id="ra_stop_kodi" label="Stop Kodi before launching RetroArch" type="bool" default="true" />
		<setting id="ra_xbox360_shutdown" label="Turn off Xbox360 controllers after closing RetroArch" type="bool" default="true" />
		<setting id="ra_cec_remote" label="Use CEC remote control with RetroArch" type="bool" default="true" />
	</category>
	<category label="Paths">
		<setting id="ra_roms_remote" label="Mount remote path for RetroArch roms" type="bool" default="false" />
		<setting id="ra_roms_remote_path" label="Remote path" type="text" default="" enable="eq(-1,true)" subsetting="true"/>
		<setting id="ra_roms_remote_user" label="Username" type="text" default="" enable="eq(-2,true)" subsetting="true"/>
		<setting id="ra_roms_remote_password" label="Password" type="text" default="" enable="eq(-3,true)" subsetting="true"/>
	</category>
	<category label="Logging">
		<setting id="ra_log" label="Logging of RetroArch output" type="bool" default="false" />
		<setting id="ra_verbose" label="Verbose logging (for debugging)" type="bool" default="false" />
	</category>
</settings>
EOF

read -d '' settings_default_xml <<EOF
<settings>
	<setting id="ra_stop_kodi" value="true" />
	<setting id="ra_xbox360_shutdown" value="true" />
	<setting id="ra_cec_remote" value="true" />
	<setting id="ra_roms_remote" value="false" />
	<setting id="ra_roms_remote_path" value="" />
	<setting id="ra_roms_remote_user" value="" />
	<setting id="ra_roms_remote_password" value="" />
	<setting id="ra_log" value="false" />
	<setting id="ra_verbose" value="false" />
</settings>
EOF

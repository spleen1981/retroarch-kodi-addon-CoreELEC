#!/bin/bash

read -d '' retroarch_sh <<EOF
#!/bin/sh

systemd-run -u retroarch \$HOME/.kodi/addons/script.retroarch.launcher.Amlogic-ng.arm/bin/retroarch.start "\$@"
EOF

read -d '' retroarch_start <<EOF
#!/bin/sh

#Fixes a bug up to CoreELEC 19.4
oe_setup_addon_new() {
  if [ ! -z \$1 ] ; then
    DEF="/storage/.kodi/addons/\$1/settings-default.xml"
    CUR="/storage/.kodi/userdata/addon_data/\$1/settings.xml"

    # export some useful variables
    ADDON_DIR="\$HOME/.kodi/addons/\$1"
    ADDON_HOME="\$HOME/.kodi/userdata/addon_data/\$1"
    ADDON_LOG_FILE="\$ADDON_HOME/service.log"

    [ ! -d \$ADDON_HOME ] && mkdir -p \$ADDON_HOME

    # copy defaults
    if [ -f "\$DEF" -a ! -f "\$CUR" ] ; then
      cp "\$DEF" "\$CUR"
    fi

    # parse config
    for xml_file in "\$DEF" "\$CUR"; do
      if [ -f "\$xml_file" ]; then
        XML_SETTINGS_VER="\$(xmlstarlet sel -t -m settings -v @version \$xml_file)"
        if [ "\$XML_SETTINGS_VER" = "2" ]; then
          eval \$(xmlstarlet sel -t -m settings/setting -v @id -o "=" -v . -n "\$xml_file" | sed -e "s/'/'\\\\\\\\\\\\\\\\''/g; s/=/='/; s/\$/'/")
        else
          eval \$(xmlstarlet sel -t -m settings -m setting -v @id -o "=" -v @value -n "\$xml_file" | sed -e "s/'/'\\\\\\\\\\\\\\\\''/g; s/=/='/; s/\$/'/")
        fi
      fi
    done
  fi
}

sync_audio_settings(){
KODI_AUDIO_SETTING=\$(cat /storage/.kodi/userdata/guisettings.xml | grep "audiooutput.audiodevice" | tr "" " " | sed -E 's|</.*>||' | sed -E 's|<.*>||' | sed 's| ||g')
KODI_AUDIO_DRIVER=\$(echo \$KODI_AUDIO_SETTING | sed -E 's|:.*||')
KODI_AUDIO_DEVICE=\$(echo \$KODI_AUDIO_SETTING | sed "s|\$KODI_AUDIO_DRIVER:||")

retroarch --features | tr "\\\\n" "|" |sed "s/|\\\\t\\\\t/ /g" | tr "|" "\\\\n" | grep -Eiq "\${KODI_AUDIO_DRIVER}.*yes"

[ \$? -eq 1 ] && return 1

case \$KODI_AUDIO_DRIVER in
	ALSA)
		RA_AUDIO_DRIVER=alsa
		RA_AUDIO_DEVICE=\$KODI_AUDIO_DEVICE
                #Double check device exists
		aplay -L | grep -q \$RA_AUDIO_DEVICE
		[ \$? -eq 1 ] && return 1
		;;
	PULSE)
		RA_AUDIO_DRIVER=pulse
		RA_AUDIO_DEVICE=""
		;;
	*)
		#Additional cases TBD
		return 1
		;;
esac

#If current device is suitable, retain current setting
cat \$RA_CONFIG_FILE | grep -Eq "audio_driver.*\$RA_AUDIO_DRIVER"
[ \$? -eq 1 ] && sed -i "s|^audio_driver.*|audio_driver = \$RA_AUDIO_DRIVER|g" \$RA_CONFIG_FILE

sed -i "s|^audio_device.*|audio_device = \$RA_AUDIO_DEVICE|g" \$RA_CONFIG_FILE
}

exit_script(){
	[ "\$ra_cec_remote" = "true" ] && systemctl stop cec-kb.service

	[ "\$ra_xbox360_shutdown" = "true" ] && "\$ADDON_DIR"/bin/xbox360-controllers-shutdown

	[ "\$ra_roms_remote" = "true" ] && umount "\$ROMS_FOLDER"

	if [ "\$ra_force_refresh_rate" = "true" -a ! -z "\$VIDEO_MODE_RES" ] ; then
		VIDEO_MODE_OLD="\$VIDEO_MODE_RES"
		[ ! -z \$VIDEO_MODE_RATE ] && VIDEO_MODE_OLD=\${VIDEO_MODE_OLD}\${VIDEO_MODE_RATE}hz
		echo "\$VIDEO_MODE_OLD" > "/sys/class/display/mode"
	fi

	if [ "\$ra_stop_kodi" = "true" ] ; then
		sed -E -i "s/\${CAP_GROUP_CEC}(.*)\\\"/\${CAP_GROUP_CEC}\${CEC_SHUTDOWN_SETTING_PREV}\\\"/" \$KODI_CEC_SETTINGS_FILE
		systemctl start kodi
	else
		pgrep kodi.bin | xargs kill -SIGCONT
	fi
	$HOOK_RETROARCH_START_1
	exit 0
}

. /etc/profile

oe_setup_addon_new ${ADDON_NAME}

trap exit_script SIGINT SIGTERM
$HOOK_RETROARCH_START_0
PATH="\$ADDON_DIR/bin:\$PATH"
LD_LIBRARY_PATH="\$ADDON_DIR/lib:\$LD_LIBRARY_PATH"
RA_CONFIG_DIR="/storage/.config/retroarch"
RA_CONFIG_FILE="\$RA_CONFIG_DIR/retroarch.cfg"
RA_CONFIG_SUBDIRS="savestates savefiles remappings playlists system thumbnails assets"
RA_CONFIG_CAN_OVERRIDE_SUBDIRS="assets system"
RA_EXE="\$ADDON_DIR/bin/retroarch"
RA_LOG=""
ROMS_FOLDER="/storage/roms"
DOWNLOADS="downloads"
RA_PARAMS="--config=\$RA_CONFIG_FILE"
LOGFILE="/storage/retroarch.log"
CAP_GROUP_CEC="<setting id=\\\"standby_devices\\\" value=\\\""
CEC_SHUTDOWN_SETTING_NO="231"
KODI_CEC_SETTINGS_FILE="\$(ls /storage/.kodi/userdata/peripheral_data/*CEC*.xml)"
VIDEO_MODE_RATE="\$(cat /sys/class/display/mode | grep -Eo [pi].+[h] | grep -Eo [0-9]+)"
VIDEO_MODE_RES="\$(cat /sys/class/display/mode | grep -Eo .\+[pi])"

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

# First run only actions
if [ ! -f \$ADDON_DIR/config/first_run_done ] ; then

	#Override default settings to point to custom directories if not empty not empty
	for subdir in \$RA_CONFIG_CAN_OVERRIDE_SUBDIRS ; do
		[ ! -z "\$(ls -A \${RA_CONFIG_DIR}/\${subdir})" ] && sed -i "s|^\${subdir}_directory.*|\${subdir}_directory = \\\"\${RA_CONFIG_DIR}/\${subdir}\\\"|g" \$RA_CONFIG_FILE
	done
	$HOOK_RETROARCH_START_2
	touch \$ADDON_DIR/config/first_run_done
fi

[ "\$ra_verbose" = "true" ] && RA_PARAMS="--verbose \$RA_PARAMS"

[ "\$ra_log" = "true" ] && RA_PARAMS="--log-file=\$LOGFILE \$RA_PARAMS"

if [ "\$ra_stop_kodi" = "true" ] ; then

	CEC_SHUTDOWN_SETTING_PREV=\$(cat "\$KODI_CEC_SETTINGS_FILE" | grep "\${CAP_GROUP_CEC}" | grep -Eow "([0-9]+)")

	if [ ! \$CEC_SHUTDOWN_SETTING_PREV == \$CEC_SHUTDOWN_SETTING_NO ] ; then
		#Workaround, as peripherals settings cannot be changed through json-rpc
		sed -E -i "s/\${CAP_GROUP_CEC}(.*)\\\"/\${CAP_GROUP_CEC}\${CEC_SHUTDOWN_SETTING_NO}\\\"/" \$KODI_CEC_SETTINGS_FILE
		pgrep kodi.bin | xargs kill -SIGHUP
	fi

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

VIDEO_MODE_NEWRATE=\$VIDEO_MODE_RATE
if [ "\$ra_force_refresh_rate" = "true" -a ! -z "\$VIDEO_MODE_RES" ] ; then
		case \$ra_forced_refresh_rate in
			"0")
				VIDEO_MODE_NEWRATE="50"
				;;
			"1")
				VIDEO_MODE_NEWRATE="60"
				;;
		esac
		echo \${VIDEO_MODE_RES}\${VIDEO_MODE_NEWRATE}hz > "/sys/class/display/mode"
fi
sed -E -i "s|video_refresh_rate.+|video_refresh_rate = \"\${VIDEO_MODE_NEWRATE}\"|g" \$RA_CONFIG_FILE

[ "\$ra_sync_audio_settings" = "true" ] && sync_audio_settings

[ "\$ra_cec_remote" = "true" ] && systemd-run -q -u cec-kb "\$ADDON_DIR/bin/cec-mini-kb"
\$RA_EXE \$RA_PARAMS "\$@"

exit_script
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

#!/bin/bash

NOTIFICATIONS_TITLE=RetroArch
LONG_NOTIFICATION=600000
SHORT_NOTIFICATION=2000
FIRST_RUN_FLAG_PREFIX=first_run_done
FIRST_RUN_FLAG_SUFFIX=10501

read -d '' retroarch_sh <<EOF
#!/bin/sh

systemd-run -u retroarch \$HOME/.kodi/addons/${ADDON_NAME}/bin/retroarch.start "\$@"
EOF

read -d '' retroarch_start <<EOF
#!/bin/sh

#substitutes 'cp -n' as not available
merge_dirs_no_clobber(){
	[ ! -d "\$1" ] && return 1
	[ ! -d "\$2" ] && return 2

	for item in "\$1/"*; do
		item_basename=\$( basename "\$item" )
		if [ -d "\$item" ]; then
			if [ -d "\$2/\$item_basename" ]; then
				merge_dirs_no_clobber "\$item" "\$2/\$item_basename"
			else
				cp -r "\$item" "\$2/"
			fi
		elif [ -f "\$item" ]; then
			[ ! -f "\$2/\$item_basename" ] && cp "\$item" "\$2/"
		fi
	done
	return 0
}

#Fixes a bug up to CoreELEC 19.4
oe_setup_addon_fix() {
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

ra_config_override(){
	[ -z "\$(ls -A \${RA_CONFIG_DIR}/\$1 2>/dev/null)" ] && return 1
	sed -i "s|=.*/resources/\$1|=\\\"\${RA_CONFIG_DIR}/\$1|g" \$RA_CONFIG_FILE
	[ ! -d "\${ADDON_DIR}/resources/\$1" ] && return 2
	if [ \$2 == 'merge_no_clobber' ]; then
		merge_dirs_no_clobber "\${ADDON_DIR}/resources/\$1" "\${RA_CONFIG_DIR}/\$1"
	else
		cp -rf "\${ADDON_DIR}/resources/\$1" "\${RA_CONFIG_DIR}/\$1"
	fi
}

. /etc/profile

oe_setup_addon_fix ${ADDON_NAME}

trap exit_script SIGINT SIGTERM
$HOOK_RETROARCH_START_0
PATH="\$ADDON_DIR/bin:\$PATH"
LD_LIBRARY_PATH="\$ADDON_DIR/lib:\$LD_LIBRARY_PATH"
RA_CONFIG_DIR="/storage/.config/retroarch"
RA_CONFIG_FILE="\$RA_CONFIG_DIR/retroarch.cfg"
RA_CONFIG_SUBDIRS="savestates savefiles remappings playlists system thumbnails assets overlays"
RA_ADDON_BIN_FOLDER="\$ADDON_DIR/bin"
RA_EXE="\$RA_ADDON_BIN_FOLDER/retroarch"
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
if [ ! -f \${ADDON_DIR}/config/${FIRST_RUN_FLAG_PREFIX}_${FIRST_RUN_FLAG_SUFFIX} ] ; then
	\$RA_ADDON_BIN_FOLDER/ra_update_utils.sh clear_flags

	ra_config_override 'system' merge_no_clobber
	ra_config_override 'assets'
	ra_config_override 'joypads'
	ra_config_override 'shaders'
	ra_config_override 'database'
	ra_config_override 'overlays'

$HOOK_RETROARCH_START_2
	touch \$ADDON_DIR/config/${FIRST_RUN_FLAG_PREFIX}_${FIRST_RUN_FLAG_SUFFIX}
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

read -d '' ra_update_utils_sh <<EOF
#!/bin/sh

ra_updater_create(){
result="#!/bin/sh
#unzip addon to folder
unzip -q -o \$RA_TMP_PATH/\$file_name -d \$HOME/.kodi/addons/
if [ ! \\\\\$? -eq 0 ] ; then
	kodi-send --action=\\\"Notification($NOTIFICATIONS_TITLE, \$FAILED_MESSAGE, $SHORT_NOTIFICATION, \$RA_ICON)\\\"
	return 31
fi
rm \$RA_TMP_PATH/\$file_name
rm \$RA_UPDATER
kodi-send --action=\\\"Notification($NOTIFICATIONS_TITLE, \$SUCCEEDED_MESSAGE, $SHORT_NOTIFICATION, \$RA_ICON)\\\"
kodi-send --action='UpdateLocalAddons'"
if [ \$1 = 'install_restart' ] ; then
	result=\${result}"
kodi-send --action=\\\"RunAddon(${ADDON_NAME})\\\""
fi
echo "\$result"
}

validate_url(){
	if [ -z "\$( wget -S --spider \$1  2>&1 | grep 'HTTP/1.1 200 OK' )" ]; then
		return 1
	else
		return 0
	fi
}

get_version(){
	[ -z \$( echo \$1 | grep ^v[0-9+]\\\.[0-9+]\\\.[0-9+]$ ) ] && return 0
	string_version=\$( echo \$1 | sed "s/v//; s/\\\./ /g" )
	n=10000
	tot=0
	for y in \$string_version; do
		let tot=tot+y*n
		let n=n/100
	done
	echo \$tot
}

get_update_url(){
	#check server can be reached
	validate_url \$SERVER_URL
	if [ ! \$? -eq 0 ] ; then
		return 2
	fi

	#check if a compatible download link exists, first one assumed as latest
	LATEST_URL=\$( curl --silent \${SERVER_URL}/spleen1981/\${REPO_NAME}/releases | grep href=.*download.*${ADDON_NAME}.*zip | sed 1q | sed "s/.*href=[\\\"\\\']//; s/zip.*/zip/")
	if [ -z \$LATEST_URL ] ; then
		return 3;
	fi

	#check if current addon is older than latest
	if [ ! \$( get_version $ADDON_VERSION ) -lt \$( get_version \$( echo \$LATEST_URL | sed "s/.*${ADDON_NAME}-//g;s/.zip.*//" ) ) ] ; then
		return 1
	fi

	#check latest addon link is valid
	echo \${SERVER_URL}\${LATEST_URL}
	validate_url \${SERVER_URL}\${LATEST_URL}
	if [ ! \$? -eq 0 ] ; then
		return 6
	fi

	return 0
}

ra_install(){
	get_update_url
	[ ! \$? -eq 0 ] && return 11
	[ -z \$2 ] && DOWNLOAD_MESSAGE='Downloading update...' || DOWNLOAD_MESSAGE="\$2"
	[ -z \$3 ] && INSTALL_MESSAGE='Installing update...' || INSTALL_MESSAGE="\$3"
	[ -z \$4 ] && FAILED_MESSAGE='Update failed' || FAILED_MESSAGE="\$4"
	[ -z \$5 ] && SUCCEEDED_MESSAGE='Update completed' || SUCCEEDED_MESSAGE="\$5"


	RA_UPDATER='/tmp/ra_updater.start'
	RA_TMP_PATH='/tmp'
	file_name=\$( echo \${LATEST_URL} | sed s/.*${ADDON_NAME}/${ADDON_NAME}/ )

	#download zip update
	kodi-send --action="Notification($NOTIFICATIONS_TITLE, \$DOWNLOAD_MESSAGE, $LONG_NOTIFICATION, \$RA_ICON)"
	wget -q -t 5 \${SERVER_URL}\${LATEST_URL} -O /\$RA_TMP_PATH/\$file_name 2>&1
	if [ ! \$? -eq 0 ] ; then
		return 12
	fi

	kodi-send --action="Notification($NOTIFICATIONS_TITLE, \$INSTALL_MESSAGE, $LONG_NOTIFICATION, \$RA_ICON)"

	ra_updater_create "\$1" > \$RA_UPDATER
	chmod +x \$RA_UPDATER
	systemd-run \$RA_UPDATER
	[ ! \$? -eq 0 ] && return 13 || return 0
}

clear_flags(){
	[ ! -z "\$(ls -A \$CLEAR_FLAGS_SRC 2>/dev/null)" ] && eval rm \$CLEAR_FLAGS_SRC
}

ra_cfg_backup_clear(){
	[ ! -f \$RA_CONFIG_FILE ] && return 1
	mv \$RA_CONFIG_FILE \${RA_CONFIG_FILE}_\$(date +%y_%m_%d_%s)
	return \$?
}

SERVER_URL='https://github.com'
REPO_NAME='retroarch-kodi-addon-CoreELEC'
RA_ICON=\$HOME/.kodi/addons/${ADDON_NAME}/resources/icon.png
CLEAR_FLAGS_SRC="\$HOME/.kodi/addons/${ADDON_NAME}/config/${FIRST_RUN_FLAG_PREFIX}*"
RA_CONFIG_DIR=\$HOME/.config/retroarch
RA_CONFIG_FILE=\$RA_CONFIG_DIR/retroarch.cfg

case \$1 in
	check)
		get_update_url
		exit \$?
		;;
	clear_flags)
		clear_flags
		exit \$?
		;;
	clear_cfg)
		ra_cfg_backup_clear
		exit \$?
		;;
	install*)
		ra_install "\$1" "\$2" "\$3" "\$4" "\$5"
		exit \$?
		;;
esac

EOF

read -d '' default_py <<EOF
import xbmcgui, xbmcaddon
import os, sys
import util

ADDON_ID = '${ADDON_NAME}'

addon = xbmcaddon.Addon(id=ADDON_ID)
addon_dir = addon.getAddonInfo('path')

icon = os.path.join(addon_dir, 'resources', 'icon.png')
fanart = os.path.join(addon_dir, 'resources', 'fanart.png')

dialog = xbmcgui.Dialog()

manual_update=False
if len(sys.argv) > 1:
	if sys.argv[1] == 'check_updates':
		manual_update=True
	elif sys.argv[1] == 'reset':
		util.resetToDefaults()
		quit()
if (addon.getSetting("ra_autoupdate")=='true' or manual_update):
	if not util.runUpdaterMenu(manual_update) or manual_update:
		quit()

dialog.notification(\'$NOTIFICATIONS_TITLE\', util.getLocalizedString(20186), icon, $LONG_NOTIFICATION)
util.runRetroarchMenu()
EOF

read -d '' util_py <<EOF
import os, subprocess, xbmc, xbmcgui, xbmcaddon

ADDON_ID = '${ADDON_NAME}'
BIN_FOLDER="bin"
RETROARCH_EXEC="retroarch.sh"
UPDATER_EXEC="ra_update_utils.sh"

addon = xbmcaddon.Addon(id=ADDON_ID)
addon_dir = addon.getAddonInfo('path')
bin_folder = os.path.join(addon_dir,BIN_FOLDER)
#usersettings_dir = addon.getAddonInfo('profile') #not needed as relevant function for kodi addon settings is already available in UI
updater_exe = os.path.join(bin_folder,UPDATER_EXEC)
retroarch_exe = os.path.join(bin_folder,RETROARCH_EXEC)

icon = os.path.join(addon_dir, 'resources', 'icon.png')
dialog = xbmcgui.Dialog()

def getLocalizedString(id):
	if (id < 32000):
		return xbmc.getLocalizedString(id)
	else:
		return addon.getLocalizedString(id)

def runRetroarchMenu():
	subprocess.run(retroarch_exe)

def resetToDefaults():
	if(dialog.yesno(getLocalizedString(13007) + \' (retroarch.cfg / setup)\', getLocalizedString(750))):
		#subprocess.run(['rm', '-rf', usersettings_dir]) #not needed as relevant function for kodi addon settings is already available in UI
		subprocess.run([updater_exe, "clear_cfg"])
		subprocess.run([updater_exe, "clear_flags"])
		dialog.notification(\'$NOTIFICATIONS_TITLE\', getLocalizedString(13007) + \' (retroarch.cfg / setup)\', icon, $SHORT_NOTIFICATION)
def runUpdaterMenu(manual_update=False):
	dialog.notification(\'$NOTIFICATIONS_TITLE\', getLocalizedString(24092), icon, $LONG_NOTIFICATION)
	resp = subprocess.run([updater_exe, "check"])
	ret=resp.returncode

	if manual_update:
		arg1="install"
	else:
		arg1="install_restart"
	if not ret:
		if(dialog.yesno(getLocalizedString(24061), getLocalizedString(24101))):
			resp = subprocess.run([updater_exe, arg1, getLocalizedString(24078), getLocalizedString(24086), getLocalizedString(113), getLocalizedString(24065)])
			ret=resp.returncode
			if ret:
				dialog.notification(\'$NOTIFICATIONS_TITLE\', getLocalizedString(113) + ' (' + str(ret) + ')', icon, $SHORT_NOTIFICATION)
		else:
			dialog.notification(\'$NOTIFICATIONS_TITLE\', getLocalizedString(16024), icon, $SHORT_NOTIFICATION)
			ret=1
	elif ret == 1:
		dialog.notification(\'$NOTIFICATIONS_TITLE\', getLocalizedString(21341), icon, $SHORT_NOTIFICATION)
	else:
		dialog.notification(\'$NOTIFICATIONS_TITLE\', getLocalizedString(113) + ' (' + str(ret) + ')', icon, $SHORT_NOTIFICATION)
	return ret
EOF

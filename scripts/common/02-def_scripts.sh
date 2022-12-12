#!/bin/bash

NOTIFICATIONS_TITLE=RetroArch
LONG_NOTIFICATION=600000
SHORT_NOTIFICATION=2000
FIRST_RUN_FLAG_PREFIX=first_run_done
BOOT_TO_RA_FLAG_TRUE=RETROARCH
BOOT_TO_RA_FLAG_FALSE=KODI

read -d '' ra_autostart_sh <<EOF
#!/bin/sh
. /etc/profile

oe_setup_addon ${ADDON_NAME}

#check settings have not be changed externally in the meanwhile (e.g. reset to defaults)
"\$ADDON_DIR"/bin/ra_boot_toggle.sh check

test \$? -eq 1 && \
systemctl mask kodi && \
pgrep splash-image | xargs kill -SIGTERM && \
eval \$(cat /usr/lib/systemd/system/kodi.service | grep ExecStartPre= | sed "s|ExecStartPre=[-]*||g;s|$| ; |g") \
systemd-run -q -u retroarch "\$ADDON_DIR/bin/retroarch.start" && \
return 0

#fallback

"\$ADDON_DIR"/bin/ra_boot_toggle.sh off && \
reboot now && \
return 1
EOF

read -d '' ra_boot_toggle_sh <<EOF
#!/bin/sh

. /etc/profile

oe_setup_addon ${ADDON_NAME}

test_boot_ra(){
	[ ! -z \$ra_boot_toggle ] && [ \$ra_boot_toggle = $BOOT_TO_RA_FLAG_TRUE ] && echo 1 && return 1
	echo 0
}

BOOT_RA_CMD="\$ADDON_DIR/bin/ra_autostart.sh 2>/dev/null"
AUTOSTART_SH=\$(cat /usr/lib/systemd/system/kodi-autostart.service| grep ExecStart= | sed "s|.*\\\(/storage/.*[0-9a-zA-Z_\\\-\\\.]\\\).*|\\\1|g")

[ -z \$1 ] && TARGET='NA' || TARGET=\$1

#setting is currently on
if [ \$(test_boot_ra) = 1 ] && [ ! \$TARGET = on ] || [ \$TARGET = off ]; then
	#if check only is required, make sure setting is properly applied forcing expected current setting
	[ \$TARGET = 'check' ] && "\$ADDON_DIR"/bin/ra_boot_toggle.sh on && return 1

	if [ -f \$AUTOSTART_SH ]; then
		sed -i "s#\$BOOT_RA_CMD##;/^$/d" \$AUTOSTART_SH
		TEST=\$(cat \$AUTOSTART_SH)
		[ -z "\$TEST" ] && rm -f \$AUTOSTART_SH
	fi
	systemctl unmask kodi
	sed -i "s#>${BOOT_TO_RA_FLAG_TRUE}<#>${BOOT_TO_RA_FLAG_FALSE}<#" \$ADDON_HOME/settings.xml && return 0
#setting is currently off
elif [ \$(test_boot_ra) = 0 ] || [ \$TARGET = on ]; then
	[ \$TARGET = 'check' ] && "\$ADDON_DIR"/bin/ra_boot_toggle.sh off && return 0

	if [ -f \$AUTOSTART_SH ]; then
		TEST=\$(cat \$AUTOSTART_SH | grep "\$BOOT_RA_CMD")
		[ -z "\$TEST" ] && echo "\$BOOT_RA_CMD" >> \$AUTOSTART_SH
	else
		echo "\$BOOT_RA_CMD" >> \$AUTOSTART_SH && chmod +x \$AUTOSTART_SH
	fi
	sed -i "s#>${BOOT_TO_RA_FLAG_FALSE}<#>${BOOT_TO_RA_FLAG_TRUE}<#" \$ADDON_HOME/settings.xml && return 0
	touch \$BOOT_TOGGLE_FILE && return 0
fi
EOF

read -d '' retroarch_sh <<EOF
#!/bin/sh

systemd-run -u retroarch \$HOME/.kodi/addons/${ADDON_NAME}/bin/retroarch.start "\$@"
EOF

read -d '' retroarch_start <<EOF
#!/bin/sh

#restore symlinks as they seem to get broken by kodi addon installer
restore_flattened_symlinks(){
	cd \$1
	[ \$? -eq 0 ] || { echo "symlinks restoring in $1 failed" ; return 1 ; }

	for file_src in * ; do
		if [ ! -d \$file_src -a ! -L \$file_src ]; then
			size_scr=\$(wc -c \$file_src)
			if [ \${size_scr//" \$file_src"} -lt 100 ]; then
				[ -f \$(cat \$file_src) ] && ln -sf \$(cat \$file_src) \$file_src
			fi
		fi
		#chmod +x \$file_src
	done
	cd - > /dev/null
}

#substitutes 'cp -n' as not available
merge_dirs_maybe_no_clobber(){
	[ ! -d "\$1" ] && return 1
	[ ! -d "\$2" ] && return 2

	for item in "\$1/"*; do
		item_basename=\$( basename "\$item" )
		if [ -d "\$item" ]; then
			if [ -d "\$2/\$item_basename" ]; then
				merge_dirs_maybe_no_clobber "\$item" "\$2/\$item_basename"
			else
				copy_if_not_equal "\$item" "\$2"
			fi
		elif [ -f "\$item" ]; then
			copy_if_not_equal "\$item" "\$2"
		fi
	done
	return 0
}

copy_if_not_equal(){
	item_basename=\$( basename "\$1" )
	if [ -f "\$2/\$item_basename" ]; then
		\$RA_ADDON_BIN_FOLDER/cmp "\$1" "\$2/\$item_basename"
		[ \$? -eq 0 ] && return 1
	fi
	cp -rf "\$1" "\$2/"
}


#Fixes a bug up to CoreELEC 19.4
oe_setup_addon_fix() {
  if [ ! -z \$1 ] ; then
    DEF="\$HOME/.kodi/addons/\$1/settings-default.xml"
    CUR="\$HOME/.kodi/userdata/addon_data/\$1/settings.xml"

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
KODI_AUDIO_SETTING=\$(cat \$HOME/.kodi/userdata/guisettings.xml | grep "audiooutput.audiodevice" | tr "" " " | sed -E 's|</.*>||' | sed -E 's|<.*>||' | sed 's| ||g')
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

	[ "\$ra_bt_shutdown" = "true" ] && bluetoothctl power off && bluetoothctl power on

	[ "\$ra_roms_remote" = "true" ] && umount "\$ROMS_FOLDER"

	if [ "\$ra_force_refresh_rate" = "true" -a ! -z "\$VIDEO_MODE_RES" ] ; then
		VIDEO_MODE_OLD="\$VIDEO_MODE_RES"
		[ ! -z \$VIDEO_MODE_RATE ] && VIDEO_MODE_OLD=\${VIDEO_MODE_OLD}\${VIDEO_MODE_RATE}hz
		echo "\$VIDEO_MODE_OLD" > "/sys/class/display/mode"
	fi

	[ ! -z "\$(systemctl status kodi | grep masked)" ] && systemctl unmask kodi

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
	[ -d "\${RA_CONFIG_DIR}/\$1" ]
	local config_res_dir_exists=\$?
	[ ! -z "\$(ls -A \${RA_CONFIG_DIR}/\$1 2>/dev/null)" ]
	local config_res_dir_exists_not_empty=\$?
	[ -d "\${ADDON_DIR}/resources/\$1" ]
	local addon_res_dir_exists=\$?

	if [ ! \$addon_res_dir_exists -eq 0 ] && [ ! \$config_res_dir_exists -eq 0 ]; then
		return 1
	fi

	#if resources are not included in the build, local config path is always preferred.
	#if resources are included in the addon but local config path is not empty, the latter is chosen and content is merged as needed
	if [ ! \$addon_res_dir_exists -eq 0 ] || [ \$config_res_dir_exists_not_empty -eq 0 ]; then
		sed -i "s|=.*/resources/\$1|= \\\"\${RA_CONFIG_DIR}/\$1|g" \$RA_CONFIG_FILE
	fi

	if [ \$addon_res_dir_exists -eq 0 ] && [ \$config_res_dir_exists -eq 0 ]; then
		if [ \$2 == 'merge_maybe_no_clobber' ]; then
			merge_dirs_maybe_no_clobber "\${ADDON_DIR}/resources/\$1" "\${RA_CONFIG_DIR}/\$1"
		else
			cp -rf "\${ADDON_DIR}/resources/\$1" "\${RA_CONFIG_DIR}/\$1"
		fi
	fi
}

. /etc/profile

oe_setup_addon_fix ${ADDON_NAME}

trap exit_script SIGINT SIGTERM
$HOOK_RETROARCH_START_0
PATH="\$ADDON_DIR/bin:\$PATH"
LD_LIBRARY_PATH="\$ADDON_DIR/lib:\$LD_LIBRARY_PATH"
RA_CONFIG_DIR="\$HOME/.config/retroarch"
RA_CONFIG_FILE="\$RA_CONFIG_DIR/retroarch.cfg"
RA_CONFIG_SUBDIRS="savestates savefiles remappings playlists thumbnails system assets joypads shaders database overlays"
RA_ADDON_BIN_FOLDER="\$ADDON_DIR/bin"
RA_EXE="\$RA_ADDON_BIN_FOLDER/retroarch"
RA_LOG=""
ROMS_FOLDER="\$HOME/roms"
DOWNLOADS="downloads"
RA_PARAMS="--config=\$RA_CONFIG_FILE"
LOGFILE="\$HOME/retroarch.log"
CAP_GROUP_CEC="<setting id=\\\"standby_devices\\\" value=\\\""
CEC_SHUTDOWN_SETTING_NO="231"
KODI_CEC_SETTINGS_FILE="\$(ls \$HOME/.kodi/userdata/peripheral_data/*CEC*.xml)"
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
if [ ! -f \${ADDON_DIR}/config/${FIRST_RUN_FLAG_PREFIX} ] ; then

	\$RA_ADDON_BIN_FOLDER/ra_update_utils.sh clear_flags

	. \$RA_ADDON_BIN_FOLDER/ra_language_utils.sh

	kodi_locale=\$(cat \$HOME/.kodi/userdata/guisettings.xml | grep locale.language | sed "s/.*resource.language.//;s/<.*>//")
	if [ -z \$(echo \$RA_CONFIG_FILE | grep user_language) ]; then
		echo "user_language = \\\"\$(ra_get_language \$kodi_locale)\\\"" >> \$RA_CONFIG_FILE
	else
		sed -i "s|user_language.*|user_language = \\\"\$(ra_get_language \$kodi_locale)\\\"|" \$RA_CONFIG_FILE
	fi

	ra_config_override 'system' merge_maybe_no_clobber
	ra_config_override 'assets'
	ra_config_override 'joypads'
	ra_config_override 'shaders'
	ra_config_override 'database'
	ra_config_override 'overlays'

	restore_flattened_symlinks \$ADDON_DIR/lib

	#workaround for CE20 missing symlinks
	ln -sf /lib/libssl.so \${ADDON_DIR}/lib/libssl.so.1.1
	ln -sf /lib/libcrypto.so \${ADDON_DIR}/lib/libcrypto.so.1.1

$HOOK_RETROARCH_START_2
	touch \$ADDON_DIR/config/${FIRST_RUN_FLAG_PREFIX}
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

#CEC remote
RA_POWEROFF_OPTS_PRE=""
RA_POWEROFF_OPTS_CMD=""
if [ "\$ra_cec_poweroff" = '0' ] ; then
	RA_POWEROFF_OPTS_PRE="--poweroff"
	[ "\$ra_xbox360_shutdown" = "true" ] && RA_POWEROFF_OPTS_CMD="\${ADDON_DIR}/bin/xbox360-controllers-shutdown;"
	RA_POWEROFF_OPTS_CMD="\${RA_POWEROFF_OPTS_CMD}shutdown -P now"
fi
[ "\$ra_cec_remote" = "true" ] && systemd-run -q -u cec-kb "\$ADDON_DIR/bin/cec-mini-kb" \$RA_POWEROFF_OPTS_PRE "\$RA_POWEROFF_OPTS_CMD"
\$RA_EXE \$RA_PARAMS "\$@"

exit_script
EOF

read -d '' ra_update_utils_sh <<EOF
#!/bin/sh

ra_updater_create(){
result="#!/bin/sh

#unzip addon to folder
mv \$ADDON_SRC \${ADDON_SRC}_bkp
[ \\\\\$? -eq 0 ] && unzip -q -o \$RA_TMP_PATH/\$file_name -d \$HOME/.kodi/addons/
if [ ! \\\\\$? -eq 0 ] ; then
	kodi-send --action=\\\"Notification($NOTIFICATIONS_TITLE, \$FAILED_MESSAGE, $SHORT_NOTIFICATION, \$RA_ICON)\\\"
	if [ -d \${ADDON_SRC}_bkp ] ; then
		[ -d \${ADDON_SRC} ] && rm -rf \${ADDON_SRC}
		mv \${ADDON_SRC}_bkp \${ADDON_SRC}
	fi
	return 31
fi
rm -rf \${ADDON_SRC}_bkp
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

#no array support in busybox shell
get_array_element(){
	local i=0
	local temp=""
	for element in \$1; do
		temp=\$element
		[ \$i -eq \$2 ] && break
		i=\$((\$i + 1))
	done
	[ -z \$temp ] || echo \$temp
}

validate_url(){
	if [ -z "\$( wget -S --spider \$1  2>&1 | grep 'HTTP/1.1 200 OK' )" ]; then
		return 1
	else
		return 0
	fi
}

get_version(){
	[ -z \$( echo \$1 | grep -E ^v[0-9]+\\\.[0-9]+\\\.[0-9]+$ ) ] && return 0
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
	validate_url \$REPO_INFO_URL
	if [ ! \$? -eq 0 ] ; then
		return 2
	fi

	source /etc/os-release

	local VERSION_QUERY=" and @min_ver<=\$VERSION_ID"

	[ -z \$( echo \$VERSION_ID | grep -E ^[0-9]+\\\.[0-9]+\$ ) -a -z \$( echo \$VERSION_ID | grep -E ^[0-9]+\$ ) ] && VERSION_QUERY=""
	local BASE_QUERY="//updates/latest[@arch=\\\"$RA_NAME_SUFFIX\\\" and @distro=\\\"\${ID}\\\"\${VERSION_QUERY}]/"

	local TEMP_XML="\$( curl --silent \$REPO_INFO_URL )"

	#check if compatible update is available and get download url
	#last element is selected in case of multiple possibilities

	local LATEST_VER=\$( echo \$TEMP_XML | xmlstarlet sel -t -v "\${BASE_QUERY}"version )
	LATEST_VER=\$( get_array_element "\$LATEST_VER" -1 )

	[ \$( get_version $ADDON_VERSION ) -lt \$( get_version \$LATEST_VER ) ] 1>/dev/null 2>&1
	[ ! \$? -eq 0 ] && return 1

	LATEST_URL=\$( echo \$TEMP_XML | xmlstarlet sel -t -v "\${BASE_QUERY}"download_url )
	LATEST_URL=\$( get_array_element "\$LATEST_URL" -1 )
	if [ -z \$LATEST_URL ] ; then
		return 3;
	fi

	#check update url is valid
	validate_url \${LATEST_URL}
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
	wget -q -t 5 \${LATEST_URL} -O /\$RA_TMP_PATH/\$file_name 2>&1
	if [ ! \$? -eq 0 ] ; then
		return 12
	fi

	kodi-send --action="Notification($NOTIFICATIONS_TITLE, \$INSTALL_MESSAGE, $LONG_NOTIFICATION, \$RA_ICON)"

	ra_updater_create "\$1" > \$RA_UPDATER
	chmod +x \$RA_UPDATER
	systemd-run \$RA_UPDATER
	[ \$? -eq 0 ] && return 0 || return 13
}

clear_flags(){
	[ ! -z "\$(ls -A \$CLEAR_FLAGS_SRC 2>/dev/null)" ] && eval rm \$CLEAR_FLAGS_SRC
}

ra_cfg_backup_clear(){
	[ ! -f \$RA_CONFIG_FILE ] && return 1
	mv \$RA_CONFIG_FILE \${RA_CONFIG_FILE}_\$(date +%y_%m_%d_%s)
	return \$?
}

REPO_INFO_URL='https://raw.githubusercontent.com/spleen1981/retroarch-kodi-addon-CoreELEC/master/updates.xml'
RA_ICON=\$HOME/.kodi/addons/${ADDON_NAME}/resources/icon.png
ADDON_SRC="\$HOME/.kodi/addons/${ADDON_NAME}"
CLEAR_FLAGS_SRC="\${ADDON_SRC}/config/${FIRST_RUN_FLAG_PREFIX}*"
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

read -d '' ra_language_utils_sh <<EOF
#!/bin/sh

ra_get_language(){
	#ref. libretro.h
	RETRO_LANGUAGE_ENGLISH=0
	RETRO_LANGUAGE_JAPANESE=1
	RETRO_LANGUAGE_FRENCH=2
	RETRO_LANGUAGE_SPANISH=3
	RETRO_LANGUAGE_GERMAN=4
	RETRO_LANGUAGE_ITALIAN=5
	RETRO_LANGUAGE_DUTCH=6
	RETRO_LANGUAGE_PORTUGUESE_BRAZIL=7
	RETRO_LANGUAGE_PORTUGUESE_PORTUGAL=8
	RETRO_LANGUAGE_RUSSIAN=9
	RETRO_LANGUAGE_KOREAN=10
	RETRO_LANGUAGE_CHINESE_TRADITIONAL=11
	RETRO_LANGUAGE_CHINESE_SIMPLIFIED=12
	RETRO_LANGUAGE_ESPERANTO=13
	RETRO_LANGUAGE_POLISH=14
	RETRO_LANGUAGE_VIETNAMESE=15
	RETRO_LANGUAGE_ARABIC=16
	RETRO_LANGUAGE_GREEK=17
	RETRO_LANGUAGE_TURKISH=18
	RETRO_LANGUAGE_SLOVAK=19
	RETRO_LANGUAGE_PERSIAN=20
	RETRO_LANGUAGE_HEBREW=21
	RETRO_LANGUAGE_ASTURIAN=22
	RETRO_LANGUAGE_FINNISH=23
	RETRO_LANGUAGE_INDONESIAN=24
	RETRO_LANGUAGE_SWEDISH=25
	RETRO_LANGUAGE_UKRAINIAN=26
	RETRO_LANGUAGE_CZECH=27
	RETRO_LANGUAGE_VALENCIAN=28

	case \$1 in
		ja*)
			echo \$RETRO_LANGUAGE_JAPANESE
			;;
		fr*)
			echo \$RETRO_LANGUAGE_FRENCH
			;;
		es*)
			echo \$RETRO_LANGUAGE_SPANISH
			;;
		de*)
			echo \$RETRO_LANGUAGE_GERMAN
			;;
		it*)
			echo \$RETRO_LANGUAGE_ITALIAN
			;;
		pt_br)
			echo \$RETRO_LANGUAGE_PORTUGUESE_BRAZIL
			;;
		pt*)
			echo \$RETRO_LANGUAGE_PORTUGUESE_PORTUGAL
			;;
		ru*)
			echo \$RETRO_LANGUAGE_RUSSIAN
			;;
		ko*)
			echo \$RETRO_LANGUAGE_KOREAN
			;;
		zh_tw)
			echo \$RETRO_LANGUAGE_CHINESE_TRADITIONAL
			;;
		zh*)
			echo \$RETRO_LANGUAGE_CHINESE_SIMPLIFIED
			;;
		eo*)
			echo \$RETRO_LANGUAGE_ESPERANTO
			;;
		pl*)
			echo \$RETRO_LANGUAGE_POLISH
			;;
		vi*)
			echo \$RETRO_LANGUAGE_VIETNAMESE
			;;
		ar*)
			echo \$RETRO_LANGUAGE_ARABIC
			;;
		el*)
			echo \$RETRO_LANGUAGE_GREEK
			;;
		tr*)
			echo \$RETRO_LANGUAGE_TURKISH
			;;
		sk*)
			echo \$RETRO_LANGUAGE_SLOVAK
			;;
		fa*)
			echo \$RETRO_LANGUAGE_PERSIAN
			;;
		he*)
			echo \$RETRO_LANGUAGE_HEBREW
			;;
		ast*)
			echo \$RETRO_LANGUAGE_ASTURIAN
			;;
		fi*)
			echo \$RETRO_LANGUAGE_FINNISH
			;;
		id*)
			echo \$RETRO_LANGUAGE_INDONESIAN
			;;
		sv*)
			echo \$RETRO_LANGUAGE_SWEDISH
			;;
		uk*)
			echo \$RETRO_LANGUAGE_UKRAINIAN
			;;
		cs*)
			echo \$RETRO_LANGUAGE_CZECH
			;;
		ca*)
			echo \$RETRO_LANGUAGE_VALENCIAN
			;;
		*)
			echo \$RETRO_LANGUAGE_ENGLISH
			;;
	esac
}

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
	elif sys.argv[1] == 'boot_toggle':
		util.bootToggle()
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
BOOT_TOGGLE_EXEC="ra_boot_toggle.sh"

addon = xbmcaddon.Addon(id=ADDON_ID)
addon_dir = addon.getAddonInfo('path')
bin_folder = os.path.join(addon_dir,BIN_FOLDER)
#usersettings_dir = addon.getAddonInfo('profile') #not needed as relevant function for kodi addon settings is already available in UI
updater_exe = os.path.join(bin_folder,UPDATER_EXEC)
retroarch_exe = os.path.join(bin_folder,RETROARCH_EXEC)
boot_toggle_exe = os.path.join(bin_folder,BOOT_TOGGLE_EXEC)

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
def bootToggle():
	current_setting = addon.getSetting( "ra_boot_toggle" )
	boot_status = "${BOOT_TO_RA_FLAG_TRUE}. "+getLocalizedString(32012)+" ${BOOT_TO_RA_FLAG_FALSE}?" if current_setting == "${BOOT_TO_RA_FLAG_TRUE}" else "${BOOT_TO_RA_FLAG_FALSE}. "+getLocalizedString(32012)+" ${BOOT_TO_RA_FLAG_TRUE}?"
	if(dialog.yesno(getLocalizedString(32010),getLocalizedString(32011)+" "+boot_status)):
		subprocess.run(boot_toggle_exe)
		#set setting again to update UI. @TODO: evaluate moving the entire logic to python
		addon.setSetting( "ra_boot_toggle", "${BOOT_TO_RA_FLAG_FALSE}" if current_setting == "${BOOT_TO_RA_FLAG_TRUE}" else "${BOOT_TO_RA_FLAG_TRUE}" )
EOF

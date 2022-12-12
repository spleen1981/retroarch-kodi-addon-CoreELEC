#!/bin/bash

apply_patches(){
	cd "${LAKKA_DIR}"
	local message="Applying"
	local argument_apply=""
	local i=0
	local patch_files_sorted=""
	local patch_files=""

	if [ "$1" = "revert" ]; then
		message="Reverting"
		argument_apply="--reverse"
	fi
	shopt -s nullglob

	#Retrieving patches array
	for patch_path in "$SCRIPT_DIR/patches/common" "$SCRIPT_DIR/patches/$DEVICE" "$SCRIPT_DIR/patches/$PROJECT" "$SCRIPT_DIR/patches/$ARCH" "$SCRIPT_DIR/patches/hooks/$HOOK" ; do
		for patch_file in $patch_path/*.patch ; do
			if [ -f "$patch_file" ]; then
				patch_files[i++]="$patch_file"
			fi
		done
	done

	#Sorting patches array
	if [ "$1" = "revert" ]; then
		for ((j=0 ; j<i; j++ )); do
			patch_files_sorted[j]=${patch_files[i-j-1]}
		done
	else
		patch_files_sorted=("${patch_files[@]}")
	fi

	#Processing patches
	for patch_file in "${patch_files_sorted[@]}" ; do
		echo -ne "$message $patch_file "
		git apply $argument_apply "$patch_file" &>>"$LOG"
		[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; [ "$1" = "revert" ] || exit_script 1 ; }
	done

	cd - &>>"$LOG"
}

exit_script(){
	[ "$LAKKA_PATCHED" = yes ] && apply_patches revert
	exit $1
}

setup_general(){
	# Colors and standard messages
	Color_Off='\033[0m'       # Text Reset
	Red='\033[0;31m'          # Red
	Green='\033[0;32m'        # Green
	Yellow='\033[0;33m'       # Yellow

	ok="${Green}(ok)${Color_Off}"
	fail="${Red}(failed)${Color_Off}"
	skip="${Yellow}(skipped)${Color_Off}"

	echo "GIT_SSL_NO_VERIFY set to 1"

	#Source local overrides
	if [ -f "${SCRIPT_DIR}/local.conf" ] ; then
		source "${SCRIPT_DIR}/local.conf"
	fi

	#Platform and general settings variables
	BASE_NAME="$PROVIDER.retroarch"
	[ -z "$PROJECT" ] && PROJECT="Amlogic-ce"
	[ -z "$ARCH" ] && ARCH=arm
	[ -z "$DEVICE" ] && [ "$PROJECT" = "Amlogic-ce" ] && DEVICE="Amlogic-ng"
	[ -z "$ADDON_VERSION" ] && read -p "Enter version tag [e.g. v1.0.0]: " ADDON_VERSION
	[ -z "$PROVIDER" ] && PROVIDER="${USER}"
	[ -z "$INCLUDE_DLC" ] && INCLUDE_DLC=""

	#Addon path and filename variables
	SCRIPT_DIR=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )/..
	[ -z "$ADDON_BUILD_DIR" ] && ADDON_BUILD_DIR="${SCRIPT_DIR}/build"
	[ -n "$DEVICE" ] && RA_NAME_SUFFIX=${DEVICE}.${ARCH} ||	RA_NAME_SUFFIX=${PROJECT}.${ARCH}
	TMP_PROJECT_DIR="${SCRIPT_DIR}/retroarch_work"
	TMP_TARGET_DIR="${TMP_PROJECT_DIR}/`date +%Y-%m-%d_%H%M%S`"
	ADDON_NAME="script.retroarch.launcher.${RA_NAME_SUFFIX}"
	ADDON_DIR="${TMP_PROJECT_DIR}/${ADDON_NAME}"
	ARCHIVE_NAME="${ADDON_NAME}-${ADDON_VERSION}.zip"
	LOG="${SCRIPT_DIR}/retroarch-kodi_`date +%Y%m%d_%H%M%S`.log"

	#Lakka variables
	[ -z "$DISTRONAME" ] && DISTRONAME="Lakka"
	[ -z "$LAKKA_VERSION" ] && LAKKA_VERSION="9e969c418db8e428ff1b71330c3d12ac6a668a6e"
	[ -z "$DISTRO_BUILD_SCRIPT" ] && DISTRO_BUILD_SCRIPT="scripts/build"
	[ -z "$LAKKA_DIR" ] && LAKKA_DIR="${SCRIPT_DIR}/Lakka-LibreELEC"
	if [ ! -d "$LAKKA_DIR" ] ; then
		echo "Folder '$LAKKA_DIR' does not exist! Aborting!" >&2
		exit_script 1
	else
		LAKKA_DIR="$(cd "${LAKKA_DIR}"; pwd)"
	fi
}


setup_packages(){
	#Misc packages variables
	[ -z "$DISTRO_PACKAGES_SUBDIR" ] && DISTRO_PACKAGES_SUBDIR="packages"
	[ -z "$PKG_TYPES" ] && PKG_TYPES="LIBRETRO_BASE LIBRETRO_CORES LAKKA_TOOLS AUDIO COMPRESS SYSTEM_TOOLS"
	[ -z "$PKG_SUBDIR_LIBRETRO_CORES" ] && PKG_SUBDIR_LIBRETRO_CORES="lakka/libretro_cores"
	[ -z "$PKG_SUBDIR_LIBRETRO_BASE" ] && PKG_SUBDIR_LIBRETRO_BASE="lakka/retroarch_base"
	[ -z "$PKG_SUBDIR_LAKKA_TOOLS" ] && PKG_SUBDIR_LAKKA_TOOLS="lakka/lakka_tools"
        [ -z "$PKG_SUBDIR_AUDIO" ] && PKG_SUBDIR_AUDIO="audio"
	[ -z "$PKG_SUBDIR_COMPRESS" ] && PKG_SUBDIR_COMPRESS="compress"
	[ -z "$PKG_SUBDIR_SYSTEM_TOOLS" ] && PKG_SUBDIR_SYSTEM_TOOLS="addons/addon-depends/system-tools-depends"

	#Building libretro core variable list from Lakka sources
	source "${LAKKA_DIR}/distributions/Lakka/options"
	[ -z "$LIBRERETRO_CORES_ADD" ] && LIBRERETRO_CORES_ADD="puae2021 mupen64plus scummvm_mainline"
	[ -z "$LIBRERETRO_CORES_RM" ] && LIBRERETRO_CORES_RM=""

	#Disable specific cores for Amlogic-ng
	if [ "$DEVICE" = "Amlogic-ng" ]; then
		LIBRERETRO_CORES_RM="$LIBRERETRO_CORES_RM puae mupen64plus-next mame scummvm"
	fi
	for CORE in $LIBRERETRO_CORES_RM $LIBRERETRO_CORES_ADD ; do
		LIBRETRO_CORES="${LIBRETRO_CORES// $CORE /}"
	done
	for CORE in $LIBRERETRO_CORES_ADD ; do
		LIBRETRO_CORES+=" $CORE "
	done
	PACKAGES_LIBRETRO_CORES="$LIBRETRO_CORES"

	#Building retroarch core list
	[ -z "$LIBRETRO_BASE" ] && LIBRETRO_BASE="retroarch core_info"
	[ ! -z "$INCLUDE_DLC" ] && LIBRETRO_BASE="$LIBRETRO_BASE retroarch_assets retroarch_joypad_autoconfig retroarch_overlays libretro_database glsl_shaders slang_shaders"
	PACKAGES_LIBRETRO_BASE="$LIBRETRO_BASE"

	#Building other pkgs list
	[ -z "$PACKAGES_LAKKA_TOOLS" ] && PACKAGES_LAKKA_TOOLS="joyutils sixpair empty xbox360_controllers_shutdown cec-mini-kb"
        [ -z "$PACKAGES_AUDIO" ] && PACKAGES_AUDIO="flac libogg"
	[ -z "$PACKAGES_COMPRESS" ] && PACKAGES_COMPRESS="zstd"
	[ -z "$PACKAGES_SYSTEM_TOOLS" ] && PACKAGES_SYSTEM_TOOLS="diffutils"

	#Aggregate entire package list
	PACKAGES_ALL=""
	for suffix in $PKG_TYPES ; do
		varname="PACKAGES_$suffix"
		PACKAGES_ALL="$PACKAGES_ALL ${!varname}"
	done
}

load_scripts(){
	#Applying auxiliary scripts
	for script_file in "$SCRIPT_DIR/scripts/hooks/$HOOK.sh" "$SCRIPT_DIR/scripts/common"/*.sh ; do
			if [ -f "$script_file" ] ; then
					source "$script_file"
			fi
	done
}

build_from_lakka(){
read -d '' message <<EOF
DISTRO=${DISTRONAME}
PROJECT=${PROJECT}
DEVICE=${DEVICE}
ARCH=${ARCH}
VERSION=${ADDON_VERSION}

Working in: ${SCRIPT_DIR}
Temporary project folder: ${TMP_TARGET_DIR}

Target zip: ${ADDON_BUILD_DIR}/${ADDON_NAME}/${ARCHIVE_NAME}
EOF

	echo "$message"
	echo

	# Checks folders
	for folder in ${ADDON_BUILD_DIR} ${ADDON_BUILD_DIR}/${ADDON_NAME} ${ADDON_BUILD_DIR}/${ADDON_NAME}/resources ; do
		[ ! -d "$folder" ] && { mkdir -p "$folder" && echo "Created folder '$folder'" || { echo "Could not create folder '$folder'!" ; exit_script 1 ; } ; } || echo "Folder '$folder' exists."
	done
	echo

	#Translating PROJECT/DEVICES in Lakka ones if needed
	if [ "$DEVICE" = "Amlogic-ng" ]; then
		PROJECT_LAKKA=Amlogic
		DEVICE_LAKKA=AMLGX
	fi
	LAKKA_BUILD_SUBDIR="build.${DISTRONAME}-${DEVICE_LAKKA:-$PROJECT_LAKKA}.${ARCH}"

	cd "$LAKKA_DIR"
	git checkout ${LAKKA_VERSION} &>>"$LOG"

	#Apply required patches to Lakka
	LAKKA_PATCHED=yes
	apply_patches

	echo "Building packages:"
	for package in $PACKAGES_ALL ; do
		echo -ne "\t$package "
		GIT_SSL_NO_VERIFY=1 IGNORE_VERSION=1 DISTRO=$DISTRONAME PROJECT=$PROJECT_LAKKA DEVICE=$DEVICE_LAKKA ARCH=$ARCH ./$DISTRO_BUILD_SCRIPT $package &>>"$LOG"
		if [ $? -eq 0 ] ; then
			echo -e "$ok"
		else
			echo -e "$fail"
			echo "Error building package '$package'!"
			exit_script 1
		fi
	done
	echo

	#Creating addon working folders
	if [ ! -d "$TMP_TARGET_DIR" ] ; then
		echo -n "Creating target folder '$TMP_TARGET_DIR'..."
		mkdir -p "$TMP_TARGET_DIR" &>>"$LOG"
		if [ $? -eq 0 ] ; then
			echo -e "$ok"
		else
			echo -e "$fail"
			echo "Could not create folder '$TMP_TARGET_DIR'!"
			exit_script 1
		fi
	fi
	echo

	#Copying files from Lakka build to addon folders
	echo "Copying packages:"
	for suffix in $PKG_TYPES ; do
		varname="PKG_SUBDIR_${suffix}"
		path="${DISTRO_PACKAGES_SUBDIR}/${!varname}"
		varname="PACKAGES_${suffix}"
		for package in ${!varname} ; do
			echo -ne "\t$package "
			SRC="${path}/${package}/package.mk"
			if [ -f "$SRC" ] ; then
				PKG_VERSION=`cat $SRC | sed -En "s/ *#.*//g;s/PKG_VERSION=\"(.*)#*\"/\1/p"`
			else
				echo -e "$skip (no package.mk)"
				continue
			fi
			PKG_FOLDER="${LAKKA_BUILD_SUBDIR}/install_pkg/${package}-${PKG_VERSION}"
			if [ -d "$PKG_FOLDER" ] ; then
				cp -Rf "${PKG_FOLDER}/"* "${TMP_TARGET_DIR}/" &>>"$LOG"
				[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
			else
				echo -e "$skip (not found)"
				continue
			fi
		done
	done
	echo

	apply_patches revert
	LAKKA_PATCHED=no
	echo
}

setup_addon(){
	#Creating addon folders
	if [ -d "$ADDON_DIR" ] ; then
		echo -n "Removing previous addon..."
		rm -rf "${ADDON_DIR}" &>>"$LOG"
		[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; echo "Error removing folder '${ADDON_DIR}'!" ; exit_script 1 ; }
		echo
	fi
	echo -n "Creating addon folder..."
	mkdir -p "${ADDON_DIR}" &>>"$LOG"
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; echo "Error creating folder '${ADDON_DIR}'!" ; exit_script 1 ; }
	echo
	cd "${ADDON_DIR}"
	echo "Creating folder structure..."
	for f in config resources ; do
		echo -ne "\t$f "
		mkdir $f &>>"$LOG"
		[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	done
	echo
}

creating_new_files(){
	#Creating new addon files
	echo "Creating files..."
	echo -ne "\tretroarch.sh "
	echo "$retroarch_sh" > bin/retroarch.sh
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	chmod +x bin/retroarch.sh
	echo -ne "\tretroarch.start "
	echo "$retroarch_start" > bin/retroarch.start
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	chmod +x bin/retroarch.start
	echo -ne "\tra_update_utils_sh "
	echo "$ra_update_utils_sh" > bin/ra_update_utils.sh
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	chmod +x bin/ra_update_utils.sh
	echo -ne "\tra_language_utils_sh "
	echo "$ra_language_utils_sh" > bin/ra_language_utils.sh
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	chmod +x bin/ra_language_utils.sh
	echo -ne "\tra_boot_toggle.sh "
	echo "$ra_boot_toggle_sh" > bin/ra_boot_toggle.sh
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	chmod +x bin/ra_boot_toggle.sh
	echo -ne "\tra_autostart.sh "
	echo "$ra_autostart_sh" > bin/ra_autostart.sh
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	chmod +x bin/ra_autostart.sh
	echo -ne "\taddon.xml "
	echo "$addon_xml" > addon.xml
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tdefault.py "
	echo "$default_py" > default.py
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tutil.py "
	echo "$util_py" > util.py
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tsettings.xml "
	echo "$settings_xml" > resources/settings.xml
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tsettings-default.xml "
	echo "$settings_default_xml"  > settings-default.xml
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tfanart.jpg "
	echo "$fanart" | base64 --decode > resources/fanart.jpg
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\ticon.png "
	echo "$icon" | base64 --decode > resources/icon.png
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo

	#Creating language files
	echo "Creating languages files and folders..."
	echo -ne "\tlanguage "
	mkdir resources/language
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	for lang_item in $LANG_list ; do
		echo -ne "\t$lang_item "
		mkdir "resources/language/resource.language.$lang_item"
		lang_file_output=$(printf "$LANG_header" ${ADDON_VERSION} $(echo "$lang_item" | sed -e 's/_\(.*\)/_\U\1/'))
		for lang_msg_no in 0 1 2 $(seq 32000 $LANG_max) ; do
			varname1="LANG_${lang_msg_no}_en_gb"
			[ -z "${!varname1}" ] && continue
			if [ $lang_msg_no -lt 32000 ] ; then
				varname0="LANG_${lang_msg_no}_ctx"
				lang_file_output="${lang_file_output}\nmsgctxt \"${!varname0}\""
			else
				lang_file_output="${lang_file_output}\nmsgctxt \"#${lang_msg_no}\""
			fi
			lang_file_output="${lang_file_output}\nmsgid \"${!varname1}\""
			if [ "$lang_item" = en_gb ] ; then
				lang_file_output="${lang_file_output}\nmsgstr \"\""
			else
				varname2="LANG_${lang_msg_no}_${lang_item}"
				lang_file_output="${lang_file_output}\nmsgstr \"${!varname2}\""
			fi
			lang_file_output="${lang_file_output}\n"
		done
		echo -e "$lang_file_output" > resources/language/resource.language.${lang_item}/strings.po
		[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	done
	echo
}

populating_addon(){
	#Moving files from working to addon folders
	echo "Moving files to addon..."
	echo -ne "\tretroarch.cfg "
	mv -v "${TMP_TARGET_DIR}/etc/retroarch.cfg" "${ADDON_DIR}/config/" &>>"$LOG"
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tbinaries "
	mv -v "${TMP_TARGET_DIR}/usr/bin" "${ADDON_DIR}/" &>>"$LOG"
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tlibraries and cores "
	mv -v "${TMP_TARGET_DIR}/usr/lib" "${ADDON_DIR}/" &>>"$LOG"
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\taudio filters "
	mv -v "${TMP_TARGET_DIR}/usr/share/audio_filters" "${ADDON_DIR}/resources/" &>>"$LOG"
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tvideo filters "
	mv -v "${TMP_TARGET_DIR}/usr/share/video_filters" "${ADDON_DIR}/resources/" &>>"$LOG"
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tsystem "
	mv -v "${TMP_TARGET_DIR}/usr/share/retroarch-system" "${ADDON_DIR}/resources/system" &>>"$LOG"
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }

	if [ ! -z "$INCLUDE_DLC" ]; then
		echo -ne "\tjoypads "
		mv -v "${TMP_TARGET_DIR}/etc/retroarch-joypad-autoconfig" "${ADDON_DIR}/resources/joypads" &>>"$LOG"
		[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
		echo -ne "\tshaders "
		mv -v "${TMP_TARGET_DIR}/usr/share/common-shaders" "${ADDON_DIR}/resources/shaders" &>>"$LOG"
		[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
		echo -ne "\tdatabases "
		mv -v "${TMP_TARGET_DIR}/usr/share/libretro-database" "${ADDON_DIR}/resources/database" &>>"$LOG"
		[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
		echo -ne "\tassets "
		mv -v "${TMP_TARGET_DIR}/usr/share/retroarch-assets" "${ADDON_DIR}/resources/assets" &>>"$LOG"
		[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
		echo -ne "\toverlays "
		mv -v "${TMP_TARGET_DIR}/usr/share/retroarch-overlays" "${ADDON_DIR}/resources/overlays" &>>"$LOG"
		[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	fi
	echo
}

customize_retroarch(){
	#Customizing retroarch.cfg
	echo "Making modifications to retroarch.cfg..."
	CFG="config/retroarch.cfg"
	RA_CFG_DIR="/storage/\.config/retroarch"
	RA_CORES_DIR="/storage/\.kodi/addons/${ADDON_NAME}/lib/libretro"
	RA_RES_DIR="/storage/\.kodi/addons/${ADDON_NAME}/resources"
	echo -ne "\tsavefiles "
	sed -i "s|/.*/savefiles|${RA_CFG_DIR}/savefiles|g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tsavestates "
	sed -i "s|/.*/savestates|${RA_CFG_DIR}/savestates|g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tremappings "
	sed -i "s|/.*/remappings|${RA_CFG_DIR}/remappings|g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tplaylists "
	sed -i "s|/.*/playlists|${RA_CFG_DIR}/playlists|g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tcores "
	sed -i "s|/.*/cores|${RA_CORES_DIR}|g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tsystem "
	sed -i "s|/.*/system|${RA_RES_DIR}/system|g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tassets "
	sed -i -E "s#([= \"])/.*?/assets#\1${RA_RES_DIR}/assets#g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tthumbnails "
	sed -i "s|/.*/thumbnails|${RA_CFG_DIR}/thumbnails|g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tshaders "
	sed -i "s|/.*/shaders|${RA_RES_DIR}/shaders|g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tvideo_filters "
	sed -i "s|/.*/video_filters|${RA_RES_DIR}/video_filters|g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\taudio_filters "
	sed -i "s|/.*/audio_filters|${RA_RES_DIR}/audio_filters|g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tretroarch-assets "
	sed -i "s|/.*/retroarch-assets|${RA_RES_DIR}/assets|g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tjoypads "
	sed -i "s|/.*/joypads|${RA_RES_DIR}/joypads|g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tdatabase "
	sed -i "s|/.*/database|${RA_RES_DIR}/database|g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\toverlays "
	sed -i "s|/.*/overlays|${RA_RES_DIR}/overlays|g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tmisc settings "
	sed -i "s|^.*all_users_control_menu =.*|all_users_control_menu = \"true\"|g" $CFG
	sed -i "s|^.*content_show_images =.*|content_show_images = \"false\"|g" $CFG
	sed -i "s|^.*content_show_music =.*|content_show_music = \"false\"|g" $CFG
	sed -i "s|^.*content_show_video =.*|content_show_video = \"false\"|g" $CFG
	sed -i "s|^.*input_menu_toggle_gamepad_combo =.*|input_menu_toggle_gamepad_combo = \"4\"|g" $CFG
	sed -i "s|^.*menu_driver =.*|menu_driver = \"xmb\"|g" $CFG
	sed -i "s|^.*menu_swap_ok_cancel_buttons =.*|menu_swap_ok_cancel_buttons = \"true\"|g" $CFG
	sed -i "s|^.*video_threaded =.*|video_threaded = \"false\"|g" $CFG
	sed -i "s|^.*menu_core_enable =.*|menu_core_enable = \"true\"|g" $CFG
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo
}

apply_hook_function(){
	#Applying hook function if any
	[ "$(type -t hook_function)" = function ] && hook_function
}

create_archive(){
	#Archive creation
	echo -n "Creating archive..."
	cd ..
	zip -y -r "${ARCHIVE_NAME}" "${ADDON_NAME}" &>>"$LOG"
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo
	echo "Creating repository files..."
	echo -ne "\tzip "
	mv -vf "${ARCHIVE_NAME}" "${ADDON_BUILD_DIR}/${ADDON_NAME}/" &>>"$LOG"
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tsymlink "
	ln -vsf "${ARCHIVE_NAME}" "${ADDON_BUILD_DIR}/${ADDON_NAME}/${ADDON_NAME}-LATEST.zip" &>>"$LOG"
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo
}

cleanup(){
	#Cleanup
	echo "Cleaning up..."
	cd "${SCRIPT_DIR}"
	echo -ne "\tproject folder "
	rm -vrf "${TMP_PROJECT_DIR}" &>>"$LOG"
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo -ne "\tlog file "
	rm -rf "$LOG"
	[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }
	echo
}

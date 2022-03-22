#!/bin/bash

apply_patches(){
	cd "${LAKKA_DIR}"
	local message="Applying"
	local argument=""
	if [ "$1" = "revert" ]; then
		message="Reverting"
		argument="--reverse"
	fi
	shopt -s nullglob
	for patch_path in "$SCRIPT_DIR/patches/common" "$SCRIPT_DIR/patches/$DEVICE" "$SCRIPT_DIR/patches/$PROJECT" "$SCRIPT_DIR/patches/$ARCH" "$SCRIPT_DIR/patches/hooks/$HOOK" ; do
		for patch_file in "$patch_path"/*.patch ; do
			if [ -f "$patch_file" ]; then
				echo "$message $patch_file"
				git apply $argument "$patch_file" &>>"$LOG"
			fi
		done
	done
	cd - &>>"$LOG"
}

exit_script(){
	apply_patches revert
	exit $1
}
trap exit_script SIGINT SIGTERM

#Source local overrides
if [ -f "${SCRIPT_DIR}/local.conf" ] ; then
	source "${SCRIPT_DIR}/local.conf"
fi

#Platform and general settings variables
BASE_NAME="$PROVIDER.retroarch"
[ -z "$PROJECT" ] && PROJECT=Amlogic-ng
[ -z "$ARCH" ] && ARCH=arm
[ -z "$DEVICE" ] && DEVICE=""
[ -z "$ADDON_VERSION" ] && ADDON_VERSION=$(date +%y.%m.%d)
[ -z "$PROVIDER" ] && PROVIDER="${USER}"
[ -z "$INCLUDE_DLC" ] && INCLUDE_DLC=""
[ -z "$LAKKA_VERSION" ] && LAKKA_VERSION="a0f1b57bb36fa1feb50ff006ca7b46c1b7b7cb45"
[ -z "$DISTRONAME" ] && DISTRONAME="Lakka"

#Path and filename variables
[ -z "$SCRIPT_DIR" ] && SCRIPT_DIR=$(pwd)
[ -z "$DISTRO_PACKAGES_SUBDIR" ] && DISTRO_PACKAGES_SUBDIR="packages"
[ -z "$ADDON_BUILD_DIR" ] && ADDON_BUILD_DIR="${SCRIPT_DIR}/build"
[ -z "$DISTRO_BUILD_SCRIPT" ] && DISTRO_BUILD_SCRIPT="scripts/build"
[ -z "$LAKKA_DIR" ] && LAKKA_DIR="${SCRIPT_DIR}/Lakka-LibreELEC"
if [ ! -d "$LAKKA_DIR" ] ; then
	echo "Folder '$LAKKA_DIR' does not exist! Aborting!" >&2
	exit_script 1
else
	LAKKA_DIR="$(cd "${LAKKA_DIR}"; pwd)"
fi
[ -n "$DEVICE" ] && RA_NAME_SUFFIX=${DEVICE}.${ARCH} ||	RA_NAME_SUFFIX=${PROJECT}.${ARCH}
TMP_PROJECT_DIR="${SCRIPT_DIR}/retroarch_work"
TMP_TARGET_DIR="${TMP_PROJECT_DIR}/`date +%Y-%m-%d_%H%M%S`"
ADDON_NAME="script.retroarch.launcher.${RA_NAME_SUFFIX}"
ADDON_DIR="${TMP_PROJECT_DIR}/${ADDON_NAME}"
ARCHIVE_NAME="${ADDON_NAME}-${ADDON_VERSION}.zip"
LOG="${SCRIPT_DIR}/retroarch-kodi_`date +%Y%m%d_%H%M%S`.log"

#Misc packages variables
[ -z "$PKG_TYPES" ] && PKG_TYPES="LIBRETRO TOOLS NETWORK SYSUTILS"
[ -z "$PKG_SUBDIR_TOOLS" ] && PKG_SUBDIR_TOOLS="tools"
[ -z "$PKG_SUBDIR_NETWORK" ] && PKG_SUBDIR_NETWORK="network"
[ -z "$PKG_SUBDIR_SYSUTILS" ] && PKG_SUBDIR_SYSUTILS="sysutils"
[ -z "$PACKAGES_TOOLS" ] && PACKAGES_TOOLS="joyutils xbox360-controllers-shutdown cec-mini-kb"
[ -z "$PACKAGES_NETWORK" ] && PACKAGES_NETWORK="sixpair"
[ -z "$PACKAGES_SYSUTILS" ] && PACKAGES_SYSUTILS="empty"

#Applying auxiliary scripts
for script_file in "$SCRIPT_DIR/scripts/hooks/$HOOK.sh" "$SCRIPT_DIR/scripts/common"/*.sh ; do
        if [ -f "$script_file" ] ; then
                source "$script_file"
        fi
done

#Building libretro core variable list from Lakka sources
source "${LAKKA_DIR}/distributions/Lakka/options"
[ -z "$LIBRERETRO_CORES_ADD" ] && LIBRERETRO_CORES_ADD=""
[ -z "$LIBRERETRO_CORES_RM" ] && LIBRERETRO_CORES_RM=""
for CORE in $LIBRERETRO_CORES_RM $LIBRERETRO_CORES_ADD ; do
	LIBRETRO_CORES="${LIBRETRO_CORES// $CORE /}"
done
for CORE in $LIBRERETRO_CORES_ADD ; do
	LIBRETRO_CORES+=" $CORE "
done

#Others libretro packages variables
[ -z "$LIBRETRO_BASE" ] && LIBRETRO_BASE="retroarch core-info"
[ ! -z "$INCLUDE_DLC" ] && LIBRETRO_BASE="$LIBRETRO_BASE retroarch-assets retroarch-joypad-autoconfig retroarch-overlays libretro-database glsl-shaders"

#Aggregate entire package list
[ -z "$PKG_SUBDIR_LIBRETRO" ] && PKG_SUBDIR_LIBRETRO="libretro"
PACKAGES_LIBRETRO="$LIBRETRO_BASE $LIBRETRO_CORES"
PACKAGES_ALL=""
for suffix in $PKG_TYPES ; do
	varname="PACKAGES_$suffix"
	PACKAGES_ALL="$PACKAGES_ALL ${!varname}"
done

read -d '' message <<EOF
Building RetroArch KODI add-on for CoreELEC:

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
if [ "$PROJECT" = "Amlogic-ng" ]; then
	PROJECT_LAKKA=Amlogic
	DEVICE_LAKKA=AMLG12
fi
LAKKA_BUILD_SUBDIR="build.${DISTRONAME}-${DEVICE_LAKKA:-$PROJECT_LAKKA}.${ARCH}"

cd "$LAKKA_DIR"
git checkout ${LAKKA_VERSION} &>>"$LOG"

#Apply required patches to Lakka
apply_patches

echo "Building packages:"
for package in $PACKAGES_ALL ; do
	echo -ne "\t$package "
	IGNORE_VERSION=1 DISTRO=$DISTRONAME PROJECT=$PROJECT_LAKKA DEVICE=$DEVICE_LAKKA ARCH=$ARCH ./$DISTRO_BUILD_SCRIPT $package &>>"$LOG"
	if [ $? -eq 0 ] ; then
		echo "(ok)"
	else
		echo "(failed) $?"
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
		echo "done."
	else
		echo "failed!"
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
			PKG_VERSION=`cat $SRC | sed -En "s/PKG_VERSION=\"(.*)\"/\1/p"`
		else
			echo "(skipped - no package.mk)"
			continue
		fi
		PKG_FOLDER="${LAKKA_BUILD_SUBDIR}/${package}-${PKG_VERSION}/.install_pkg"
		if [ -d "$PKG_FOLDER" ] ; then
			cp -Rf "${PKG_FOLDER}/"* "${TMP_TARGET_DIR}/" &>>"$LOG"
			[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
		else
			echo "(skipped - not found)"
			continue
		fi
	done
done
echo

#Creating addon folders
if [ -d "$ADDON_DIR" ] ; then
	echo -n "Removing previous addon..."
	rm -rf "${ADDON_DIR}" &>>"$LOG"
	[ $? -eq 0 ] && echo "done." || { echo "failed!" ; echo "Error removing folder '${ADDON_DIR}'!" ; exit_script 1 ; }
	echo
fi
echo -n "Creating addon folder..."
mkdir -p "${ADDON_DIR}" &>>"$LOG"
[ $? -eq 0 ] && echo "done." || { echo "failed!" ; echo "Error creating folder '${ADDON_DIR}'!" ; exit_script 1 ; }
echo
cd "${ADDON_DIR}"
echo "Creating folder structure..."
for f in config resources ; do
	echo -ne "\t$f "
	mkdir $f &>>"$LOG"
	[ $? -eq 0 ] && echo -e "(ok)" || { echo -e "(failed)" ; exit_script 1 ; }
done
echo

#Moving files from working to addon folders
echo "Moving files to addon..."
echo -ne "\tretroarch.cfg "
mv -v "${TMP_TARGET_DIR}/etc/retroarch.cfg" "${ADDON_DIR}/config/" &>>"$LOG"
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tbinaries "
mv -v "${TMP_TARGET_DIR}/usr/bin" "${ADDON_DIR}/" &>>"$LOG"
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tlibraries and cores "
mv -v "${TMP_TARGET_DIR}/usr/lib" "${ADDON_DIR}/" &>>"$LOG"
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\taudio filters "
mv -v "${TMP_TARGET_DIR}/usr/share/audio_filters" "${ADDON_DIR}/resources/" &>>"$LOG"
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tvideo filters "
mv -v "${TMP_TARGET_DIR}/usr/share/video_filters" "${ADDON_DIR}/resources/" &>>"$LOG"
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tsystem "
mv -v "${TMP_TARGET_DIR}/usr/share/retroarch-system" "${ADDON_DIR}/resources/system" &>>"$LOG"
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }

if [ ! -z "$INCLUDE_DLC" ]; then
	echo -ne "\tjoypads "
	mv -v "${TMP_TARGET_DIR}/etc/retroarch-joypad-autoconfig" "${ADDON_DIR}/resources/joypads" &>>"$LOG"
	[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
	echo -ne "\tshaders "
	mv -v "${TMP_TARGET_DIR}/usr/share/common-shaders" "${ADDON_DIR}/resources/shaders" &>>"$LOG"
	[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
	echo -ne "\tdatabases "
	mv -v "${TMP_TARGET_DIR}/usr/share/libretro-database" "${ADDON_DIR}/resources/database" &>>"$LOG"
	[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
	echo -ne "\tassets "
	mv -v "${TMP_TARGET_DIR}/usr/share/retroarch-assets" "${ADDON_DIR}/resources/assets" &>>"$LOG"
	[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
	echo -ne "\toverlays "
	mv -v "${TMP_TARGET_DIR}/usr/share/retroarch-overlays" "${ADDON_DIR}/resources/overlays" &>>"$LOG"
	[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
fi
echo

#Creating new addon files
echo "Creating files..."
echo -ne "\tretroarch.sh "
echo "$retroarch_sh" > bin/retroarch.sh
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
chmod +x bin/retroarch.sh
echo -ne "\tretroarch.start "
echo "$retroarch_start" > bin/retroarch.start
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
chmod +x bin/retroarch.start
echo "$ra_update_utils_sh" > bin/ra_update_utils.sh
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
chmod +x bin/ra_update_utils.sh
echo -ne "\taddon.xml "
echo "$addon_xml" > addon.xml
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tdefault.py "
echo "$default_py" > default.py
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tutil.py "
echo "$util_py" > util.py
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tsettings.xml "
echo "$settings_xml" > resources/settings.xml
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tsettings-default.xml "
echo "$settings_default_xml"  > settings-default.xml
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tfanart.jpg "
echo "$fanart" | base64 --decode > resources/fanart.jpg
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\ticon.png "
echo "$icon" | base64 --decode > resources/icon.png
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo

#Creating language files
echo "Creating languages files and folders..."
echo -ne "\tlanguage "
mkdir resources/language
[ $? -eq 0 ] && echo -e "(ok)" || { echo -e "(failed)" ; exit_script 1 ; }
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
	[ $? -eq 0 ] && echo -e "(ok)" || { echo -e "(failed)" ; exit_script 1 ; }
done
echo

#Customizing retroarch.cfg
echo "Making modifications to retroarch.cfg..."
CFG="config/retroarch.cfg"
RA_CFG_DIR="\/storage\/\.config\/retroarch"
RA_CORES_DIR="\/storage\/\.kodi\/addons\/${ADDON_NAME}\/lib\/libretro"
RA_RES_DIR="\/storage\/\.kodi\/addons\/${ADDON_NAME}\/resources"
echo -ne "\tsavefiles "
sed -i "s/\/storage\/savefiles/${RA_CFG_DIR}\/savefiles/g" $CFG
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tsavestates "
sed -i "s/\/storage\/savestates/${RA_CFG_DIR}\/savestates/g" $CFG
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tremappings "
sed -i "s/\/storage\/remappings/${RA_CFG_DIR}\/remappings/g" $CFG
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tplaylists "
sed -i "s/\/storage\/playlists/${RA_CFG_DIR}\/playlists/g" $CFG
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tcores "
sed -i "s/\/tmp\/cores/${RA_CORES_DIR}/g" $CFG
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tsystem "
sed -i "s/\/storage\/system/${RA_RES_DIR}\/system/g" $CFG
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tassets "
sed -i "s/\/tmp\/assets/${RA_RES_DIR}\/assets/g" $CFG
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tthumbnails "
sed -i "s/\/storage\/thumbnails/${RA_CFG_DIR}\/thumbnails/g" $CFG
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tshaders "
sed -i "s/\/tmp\/shaders/${RA_RES_DIR}\/shaders/g" $CFG
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tvideo_filters "
sed -i "s/\/usr\/share\/video_filters/${RA_RES_DIR}\/video_filters/g" $CFG
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\taudio_filters "
sed -i "s/\/usr\/share\/audio_filters/${RA_RES_DIR}\/audio_filters/g" $CFG
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tretroarch-assets "
sed -i "s/\/usr\/share\/retroarch-assets/${RA_RES_DIR}\/assets/g" $CFG
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tjoypads "
sed -i "s/\/tmp\/joypads/${RA_RES_DIR}\/joypads/g" $CFG
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tdatabase "
sed -i "s/\/tmp\/database/${RA_RES_DIR}\/database/g" $CFG
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tmisc settings "
sed -i "s/all_users_control_menu = \"false\"/all_users_control_menu = \"true\"/g" $CFG
sed -i "s/content_show_images = \"true\"/content_show_images = \"false\"/g" $CFG
sed -i "s/content_show_music = \"true\"/content_show_music = \"false\"/g" $CFG
sed -i "s/content_show_video = \"true\"/content_show_video = \"false\"/g" $CFG
sed -i "s/input_menu_toggle_gamepad_combo = \"0\"/input_menu_toggle_gamepad_combo = \"4\"/g" $CFG
sed -i "s/menu_driver = \"ozone\"/menu_driver = \"xmb\"/g" $CFG
sed -i "s/menu_show_configurations = \"true\"/menu_show_configurations = \"false\"/g" $CFG
sed -i "s/menu_show_restart_retroarch = \"true\"/menu_show_restart_retroarch = \"false\"/g" $CFG
sed -i "s/menu_swap_ok_cancel_buttons = \"false\"/menu_swap_ok_cancel_buttons = \"true\"/g" $CFG
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo

#Applying hook function if any
[ "$(type -t hook_function)" = function ] && hook_function

apply_patches revert
echo

#Archive creation
echo -n "Creating archive..."
cd ..
zip -y -r "${ARCHIVE_NAME}" "${ADDON_NAME}" &>>"$LOG"
[ $? -eq 0 ] && echo "done." || { echo "failed!" ; exit_script 1 ; }
echo
echo "Creating repository files..."
echo -ne "\tzip "
mv -vf "${ARCHIVE_NAME}" "${ADDON_BUILD_DIR}/${ADDON_NAME}/" &>>"$LOG"
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tsymlink "
ln -vsf "${ARCHIVE_NAME}" "${ADDON_BUILD_DIR}/${ADDON_NAME}/${ADDON_NAME}-LATEST.zip" &>>"$LOG"
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo

#Cleanup
echo "Cleaning up..."
cd "${SCRIPT_DIR}"
echo -ne "\tproject folder "
rm -vrf "${TMP_PROJECT_DIR}" &>>"$LOG"
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo -ne "\tlog file "
rm -rf "$LOG"
[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
echo
echo "Finished."
echo

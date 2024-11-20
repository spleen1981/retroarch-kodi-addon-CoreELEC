#!/bin/bash

trap exit_script SIGINT SIGTERM
GIT_SSL_NO_VERIFY=1

SCRIPT_DIR=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )/..
source "$SCRIPT_DIR/build_functions.sh"
[ -f $SCRIPT_DIR/test/local.conf ] && source $SCRIPT_DIR/test/local.conf
rm $SCRIPT_DIR/*.log

ADDON_VERSION=x
setup_general

CUR_DIR="$(pwd)"
RA_DIR="$SCRIPT_DIR/../RetroArch/"
RA_PATCHES_SUBDIR="$LAKKA_DIR/packages/lakka/retroarch_base/retroarch/patches"

echo
echo -ne "Exporting Retroarch debug patch to Lakka"
[ -d "${RA_PATCHES_SUBDIR}" ] && rm "${RA_PATCHES_SUBDIR}"/retroarch_debug.patch 1>/dev/null 2>&1 || mkdir "${RA_PATCHES_SUBDIR}" 1>/dev/null 2>&1
cd "$RA_DIR"
git diff > "${RA_PATCHES_SUBDIR}"/retroarch_debug.patch
[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; exit_script 1 ; }

cd "$SCRIPT_DIR"

echo
echo "Building RetroArch"
echo

DISTRO_PACKAGES_SUBDIR="packages/lakka"
PKG_TYPES="LIBRETRO_BASE"
PKG_SUBDIR_LIBRETRO_BASE="retroarch_base"
PACKAGES_LIBRETRO_BASE="retroarch"
PACKAGES_ALL=$PACKAGES_LIBRETRO_BASE

load_scripts
build_from_lakka
setup_addon

rm "${RA_PATCHES_SUBDIR}"/retroarch_debug.patch

echo -ne "Sending Retroarch to test device..."
sshpass -p "$REMOTE_PASSWORD" scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -q "${TMP_TARGET_DIR}/usr/bin/retroarch" ${REMOTE_ROOT_USER}@${REMOTE_IP}:/storage/.kodi/addons/script.retroarch.launcher.Amlogic-ng.arm/bin/
[ $? -eq 0 ] || scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -q "${TMP_TARGET_DIR}/usr/bin/retroarch" ${REMOTE_ROOT_USER}@${REMOTE_IP}:/storage/.kodi/addons/script.retroarch.launcher.Amlogic-ng.arm/bin
[ $? -eq 0 ] && echo -e "$ok" || { echo -e "$fail" ; echo "copying retroarch in $CUR_DIR for manual upload" ; cp "${TMP_TARGET_DIR}/usr/bin/retroarch" "$CUR_DIR/". ; exit_script 1 ; }
echo

cleanup

echo
echo "Finished."
echo

cd "$CUR_DIR"

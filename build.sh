#!/bin/bash

build(){
	setup_general
	setup_packages
	load_scripts
	build_from_lakka
	setup_addon
	populating_addon
	add_fallback_precompiled_cores
	creating_new_files
	customize_retroarch
	apply_hook_function
	create_archive
	cleanup
}

trap exit_script SIGINT SIGTERM
GIT_SSL_NO_VERIFY=1

echo
echo "Building RetroArch KODI add-on for CoreELEC:"
echo

source scripts/build_functions.sh

if [ -z $DEVICE ] ; then
	DEVICE=Amlogic-ng && build
	DEVICE=Amlogic-no && build
else
	build
fi

echo
echo "Finished."
echo

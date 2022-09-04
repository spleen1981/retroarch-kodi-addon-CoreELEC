#!/bin/bash

trap exit_script SIGINT SIGTERM
GIT_SSL_NO_VERIFY=1

echo
echo "Building RetroArch KODI add-on for CoreELEC:"
echo

source scripts/build_functions.sh

setup_general
setup_packages
load_scripts
build_from_lakka
setup_addon
populating_addon
customize_retroarch
apply_hook_function
create_archive
cleanup

echo
echo "Finished."
echo

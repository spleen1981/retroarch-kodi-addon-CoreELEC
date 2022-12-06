#!/bin/bash

trap exit_script SIGINT SIGTERM
GIT_SSL_NO_VERIFY=1

echo
echo "Testing creation of new files"
echo

source scripts/build_functions.sh

ADDON_VERSION=test setup_general
load_scripts

HERE=$(pwd)
TMP_DIR=tmp_test_files
[ -d $HERE/$TMP_DIR ] && rm -rf $HERE/$TMP_DIR/*
mkdir -p $HERE/$TMP_DIR/resources/language
mkdir -p $HERE/$TMP_DIR/bin
cd $TMP_DIR

creating_new_files

cd - > /dev/null
echo
echo "Finished."
echo

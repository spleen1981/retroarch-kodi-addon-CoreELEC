#!/bin/bash

parent_path=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )

echo $parent_path

source $parent_path/../build_functions.sh
ADDON_VERSION=x setup_general
apply_patches $1

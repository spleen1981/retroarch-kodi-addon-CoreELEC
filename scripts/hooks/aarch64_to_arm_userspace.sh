#!/bin/bash

ln_crawler(){
	for path in $TARG_DIR ; do
		if [ -L $path$1 ] ; then
			[ -L $DEST_DIR$1 ] && break
			ln -sf $( basename $( readlink $path$1 ) ) $DEST_DIR$1
			ln_crawler $( basename $( readlink $path$1 ) )
			break
		elif [ -f $path$1 ] ; then
			[ -f $DEST_DIR$1 ] && break
			cp $path$1 $DEST_DIR
			#chmod +x $DEST_DIR$1
			ld_crawler $1
			break
		fi
	done
}

ld_crawler(){
	for path in $TARG_DIR ; do
		if [ -f $path$1 ] ; then
			local LD_LIST
			LD_LIST=`readelf -d $path$1 |grep NEEDED`
			LD_LIST=${LD_LIST//"0x0000000000000001 (NEEDED)             Shared library: ["}
			LD_LIST=${LD_LIST//"]"}
			for ld_file in $LD_LIST ; do
				ln_crawler $ld_file
			done
		fi
	done
}

add_extra_pkg_src(){
	local suffix_found
	local src_pkg

	for suffix in $PKG_TYPES ; do
		for package in ${PACKAGES_$suffix} ; do

			if [ package == $1 ] ; then
				suffix_found=${suffix}
				break
			fi

		done

		src_pkg="${LAKKA_DIR}/${DISTRO_PACKAGES_SUBDIR}/${PKG_SUBDIR_$suffix_found}/$1/package.mk"


		if [ -f "$src_pkg" ] ; then
			pkg_ver=`cat $src_pkg | sed -En "s/PKG_VERSION=\"(.*)\"/\1/p"`
			SRC_EXTRA="$SRC_EXTRA ${LAKKA_DIR}/${LAKKA_BUILD_SUBDIR}/$1-${pkg_ver}/.install_pkg/usr/lib/"
			return 0
		fi
	done
	echo "Failed - no $1 package.mk"
	exit_script 1
}

hook_function(){
if [[ "$PROJECT" == "Amlogic-ng" && "$ARCH" == aarch64 ]] ; then
	#Patching ELF to set aarch64 local interpreter
	echo "Applying arm64_to_arm32_userspace hack"

	echo -e "\tPatching bin ELF "
	for bin_file in "${ADDON_DIR}"/bin/* ; do
		[[ "$bin_file" == *".sh" || "$bin_file" == *".start" ]] && continue
		echo -ne "\t\t$( basename $bin_file )"
		patchelf --set-interpreter ../lib/lib64/ld-linux-aarch64.so.1 "$bin_file" &>>"$LOG"
		[ $? -eq 0 ] && echo "(ok)" || { echo "(failed)" ; exit_script 1 ; }
	done

	#Creating lib64 directory
#	add_extra_pkg_src opengl-meson-coreelec
#	add_extra_pkg_src libcec

	LD64_SRC1="${LAKKA_DIR}/${LAKKA_BUILD_SUBDIR}/toolchain/aarch64-libreelec-linux-gnueabi/sysroot/usr/lib/"
	LD64_SRC2="${LAKKA_DIR}/${LAKKA_BUILD_SUBDIR}/toolchain/aarch64-libreelec-linux-gnueabi/lib64/"
	TARG_DIR="${ADDON_DIR}/lib/ ${ADDON_DIR}/bin/ ${SRC_EXTRA} ${LD64_SRC1} ${LD64_SRC2} ${ADDON_DIR}/usr/lib/libretro/"
	echo -e "\tCreating lib64 directory"
	DEST_DIR="${ADDON_DIR}/lib/lib64/"
	mkdir -p "$DEST_DIR"
	for bin_file in "${ADDON_DIR}"/bin/* ; do
		[[ "$bin_file" == *".sh" || "$bin_file" == *".start" ]] && continue
		echo -ne "\t\tCrawling $( basename $bin_file )"
		ld_crawler "$( basename $bin_file )"
		[ $? -eq 0 ] && echo "(ok)" || { echo "(failed - can't patchelf)" ; exit_script 1 ; }
	done
	echo
fi
}

PKG_TYPES="$PKG_TYPES DEVEL"
PKG_SUBDIR_DEVEL="devel"
PACKAGES_DEVEL="libcec"

PACKAGES_SYSUTILS="$PACKAGES_SYSUTILS opengl-meson-coreelec"

HOOK_RETROARCH_START_0="LD_LIBRARY_PATH=\"\$LD_LIBRARY_PATH:\$ADDON_DIR/lib/lib64\""
HOOK_RETROARCH_START_1="LD_LIBRARY_PATH=\"\${LD_LIBRARY_PATH//\\:\${ADDON_DIR//\\//\\\\\\/}\\/lib\\/lib64}\""

read -d '' HOOK_RETROARCH_START_2 <<EOF
cd \$ADDON_DIR/lib/lib64
for file_src in * ; do
	size_scr=\$(wc -c \$file_src)
	if [ \${size_scr//" \$file_src"} -lt 100 -a ! -L \$file_src ]; then
		[ -f \$(cat \$file_src) ] && ln -sf \$(cat \$file_src) \$file_src
	fi
	chmod +x \$file_src
done
cd - > /dev/null
EOF

#!/bin/bash

ADDON_XML_LANG_CONTENT=""

for lang_item in $LANG_list ; do
	varname0="LANG_0_${lang_item}"
	varname1="LANG_1_${lang_item}"
	varname2="LANG_2_${lang_item}"
	ADDON_XML_LANG_CONTENT="$ADDON_XML_LANG_CONTENT
		\<summary lang=\"$(echo $lang_item | sed -e 's/_\(.*\)/_\U\1/')\"\>${!varname0}\</summary\>
		\<description lang=\"$(echo $lang_item | sed -e 's/_\(.*\)/_\U\1/')\"\>${!varname1}\</description\>
		\<disclaimer lang=\"$(echo $lang_item | sed -e 's/_\(.*\)/_\U\1/')\"\>${!varname2}\</disclaimer\>
"
done

CHANGELOG="$(cat ${SCRIPT_DIR}/CHANGELOG.md | sed "s#&#\&amp;#g" | sed "s#\"#\&quot;#g" | sed "s#'#\&apos;#g" | sed "s#<#\&lt;#g" | sed "s#>#\&gt;#g")"

read -d '' addon_xml <<EOF
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<addon id="${ADDON_NAME}" name="RetroArch" version="${ADDON_VERSION}" provider-name="${PROVIDER}">
	<requires>
		<import addon="xbmc.python" version="3.0.0"/>
	</requires>
	<extension point="xbmc.python.pluginsource" library="default.py">
		<provides>executable game</provides>
	</extension>
	<extension point="xbmc.addon.metadata">
		<platform>linux</platform>
		<reuselanguageinvoker>true</reuselanguageinvoker>
		$ADDON_XML_LANG_CONTENT
		<forum>https://discourse.coreelec.org/t/retroarch-kodi-add-on-for-coreelec/17482</forum>
    		<source>https://github.com/spleen1981/retroarch-kodi-addon-CoreELEC</source>
		<assets>
			<icon>resources/icon.png</icon>
			<fanart>resources/fanart.jpg</fanart>
		</assets>
<news>
$CHANGELOG
</news>

	</extension>
</addon>
EOF

read -d '' settings_xml <<EOF
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<settings>
	<category label="128"> <!-- General -->
		<setting label="128" type="lsep"/>
		<setting id="ra_boot_toggle" type="action" label="32010" default="KODI" action="RunScript(script.retroarch.launcher.Amlogic-ng.arm,boot_toggle)"/>
		<setting id="ra_stop_kodi" label="32001" type="bool" default="true" />
		<setting id="ra_autoupdate" label="24063" type="bool" default="true" />
		<setting id="ra_updatenow" type="action" label="24034" action="RunScript(${ADDON_NAME},check_updates)"/>
		<setting id="ra_reset" type="action" label="13007" action="RunScript(${ADDON_NAME},reset)"/>
	</category>
	<category label="35234"> <!-- Controls -->
		<setting label="35234" type="lsep"/>
		<setting id="ra_xbox360_shutdown" label="32002" type="bool" default="true" />
		<setting id="ra_bt_shutdown" label="32009" type="bool" default="false" />
		<setting id="ra_cec_remote" label="32003" type="bool" default="true" />
		<setting id="ra_cec_poweroff" label="36029" type="enum" lvalues="13005|36028" default="13005" enable="eq(-1,true)" subsetting="true" />

	</category>
	<category label="157"><!-- Video -->
		<setting label="157" type="lsep"/>
		<setting id="ra_force_refresh_rate" label="32004" type="bool" default="true" />
		<setting id="ra_forced_refresh_rate" label="32005" type="enum" values="50Hz (PAL)|60Hz (NTSC)" default="1" enable="eq(-1,true)" subsetting="true" />
	</category>
	<category label="292"> <!-- Audio -->
		<setting label="292" type="lsep"/>
		<setting id="ra_sync_audio_settings" label="32006" type="bool" default="true" />
	</category>
	<category label="573"> <!-- Paths -->
		<setting label="573" type="lsep"/>
		<setting id="ra_roms_remote" label="32007" type="bool" default="false" />
		<setting id="ra_roms_remote_path" label="573" type="text" default="" enable="eq(-1,true)" subsetting="true"/>
		<setting id="ra_roms_remote_user" label="1048" type="text" default="" enable="eq(-2,true)" subsetting="true"/>
		<setting id="ra_roms_remote_password" label="733" type="text" default="" enable="eq(-3,true)" subsetting="true"/>
	</category>
	<category label="14092"> <!-- Log -->
		<setting label="14092" type="lsep"/>
		<setting id="ra_log" label="32008" type="bool" default="false" />
		<setting id="ra_verbose" label="20191" type="bool" default="false" />
	</category>
</settings>
EOF

read -d '' settings_default_xml <<EOF
<settings>
	<setting id="ra_stop_kodi" value="true" />
	<setting id="ra_xbox360_shutdown" value="true" />
	<setting id="ra_bt_shutdown" value="false" />
	<setting id="ra_cec_remote" value="true" />
	<setting id="ra_cec_poweroff" value="0" />
	<setting id="ra_force_refresh_rate" value="true" />
	<setting id="ra_forced_refresh_rate" value="1" />
	<setting id="ra_sync_audio_settings" value="true" />
	<setting id="ra_roms_remote" value="false" />
	<setting id="ra_roms_remote_path" value="" />
	<setting id="ra_roms_remote_user" value="" />
	<setting id="ra_roms_remote_password" value="" />
	<setting id="ra_autoupdate" value="true" />
	<setting id="ra_log" value="false" />
	<setting id="ra_verbose" value="false" />
	<setting id="ra_boot_toggle" value="KODI"/>
</settings>
EOF

#!/bin/bash

LANG_header='# XBMC Media Center language file
# Addon Name: RetroArch
# Addon id: script.retroarch.launcher.Amlogic-ng.arm
# Addon version: %s
# Addon Provider: spleen1981
msgid ""
msgstr ""
"Project-Id-Version: XBMC-Addons\\\\n"
"Report-Msgid-Bugs-To: https://github.com/spleen1981/retroarch-kodi-addon-CoreELEC/issues\\\\n"
"POT-Creation-Date: YEAR-MO-DA HO:MI+ZONE\\\\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\\\\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\\\\n"
"Language-Team: LANGUAGE\\\\n"
"MIME-Version: 1.0\\\\n"
"Content-Type: text/plain; charset=UTF-8\\\\n"
"Content-Transfer-Encoding: 8bit\\\\n"
"Language: %s\\\\n"
"Plural-Forms: nplurals=2; plural=(n != 1)\\\\n"\\n'

LANG_list="en_gb cs_cz it_it zh_cn sk_sk"
LANG_max=32013

LANG_0_ctx="Addon Summary"
LANG_0_en_gb="RetroArch add-on for Kodi (${RA_NAME_SUFFIX}). RetroArch is a frontend for emulators, game engines and media players."
LANG_0_cs_cz="Doplněk RetroArch pro Kodi (${RA_NAME_SUFFIX}). RetroArch je frontend pro emulátory, herní enginy a přehrávače médií."
LANG_0_it_it="RetroArch add-on per Kodi (${RA_NAME_SUFFIX}). RetroArch è un frontend per emulatori, giochi e media player."
LANG_0_sk_sk="Doplnok RetroArch pre Kodi (${RA_NAME_SUFFIX}). RetroArch je frontend pre emulátory, herné enginy a prehrávače médií."
LANG_0_zh_cn="Kodi (${RA_NAME_SUFFIX}) 的 RetroArch 附加组件。RetroArch 是一个模拟器、游戏引擎和媒体播放器的前端。"

LANG_1_ctx="Addon Description"
LANG_1_en_gb="The add-on provides binary, cores and basic settings to launch RetroArch from Kodi UI, plus additional features to improve user experience. It is built from Lakka sources."
LANG_1_cs_cz="Doplněk poskytuje jádra a základní nastavení pro spuštění RetroArch z uživatelského rozhraní Kodi a navíc další funkce pro zlepšení uživatelského zážitku. Je postaven ze zdrojů Lakka."
LANG_1_it_it="Questa add-on include i binari, i core e i settaggi di base per eseguire RetroArch dalla UI di Kodi, più funzionalità aggiuntive per migliorare l'esperienza utente. È costruito dai sorgenti di Lakka."
LANG_1_sk_sk="Doplnok poskytuje jadrá a základné nastavenia pre spustenie RetroArch z rozhrania Kodi a dodatočné funkcie pre zlepšenie používateľského zážitku. Je postavený na zdrojoch Lakka."
LANG_1_zh_cn="此附加组件从 Lakka 源码直接构建，同时提供了二进制，内核，从 Kodi UI 启动 RetroArch 的基本设置，以及改善用户体验的附加功能。"

LANG_2_ctx="Addon Disclaimer"
LANG_2_en_gb="This is an unofficial add-on. Use github.com/spleen1981/retroarch-kodi-addon-CoreELEC to submit issues."
LANG_2_cs_cz="Toto je neoficiální doplněk. K odeslání problémů použijte: github.com/spleen1981/retroarch-kodi-addon-CoreELEC."
LANG_2_it_it="Questa è una add-on non ufficiale. Usa github.com/spleen1981/retroarch-kodi-addon-CoreELEC per segnalare eventuali problemi."
LANG_2_sk_sk="Toto je neoficiálny doplnok. Na nahlásenie problémov použite github.com/spleen1981/retroarch-kodi-addon-CoreELEC."
LANG_2_zh_cn="这是一个非官方的附加组件。使用 github.com/spleen1981/retroarch-kodi-addon-CoreELEC 提交问题。"

LANG_32002_en_gb="Turn off Xbox360 controllers after closing RetroArch"
LANG_32002_cs_cz="Po vypnutí RetroArch vypněte ovladače Xbox360"
LANG_32002_it_it="Spegni i controller Xbox360 all'uscita di RetroArch"
LANG_32002_sk_sk="Po vypnutí RetroArch vypnite ovládače Xbox360"
LANG_32002_zh_cn="在关闭 RetroArch 时关闭 Xbox360 控制器"

LANG_32003_en_gb="Use remote control (CEC) with RetroArch"
LANG_32003_cs_cz="Použijte dálkové ovládání (CEC) s Retroarch"
LANG_32003_it_it="Usa telecomando (CEC) con Retroarch"
LANG_32003_sk_sk="Použite diaľkové ovládanie (CEC) s Retroarch"
LANG_32003_zh_cn="在 RetroArch 中使用 CEC 控制"

LANG_32004_en_gb="Override Kodi refresh rate settings"
LANG_32004_cs_cz="Přepsat nastavení obnovovací frekvence Kodi"
LANG_32004_it_it="Ignora frequenza di aggiornamento impostata in Kodi"
LANG_32004_sk_sk="Prepísať nastavenia obnovovacej frekvencie Kodi"
LANG_32004_zh_cn="覆盖 Kodi 的刷新率设置"

LANG_32005_en_gb="RetroArch refresh rate"
LANG_32005_cs_cz="Obnovovací frekvence RetroArch"
LANG_32005_it_it="Frequenza di aggiornamento RetroArch"
LANG_32005_sk_sk="Obnovovacia frekvencia RetroArch"
LANG_32005_zh_cn="RetroArch 刷新率"

LANG_32006_en_gb="Sync RetroArch audio driver/device with Kodi"
LANG_32006_cs_cz="Synchronizovat zvukový ovladač/zařízení RetroArch s Kodi"
LANG_32006_it_it="Sincronizza impostazioni driver/device audio di RetroArch con Kodi"
LANG_32006_sk_sk="Synchronizovať zvukový ovládač/zariadenie RetroArch s Kodi"
LANG_32006_zh_cn="将 RetroArch 音频驱动程序/设备与 Kodi 同步"

LANG_32007_en_gb="Mount remote path for RetroArch ROMs"
LANG_32007_cs_cz="Připojit vzdálenou cestu pro ROMs RetroArch"
LANG_32007_it_it="Monta percorso remoto per le ROM di RetroArch"
LANG_32007_sk_sk="Pripojiť vzdialenú cestu pre ROMky RetroArch"
LANG_32007_zh_cn="为 RetroArch ROMs 挂载远程路径"

LANG_32008_en_gb="Save RetroArch logs to file"
LANG_32008_cs_cz="Uložit protokoly RetroArch do souboru"
LANG_32008_it_it="Salva i log di RetroArch su file"
LANG_32008_sk_sk="Uložiť protokoly RetroArch do súboru"
LANG_32008_zh_cn="将 RetroArch 日志保存到文件"

LANG_32009_en_gb="Turn off BT controllers on RetroArch exit (if supported)"
LANG_32009_it_it="Spegni i controller BT all'uscita di RetroArch (se supportato)"
LANG_32009_sk_sk="Vypnúť BT ovládače pri vypnutí RetroArch-u (ak je podporované)"
LANG_32009_zh_cn="在 RetroArch 退出时关闭蓝牙控制器（如果支持的话）"

LANG_32010_en_gb="Boot the system to"
LANG_32010_it_it="Avvia il sistema con"
LANG_32010_sk_sk="Naštartovať systém do"
LANG_32010_zh_cn="启动系统时打开"

LANG_32011_en_gb="Currently the system boots to"
LANG_32011_it_it="Il sistema attualmente si avvia con"
LANG_32011_sk_sk="Systém aktuálne štartuje do"
LANG_32011_zh_cn="当前启动系统时会打开"

LANG_32012_en_gb="Do you want to change the setting and boot to"
LANG_32012_it_it="Vuoi cambiare l'impostazione e avviare con"
LANG_32012_sk_sk="Chcete zmeniť nastavenie a štartovať do"
LANG_32012_zh_cn="你是否想要改变系统启动时打开的程序"

LANG_32013_en_gb="SMB protocol version"
LANG_32013_it_it="Versione protocollo SMB"
LANG_32013_sk_sk="Verzia SMB protokolu"
LANG_32013_zh_cn="SMB 协议版本"

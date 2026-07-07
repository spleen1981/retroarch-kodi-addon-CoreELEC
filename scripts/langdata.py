"""i18n source of truth for the build pipeline.

Two consumers:

    * `package.emit_addon_xml`   uses `translate(id, lang, ...)` to fill the
                                 <summary>/<description>/<disclaimer> tags
                                 (ids 0, 1, 2).
    * `package.emit_language_files` iterates `entries()` to produce one
                                 strings.po per language under
                                 resources/language/.

PO files are generated at packaging time and dropped into the
addon dir.

Placeholder convention: strings with `${RA_NAME_SUFFIX}` are substituted at
render time. Anything else is literal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


LANGUAGES: tuple[str, ...] = (
    "en_gb", "es_es", "cs_cz", "it_it",
    "zh_cn", "sk_sk", "pt_br", "de_de",
)


@dataclass(frozen=True)
class Entry:
    """One translatable string with a context tag and per-language values.

    `ctx` is what lands in the PO file as `msgctxt`. For numeric ids it is
    `#NNNNN` (Kodi convention); for the three addon.xml metadata strings
    (Summary / Description / Disclaimer) it is the human-readable label.
    """
    msg_id: int
    ctx: str
    translations: dict  # lang_code -> raw string

    def text(self, lang_code: str, *, ra_name_suffix: str = "") -> str:
        """Return the translation for `lang_code`, substituting placeholders.

        Returns "" for languages with no translation — callers that want
        en_gb fallback should call `translate()` instead.

        When `ra_name_suffix` is empty (the v2 platform-independent build),
        drop the " (${RA_NAME_SUFFIX})" parenthetical cleanly so the summary
        reads "RetroArch add-on for Kodi." instead of "… for Kodi ()."
        """
        raw = self.translations.get(lang_code, "")
        if ra_name_suffix:
            return raw.replace("${RA_NAME_SUFFIX}", ra_name_suffix)
        return raw.replace(" (${RA_NAME_SUFFIX})", "").replace("${RA_NAME_SUFFIX}", "")


def translate(msg_id: int, lang_code: str, *, ra_name_suffix: str = "") -> str:
    """Render entry `msg_id` for `lang_code` with en_gb fallback.

    Used by `emit_addon_xml` so a missing translation doesn't leave an
    empty tag in addon.xml.
    """
    entry = _BY_ID.get(msg_id)
    if entry is None:
        return ""
    if lang_code in entry.translations:
        return entry.text(lang_code, ra_name_suffix=ra_name_suffix)
    return entry.text("en_gb", ra_name_suffix=ra_name_suffix)


def entries() -> Iterator[Entry]:
    """Yield every entry in id order (addon.xml metadata first, labels after)."""
    return iter(_ENTRIES)


# =================================================================== data ==

# Order matters: ids 0/1/2 first (with named ctx), then numeric labels with
# `#NNNNN` ctx. Listed in source-file order so a diff against the legacy
# `01-def_lang.sh` is easy to read.

_ENTRIES: tuple[Entry, ...] = (
    Entry(0, "Addon Summary", {
        "en_gb": "RetroArch add-on for Kodi (${RA_NAME_SUFFIX}). RetroArch is a frontend for emulators, game engines and media players.",
        "es_es": "Complemento RetroArch para Kodi (${RA_NAME_SUFFIX}). RetroArch es una interfaz para emuladores, motores de juego y reproductores multimedia.",
        "cs_cz": "Doplněk RetroArch pro Kodi (${RA_NAME_SUFFIX}). RetroArch je frontend pro emulátory, herní enginy a přehrávače médií.",
        "it_it": "RetroArch add-on per Kodi (${RA_NAME_SUFFIX}). RetroArch è un frontend per emulatori, giochi e media player.",
        "sk_sk": "Doplnok RetroArch pre Kodi (${RA_NAME_SUFFIX}). RetroArch je frontend pre emulátory, herné enginy a prehrávače médií.",
        "zh_cn": "Kodi (${RA_NAME_SUFFIX}) 的 RetroArch 附加组件。RetroArch 是一个模拟器、游戏引擎和媒体播放器的前端。",
        "pt_br": "Add-on RetroArch para Kodi (${RA_NAME_SUFFIX}). RetroArch é um frontend para emuladores, motores de jogos e reprodutores de mídia.",
        "de_de": "RetroArch Addon für Kodi (${RA_NAME_SUFFIX}). RetroArch ist ein Frontend für Emulatoren, Game-Engines und Mediaplayer.",
    }),
    Entry(1, "Addon Description", {
        "en_gb": "Integrates RetroArch with Kodi on CoreELEC. Automatically downloads and updates the appropriate RetroArch runtime, supports boot-to-RetroArch, and provides additional tools and configuration features for a seamless user experience.",
        "de_de": "Integriert RetroArch in Kodi auf CoreELEC. Lädt automatisch die passende RetroArch-Laufzeitumgebung herunter, hält sie aktuell, unterstützt Boot-to-RetroArch und bietet zusätzliche Werkzeuge sowie Konfigurationsfunktionen für eine nahtlose Benutzererfahrung.",
        "es_es": "Integra RetroArch con Kodi en CoreELEC. Descarga y actualiza automáticamente el entorno de ejecución adecuado de RetroArch, admite el arranque directo en RetroArch y proporciona herramientas y opciones de configuración adicionales para una experiencia de usuario fluida.",
        "fr_fr": "Intègre RetroArch à Kodi sur CoreELEC. Télécharge et met automatiquement à jour l’environnement d’exécution RetroArch approprié, prend en charge le démarrage direct vers RetroArch et fournit des outils et options de configuration supplémentaires pour une expérience utilisateur fluide.",
        "it_it": "Integra RetroArch con Kodi su CoreELEC. Scarica e aggiorna automaticamente il runtime RetroArch appropriato, supporta l’avvio diretto in RetroArch e offre strumenti e funzionalità di configurazione aggiuntivi per un’esperienza utente senza interruzioni.",
        "pl_pl": "Integruje RetroArch z Kodi w systemie CoreELEC. Automatycznie pobiera i aktualizuje odpowiednie środowisko uruchomieniowe RetroArch, obsługuje uruchamianie bezpośrednio do RetroArch oraz udostępnia dodatkowe narzędzia i opcje konfiguracji zapewniające płynną obsługę.",
        "pt_br": "Integra o RetroArch ao Kodi no CoreELEC. Faz o download e atualiza automaticamente o ambiente de execução apropriado do RetroArch, oferece suporte ao boot direto para o RetroArch e fornece ferramentas e recursos de configuração adicionais para uma experiência de uso integrada.",
        "ru_ru": "Интегрирует RetroArch с Kodi в CoreELEC. Автоматически загружает и обновляет подходящую среду выполнения RetroArch, поддерживает прямую загрузку в RetroArch и предоставляет дополнительные инструменты и возможности настройки для удобной работы.",
        "zh_cn": "将 RetroArch 与 CoreELEC 上的 Kodi 集成。自动下载并更新合适的 RetroArch 运行环境，支持直接启动到 RetroArch，并提供额外的工具和配置功能，以获得更流畅的使用体验。"
    }),
    Entry(2, "Addon Disclaimer", {
        "en_gb": "This is an unofficial add-on. Use github.com/spleen1981/retroarch-kodi-addon-CoreELEC to submit issues.",
        "es_es": "Este es un complemento no oficial. Utiliza github.com/spleen1981/retroarch-kodi-addon-CoreELEC para reportar problemas.",
        "cs_cz": "Toto je neoficiální doplněk. K odeslání problémů použijte: github.com/spleen1981/retroarch-kodi-addon-CoreELEC.",
        "it_it": "Questa è una add-on non ufficiale. Usa github.com/spleen1981/retroarch-kodi-addon-CoreELEC per segnalare eventuali problemi.",
        "sk_sk": "Toto je neoficiálny doplnok. Na nahlásenie problémov použite github.com/spleen1981/retroarch-kodi-addon-CoreELEC.",
        "zh_cn": "这是一个非官方的附加组件。使用 github.com/spleen1981/retroarch-kodi-addon-CoreELEC 提交问题。",
        "pt_br": "Este é um add-on não oficial. Use github.com/spleen1981/retroarch-kodi-addon-CoreELEC para enviar os problemas encontrados.",
        "de_de": "Dies ist ein inoffizielles Addon. Verwenden Sie github.com/spleen1981/retroarch-kodi-addon-CoreELEC um Probleme zu melden.",
    }),
    Entry(32002, "#32002", {
        "en_gb": "Turn off Xbox360 controllers after closing RetroArch",
        "es_es": "Apagar los controladores de Xbox360 después de cerrar RetroArch",
        "cs_cz": "Po vypnutí RetroArch vypněte ovladače Xbox360",
        "it_it": "Spegni i controller Xbox360 all'uscita di RetroArch",
        "sk_sk": "Po vypnutí RetroArch vypnite ovládače Xbox360",
        "zh_cn": "在关闭 RetroArch 时关闭 Xbox360 控制器",
        "pt_br": "Desligar os controles do Xbox360 após fechar o RetroArch",
        "de_de": "Schalten Sie Xbox360-Controller aus, nachdem Sie RetroArch geschlossen haben",
    }),
    Entry(32003, "#32003", {
        "en_gb": "Use remote control (CEC) with RetroArch",
        "es_es": "Usar control remoto (CEC) con RetroArch",
        "cs_cz": "Použijte dálkové ovládání (CEC) s Retroarch",
        "it_it": "Usa telecomando (CEC) con Retroarch",
        "sk_sk": "Použite diaľkové ovládanie (CEC) s Retroarch",
        "zh_cn": "在 RetroArch 中使用 CEC 控制",
        "pt_br": "Usar controle remoto (CEC) com o RetroArch",
        "de_de": "Verwenden Sie die Fernbedienung (CEC) mit RetroArch",
    }),
    Entry(32004, "#32004", {
        "en_gb": "Override Kodi refresh rate settings",
        "es_es": "Sobrescribir configuraciones de frecuencia de actualización de Kodi",
        "cs_cz": "Přepsat nastavení obnovovací frekvence Kodi",
        "it_it": "Ignora frequenza di aggiornamento impostata in Kodi",
        "sk_sk": "Prepísať nastavenia obnovovacej frekvencie Kodi",
        "zh_cn": "覆盖 Kodi 的刷新率设置",
        "pt_br": "Substituir as configurações da taxa de atualização do Kodi",
        "de_de": "Bildwiederholfrequenz von Kodi überschreiben",
    }),
    Entry(32005, "#32005", {
        "en_gb": "RetroArch refresh rate",
        "es_es": "Frecuencia de actualización de RetroArch",
        "cs_cz": "Obnovovací frekvence RetroArch",
        "it_it": "Frequenza di aggiornamento RetroArch",
        "sk_sk": "Obnovovacia frekvencia RetroArch",
        "zh_cn": "RetroArch 刷新率",
        "pt_br": "Taxa de atualização do RetroArch",
        "de_de": "RetroArch Bildwiederholfrequenz",
    }),
    Entry(32006, "#32006", {
        "en_gb": "Sync RetroArch audio driver/device with Kodi",
        "es_es": "Sincronizar el controlador/dispositivo de audio de RetroArch con Kodi",
        "cs_cz": "Synchronizovat zvukový ovladač/zařízení RetroArch s Kodi",
        "it_it": "Sincronizza impostazioni driver/device audio di RetroArch con Kodi",
        "sk_sk": "Synchronizovať zvukový ovládač/zariadenie RetroArch s Kodi",
        "zh_cn": "将 RetroArch 音频驱动程序/设备与 Kodi 同步",
        "pt_br": "Sincronizar o driver/dispositivo de áudio do RetroArch com o Kodi",
        "de_de": "RetroArch Audiotreiber/-Gerät mit Kodi synchronisieren",
    }),
    Entry(32007, "#32007", {
        "en_gb": "Mount remote path for RetroArch ROMs",
        "es_es": "Montar ruta remota para las ROMs de RetroArch",
        "cs_cz": "Připojit vzdálenou cestu pro ROMs RetroArch",
        "it_it": "Monta percorso remoto per le ROM di RetroArch",
        "sk_sk": "Pripojiť vzdialenú cestu pre ROMky RetroArch",
        "zh_cn": "为 RetroArch ROMs 挂载远程路径",
        "pt_br": "Montar caminho remoto para as ROMs do RetroArch",
        "de_de": "Remote-Pfad (UNC) für RetroArch ROMs mounten",
    }),
    Entry(32008, "#32008", {
        "en_gb": "RetroArch log level",
        "it_it": "Livello log RetroArch",
        "es_es": "Nivel de registro de RetroArch",
        "cs_cz": "Úroveň protokolování RetroArch",
        "zh_cn": "RetroArch 日志级别",
        "sk_sk": "Úroveň protokolovania RetroArch",
        "pt_br": "Nível de log do RetroArch",
        "de_de": "RetroArch-Protokollstufe",
    }),
    # 32009 has no es_es translation in the legacy source.
    Entry(32009, "#32009", {
        "en_gb": "Turn off BT controllers on RetroArch exit (if supported)",
        "it_it": "Spegni i controller BT all'uscita di RetroArch (se supportato)",
        "sk_sk": "Vypnúť BT ovládače pri vypnutí RetroArch-u (ak je podporované)",
        "zh_cn": "在 RetroArch 退出时关闭蓝牙控制器（如果支持的话）",
        "pt_br": "Desligar os controles Bluetooth ao sair do RetroArch (se suportado)",
        "de_de": "Schalten Sie die Bluetooth-Controller beim Beenden von RetroArch aus (falls unterstützt)",
        "es_es": "Apagar los controles Bluetooth al salir de RetroArch (si es compatible)",
        "cs_cz": "Vypnout ovladače Bluetooth při ukončení RetroArch (pokud je podporováno)",
    }),
    # 32010-32013 have no cs_cz translation in the legacy source.
    Entry(32010, "#32010", {
        "en_gb": "Boot the system to",
        "es_es": "Arrancar el sistema a",
        "it_it": "Avvia il sistema con",
        "sk_sk": "Naštartovať systém do",
        "zh_cn": "启动系统时打开",
        "pt_br": "Inicializar o sistema com",
        "de_de": "Booten Sie das System zu",
        "cs_cz": "Spustit systém do",
    }),
    Entry(32011, "#32011", {
        "en_gb": "Currently the system boots to",
        "es_es": "Actualmente el sistema arranca a",
        "it_it": "Il sistema attualmente si avvia con",
        "sk_sk": "Systém aktuálne štartuje do",
        "zh_cn": "当前启动系统时会打开",
        "pt_br": "Atualmente o sistema inicializa com",
        "de_de": "Systemneustart zu",
        "cs_cz": "Systém se aktuálně spouští do",
    }),
    Entry(32012, "#32012", {
        "en_gb": "Do you want to change the setting and boot to",
        "es_es": "¿Quieres cambiar la configuración y arrancar a",
        "it_it": "Vuoi cambiare l'impostazione e avviare con",
        "sk_sk": "Chcete zmeniť nastavenie a štartovať do",
        "zh_cn": "你是否想要改变系统启动时打开的程序",
        "pt_br": "Deseja alterar a configuração e inicializar com",
        "de_de": "Möchten Sie die Einstellung ändern und starten zu",
        "cs_cz": "Chcete změnit nastavení a spouštět do",
    }),
    Entry(32013, "#32013", {
        "en_gb": "SMB protocol version",
        "es_es": "Versión del protocolo SMB",
        "it_it": "Versione protocollo SMB",
        "sk_sk": "Verzia SMB protokolu",
        "zh_cn": "SMB 协议版本",
        "pt_br": "Versão do protocolo SMB",
        "de_de": "SMB Protokollversion",
        "cs_cz": "Verze protokolu SMB",
    }),
    # 32014 has no cs_cz, sk_sk, zh_cn translation in the legacy source.
    # 32015 has no cs_cz, sk_sk, zh_cn translation in the legacy source.
    Entry(32016, "#32016", {
        "en_gb": "Add-on version",
        "it_it": "Versione add-on",
        "es_es": "Versión del complemento",
        "cs_cz": "Verze doplňku",
        "zh_cn": "附加组件版本",
        "sk_sk": "Verzia doplnku",
        "pt_br": "Versão do add-on",
        "de_de": "Addon-Version",
    }),
    Entry(32017, "#32017", {
        "en_gb": "Platform",
        "it_it": "Piattaforma",
        "es_es": "Plataforma",
        "cs_cz": "Platforma",
        "zh_cn": "平台",
        "sk_sk": "Platforma",
        "pt_br": "Plataforma",
        "de_de": "Plattform",
    }),
    Entry(32018, "#32018", {
        "en_gb": "RetroArch package",
        "it_it": "Pacchetto RetroArch",
        "es_es": "Paquete RetroArch",
        "cs_cz": "Balíček RetroArch",
        "zh_cn": "RetroArch 软件包",
        "sk_sk": "Balík RetroArch",
        "pt_br": "Pacote RetroArch",
        "de_de": "RetroArch-Paket",
    }),
    Entry(32019, "#32019", {
        "en_gb": "Refresh info",
        "it_it": "Aggiorna info",
        "es_es": "Actualizar información",
        "cs_cz": "Obnovit informace",
        "zh_cn": "刷新信息",
        "sk_sk": "Obnoviť informácie",
        "pt_br": "Atualizar informações",
        "de_de": "Informationen aktualisieren",
    }),
    Entry(32020, "#32020", {
        "en_gb": "No log",
        "it_it": "Nessun log",
        "es_es": "Sin registro",
        "cs_cz": "Bez protokolu",
        "zh_cn": "不记录日志",
        "sk_sk": "Bez protokolu",
        "pt_br": "Sem log",
        "de_de": "Kein Protokoll",
    }),
    Entry(32021, "#32021", {
        "en_gb": "Errors only",
        "it_it": "Solo errori",
        "es_es": "Solo errores",
        "cs_cz": "Pouze chyby",
        "zh_cn": "仅错误",
        "sk_sk": "Iba chyby",
        "pt_br": "Apenas erros",
        "de_de": "Nur Fehler",
    }),
    Entry(32022, "#32022", {
        "en_gb": "Verbose",
        "it_it": "Dettagliato",
        "es_es": "Detallado",
        "cs_cz": "Podrobné",
        "zh_cn": "详细",
        "sk_sk": "Podrobné",
        "pt_br": "Detalhado",
        "de_de": "Ausführlich",
    }),
    Entry(32023, "#32023", {
        "en_gb": "Preparing RetroArch resources...",
        "it_it": "Preparazione risorse RetroArch...",
        "es_es": "Preparando recursos de RetroArch...",
        "cs_cz": "Příprava prostředků RetroArch...",
        "zh_cn": "正在准备 RetroArch 资源...",
        "sk_sk": "Pripravujú sa prostriedky RetroArch...",
        "pt_br": "Preparando recursos do RetroArch...",
        "de_de": "RetroArch-Ressourcen werden vorbereitet...",
    }),

    Entry(32024, "#32024", {
        'en_gb': 'Audio / Video',
        'es_es': 'Audio / Vídeo',
        'cs_cz': 'Audio / Video',
        'it_it': 'Audio / Video',
        'zh_cn': '音频 / 视频',
        'sk_sk': 'Audio / Video',
        'pt_br': 'Áudio / Vídeo',
        'de_de': 'Audio / Video',
    }),
    Entry(32025, "#32025", {
        'en_gb': 'Information',
        'es_es': 'Información',
        'cs_cz': 'Informace',
        'it_it': 'Informazioni',
        'zh_cn': '信息',
        'sk_sk': 'Informácie',
        'pt_br': 'Informações',
        'de_de': 'Informationen',
    }),
    Entry(32026, "#32026", {
        'en_gb': 'Startup',
        'es_es': 'Inicio',
        'cs_cz': 'Spuštění',
        'it_it': 'Avvio',
        'zh_cn': '启动',
        'sk_sk': 'Spustenie',
        'pt_br': 'Inicialização',
        'de_de': 'Start',
    }),
    Entry(32027, "#32027", {
        'en_gb': 'Updates',
        'es_es': 'Actualizaciones',
        'cs_cz': 'Aktualizace',
        'it_it': 'Aggiornamenti',
        'zh_cn': '更新',
        'sk_sk': 'Aktualizácie',
        'pt_br': 'Atualizações',
        'de_de': 'Updates',
    }),
    Entry(32028, "#32028", {
        'en_gb': 'Logging',
        'es_es': 'Registro',
        'cs_cz': 'Protokolování',
        'it_it': 'Log',
        'zh_cn': '日志',
        'sk_sk': 'Protokolovanie',
        'pt_br': 'Log',
        'de_de': 'Protokollierung',
    }),
    Entry(32029, "#32029", {
        'en_gb': 'Maintenance',
        'es_es': 'Mantenimiento',
        'cs_cz': 'Údržba',
        'it_it': 'Manutenzione',
        'zh_cn': '维护',
        'sk_sk': 'Údržba',
        'pt_br': 'Manutenção',
        'de_de': 'Wartung',
    }),
    Entry(32030, "#32030", {
        'en_gb': 'Resources',
        'es_es': 'Recursos',
        'cs_cz': 'Prostředky',
        'it_it': 'Risorse',
        'zh_cn': '资源',
        'sk_sk': 'Prostriedky',
        'pt_br': 'Recursos',
        'de_de': 'Ressourcen',
    }),
    Entry(32031, "#32031", {
        'en_gb': 'Configuration',
        'es_es': 'Configuración',
        'cs_cz': 'Konfigurace',
        'it_it': 'Configurazione',
        'zh_cn': '配置',
        'sk_sk': 'Konfigurácia',
        'pt_br': 'Configuração',
        'de_de': 'Konfiguration',
    }),
    Entry(32032, "#32032", {
        'en_gb': 'Force RetroArch resources sync',
        'es_es': 'Forzar sincronización de recursos de RetroArch',
        'cs_cz': 'Vynutit synchronizaci prostředků RetroArch',
        'it_it': 'Forza sincronizzazione risorse RetroArch',
        'zh_cn': '强制同步 RetroArch 资源',
        'sk_sk': 'Vynútiť synchronizáciu prostriedkov RetroArch',
        'pt_br': 'Forçar sincronização dos recursos do RetroArch',
        'de_de': 'Synchronisierung der RetroArch-Ressourcen erzwingen',
    }),
    Entry(32033, "#32033", {
        'en_gb': 'Reset RetroArch configuration',
        'es_es': 'Restablecer configuración de RetroArch',
        'cs_cz': 'Obnovit konfiguraci RetroArch',
        'it_it': 'Reimposta configurazione RetroArch',
        'zh_cn': '重置 RetroArch 配置',
        'sk_sk': 'Obnoviť konfiguráciu RetroArch',
        'pt_br': 'Redefinir configuração do RetroArch',
        'de_de': 'RetroArch-Konfiguration zurücksetzen',
    }),
    Entry(32034, "#32034", {
        'en_gb': 'Factory reset',
        'es_es': 'Restablecimiento completo',
        'cs_cz': 'Obnovení továrního nastavení',
        'it_it': 'Ripristino completo',
        'zh_cn': '恢复出厂设置',
        'sk_sk': 'Obnovenie výrobných nastavení',
        'pt_br': 'Redefinição de fábrica',
        'de_de': 'Werkseinstellungen',
    }),
    Entry(32036, "#32036", {
        'en_gb': 'Removes all add-on user data and .config/retroarch',
        'es_es': 'Elimina todos los datos de usuario del complemento y .config/retroarch',
        'cs_cz': 'Odstraní všechna uživatelská data doplňku a .config/retroarch',
        'it_it': "Rimuove tutti i dati utente dell'add-on e .config/retroarch",
        'zh_cn': '删除所有附加组件用户数据和 .config/retroarch',
        'sk_sk': 'Odstráni všetky používateľské údaje doplnku a .config/retroarch',
        'pt_br': 'Remove todos os dados de usuário do add-on e .config/retroarch',
        'de_de': 'Entfernt alle Addon-Benutzerdaten und .config/retroarch',
    }),
    Entry(32037, "#32037", {
        'en_gb': 'This will remove all add-on user data and .config/retroarch. Do you want to continue?',
        'es_es': 'Esto eliminará todos los datos de usuario del complemento y .config/retroarch. ¿Quieres continuar?',
        'cs_cz': 'Tím se odstraní všechna uživatelská data doplňku a .config/retroarch. Chcete pokračovat?',
        'it_it': "Questo rimuoverà tutti i dati utente dell'add-on e .config/retroarch. Vuoi continuare?",
        'zh_cn': '这将删除所有附加组件用户数据和 .config/retroarch。是否继续？',
        'sk_sk': 'Týmto sa odstránia všetky používateľské údaje doplnku a .config/retroarch. Chcete pokračovať?',
        'pt_br': 'Isso removerá todos os dados de usuário do add-on e .config/retroarch. Deseja continuar?',
        'de_de': 'Dadurch werden alle Addon-Benutzerdaten und .config/retroarch entfernt. Möchten Sie fortfahren?',
    }),
    Entry(32038, "#32038", {
        'en_gb': 'RetroArch configuration reset',
        'es_es': 'Configuración de RetroArch restablecida',
        'cs_cz': 'Konfigurace RetroArch obnovena',
        'it_it': 'Configurazione RetroArch reimpostata',
        'zh_cn': 'RetroArch 配置已重置',
        'sk_sk': 'Konfigurácia RetroArch bola obnovená',
        'pt_br': 'Configuração do RetroArch redefinida',
        'de_de': 'RetroArch-Konfiguration zurückgesetzt',
    }),
    Entry(32040, "#32040", {
        'en_gb': 'Automatic update on startup',
        'es_es': 'Actualización automática al iniciar',
        'cs_cz': 'Automatická aktualizace při spuštění',
        'it_it': "Aggiornamento automatico all'avvio",
        'zh_cn': '启动时自动更新',
        'sk_sk': 'Automatická aktualizácia pri spustení',
        'pt_br': 'Atualização automática na inicialização',
        'de_de': 'Automatisches Update beim Start',
    }),
    Entry(32041, "#32041", {
        'en_gb': 'Check for updates now',
        'es_es': 'Buscar actualizaciones ahora',
        'cs_cz': 'Zkontrolovat aktualizace nyní',
        'it_it': 'Controlla aggiornamenti ora',
        'zh_cn': '立即检查更新',
        'sk_sk': 'Skontrolovať aktualizácie teraz',
        'pt_br': 'Verificar atualizações agora',
        'de_de': 'Jetzt nach Updates suchen',
    }),
    Entry(32042, "#32042", {
        'en_gb': 'Factory reset completed',
        'es_es': 'Restablecimiento completo finalizado',
        'cs_cz': 'Obnovení továrního nastavení dokončeno',
        'it_it': 'Ripristino completo completato',
        'zh_cn': '恢复出厂设置已完成',
        'sk_sk': 'Obnovenie výrobných nastavení dokončené',
        'pt_br': 'Redefinição de fábrica concluída',
        'de_de': 'Werkseinstellungen abgeschlossen',
    }),

    Entry(32039, "#32039", {
        'en_gb': 'RetroArch resources synchronized',
        'es_es': 'Recursos de RetroArch sincronizados',
        'cs_cz': 'Prostředky RetroArch synchronizovány',
        'it_it': 'Risorse RetroArch sincronizzate',
        'zh_cn': 'RetroArch 资源已同步',
        'sk_sk': 'Prostriedky RetroArch boli synchronizované',
        'pt_br': 'Recursos do RetroArch sincronizados',
        'de_de': 'RetroArch-Ressourcen synchronisiert',
    }),

)

_BY_ID: dict[int, Entry] = {e.msg_id: e for e in _ENTRIES}

#!/bin/sh
# RetroArch autostart shim for CoreELEC. Boot-to-RA path only.
# CoreELEC runs $HOME/.config/autostart.sh once at boot (kodi-autostart.service,
# Before=kodi.service WantedBy=kodi.service).

. /etc/profile
oe_setup_addon "script.retroarch.launcher"

PYTHONPATH="$ADDON_DIR/lib${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

# HARDENED: resolve paths in pure shell so recovery never depends on python.
AUTOSTART="${HOME:-/storage}/.config/autostart.sh"
SHIM_LOG="${ADDON_HOME:-${HOME:-/storage}/.kodi/userdata/addon_data/script.retroarch.launcher}/logs/boot_shim.log"

shim_log() {
	mkdir -p "$(dirname "$SHIM_LOG")" 2>/dev/null
	echo "$(date '+%F %T') $*" >> "$SHIM_LOG" 2>/dev/null
}

# HARDENED: remove our boot line WITHOUT python. Deletes the file if only
# comments/blank lines remain. This is the loop-proof escape hatch.
disable_autostart() {
	[ -f "$AUTOSTART" ] || return 0
	sed -i '/ra_autostart\.sh/d' "$AUTOSTART" 2>/dev/null
	if [ -z "$(grep -vE '^[[:space:]]*(#|$)' "$AUTOSTART" 2>/dev/null)" ]; then
		rm -f "$AUTOSTART"
	fi
}

# HARDENED: fail-safe — disable our line and boot to Kodi. Never reboots.
bail_to_kodi() {
	shim_log "self-heal: $* -> disabling boot line, booting to kodi"
	disable_autostart
	systemctl unmask kodi 2>/dev/null
	exit 0
}

# Defensive unmask FIRST: if we bail anywhere below, kodi must be able to start.
systemctl unmask kodi 2>/dev/null

# Reconcile desired state with settings.
#   rc=0  -> settings still want RetroArch -> proceed
#   non-0 -> settings say Kodi, or python crashed -> self-heal to Kodi
python3 -m ra boot_toggle check
rc=$?
[ "$rc" -ne 0 ] && bail_to_kodi "boot_toggle check rc=$rc"

# Gates BEFORE masking: never mask kodi with nothing to launch. Fast & offline.
if ! python3 -m ra appimage_ready; then
	shim_log "no compatible AppImage; booting to kodi"
	exit 0
fi
if ! python3 -c 'import ra' 2>/dev/null; then
	shim_log "ra not importable; booting to kodi"
	exit 0
fi

# Skip kodi: mask it so kodi.service won't start when this script exits.
# Recovery: runtime unmasks+starts kodi when RA exits; the defensive unmask
# above also clears it on the next boot, and bail_to_kodi/SSH always can too.
systemctl mask kodi 2>/dev/null
shim_log "masked kodi; launching RA directly (skip kodi boot) uptime=$(cut -d' ' -f1 /proc/uptime 2>/dev/null)s"

# Detached launcher so this script can return; RA owns the framebuffer.
systemd-run -q --collect -u ra-launcher /bin/sh -c "
	export HOME='$HOME'
	export PYTHONPATH='$PYTHONPATH'
	export ADDON_DIR='$ADDON_DIR'
	export ADDON_HOME='$ADDON_HOME'

	LOGF=\"\$ADDON_HOME/logs/boot_shim.log\"
	logf() { mkdir -p \"\$(dirname \"\$LOGF\")\" 2>/dev/null; echo \"\$(date '+%F %T') ra-launcher \$*\" >> \"\$LOGF\" 2>/dev/null; }

	# Brief settle after the CoreELEC splash so the framebuffer is ready.
	# TUNABLE: lower toward 0 to launch sooner, raise if RA shows a black screen.
	# sleep 2

	# Take the framebuffer from the splash service.
	pgrep splash-image | xargs -r kill -SIGTERM 2>/dev/null

	logf \"exec ra start (uptime \$(cut -d' ' -f1 /proc/uptime)s)\"
	exec python3 -m ra start
"
exit 0

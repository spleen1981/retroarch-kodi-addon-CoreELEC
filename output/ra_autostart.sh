#!/bin/sh
# RetroArch autostart shim for CoreELEC. Boot-to-RA path only.
# CoreELEC runs $HOME/.config/autostart.sh once at boot (kodi-autostart.service,
# Before=kodi.service WantedBy=kodi.service). CE22 strategy: let kodi start to
# init the Amlogic display, then a transient ra-launcher unit takes over.

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

# Defensive unmask (no-op if not masked).
systemctl unmask kodi 2>/dev/null

# Reconcile desired state with settings.
#   rc=0  -> settings still want RetroArch -> proceed to launch
#   rc=1  -> settings say Kodi (reset)     -> self-heal to Kodi
#   other -> python couldn't run / crashed -> self-heal to Kodi
python3 -m ra boot_toggle check
rc=$?
# HARDENED: any non-zero (intended "1" OR a python crash) -> bail safely.
# No `reboot now`: we simply fall through to a normal Kodi boot.
[ "$rc" -ne 0 ] && bail_to_kodi "boot_toggle check rc=$rc"

# Kick off the ra-launcher transient unit and exit so kodi.service proceeds.
systemd-run -q -u ra-launcher /bin/sh -c "
	export HOME='$HOME'
	export PYTHONPATH='$PYTHONPATH'
	export ADDON_DIR='$ADDON_DIR'
	export ADDON_HOME='$ADDON_HOME'
	# Wait for kodi.bin (display init happens inside it).
	for i in \$(seq 1 60); do
		pgrep -x kodi.bin >/dev/null && break
		sleep 0.5
	done
	# No compatible RetroArch AppImage -> stay in kodi (nothing to launch).
	if ! python3 -m ra appimage_ready; then
		echo 'ra_autostart: no compatible RetroArch package; staying in kodi' >&2
		exit 0
	fi
	# HARDENED: never stop kodi unless 'ra' is actually importable, otherwise a
	# launch failure would leave a black screen (kodi stopped, RA never up).
	if ! python3 -c 'import ra' 2>/dev/null; then
		echo 'ra_autostart: ra module not importable; staying in kodi' >&2
		exit 0
	fi
	# Let kodi finish opening /dev/dri/card0; 3s settles the framebuffer.
	sleep 3
	systemctl stop kodi
	pgrep splash-image | xargs -r kill -SIGTERM 2>/dev/null
	exec python3 -m ra start
"

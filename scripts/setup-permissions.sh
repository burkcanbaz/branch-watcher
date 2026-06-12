#!/usr/bin/env bash
# Grant the current user passwordless sudo for ONLY arp-scan and ufw, so the
# backend can resolve the allowed client's IP and update the firewall on startup
# without a password prompt. Run once, on the machine that hosts the backend:
#
#     ./setup-permissions.sh
#
# Re-run is safe (it overwrites the same file).
set -euo pipefail

ARP_SCAN_BIN="$(command -v arp-scan || echo /usr/sbin/arp-scan)"
UFW_BIN="$(command -v ufw || echo /usr/sbin/ufw)"
USER_NAME="${SUDO_USER:-$USER}"
SUDOERS_FILE="/etc/sudoers.d/branch-watcher"

RULE="$USER_NAME ALL=(root) NOPASSWD: $ARP_SCAN_BIN, $UFW_BIN"

echo "Granting passwordless sudo to '$USER_NAME' for:"
echo "  $ARP_SCAN_BIN"
echo "  $UFW_BIN"

# Write via a temp file + visudo -c so a typo can never lock you out of sudo.
TMP="$(mktemp)"
echo "$RULE" > "$TMP"
if sudo visudo -c -f "$TMP" >/dev/null; then
    sudo install -m 0440 -o root -g root "$TMP" "$SUDOERS_FILE"
    rm -f "$TMP"
    echo "✅ Wrote $SUDOERS_FILE"
else
    rm -f "$TMP"
    echo "❌ Generated sudoers rule failed validation; nothing changed." >&2
    exit 1
fi

# Quick check that it actually works without a password.
if sudo -n "$UFW_BIN" status >/dev/null 2>&1; then
    echo "✅ Passwordless 'sudo ufw' confirmed."
else
    echo "⚠️  'sudo -n ufw' still asks for a password — check the sudoers file." >&2
fi

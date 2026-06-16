#!/usr/bin/env bash
# Grant the current user passwordless sudo for the few binaries the backend
# runs with elevated privileges, so it can work unattended without a password
# prompt. Run once, on the machine that hosts the backend:
#
#     ./setup-permissions.sh
#
# What gets whitelisted (NOPASSWD), and why:
#   * ufw  - lock the web port down to a single client IP on startup
#            (BW_ALLOW_IP, see firewall.py). Needs root.
#   * git  - run the comparison / `git fetch` (BW_FETCH) against a repo that may
#            be owned by another user, e.g. when the watched repo lives in a
#            teammate's tree. Without this, `sudo git ... fetch` would prompt.
#
# Security note: NOPASSWD git is broad (git can run arbitrary code via hooks /
# -c). It's scoped to this single user on a trusted LAN dev box on purpose; do
# not copy this onto a shared/production host.
#
# Re-run is safe (it overwrites the same file).
set -euo pipefail

USER_NAME="${SUDO_USER:-$USER}"
SUDOERS_FILE="/etc/sudoers.d/branch-watcher"

# Binaries to grant passwordless sudo for. Add more here if the backend grows
# new privileged operations.
BINARIES=(ufw git)

# Resolve each binary to an absolute path (sudoers rules must be absolute),
# falling back to common locations when it isn't on PATH yet.
declare -a RESOLVED=()
for bin in "${BINARIES[@]}"; do
    path="$(command -v "$bin" 2>/dev/null || true)"
    if [[ -z "$path" ]]; then
        for cand in "/usr/sbin/$bin" "/usr/bin/$bin" "/sbin/$bin" "/bin/$bin"; do
            [[ -x "$cand" ]] && path="$cand" && break
        done
    fi
    if [[ -z "$path" ]]; then
        echo "⚠️  '$bin' not found on this machine — skipping its sudo rule." >&2
        continue
    fi
    RESOLVED+=("$path")
done

if [[ ${#RESOLVED[@]} -eq 0 ]]; then
    echo "❌ None of the required binaries were found; nothing to do." >&2
    exit 1
fi

echo "Granting passwordless sudo to '$USER_NAME' for:"
for path in "${RESOLVED[@]}"; do
    echo "  $path"
done

# Build the sudoers content: one NOPASSWD rule per resolved binary.
TMP="$(mktemp)"
{
    echo "# Managed by branch-watcher setup-permissions.sh — do not edit by hand."
    for path in "${RESOLVED[@]}"; do
        echo "$USER_NAME ALL=(root) NOPASSWD: $path"
    done
} > "$TMP"

# Write via a temp file + visudo -c so a typo can never lock you out of sudo.
if sudo visudo -c -f "$TMP" >/dev/null; then
    sudo install -m 0440 -o root -g root "$TMP" "$SUDOERS_FILE"
    rm -f "$TMP"
    echo "✅ Wrote $SUDOERS_FILE"
else
    rm -f "$TMP"
    echo "❌ Generated sudoers rule failed validation; nothing changed." >&2
    exit 1
fi

# Quick check that each one actually works without a password.
for path in "${RESOLVED[@]}"; do
    if sudo -n "$path" --version >/dev/null 2>&1; then
        echo "✅ Passwordless 'sudo $(basename "$path")' confirmed."
    else
        echo "⚠️  'sudo -n $(basename "$path")' still asks for a password — check $SUDOERS_FILE." >&2
    fi
done

#!/usr/bin/env python3
"""Lock a TCP port down to a single machine identified by its MAC address.

Resolves the MAC to its *current* LAN IP (via arp_scan) and rewrites the ufw
rules so only that IP may reach the port; everyone else is denied. Because the
IP is looked up fresh every run, this keeps working even when the client's IP
changes (DHCP) — just call it again (e.g. each time the backend starts).

Needs root for both arp-scan and ufw. Configure passwordless sudo once so it can
run unattended from a backend (see setup-permissions.sh / README).

Usage:
    python firewall.py --port 9534 --mac AA:BB:CC:DD:EE:FF
    sudo python firewall.py --port 9534 --mac AA:BB:CC:DD:EE:FF
"""

import argparse
import os
import re
import subprocess
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# arp_scan is the standalone scanner; firewall is where it gets integrated.
from arp_scan import find_ip_by_mac, normalize_mac
from logging_setup import get_logger

log = get_logger(__name__)

# Prefix used for every privileged call. "sudo -n" fails fast instead of
# hanging on a password prompt when run from a backend without NOPASSWD set up.
SUDO = os.getenv("SUDO_CMD", "sudo -n").split()
BW_ALLOW_MAC = os.getenv("BW_ALLOW_MAC", "")


def _ufw(*args, check=True):
    """Run a ufw subcommand under sudo."""
    return subprocess.run(SUDO + ["ufw", *args], check=check, capture_output=True, text=True)


def _clear_port_rules(port):
    """Delete every existing ufw rule that mentions this port (any source).

    Done by reading 'ufw status numbered' and deleting matching rule numbers in
    descending order so the numbering stays valid as we go.
    """
    out = _ufw("status", "numbered", check=False).stdout
    nums = []
    for line in out.splitlines():
        # e.g. "[ 3] 9534    DENY IN   Anywhere"  /  "[ 4] 9534  ALLOW IN  192.168.1.50"
        m = re.match(r"\[\s*(\d+)\]", line.strip())
        if m and re.search(rf"(^|\D){port}(\D|$)", line):
            nums.append(int(m.group(1)))
    for n in sorted(nums, reverse=True):
        _ufw("--force", "delete", str(n), check=False)


def allow_only(port, mac, interface=None):
    """Allow only the machine with `mac` to reach `port`; deny everyone else.

    Returns the resolved IP. Raises RuntimeError if the MAC can't be found on the
    LAN or a ufw/sudo command fails.
    """
    log.info("allow_only: locking port %s to MAC %s", port, normalize_mac(mac))
    ip = find_ip_by_mac(mac, interface=interface)
    if ip is None:
        log.error(
            "allow_only: MAC %s not found on the LAN — firewall rule not changed",
            normalize_mac(mac),
        )
        raise RuntimeError(
            f"MAC {normalize_mac(mac)} not found on the LAN — firewall rule not changed."
        )

    try:
        _ufw("--force", "enable")          # make sure the firewall is on
        _clear_port_rules(port)            # wipe stale rules for this port
        # Order matters: the specific allow gets a lower rule number than the
        # blanket deny, so ufw matches our IP first.
        _ufw("allow", "from", ip, "to", "any", "port", str(port))
        _ufw("deny", str(port))
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        log.error("allow_only: ufw command failed: %s", detail or exc)
        raise RuntimeError(f"ufw command failed: {detail or exc}")
    log.info("allow_only: port %s now reachable only from %s", port, ip)
    return ip


def main():
    parser = argparse.ArgumentParser(
        description="Lock a port down to a single MAC's current IP via ufw."
    )
    parser.add_argument("--port", type=int, required=True, help="TCP port to protect")
    parser.add_argument(
        "--mac", default=BW_ALLOW_MAC, help="MAC allowed to connect (env: BW_ALLOW_MAC)"
    )
    parser.add_argument(
        "--interface", default=None, help="Network interface for arp-scan (env: ARP_INTERFACE)"
    )
    args = parser.parse_args()

    if not args.mac:
        parser.error("a MAC is required (pass --mac or set BW_ALLOW_MAC)")

    try:
        ip = allow_only(args.port, args.mac, interface=args.interface)
    except (ValueError, RuntimeError) as exc:
        print(f"❌ {exc}")
        sys.exit(1)
    print(f"✅ Port {args.port} now reachable only from {ip} (MAC {normalize_mac(args.mac)}).")


if __name__ == "__main__":
    main()

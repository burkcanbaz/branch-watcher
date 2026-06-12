#!/usr/bin/env python3
"""Lock a TCP port down to a single client IP via ufw.

Rewrites the ufw rules so only the given IP may reach the port; everyone else
is denied.

Needs root for ufw. Configure passwordless sudo once so it can run unattended
from a backend (see setup-permissions.sh / README).

Usage:
    python firewall.py --port 9534 --ip 192.168.1.50
    sudo python firewall.py --port 9534 --ip 192.168.1.50
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

from logging_setup import get_logger

log = get_logger(__name__)

# Prefix used for every privileged call. "sudo -n" fails fast instead of
# hanging on a password prompt when run from a backend without NOPASSWD set up.
SUDO = os.getenv("SUDO_CMD", "sudo -n").split()
BW_ALLOW_IP = os.getenv("BW_ALLOW_IP", "")

_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


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


def allow_ip(port, ip):
    """Allow only `ip` to reach `port`; deny everyone else. Returns the IP.

    Raises ValueError on a malformed IP or RuntimeError if a ufw command fails.
    """
    ip = ip.strip()
    if not _IP_RE.match(ip):
        log.error("allow_ip: invalid IP address: %r", ip)
        raise ValueError(f"Invalid IP address: {ip!r}")

    log.info("allow_ip: locking port %s to IP %s", port, ip)
    try:
        _ufw("--force", "enable")          # make sure the firewall is on
        _clear_port_rules(port)            # wipe stale rules for this port
        # Order matters: the specific allow gets a lower rule number than the
        # blanket deny, so ufw matches our IP first.
        _ufw("allow", "from", ip, "to", "any", "port", str(port))
        _ufw("deny", str(port))
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        log.error("allow_ip: ufw command failed: %s", detail or exc)
        raise RuntimeError(f"ufw command failed: {detail or exc}")
    log.info("allow_ip: port %s now reachable only from %s", port, ip)
    return ip


def main():
    parser = argparse.ArgumentParser(
        description="Lock a port down to a single client IP via ufw."
    )
    parser.add_argument("--port", type=int, required=True, help="TCP port to protect")
    parser.add_argument(
        "--ip", default=BW_ALLOW_IP, help="IP allowed to connect (env: BW_ALLOW_IP)"
    )
    args = parser.parse_args()

    if not args.ip:
        parser.error("an IP is required (pass --ip or set BW_ALLOW_IP)")

    try:
        ip = allow_ip(args.port, args.ip)
    except (ValueError, RuntimeError) as exc:
        print(f"❌ {exc}")
        sys.exit(1)
    print(f"✅ Port {args.port} now reachable only from {ip}.")


if __name__ == "__main__":
    main()

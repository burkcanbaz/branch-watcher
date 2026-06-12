#!/usr/bin/env python3
"""Standalone LAN scanner built on arp-scan.

Self-contained: no dependency on branch_status.py. Drop this file anywhere and
integrate the functions, or run it directly.

Usage:
    python arp_scan.py                          # list every host on the LAN
    python arp_scan.py --mac AA:BB:CC:DD:EE:FF   # print the IP for one MAC
    python arp_scan.py --interface wlan0         # force an interface

Configuration via environment (or a .env file if python-dotenv is installed):
    ARP_SCAN_CMD   command used to scan      (default: "sudo arp-scan --localnet")
    ARP_INTERFACE  force a network interface (default: auto)
    TARGET_MAC     default MAC to resolve    (default: none)
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


# --- configuration ----------------------------------------------------------
ARP_SCAN_CMD = os.getenv("ARP_SCAN_CMD", "sudo arp-scan --localnet")
ARP_INTERFACE = os.getenv("ARP_INTERFACE", "")  # e.g. "eth0" / "wlan0"; empty = auto
TARGET_MAC = os.getenv("TARGET_MAC", "")  # default MAC to look up


_MAC_RE = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")

# arp-scan lines look like:  192.168.1.42<TAB>aa:bb:cc:dd:ee:ff<TAB>Vendor Name
_ARP_LINE_RE = re.compile(
    r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+((?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})\s*(.*)$"
)


def normalize_mac(mac):
    """Lowercase a MAC and accept '-' or '.' separators -> colon form."""
    if not mac:
        return ""
    return mac.strip().lower().replace("-", ":").replace(".", ":")


def arp_scan(interface=None):
    """Run arp-scan over the local network and return a list of hosts.

    Each host is a dict: {"ip": ..., "mac": ..., "vendor": ...}.
    Requires arp-scan installed and (usually) root, hence the default
    'sudo arp-scan --localnet'. Raises RuntimeError on failure.
    """
    cmd = ARP_SCAN_CMD.split()
    iface = interface if interface is not None else ARP_INTERFACE
    if iface:
        cmd += ["--interface", iface]

    log.debug("arp_scan: running %s", " ".join(cmd))
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode(
            errors="replace"
        )
    except FileNotFoundError:
        log.error("arp_scan: arp-scan binary not found on PATH")
        raise RuntimeError(
            "arp-scan not found. Install it (e.g. 'sudo apt install arp-scan')."
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.output.decode(errors="replace").strip()
        log.error("arp_scan: arp-scan failed: %s", detail)
        raise RuntimeError(f"arp-scan failed: {detail}")

    hosts = []
    for line in out.splitlines():
        m = _ARP_LINE_RE.match(line)
        if m:
            hosts.append(
                {
                    "ip": m.group(1),
                    "mac": m.group(2).lower(),
                    "vendor": m.group(3).strip(),
                }
            )
    log.info("arp_scan: found %d host(s) on the LAN", len(hosts))
    return hosts


def find_ip_by_mac(mac, interface=None):
    """Scan the LAN and return the IP belonging to the given MAC address.

    Returns the IP string, or None if the MAC is not present on the network.
    """
    wanted = normalize_mac(mac)
    log.debug("find_ip_by_mac: looking up MAC %s", wanted)
    if not _MAC_RE.match(wanted):
        log.error("find_ip_by_mac: invalid MAC address: %r", mac)
        raise ValueError(f"Invalid MAC address: {mac!r}")
    try:
        hosts = arp_scan(interface=interface)
    except RuntimeError:
        # arp_scan already logged the underlying cause; re-raise for the caller.
        log.error("find_ip_by_mac: scan failed while resolving MAC %s", wanted)
        raise
    for host in hosts:
        if host["mac"] == wanted:
            log.info("find_ip_by_mac: MAC %s -> %s", wanted, host["ip"])
            return host["ip"]
    log.error("find_ip_by_mac: MAC %s not found on the LAN", wanted)
    return None


def main():
    parser = argparse.ArgumentParser(description="Scan the LAN with arp-scan.")
    parser.add_argument(
        "--mac",
        default=TARGET_MAC,
        help="Print the IP for this MAC address (env: TARGET_MAC)",
    )
    parser.add_argument(
        "--interface", default=None, help="Network interface (env: ARP_INTERFACE)"
    )
    args = parser.parse_args()

    try:
        if args.mac:
            ip = find_ip_by_mac(args.mac, interface=args.interface)
            if ip is None:
                print(f"❌ MAC {normalize_mac(args.mac)} not found on the LAN.")
                sys.exit(1)
            print(ip)
        else:
            hosts = arp_scan(interface=args.interface)
            print(f"Found {len(hosts)} host(s):")
            for h in hosts:
                print(f"  {h['ip']:<15}  {h['mac']}  {h['vendor']}")
    except (ValueError, RuntimeError) as exc:
        print(f"❌ {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()

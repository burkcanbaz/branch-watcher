#!/usr/bin/env python3
"""Manage a single branch-watcher entry in the current user's crontab.

The notifier pushes a daily clock time here (see /api/cron in branch_status.py);
we translate it into a real crontab line that runs ``BW_CRON_CMD`` every day at
that minute. Our line is wrapped in marker comments so we can find / replace /
remove *only* our entry idempotently, leaving any other cron jobs untouched.

When disabled we keep the line but prefix it with ``#DISABLED`` so the chosen
time can still be read back (and re-enabled) later.

Default command, overridable with ``BW_CRON_CMD``: run a fetch + status refresh
so that when the notifier polls this machine, the ahead/behind numbers it reads
are already up to date.
"""

import os
import re
import shlex
import subprocess
import sys

from logging_setup import get_logger

log = get_logger(__name__)

BEGIN = "# >>> branch-watcher (managed) >>>"
END = "# <<< branch-watcher (managed) <<<"
DISABLED_PREFIX = "#DISABLED "

# A cron schedule for "every day at H:M": "M H * * *". We only ever write daily
# entries, so the three trailing fields are always "* * *".
_CRON_RE = re.compile(r"^\s*(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*\s+(.*)$")


def default_command():
    """The shell command the managed cron line runs each day."""
    env_cmd = os.getenv("BW_CRON_CMD")
    if env_cmd:
        return env_cmd
    py = sys.executable or "python3"
    app_dir = os.path.dirname(os.path.abspath(__file__))
    # cd into app/ so branch_status.py and .env resolve exactly like a manual run
    return f"cd {shlex.quote(app_dir)} && {shlex.quote(py)} branch_status.py --fetch"


def _run_crontab(args, stdin=None):
    """Run `crontab <args>`, returning (rc, stdout, stderr)."""
    proc = subprocess.run(
        ["crontab", *args],
        input=stdin,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _read_crontab():
    """Current crontab as a list of lines (empty if the user has none)."""
    rc, out, err = _run_crontab(["-l"])
    if rc != 0:
        # "no crontab for <user>" is the normal empty case, not an error.
        if "no crontab" in (err or "").lower():
            return []
        raise RuntimeError(err.strip() or "failed to read crontab")
    return out.splitlines()


def _split_managed(lines):
    """Return (before, managed_block, after) around our marker block."""
    try:
        i = lines.index(BEGIN)
        j = lines.index(END, i + 1)
    except ValueError:
        return lines, [], []
    return lines[:i], lines[i : j + 1], lines[j + 1 :]


def _parse_time(line):
    """Pull 'HH:MM' out of a (possibly #DISABLED-prefixed) cron line."""
    stripped = line[len(DISABLED_PREFIX):] if line.startswith(DISABLED_PREFIX) else line
    m = _CRON_RE.match(stripped)
    if not m:
        return None
    minute, hour = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def read():
    """Read the managed schedule: {time, enabled, command}."""
    _, managed, _ = _split_managed(_read_crontab())
    for line in managed:
        if line in (BEGIN, END):
            continue
        if not line.strip():
            continue
        time = _parse_time(line)
        if time is None:
            continue
        enabled = not line.startswith(DISABLED_PREFIX)
        command = line.split("* * *", 1)[1].strip() if "* * *" in line else ""
        return {"time": time, "enabled": enabled, "command": command}
    return {"time": None, "enabled": False, "command": default_command()}


def apply(time, enabled=True, command=None):
    """Install/replace the managed cron entry for daily 'HH:MM'. Returns read()."""
    hour, minute = (int(p) for p in str(time).strip().split(":", 1))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"time out of range: {time!r}")

    command = command or default_command()
    cron_line = f"{minute} {hour} * * * {command}"
    if not enabled:
        cron_line = DISABLED_PREFIX + cron_line

    before, _, after = _split_managed(_read_crontab())
    block = [BEGIN, cron_line, END]
    # Drop any trailing blank lines from `before` so we don't pile up gaps on
    # repeated edits, then rejoin everything with our block in the middle.
    while before and not before[-1].strip():
        before.pop()
    new_lines = [*before, *block, *after]
    payload = "\n".join(new_lines) + "\n"

    rc, _out, err = _run_crontab(["-"], stdin=payload)
    if rc != 0:
        raise RuntimeError(err.strip() or "failed to write crontab")
    log.info("cron: set daily %s (enabled=%s) -> %s", time, enabled, command)
    return read()


def remove():
    """Remove our managed entry entirely (leaving other cron jobs intact)."""
    before, managed, after = _split_managed(_read_crontab())
    if not managed:
        return read()
    while before and not before[-1].strip():
        before.pop()
    payload = ("\n".join([*before, *after]).strip() + "\n") if (before or after) else ""
    # An empty payload clears the crontab; that's correct if ours was the only job.
    rc, _out, err = _run_crontab(["-"], stdin=payload or "\n")
    if rc != 0:
        raise RuntimeError(err.strip() or "failed to write crontab")
    log.info("cron: removed managed entry")
    return read()


# Small CLI for manual testing: `python cron.py 10:00` / `--off` / `--show`.
if __name__ == "__main__":
    if "--show" in sys.argv or len(sys.argv) == 1:
        print(read())
    elif "--off" in sys.argv:
        print(remove())
    else:
        print(apply(sys.argv[1], enabled="--disabled" not in sys.argv))

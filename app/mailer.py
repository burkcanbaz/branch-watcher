#!/usr/bin/env python3
"""Daily branch-status e-mail.

Compares the watched repo's current branch against the target branch (default
`origin/develop`) and e-mails the result — ahead/behind counts, the commits on
each side and a clear "merge needed / up to date" verdict — to everyone in
BW_MAIL_TO.

Runs as a long-lived process that wakes up once a day at BW_MAIL_TIME in
BW_MAIL_TZ (default 09:15 Europe/Istanbul = UTC+3). No cron, no git hooks: the
container itself keeps the schedule.

Usage:
    python mailer.py                 # daemon: send every day at BW_MAIL_TIME
    python mailer.py --once          # send one mail right now and exit
    python mailer.py --dry-run       # render and print the mail, send nothing
    python mailer.py /path/to/repo --target origin/main

Every SMTP setting comes from the environment (see .env.example) so each person
puts their own credentials in their own .env — nothing is baked into the image.
"""

import argparse
import os
import smtplib
import ssl
import sys
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, formatdate, parseaddr
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from branch_status import DEFAULT_REPO, DEFAULT_TARGET, _env_bool, get_status, is_git_repo
from logging_setup import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration (env-driven; credentials never live in the code or the image)
# ---------------------------------------------------------------------------
SMTP_HOST = os.getenv("BW_SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("BW_SMTP_PORT", "587"))
SMTP_USER = os.getenv("BW_SMTP_USER", "").strip()
SMTP_PASS = os.getenv("BW_SMTP_PASS", "")
# How to secure the connection: starttls (587) / ssl (465) / none (local relay)
SMTP_SECURITY = os.getenv("BW_SMTP_SECURITY", "starttls").strip().lower()
SMTP_TIMEOUT = int(os.getenv("BW_SMTP_TIMEOUT", "30"))

MAIL_FROM = os.getenv("BW_MAIL_FROM", "").strip() or SMTP_USER
MAIL_FROM_NAME = os.getenv("BW_MAIL_FROM_NAME", "Branch Watcher").strip()
MAIL_TO = os.getenv("BW_MAIL_TO", "")
SUBJECT_PREFIX = os.getenv("BW_MAIL_SUBJECT_PREFIX", "[branch-watcher]").strip()

MAIL_TIME = os.getenv("BW_MAIL_TIME", "09:15").strip()
MAIL_TZ = os.getenv("BW_MAIL_TZ", "Europe/Istanbul").strip()

# Refresh the remote refs before comparing, so 'behind' reflects what is really
# on develop this morning and not whatever the last local fetch happened to see.
MAIL_FETCH = _env_bool("BW_MAIL_FETCH", True)
# Send one mail immediately on startup too — handy to verify the setup.
MAIL_ON_START = _env_bool("BW_MAIL_ON_START", False)
# Only mail when the branch is actually behind (i.e. a merge is needed).
ONLY_WHEN_BEHIND = _env_bool("BW_MAIL_ONLY_WHEN_BEHIND", False)

SEND_RETRIES = int(os.getenv("BW_MAIL_RETRIES", "3"))
RETRY_DELAY = int(os.getenv("BW_MAIL_RETRY_DELAY", "30"))

# Longest single sleep in the scheduler loop. Short naps (instead of one big
# one) keep 'docker stop' responsive and let the loop notice clock jumps.
_SLEEP_SLICE = 300


def recipients(raw=None):
    """Parse BW_MAIL_TO into a list. Commas, semicolons or whitespace."""
    raw = MAIL_TO if raw is None else raw
    for sep in (";", "\n", "\t"):
        raw = raw.replace(sep, ",")
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


def _timezone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        log.error("Unknown timezone %r — falling back to UTC", name)
        return ZoneInfo("UTC")


def _parse_hhmm(value):
    """'09:15' -> (9, 15). Raises ValueError on anything else."""
    hh, _, mm = value.partition(":")
    hour, minute = int(hh), int(mm)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"time out of range: {value}")
    return hour, minute


# ---------------------------------------------------------------------------
# Status -> mail content
# ---------------------------------------------------------------------------
def collect_status(repo, target, do_fetch):
    """Get the branch status, degrading gracefully when the fetch fails.

    A daily unattended job must still deliver *something* when the network or
    the credentials are unavailable, so a failed fetch falls back to the refs
    already in .git and the mail says the data may be stale.
    """
    status = get_status(repo, target, do_fetch=do_fetch)
    if do_fetch and status.get("error", "").startswith("git fetch failed"):
        log.warning("Fetch failed, reporting on the local refs instead: %s", status["error"])
        stale_reason = status["error"]
        status = get_status(repo, target, do_fetch=False)
        status["stale"] = stale_reason
    return status


def verdict(status):
    """One-line answer to 'do I need to merge?'."""
    if status.get("error"):
        return "error"
    if status["behind"] > 0:
        return "merge-needed"
    return "up-to-date"


def build_subject(status):
    branch = status.get("current_branch") or "?"
    target = status.get("target_branch") or DEFAULT_TARGET
    state = verdict(status)
    if state == "error":
        parts = f"⚠️ could not read branch status ({branch})"
    elif state == "merge-needed":
        parts = (
            f"⚠️ {branch}: {status['behind']} commit(s) behind {target} — merge needed"
        )
    else:
        ahead = status["ahead"]
        extra = f", {ahead} local commit(s) to push" if ahead else ""
        parts = f"✅ {branch}: up to date with {target}{extra}"
    return f"{SUBJECT_PREFIX} {parts}".strip()


def render(status, now_text, tz_name):
    """Render the (html, text) bodies for the mail."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    templates = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    env = Environment(
        loader=FileSystemLoader(templates), autoescape=select_autoescape(["html"])
    )
    context = {
        "s": status,
        "verdict": verdict(status),
        "now": now_text,
        "tz": tz_name,
        "host": os.getenv("HOSTNAME", ""),
    }
    html = env.get_template("email.html").render(**context)
    return html, render_text(status, now_text, tz_name)


def render_text(status, now_text, tz_name):
    """Plain-text alternative, for clients that don't render HTML."""
    lines = []
    if status.get("error"):
        lines.append(f"ERROR: {status['error']}")
        if status.get("current_branch"):
            lines.append(f"current branch: {status['current_branch']}")
        lines.append("")
        lines.append(f"{now_text} ({tz_name})")
        return "\n".join(lines)

    lines += [
        f"Repo:    {status['repo']}",
        f"Branch:  {status['current_branch']}",
        f"Target:  {status['target_branch']}",
        f"Ahead:   {status['ahead']}   Behind: {status['behind']}",
        "",
    ]
    if status.get("stale"):
        lines += [f"! Remote refs may be stale: {status['stale']}", ""]
    if status["behind"] > 0:
        lines.append(
            f"MERGE NEEDED — behind {status['target_branch']} by "
            f"{status['behind']} commit(s). Merge or rebase before opening a PR."
        )
    else:
        lines.append(f"Up to date with {status['target_branch']}.")

    for title, key in (
        (f"Incoming commits from {status['target_branch']}", "incoming_commits"),
        (f"Local commits ahead of {status['target_branch']}", "local_commits"),
    ):
        commits = status[key]
        lines += ["", f"{title} ({len(commits)})"]
        if not commits:
            lines.append("  -")
        for c in commits:
            lines.append(f"  {c['date']}  {c['hash']}  {c['author']}: {c['message']}")

    lines += ["", f"{now_text} ({tz_name})"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SMTP
# ---------------------------------------------------------------------------
def check_config(to_addrs):
    """Fail fast on a broken setup instead of at 09:15 tomorrow."""
    problems = []
    if not SMTP_HOST:
        problems.append("BW_SMTP_HOST is empty")
    if not to_addrs:
        problems.append("BW_MAIL_TO is empty (nobody to send to)")
    if not MAIL_FROM:
        problems.append("BW_MAIL_FROM (or BW_SMTP_USER) is empty")
    if SMTP_SECURITY not in {"starttls", "ssl", "none"}:
        problems.append(f"BW_SMTP_SECURITY must be starttls/ssl/none, got {SMTP_SECURITY!r}")
    for addr in [MAIL_FROM, *to_addrs]:
        if addr and "@" not in parseaddr(addr)[1]:
            problems.append(f"not a valid e-mail address: {addr}")
    return problems


def build_message(subject, html, text, to_addrs):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((MAIL_FROM_NAME, MAIL_FROM)) if MAIL_FROM_NAME else MAIL_FROM
    msg["To"] = ", ".join(to_addrs)
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send(msg, to_addrs):
    """Deliver the message over SMTP. Raises on final failure."""
    context = ssl.create_default_context()
    log.info(
        "SMTP %s:%s (%s) -> %s", SMTP_HOST, SMTP_PORT, SMTP_SECURITY, ", ".join(to_addrs)
    )
    if SMTP_SECURITY == "ssl":
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT, context=context)
    else:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT)
    with server:
        server.ehlo()
        if SMTP_SECURITY == "starttls":
            server.starttls(context=context)
            server.ehlo()
        # An unauthenticated local relay is a valid setup, so only log in when
        # a user is configured.
        if SMTP_USER:
            server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg, from_addr=MAIL_FROM, to_addrs=to_addrs)


def send_with_retries(msg, to_addrs):
    """Send, retrying a few times — a daily job shouldn't lose a whole day to
    one flaky connection."""
    last = None
    for attempt in range(1, max(SEND_RETRIES, 1) + 1):
        try:
            send(msg, to_addrs)
            log.info("Mail sent to %s", ", ".join(to_addrs))
            return True
        except Exception as exc:  # smtplib raises a wide family of errors
            last = exc
            log.error("Send attempt %d/%d failed: %s", attempt, SEND_RETRIES, exc)
            if attempt < SEND_RETRIES:
                time.sleep(RETRY_DELAY)
    log.error("Giving up on this run: %s", last)
    return False


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------
def run_once(repo, target, tz, do_fetch=None, dry_run=False, to_addrs=None):
    """Build and send today's mail.

    Returns "sent", "skipped" (nothing to report / dry run) or "failed".
    """
    do_fetch = MAIL_FETCH if do_fetch is None else do_fetch
    to_addrs = recipients() if to_addrs is None else to_addrs

    status = collect_status(repo, target, do_fetch)
    state = verdict(status)
    log.info("Status: %s (ahead %s, behind %s)",
             state, status.get("ahead"), status.get("behind"))

    if ONLY_WHEN_BEHIND and state == "up-to-date":
        log.info("BW_MAIL_ONLY_WHEN_BEHIND is on and nothing to merge — no mail sent.")
        return "skipped"

    now_text = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    subject = build_subject(status)
    html, text = render(status, now_text, str(tz))

    if dry_run:
        print(f"--- To: {', '.join(to_addrs) or '(nobody)'}")
        print(f"--- Subject: {subject}\n")
        print(text)
        return "skipped"

    msg = build_message(subject, html, text, to_addrs)
    return "sent" if send_with_retries(msg, to_addrs) else "failed"


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
def next_run_at(now, hour, minute):
    """The next occurrence of hour:minute strictly after `now`, same tz."""
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def run_daemon(repo, target, tz, hour, minute, dry_run=False):
    to_addrs = recipients()
    log.info(
        "Daily mail scheduled for %02d:%02d %s -> %s",
        hour, minute, tz, ", ".join(to_addrs),
    )
    print(f"⏰ Daily branch report at {hour:02d}:{minute:02d} ({tz}) → {', '.join(to_addrs)}")

    if MAIL_ON_START:
        log.info("BW_MAIL_ON_START is on — sending a mail now.")
        run_once(repo, target, tz, dry_run=dry_run, to_addrs=to_addrs)

    while True:
        now = datetime.now(tz)
        due = next_run_at(now, hour, minute)
        log.info("Next mail at %s", due.strftime("%Y-%m-%d %H:%M %Z"))
        # Nap in slices and re-check the clock, so a suspended host or a time
        # change can't make us oversleep the slot by hours.
        while True:
            remaining = (due - datetime.now(tz)).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(remaining, _SLEEP_SLICE))
        try:
            run_once(repo, target, tz, dry_run=dry_run, to_addrs=to_addrs)
        except Exception as exc:
            # Never let one bad morning kill the scheduler.
            log.exception("Run failed: %s", exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="E-mail a daily branch-vs-target report."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=DEFAULT_REPO or None,
        help="Path to the git working tree (env: BW_REPO)",
    )
    parser.add_argument(
        "--target", default=DEFAULT_TARGET, help=f"Target branch (default: {DEFAULT_TARGET})"
    )
    parser.add_argument(
        "--once", action="store_true", help="Send one mail now and exit (no scheduling)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the report instead of sending it"
    )
    parser.add_argument(
        "--time", default=MAIL_TIME, help=f"Daily send time HH:MM (default: {MAIL_TIME})"
    )
    parser.add_argument(
        "--tz", default=MAIL_TZ, help=f"Timezone for --time (default: {MAIL_TZ})"
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip 'git fetch' before comparing (env: BW_MAIL_FETCH)",
    )
    args = parser.parse_args()

    if not args.path:
        parser.error("a repo path is required (pass one or set BW_REPO)")

    repo = os.path.abspath(os.path.expanduser(args.path))
    if not is_git_repo(repo):
        print(f"❌ No git repository found at: {repo}")
        sys.exit(1)

    try:
        hour, minute = _parse_hhmm(args.time)
    except ValueError as exc:
        parser.error(f"--time must look like 09:15 ({exc})")

    tz = _timezone(args.tz)
    do_fetch = False if args.no_fetch else None

    if not args.dry_run:
        # Nothing configured at all + daemon mode = someone who only wants the
        # web UI. Idle quietly instead of crash-looping against `restart:
        # unless-stopped` and filling their logs.
        if not SMTP_HOST and not recipients() and not args.once:
            msg = (
                "Daily mail is not configured (BW_SMTP_HOST and BW_MAIL_TO are "
                "empty) — idling. Fill them in .env and restart to enable it."
            )
            log.warning(msg)
            print(f"💤 {msg}")
            while True:
                time.sleep(3600)

        problems = check_config(recipients())
        if problems:
            print("❌ Mail configuration is incomplete:", file=sys.stderr)
            for p in problems:
                print(f"   - {p}", file=sys.stderr)
            print("   Fill these in your .env (see .env.example).", file=sys.stderr)
            sys.exit(2)

    if args.once or args.dry_run:
        result = run_once(repo, args.target, tz, do_fetch=do_fetch, dry_run=args.dry_run)
        sys.exit(1 if result == "failed" else 0)

    run_daemon(repo, args.target, tz, hour, minute)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Branch status watcher (Flask app).

Driven entirely by .env (see .env.example). For the repo at BW_REPO it:
  * reads the current branch from .git/HEAD
  * compares it against BW_TARGET (e.g. origin/develop)
  * reports how many commits the local branch is ahead / behind
  * lists local commits (target..HEAD) and incoming commits (HEAD..target)

Run it as a Flask app:
    python branch_status.py          # uses BW_HOST / BW_PORT
    flask --app branch_status run
"""

import os
import socket
import subprocess
from datetime import datetime

from flask import Flask, jsonify, render_template

# Optional: load a local .env so the same app can be reconfigured on another
# machine just by editing values, without touching the code.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from logging_setup import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration (env-driven so the app is portable across machines)
# ---------------------------------------------------------------------------
def _env_bool(name, default=False):
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


REPO = os.path.abspath(os.path.expanduser(os.getenv("BW_REPO", "")))
TARGET = os.getenv("BW_TARGET", "origin/develop")
HOST = os.getenv("BW_HOST", "0.0.0.0")
PORT = int(os.getenv("BW_PORT", "9534"))
REFRESH = int(os.getenv("BW_REFRESH", "30"))
FETCH = _env_bool("BW_FETCH", False)

# If set, the backend locks its port down to this single client IP on startup
# (via ufw): only this IP may reach the port, everyone else is denied. Empty =
# open to the whole LAN. See firewall.py.
ALLOW_IP = os.getenv("BW_ALLOW_IP", "")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
def resolve_git_dir(repo):
    """Return the real .git directory, handling the '.git file' indirection
    used by worktrees and submodules."""
    git_path = os.path.join(repo, ".git")
    if os.path.isdir(git_path):
        return git_path
    if os.path.isfile(git_path):
        with open(git_path, "r", encoding="utf-8") as fh:
            content = fh.read().strip()
        if content.startswith("gitdir:"):
            target = content.split("gitdir:", 1)[1].strip()
            return target if os.path.isabs(target) else os.path.join(repo, target)
    return None


def is_git_repo(repo):
    return resolve_git_dir(repo) is not None


def git(repo, *args):
    return (
        subprocess.check_output(["git", *args], cwd=repo, stderr=subprocess.STDOUT)
        .decode()
        .strip()
    )


def get_current_branch(repo):
    """Return the current branch name, asking git itself (portable across
    machines, worktrees and packed/loose ref layouts)."""
    try:
        branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    except subprocess.CalledProcessError:
        return None
    if branch == "HEAD":
        # detached HEAD: report the short commit instead of the literal "HEAD"
        try:
            return f"(detached @ {git(repo, 'rev-parse', '--short', 'HEAD')})"
        except subprocess.CalledProcessError:
            return None
    return branch


def resolve_ref(repo, ref):
    """Resolve a ref (e.g. 'origin/develop') to its commit SHA using git, so we
    handle every namespace/packed/worktree case git itself handles. Returns the
    SHA, or None if the ref cannot be found."""
    try:
        return git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except subprocess.CalledProcessError:
        return None


def parse_commits(output):
    commits = []
    if output:
        for line in output.split("\n"):
            parts = line.split("|")
            if len(parts) == 4:
                commits.append(
                    {
                        "hash": parts[0],
                        "author": parts[1],
                        "date": parts[2],
                        "message": parts[3],
                    }
                )
    return commits


def commit_log(repo, rev_range):
    out = git(
        repo,
        "log",
        rev_range,
        "--pretty=format:%h|%an|%ad|%s",
        "--date=format-local:%Y-%m-%d %H:%M",
    )
    return parse_commits(out)


def get_status(repo, target, do_fetch=False):
    """Build the full status dict for a repo."""
    log.debug("get_status: repo=%s target=%s fetch=%s", repo, target, do_fetch)
    if not repo:
        log.error("get_status: BW_REPO is not set")
        return {"error": "BW_REPO is not set — point it at a git repo in .env"}
    if not is_git_repo(repo):
        log.error("get_status: no git repository found at %s", repo)
        return {"error": f"No git repository found at: {repo}"}

    # Probe with a plain git call: if this fails it's a real git problem
    # (e.g. "dubious ownership" on a teammate's box, or a corrupt repo) and we
    # surface it instead of later misreporting it as "branch not found".
    try:
        git(repo, "rev-parse", "--git-dir")
    except subprocess.CalledProcessError as exc:
        detail = exc.output.decode(errors="replace").strip()
        log.error("get_status: git unusable in %s: %s", repo, detail)
        return {"error": f"git error: {detail}"}

    current_branch = get_current_branch(repo)

    if do_fetch:
        # 'origin/develop' -> remote 'origin'
        remote = target.split("/", 1)[0] if "/" in target else "origin"
        try:
            git(repo, "fetch", "--quiet", remote)
        except subprocess.CalledProcessError as exc:
            detail = exc.output.decode(errors="replace").strip()
            log.error("get_status: git fetch failed: %s", detail)
            return {
                "error": f"git fetch failed: {detail}",
                "current_branch": current_branch,
            }

    # Make sure the target ref actually exists (git resolves any namespace).
    if resolve_ref(repo, target) is None:
        log.error("get_status: target branch %r not found", target)
        return {
            "error": f"Target branch '{target}' not found (set BW_FETCH=true).",
            "current_branch": current_branch,
        }

    try:
        ahead = int(git(repo, "rev-list", "--count", f"{target}..HEAD"))
        behind = int(git(repo, "rev-list", "--count", f"HEAD..{target}"))
    except subprocess.CalledProcessError as exc:
        detail = exc.output.decode(errors="replace").strip()
        log.error("get_status: rev-list failed: %s", detail)
        return {
            "error": f"git rev-list failed: {detail}",
            "current_branch": current_branch,
        }

    log.info(
        "get_status: %s vs %s -> ahead %d, behind %d",
        current_branch, target, ahead, behind,
    )
    return {
        "repo": repo,
        "current_branch": current_branch,
        "target_branch": target,
        "ahead": ahead,
        "behind": behind,
        "local_commits": commit_log(repo, f"{target}..HEAD"),
        "incoming_commits": commit_log(repo, f"HEAD..{target}"),
    }


def lan_ip():
    """Best-effort primary LAN IP for display."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)


@app.route("/")
def index():
    status = get_status(REPO, TARGET, do_fetch=FETCH)
    return render_template(
        "status.html",
        s=status,
        refresh=REFRESH,
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


@app.route("/api")
def api():
    return jsonify(get_status(REPO, TARGET, do_fetch=FETCH))


# Optionally lock the port down to a single client IP on startup: only
# BW_ALLOW_IP may reach it, everyone else is denied (via ufw).
if ALLOW_IP:
    from firewall import allow_ip

    try:
        allow_ip(PORT, ALLOW_IP)
        log.info("Firewall: only %s may reach port %s", ALLOW_IP, PORT)
    except Exception as exc:
        log.error("Firewall setup skipped: %s", exc)


if __name__ == "__main__":
    ip = lan_ip()
    log.info("Serving branch status for %s on %s:%s", REPO, HOST, PORT)
    print(f"Serving branch status for: {REPO}")
    print(f"  local:   http://127.0.0.1:{PORT}")
    print(f"  network: http://{ip}:{PORT}    (open this from another device)")
    print(f"  json:    http://{ip}:{PORT}/api")
    app.run(host=HOST, port=PORT, debug=False)

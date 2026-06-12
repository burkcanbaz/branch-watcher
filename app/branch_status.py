#!/usr/bin/env python3
"""Branch status watcher.

Given a path to a git working tree it:
  * reads the current branch from .git/HEAD
  * compares the current branch against a target branch (default origin/develop)
  * reports how many commits the local branch is ahead / behind
  * lists local commits (target..HEAD) and incoming commits (HEAD..target)

Usage:
    python branch_status.py /path/to/repo
    python branch_status.py /path/to/repo --target origin/main
    python branch_status.py /path/to/repo --fetch        # refresh remote first
    python branch_status.py /path/to/repo --serve        # web UI on the LAN

All defaults can be overridden with environment variables (see .env.example).
"""

import argparse
import os
import socket
import subprocess
import sys

# Optional: load a local .env so the same script can be reconfigured on another
# machine just by editing values, without touching the code.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from logging_setup import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration (env-driven so the script is portable across machines)
# ---------------------------------------------------------------------------
def _env_bool(name, default=False):
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


# Static defaults pulled out into the environment. Override any of these in a
# .env file or the shell environment when running on a different PC/network.
DEFAULT_REPO = os.getenv("BW_REPO", "")
DEFAULT_TARGET = os.getenv("BW_TARGET", "origin/develop")
DEFAULT_HOST = os.getenv("BW_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.getenv("BW_PORT", "9534"))
DEFAULT_REFRESH = int(os.getenv("BW_REFRESH", "30"))
DEFAULT_FETCH = _env_bool("BW_FETCH", False)
DEFAULT_SERVE = _env_bool("BW_SERVE", False)

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


def get_current_branch(repo):
    """Read the current branch name straight from .git/HEAD."""
    git_dir = resolve_git_dir(repo)
    if not git_dir:
        return None
    head_path = os.path.join(git_dir, "HEAD")
    try:
        with open(head_path, "r", encoding="utf-8") as fh:
            head = fh.read().strip()
    except OSError:
        return None
    if head.startswith("ref:"):
        ref = head.split("ref:", 1)[1].strip()
        # refs/heads/feature/x -> feature/x
        return ref.replace("refs/heads/", "", 1)
    # detached HEAD: HEAD holds a raw commit hash
    return f"(detached @ {head[:8]})"


def _read_packed_ref(git_dir, full_ref):
    """Look up a fully-qualified ref in .git/packed-refs. Returns SHA or None."""
    packed = os.path.join(git_dir, "packed-refs")
    try:
        with open(packed, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                # skip comments ('# pack-refs ...') and peeled-tag lines ('^<sha>')
                if not line or line.startswith("#") or line.startswith("^"):
                    continue
                sha, _, name = line.partition(" ")
                if name == full_ref:
                    return sha
    except OSError:
        pass
    return None


def resolve_ref(repo, ref):
    """Resolve a ref (e.g. 'origin/develop') to its commit SHA straight from
    .git, with no git subprocess.

    Tries the common ref namespaces in git's usual precedence and, for each,
    reads the loose ref file first then falls back to .git/packed-refs.
    Returns the 40-char SHA, or None if the ref cannot be found.
    """
    git_dir = resolve_git_dir(repo)
    if not git_dir:
        return None

    # Candidate fully-qualified names, in roughly git's disambiguation order.
    if ref.startswith("refs/"):
        candidates = [ref]
    else:
        candidates = [
            f"refs/heads/{ref}",
            f"refs/tags/{ref}",
            f"refs/remotes/{ref}",       # e.g. origin/develop
            f"refs/remotes/{ref}/HEAD",  # e.g. origin -> origin/HEAD
        ]

    for full_ref in candidates:
        # 1) loose ref: a file under .git/ holding the SHA
        loose = os.path.join(git_dir, *full_ref.split("/"))
        try:
            with open(loose, "r", encoding="utf-8") as fh:
                content = fh.read().strip()
            # a loose ref may itself be a symbolic 'ref: refs/...' pointer
            if content.startswith("ref:"):
                return resolve_ref(repo, content.split("ref:", 1)[1].strip())
            if content:
                return content
        except OSError:
            pass
        # 2) fall back to packed-refs
        sha = _read_packed_ref(git_dir, full_ref)
        if sha:
            return sha
    return None


def git(repo, *args):
    return (
        subprocess.check_output(["git", *args], cwd=repo, stderr=subprocess.STDOUT)
        .decode()
        .strip()
    )


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
    if not is_git_repo(repo):
        log.error("get_status: no git repository found at %s", repo)
        return {"error": f"No git repository found at: {repo}"}

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

    # Make sure the target ref actually exists. Read it straight from .git
    # (loose ref, falling back to packed-refs) — no subprocess needed.
    if resolve_ref(repo, target) is None:
        log.error("get_status: target branch %r not found", target)
        return {
            "error": f"Target branch '{target}' not found (try --fetch).",
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


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------
def _print_commits(title, commits):
    print(f"\n{title} ({len(commits)})")
    if not commits:
        print("  —")
        return
    for i, c in enumerate(reversed(commits), 0):
        n = len(commits) - i
        print(f"  {n:>3}. {c['date']}  {c['hash']}  {c['author']}: {c['message']}")


def print_status(status):
    if "error" in status:
        print(f"❌ {status['error']}")
        if status.get("current_branch"):
            print(f"   current branch: {status['current_branch']}")
        return

    print("=" * 70)
    print(f"Repo:    {status['repo']}")
    print(f"Branch:  {status['current_branch']}")
    print(f"Target:  {status['target_branch']}")
    print(f"Ahead:   {status['ahead']}   Behind: {status['behind']}")

    if status["behind"] > 0:
        print(
            f"\n⚠️  Behind {status['target_branch']} by {status['behind']} commit(s)."
            " Merge/rebase before opening a PR."
        )
    else:
        print(f"\n✅ Up to date with {status['target_branch']}.")

    _print_commits(
        f"📤 Local commits ({status['current_branch']} ahead of {status['target_branch']})",
        status["local_commits"],
    )
    _print_commits(
        f"📥 Incoming commits from {status['target_branch']}",
        status["incoming_commits"],
    )
    print("=" * 70)


# ---------------------------------------------------------------------------
# Web server (so the box can be watched from the LAN)
# ---------------------------------------------------------------------------
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


def serve(repo, target, host, port, refresh, do_fetch):
    from datetime import datetime

    from flask import Flask, jsonify, render_template

    app = Flask(__name__)

    @app.route("/")
    def index():
        status = get_status(repo, target, do_fetch=do_fetch)
        return render_template(
            "status.html",
            s=status,
            refresh=refresh,
            now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    @app.route("/api")
    def api():
        return jsonify(get_status(repo, target, do_fetch=do_fetch))

    # Optionally lock the port down to a single client IP on startup: only
    # BW_ALLOW_IP may reach it, everyone else is denied (via ufw).
    if ALLOW_IP:
        from firewall import allow_ip

        try:
            allow_ip(port, ALLOW_IP)
            log.info("Firewall: only %s may reach port %s", ALLOW_IP, port)
            print(f"🔒 Firewall: only {ALLOW_IP} may reach port {port}.")
        except Exception as exc:
            log.error("Firewall setup skipped: %s", exc)
            print(f"⚠️  Firewall setup skipped: {exc}")

    ip = lan_ip()
    print(f"Serving branch status for: {repo}")
    print(f"  local:   http://127.0.0.1:{port}")
    print(f"  network: http://{ip}:{port}    (open this from another device)")
    print(f"  json:    http://{ip}:{port}/api")
    app.run(host=host, port=port, debug=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Compare a git branch against a target.")
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
        "--fetch",
        action="store_true",
        default=DEFAULT_FETCH,
        help="Run 'git fetch' before comparing (env: BW_FETCH)",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        default=DEFAULT_SERVE,
        help="Run the web UI (env: BW_SERVE)",
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST, help=f"Serve host (default: {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"Serve port (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--refresh",
        type=int,
        default=DEFAULT_REFRESH,
        help=f"Web auto-refresh seconds (default: {DEFAULT_REFRESH})",
    )
    args = parser.parse_args()

    if not args.path:
        parser.error("a repo path is required (pass one or set BW_REPO)")

    repo = os.path.abspath(os.path.expanduser(args.path))

    if not is_git_repo(repo):
        print(f"❌ No git repository found at: {repo}")
        sys.exit(1)

    if args.serve:
        serve(repo, args.target, args.host, args.port, args.refresh, args.fetch)
    else:
        print_status(get_status(repo, args.target, do_fetch=args.fetch))


if __name__ == "__main__":
    main()

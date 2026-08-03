#!/usr/bin/env bash
# Build and run the whole branch-watcher stack in Docker.
#
#   ./start.sh              # build (if needed) and run in the foreground
#   ./start.sh -d           # run detached, in the background
#   ./start.sh down         # stop and remove the stack
#   ./start.sh test-mail    # send one report right now (verify SMTP settings)
#   ./start.sh preview-mail # print the report to the terminal, send nothing
#
# Any extra arguments are passed straight through to `docker compose`.
set -euo pipefail

# Always operate relative to this script's location, wherever it's called from.
cd "$(dirname "$0")"
ROOT_DIR="$(pwd)"

COMPOSE_FILE="docker/docker-compose.yml"

# Force the compose project directory to the repo root so it loads the root
# .env for ${BW_REPO} substitution (otherwise compose treats docker/ as the
# project dir and won't see it) and resolves relative volume paths from here.
PROJECT_DIR=(--project-directory "$ROOT_DIR")

# Prefer the v2 plugin (`docker compose`); fall back to the legacy binary.
if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    echo "❌ Neither 'docker compose' nor 'docker-compose' is available." >&2
    exit 1
fi

# A .env at the project root holds user config (BW_REPO_HOST, BW_PORT, ...).
if [[ ! -f .env ]]; then
    echo "⚠️  No .env found — copying .env.example. Edit it, then re-run." >&2
    cp .env.example .env
fi

# `down` (and other compose subcommands) pass through; default action is `up`.
case "${1:-}" in
    down|stop|logs|ps|restart|build|pull|config|run|exec|kill)
        exec "${COMPOSE[@]}" "${PROJECT_DIR[@]}" -f "$COMPOSE_FILE" "$@"
        ;;
    test-mail|preview-mail)
        # One-off run of the mailer, outside the daily schedule. Useful right
        # after filling in the SMTP settings: test-mail actually delivers,
        # preview-mail only renders the report to stdout.
        # Note: a bare `[[ ... ]] && ...` would abort the script under `set -e`
        # whenever the test is false, so use a real if.
        if [[ "$1" == preview-mail ]]; then
            MODE="--dry-run"
        else
            MODE="--once"
        fi
        shift
        "${COMPOSE[@]}" "${PROJECT_DIR[@]}" -f "$COMPOSE_FILE" build mailer
        exec "${COMPOSE[@]}" "${PROJECT_DIR[@]}" -f "$COMPOSE_FILE" \
            run --rm mailer python mailer.py "$MODE" "$@"
        ;;
    *)
        exec "${COMPOSE[@]}" "${PROJECT_DIR[@]}" -f "$COMPOSE_FILE" up --build "$@"
        ;;
esac

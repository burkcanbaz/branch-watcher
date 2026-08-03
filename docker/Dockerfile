# Branch Watcher container image.
#
# Serves the web UI (branch_status.py --serve) or runs the daily mailer
# (mailer.py), always as a non-root `app` user. Nothing in here needs root.
FROM python:3.12-slim

# Runtime deps:
#   git            - branch comparisons / the fetch that keeps origin/develop fresh
#   openssh-client - git needs it for `git@github.com:...` remotes. --no-install-
#                    recommends means git does NOT pull it in by itself, and
#                    without it every fetch dies with "cannot run ssh".
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Non-root user the app actually runs as.
RUN useradd --create-home --shell /bin/bash app

WORKDIR /app

# Install Python deps first so the layer is cached across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code (branch_status.py, mailer.py, logging_setup.py, templates/).
COPY app/ ./

# Logs dir owned by the app user (a named volume in compose preserves this
# ownership so the non-root process can write to it).
RUN mkdir -p /app/logs && chown -R app:app /app

USER app

# The watched repo is bind-mounted from the host, so its files belong to the
# host user's UID, not to `app`. Without this git refuses to touch it with
# "detected dubious ownership in repository at '/repo'" — which would break
# every comparison on any machine whose UID isn't 1000.
RUN git config --global --add safe.directory '*'

# Unbuffered stdout so 'docker compose logs -f' shows progress live rather than
# in 8KB bursts (matters for a process that mostly sits idle until 09:15).
ENV PYTHONUNBUFFERED=1

# Default web UI port (override with BW_PORT).
EXPOSE 9534

CMD ["python", "branch_status.py", "--serve"]

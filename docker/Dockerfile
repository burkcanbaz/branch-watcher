# Branch Watcher container image.
#
# Runs the web UI by default as ROOT. The watched git repo is bind-mounted from
# the host and is owned by the host user; running as root means git can both
# read it and (for BW_FETCH) write into it regardless of host ownership, and the
# port-locking firewall (ufw) needs root anyway. This is a trusted LAN dev tool,
# so root in the container is an acceptable trade for "it just works" on every
# teammate's machine.
FROM python:3.12-slim

# Runtime deps:
#   git            - branch comparisons / optional fetch
#   openssh-client - so `git fetch` over SSH remotes works (needs the host's
#                    keys/agent mounted in; see compose). Without it git errors
#                    with "cannot run ssh".
#   ufw            - lock the port down to a single client IP (needs root)
#   iproute2       - networking utilities ufw leans on
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        openssh-client \
        ufw \
        iproute2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so the layer is cached across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code (arp_scan.py, branch_status.py, firewall.py,
# logging_setup.py and templates/).
COPY app/ ./

RUN mkdir -p /app/logs

# The repo bind-mounted at /repo is owned by the HOST user, not by whoever runs
# git inside the container (root included — git still flags a foreign-owned repo
# as "dubious ownership"). Mark it safe system-wide so git works regardless.
RUN git config --system --add safe.directory /repo \
    && git config --system --add safe.directory '*'

# Default web UI port (override with BW_PORT).
EXPOSE 9534

CMD ["python", "branch_status.py"]

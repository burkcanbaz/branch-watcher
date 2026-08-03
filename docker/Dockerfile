# Branch Watcher container image.
#
# Runs the web UI by default (branch_status.py --serve) as a non-root `app`
# user. The optional MAC-locking firewall feature needs arp-scan + ufw, which
# require root — so instead of running the whole app as root, the app user is
# granted passwordless sudo for ONLY those two binaries (see the sudoers rule
# below).
FROM python:3.12-slim

# Runtime deps:
#   git       - branch comparisons / optional fetch
#   arp-scan  - resolve a MAC to its current LAN IP   (needs root)
#   ufw       - lock the port down to a single client (needs root)
#   iproute2  - networking utilities arp-scan/ufw lean on
#   sudo      - so the non-root app user can run just arp-scan/ufw as root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        arp-scan \
        ufw \
        iproute2 \
        sudo \
    && rm -rf /var/lib/apt/lists/*

# Non-root user the app actually runs as.
RUN useradd --create-home --shell /bin/bash app

# Grant the app user passwordless sudo for ONLY arp-scan and ufw, so the
# optional firewall feature works without running everything as root.
RUN echo 'app ALL=(root) NOPASSWD: /usr/sbin/arp-scan, /usr/sbin/ufw' \
        > /etc/sudoers.d/branch-watcher \
    && chmod 0440 /etc/sudoers.d/branch-watcher

WORKDIR /app

# Install Python deps first so the layer is cached across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code (arp_scan.py, branch_status.py, firewall.py, mailer.py,
# logging_setup.py and templates/).
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

# Branch Watcher container image.
#
# Runs the web UI by default (branch_status.py --serve) as a non-root `app`
# user. The optional port-locking firewall feature needs ufw, which requires
# root — so instead of running the whole app as root, the app user is granted
# passwordless sudo for ONLY ufw (see the sudoers rule below).
FROM python:3.12-slim

# Runtime deps:
#   git       - branch comparisons / optional fetch
#   ufw       - lock the port down to a single client IP (needs root)
#   iproute2  - networking utilities ufw leans on
#   sudo      - so the non-root app user can run just ufw as root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        ufw \
        iproute2 \
        sudo \
    && rm -rf /var/lib/apt/lists/*

# Non-root user the app actually runs as.
RUN useradd --create-home --shell /bin/bash app

# Grant the app user passwordless sudo for ONLY ufw, so the firewall feature
# works without running everything as root.
RUN echo 'app ALL=(root) NOPASSWD: /usr/sbin/ufw' \
        > /etc/sudoers.d/branch-watcher \
    && chmod 0440 /etc/sudoers.d/branch-watcher

WORKDIR /app

# Install Python deps first so the layer is cached across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code (arp_scan.py, branch_status.py, firewall.py,
# logging_setup.py and templates/).
COPY app/ ./

# Logs dir owned by the app user (a named volume in compose preserves this
# ownership so the non-root process can write to it).
RUN mkdir -p /app/logs && chown -R app:app /app

USER app

# Default web UI port (override with BW_PORT).
EXPOSE 9534

CMD ["python", "branch_status.py", "--serve"]

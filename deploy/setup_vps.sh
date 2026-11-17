#!/usr/bin/env bash
# VPS setup script for Atlas service
# Run this script once on a fresh VPS to configure the Atlas systemd user service

set -uo pipefail

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Check if running as root (not recommended for user service)
if [[ $EUID -eq 0 ]]; then
    log "WARNING: Running as root. This script is designed for a regular user with sudo access."
    log "It's better to run as your regular user (e.g., 'administrator' or 'ubuntu')."
fi

# Ensure we're in the Atlas directory
cd "$(dirname "$(readlink -f "$0")")/.." || exit 1
ATLAS_DIR="$(pwd)"
log "Atlas directory: ${ATLAS_DIR}"

# 1. Check Python venv
if [[ ! -f ".venv/bin/python" ]]; then
    log "Creating Python virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
else
    log "Virtual environment exists."
fi

# 2. Check .env file
if [[ ! -f ".env" ]]; then
    if [[ -f ".env.example" ]]; then
        log "Creating .env from .env.example..."
        cp .env.example .env
        log "IMPORTANT: Edit .env and add your ATLAS_TELEGRAM_BOT_TOKEN and ATLAS_TELEGRAM_CHAT_ID"
    else
        log "WARNING: .env.example not found. Create .env manually."
    fi
else
    log ".env file exists."
fi

# 3. Run tests to verify installation
log "Running tests..."
source .venv/bin/activate
python -m pytest -q tests/test_atlas_service.py tests/test_telegram_command_service.py -x || {
    log "Tests failed. Please fix issues before continuing."
    exit 1
}

# 4. Install systemd user service
SERVICE_DIR="${HOME}/.config/systemd/user"
mkdir -p "${SERVICE_DIR}"
cp deploy/atlas.service "${SERVICE_DIR}/atlas.service"
log "Service file installed to ${SERVICE_DIR}/atlas.service"

# 5. Reload systemd
systemctl --user daemon-reload
log "Systemd daemon reloaded."

# 6. Enable and start service
systemctl --user enable --now atlas.service
log "Service enabled and started."

# 6. Enable linger for user service persistence
log "Checking linger status..."
CURRENT_USER=$(whoami)
LINGER_STATUS=$(loginctl show-user "${CURRENT_USER}" --property=Linger --value 2>/dev/null || echo "unknown")
if [[ "${LINGER_STATUS}" != "yes" ]]; then
    log "Enabling linger for user ${CURRENT_USER} (requires sudo)..."
    if sudo loginctl enable-linger "${CURRENT_USER}"; then
        log "Linger enabled. User service will persist after SSH logout and survive reboot."
    else
        log "WARNING: Failed to enable linger. Service may stop when SSH session ends."
        log "Run manually: sudo loginctl enable-linger ${CURRENT_USER}"
    fi
else
    log "Linger already enabled for ${CURRENT_USER}."
fi

# 7. Show status
log "=== Service Status ==="
systemctl --user status atlas.service --no-pager

log "=== Recent Logs ==="
journalctl --user -u atlas.service -n 20 --no-pager

log ""
log "=== VPS Setup Complete ==="
log "Useful commands:"
log "  systemctl --user status atlas.service     # Check service status"
log "  journalctl --user -u atlas.service -f     # Follow logs"
log "  journalctl --user -u atlas.service -n 100 --no-pager  # Last 100 lines"
log "  systemctl --user restart atlas.service    # Restart service"
log "  systemctl --user stop atlas.service       # Stop service"
log ""
log "To verify BotFather commands are registered:"
log "  source .venv/bin/activate"
log "  python -m telegram_botfather verify"
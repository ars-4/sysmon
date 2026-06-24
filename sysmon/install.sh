#!/usr/bin/env bash
# ── SysMon installer for Ubuntu / Debian ─────────────────────────────────
# Usage:
#   sudo bash install.sh          — install & start
#   sudo bash install.sh remove   — stop & uninstall

set -euo pipefail

SERVICE=sysmon
INSTALL_DIR=/opt/sysmon
SERVICE_FILE=/etc/systemd/system/${SERVICE}.service
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[sysmon]${NC} $*"; }
success() { echo -e "${GREEN}[sysmon]${NC} $*"; }
warn()    { echo -e "${YELLOW}[sysmon]${NC} $*"; }
die()     { echo -e "${RED}[sysmon] ERROR:${NC} $*" >&2; exit 1; }

# ── guard ─────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && die "Run this script with sudo or as root."
command -v systemctl >/dev/null 2>&1 || die "systemd not found — this script requires a systemd-based system."

# ── remove mode ───────────────────────────────────────────────────────────
if [[ "${1:-}" == "remove" ]]; then
  info "Stopping and disabling ${SERVICE}…"
  systemctl stop  ${SERVICE} 2>/dev/null || true
  systemctl disable ${SERVICE} 2>/dev/null || true
  rm -f "${SERVICE_FILE}"
  systemctl daemon-reload
  info "Removing ${INSTALL_DIR}…"
  rm -rf "${INSTALL_DIR}"
  success "SysMon has been removed."
  exit 0
fi

# ── detect OS ─────────────────────────────────────────────────────────────
if [[ -f /etc/os-release ]]; then
  . /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_LIKE="${ID_LIKE:-}"
else
  die "/etc/os-release not found. Cannot detect OS."
fi

case "${OS_ID}" in
  ubuntu|debian|raspbian) ;;
  *)
    if echo "${OS_LIKE}" | grep -qE '(ubuntu|debian)'; then
      warn "OS '${OS_ID}' is Debian-like — continuing."
    else
      die "Unsupported OS '${OS_ID}'. This script targets Ubuntu / Debian."
    fi
    ;;
esac
info "Detected OS: ${PRETTY_NAME:-${OS_ID}}"

# ── check source files ────────────────────────────────────────────────────
[[ -f "${SCRIPT_DIR}/server.py"  ]] || die "server.py not found in ${SCRIPT_DIR}"
[[ -f "${SCRIPT_DIR}/index.html" ]] || die "index.html not found in ${SCRIPT_DIR}"

# ── install python3 & pip if needed ──────────────────────────────────────
info "Checking Python 3…"
if ! command -v python3 >/dev/null 2>&1; then
  info "Installing python3…"
  apt-get update -qq
  apt-get install -y -qq python3 python3-pip
else
  PYVER=$(python3 --version 2>&1)
  info "Found ${PYVER}"
fi

# ── install psutil ────────────────────────────────────────────────────────
info "Checking psutil…"
if ! python3 -c "import psutil" 2>/dev/null; then
  info "Installing psutil…"
  # Try pip first, fall back to apt package
  if command -v pip3 >/dev/null 2>&1; then
    pip3 install --quiet psutil
  elif command -v pip >/dev/null 2>&1; then
    pip install --quiet psutil
  else
    apt-get install -y -qq python3-psutil
  fi
else
  PSUTIL_VER=$(python3 -c "import psutil; print(psutil.__version__)")
  info "psutil ${PSUTIL_VER} already installed"
fi

# ── copy files ────────────────────────────────────────────────────────────
info "Installing to ${INSTALL_DIR}…"
mkdir -p "${INSTALL_DIR}"
cp "${SCRIPT_DIR}/server.py"  "${INSTALL_DIR}/server.py"
cp "${SCRIPT_DIR}/index.html" "${INSTALL_DIR}/index.html"
chmod 644 "${INSTALL_DIR}/server.py" "${INSTALL_DIR}/index.html"

# ── write service file ────────────────────────────────────────────────────
info "Writing systemd service to ${SERVICE_FILE}…"
cat > "${SERVICE_FILE}" <<'EOF'
[Unit]
Description=SysMon System Dashboard
Documentation=https://github.com/your-repo/sysmon
After=network.target
Wants=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/sysmon
ExecStart=/usr/bin/python3 /opt/sysmon/server.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=sysmon
PrivateTmp=true
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
EOF

chmod 644 "${SERVICE_FILE}"

# ── enable & start ────────────────────────────────────────────────────────
info "Reloading systemd daemon…"
systemctl daemon-reload

info "Enabling ${SERVICE} to start on boot…"
systemctl enable "${SERVICE}"

info "Starting ${SERVICE}…"
systemctl restart "${SERVICE}"

# ── verify ────────────────────────────────────────────────────────────────
sleep 2
if systemctl is-active --quiet "${SERVICE}"; then
  success "SysMon is running!"
  echo ""
  echo -e "  ${CYAN}Dashboard:${NC}  http://$(hostname -I | awk '{print $1}'):8056"
  echo -e "  ${CYAN}API:${NC}        http://$(hostname -I | awk '{print $1}'):8056/health"
  echo ""
  echo -e "  ${YELLOW}Useful commands:${NC}"
  echo "    systemctl status  sysmon"
  echo "    systemctl restart sysmon"
  echo "    journalctl -u sysmon -f"
  echo "    sudo bash install.sh remove"
else
  die "Service failed to start. Check logs: journalctl -u ${SERVICE} -n 50"
fi

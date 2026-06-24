# ▣ SysMon

A lightweight, real-time system resource dashboard — like `btop` in your browser.
Single Python server, single HTML file, zero dependencies beyond `psutil`.

![Dashboard](https://img.shields.io/badge/Python-3.8+-blue?style=flat-square&logo=python)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Port](https://img.shields.io/badge/Port-8056-orange?style=flat-square)

---

## Features

| Tab | What you get |
|---|---|
| **Overview** | CPU, Memory, Disk, GPU VRAM summary cards with live spark line charts |
| **CPU** | Model, core count, frequency, load averages, per-core usage grid, CPU time breakdown |
| **Memory** | RAM used/free/cached/buffers/shared, memory type, swap usage |
| **Disks** | All partitions — device, mountpoint, fstype, used/free/total, read/write bytes |
| **Network** | Bytes sent/recv, packet counts, per-interface IP/MAC/speed/MTU/status |
| **GPU / Temp** | NVIDIA or AMD VRAM, core utilization, temperature, power draw; all sensor temps; battery |
| **Processes** | Top 80 by CPU — searchable, filterable by state, sortable columns, hide-idle toggle |
| **Services** | systemctl / launchctl / sc query — searchable, active/failed filters |

- Auto-refresh: 2s / 5s / 10s / 30s / paused
- Mobile-friendly responsive layout
- Zero JavaScript frameworks — pure vanilla JS + Canvas

---

## Files

```
sysmon/
├── server.py      # Python HTTP server — serves index.html + /health API
├── index.html     # Single-page dashboard (CSS + JS inline)
├── sysmon.service # systemd unit file (reference copy)
└── install.sh     # Automated installer for Ubuntu / Debian
```

---

## Quick Start (any platform)

```bash
pip install psutil
python server.py
```

Open **http://localhost:8056**

---

## Install as a systemd Service (Ubuntu / Debian)

### Automated

Put all 4 files in the same folder, then:

```bash
sudo bash install.sh
```

The installer will:
- Detect Ubuntu / Debian (including Debian-like distros)
- Install `python3` and `psutil` if missing
- Copy files to `/opt/sysmon/`
- Write and enable `/etc/systemd/system/sysmon.service`
- Start the service immediately and print the dashboard URL

### Manual

```bash
# 1. Copy files
sudo mkdir -p /opt/sysmon
sudo cp server.py index.html /opt/sysmon/

# 2. Install the service unit
sudo cp sysmon.service /etc/systemd/system/sysmon.service

# 3. Enable and start
sudo systemctl daemon-reload
sudo systemctl enable sysmon
sudo systemctl start sysmon

# 4. Verify
systemctl status sysmon
```

### Useful commands

```bash
systemctl status  sysmon       # check status
systemctl restart sysmon       # restart
journalctl -u sysmon -f        # live logs
sudo bash install.sh remove    # full uninstall
```

---

## Firewall / Network Access

### Local machine
```
http://localhost:8056
```

### LAN / remote access

The server binds to `0.0.0.0:8056` (all interfaces). To reach it from another machine:

**Linux — iptables**
```bash
sudo iptables -I INPUT -p tcp --dport 8056 -j ACCEPT

# Persist across reboots
sudo apt install iptables-persistent -y
sudo netfilter-persistent save
```

**Linux — ufw**
```bash
sudo ufw allow 8056/tcp
sudo ufw reload
```

### Oracle Cloud VPS (OCI)

Oracle Cloud blocks all inbound ports at the **network level**, outside the VM. Two steps required:

**Step 1 — OCI Console Security List**

> OCI Console → Networking → Virtual Cloud Networks → your VCN → Security Lists → Default → Add Ingress Rule

| Field | Value |
|---|---|
| Source CIDR | `0.0.0.0/0` |
| Protocol | TCP |
| Destination Port Range | `8056` |

**Step 2 — iptables on the instance**
```bash
sudo iptables -I INPUT -p tcp --dport 8056 -j ACCEPT
sudo apt install iptables-persistent -y
sudo netfilter-persistent save
```

Verify the server is listening:
```bash
ss -tlnp | grep 8056
# Should show: 0.0.0.0:8056
```

---

## GPU Support

| Vendor | Requirement |
|---|---|
| NVIDIA | `nvidia-smi` must be in PATH (included with NVIDIA drivers) |
| AMD | `rocm-smi` must be in PATH (install ROCm) |
| Apple Silicon | Activity Monitor recommended; integrated GPU stats not exposed via CLI |

If no GPU tool is found, the GPU tab shows "No GPU detected" — everything else works normally.

---

## Requirements

- Python 3.8+
- [`psutil`](https://pypi.org/project/psutil/) — `pip install psutil`
- A modern browser (Chrome, Firefox, Safari, Edge)

No other dependencies. No Node.js, no npm, no Docker.

---

## API

The `/health` endpoint returns a single JSON object with all metrics:

```
GET http://localhost:8056/health
```

```jsonc
{
  "system":       { "hostname", "os", "uptime_seconds", ... },
  "cpu":          { "model", "usage_total", "usage_per_core", "load_avg", ... },
  "memory":       { "total", "used", "free", "cached", "swap_total", ... },
  "disks":        [ { "device", "mountpoint", "fstype", "used", "total", ... } ],
  "network":      { "bytes_sent", "bytes_recv", "interfaces": [...] },
  "gpu":          [ { "vendor", "name", "vram_used_mb", "gpu_util", "temp_c", ... } ],
  "temperatures": { "sensor_name": [ { "label", "current", "critical" } ] },
  "battery":      { "percent", "plugged", "secs_left" },
  "processes":    [ { "pid", "name", "cpu", "mem_pct", "status", ... } ],
  "services":     [ { "name", "active", "sub", "description" } ]
}
```

Useful for scripting, alerting, or feeding into other tools.

---

## License

MIT

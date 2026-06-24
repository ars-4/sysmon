#!/usr/bin/env python3
"""
SysMon Dashboard - Backend Server
Runs on port 8056, exposes /health with full system metrics
"""

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

STATIC_DIR = Path(__file__).parent


# ── helpers ──────────────────────────────────────────────────────────────────

def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def run(cmd, timeout=3):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


# ── metric collectors ─────────────────────────────────────────────────────────

def get_cpu():
    if not HAS_PSUTIL:
        return {}

    per_core = psutil.cpu_percent(interval=0.2, percpu=True)
    freq = psutil.cpu_freq()
    times = psutil.cpu_times_percent(interval=0)
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
    cpu_count_logical = psutil.cpu_count(logical=True)
    cpu_count_physical = psutil.cpu_count(logical=False)

    # Try to get CPU model name
    model = platform.processor() or "Unknown"
    if platform.system() == "Linux":
        with open("/proc/cpuinfo") as f:
            for line in f:
                if "model name" in line:
                    model = line.split(":", 1)[1].strip()
                    break
    elif platform.system() == "Darwin":
        model = run(["sysctl", "-n", "machdep.cpu.brand_string"]) or model

    return {
        "model": model,
        "cores_physical": cpu_count_physical,
        "cores_logical": cpu_count_logical,
        "usage_total": sum(per_core) / len(per_core) if per_core else 0,
        "usage_per_core": per_core,
        "freq_current": round(freq.current, 0) if freq else None,
        "freq_max": round(freq.max, 0) if freq and freq.max else None,
        "load_avg": list(load),
        "times": {
            "user": times.user,
            "system": times.system,
            "idle": times.idle,
            "iowait": getattr(times, "iowait", 0),
        },
    }


def get_memory():
    if not HAS_PSUTIL:
        return {}

    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()

    # Try to get memory type
    mem_type = "Unknown"
    if platform.system() == "Linux":
        out = run(["sudo", "dmidecode", "--type", "17"], timeout=2)
        if "DDR" in out:
            for line in out.splitlines():
                if "Type:" in line and "DDR" in line:
                    mem_type = line.split(":", 1)[1].strip()
                    break
        # Fallback: check /sys
        if mem_type == "Unknown":
            try:
                path = "/sys/devices/system/edac/mc/mc0/dimm0/dimm_mem_type"
                if os.path.exists(path):
                    mem_type = open(path).read().strip()
            except Exception:
                pass

    return {
        "type": mem_type,
        "total": vm.total,
        "available": vm.available,
        "used": vm.used,
        "free": vm.free,
        "percent": vm.percent,
        "cached": getattr(vm, "cached", 0),
        "buffers": getattr(vm, "buffers", 0),
        "shared": getattr(vm, "shared", 0),
        "swap_total": sw.total,
        "swap_used": sw.used,
        "swap_free": sw.free,
        "swap_percent": sw.percent,
    }


def get_disks():
    if not HAS_PSUTIL:
        return []

    partitions = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            io = psutil.disk_io_counters(perdisk=True)
            dev_name = part.device.replace("/dev/", "").split("p")[0]  # strip partition num
            dev_io = io.get(dev_name, None) if io else None
            partitions.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent,
                "read_bytes": dev_io.read_bytes if dev_io else None,
                "write_bytes": dev_io.write_bytes if dev_io else None,
            })
        except (PermissionError, OSError):
            continue

    return partitions


def get_network():
    if not HAS_PSUTIL:
        return {}

    net_io = psutil.net_io_counters()
    ifaces = []
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()

    for iface, addr_list in addrs.items():
        st = stats.get(iface)
        ipv4 = next((a.address for a in addr_list if a.family == socket.AF_INET), None)
        ipv6 = next((a.address for a in addr_list if a.family == socket.AF_INET6), None)
        mac = next((a.address for a in addr_list if a.family == psutil.AF_LINK), None)
        ifaces.append({
            "name": iface,
            "ipv4": ipv4,
            "ipv6": ipv6,
            "mac": mac,
            "is_up": st.isup if st else False,
            "speed": st.speed if st else 0,
            "mtu": st.mtu if st else 0,
        })

    return {
        "interfaces": ifaces,
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv,
        "packets_sent": net_io.packets_sent,
        "packets_recv": net_io.packets_recv,
        "errin": net_io.errin,
        "errout": net_io.errout,
    }


def get_gpu():
    gpus = []

    # NVIDIA via nvidia-smi
    out = run([
        "nvidia-smi",
        "--query-gpu=name,temperature.gpu,utilization.gpu,utilization.memory,"
        "memory.total,memory.used,memory.free,power.draw,power.limit,clocks.gr",
        "--format=csv,noheader,nounits"
    ])
    if out:
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 10:
                def safe_float(v, default=0.0):
                    try:
                        return float(v)
                    except (ValueError, TypeError):
                        return default

                gpus.append({
                    "vendor": "NVIDIA",
                    "name": parts[0],
                    "temp_c": safe_float(parts[1]),
                    "gpu_util": safe_float(parts[2]),
                    "mem_util": safe_float(parts[3]),
                    "vram_total_mb": safe_float(parts[4]),
                    "vram_used_mb": safe_float(parts[5]),
                    "vram_free_mb": safe_float(parts[6]),
                    "power_draw_w": safe_float(parts[7]),
                    "power_limit_w": safe_float(parts[8]),
                    "clock_mhz": safe_float(parts[9]),
                })

    # AMD via rocm-smi
    if not gpus:
        out = run(["rocm-smi", "--showuse", "--showmemuse", "--showtemp", "--json"])
        if out:
            try:
                data = json.loads(out)
                for key, val in data.items():
                    if key.startswith("card"):
                        gpus.append({
                            "vendor": "AMD",
                            "name": val.get("Card series", "AMD GPU"),
                            "temp_c": float(val.get("Temperature (Sensor edge) (C)", 0)),
                            "gpu_util": float(val.get("GPU use (%)", 0)),
                            "mem_util": float(val.get("GPU memory use (%)", 0)),
                            "vram_total_mb": 0,
                            "vram_used_mb": 0,
                            "vram_free_mb": 0,
                        })
            except Exception:
                pass

    # Integrated / Apple Silicon via powermetrics (macOS)
    if not gpus and platform.system() == "Darwin":
        gpus.append({"vendor": "Apple", "name": "Integrated GPU (macOS)", "note": "Use Activity Monitor for GPU stats"})

    return gpus


def get_temperatures():
    temps = {}
    if not HAS_PSUTIL:
        return temps
    try:
        raw = psutil.sensors_temperatures()
        for sensor, entries in raw.items():
            temps[sensor] = [
                {"label": e.label or f"core{i}", "current": e.current, "high": e.high, "critical": e.critical}
                for i, e in enumerate(entries)
            ]
    except AttributeError:
        pass  # Windows / some platforms
    return temps


def get_battery():
    if not HAS_PSUTIL:
        return None
    try:
        b = psutil.sensors_battery()
        if b:
            return {
                "percent": b.percent,
                "plugged": b.power_plugged,
                "secs_left": b.secsleft if b.secsleft != psutil.POWER_TIME_UNLIMITED else -1,
            }
    except AttributeError:
        pass
    return None


def get_processes():
    if not HAS_PSUTIL:
        return []
    procs = []
    for p in psutil.process_iter(["pid", "name", "username", "status", "cpu_percent", "memory_percent", "memory_info", "create_time"]):
        try:
            info = p.info
            procs.append({
                "pid": info["pid"],
                "name": info["name"],
                "user": info["username"] or "",
                "status": info["status"],
                "cpu": round(info["cpu_percent"] or 0, 1),
                "mem_pct": round(info["memory_percent"] or 0, 2),
                "mem_rss": info["memory_info"].rss if info["memory_info"] else 0,
                "started": int(info["create_time"] or 0),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(procs, key=lambda x: x["cpu"], reverse=True)[:80]


def get_services():
    services = []
    sys = platform.system()

    if sys == "Linux":
        out = run(["systemctl", "list-units", "--type=service", "--all",
                   "--no-pager", "--no-legend", "--plain"], timeout=5)
        for line in out.splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 4:
                services.append({
                    "name": parts[0].replace(".service", ""),
                    "load": parts[1],
                    "active": parts[2],
                    "sub": parts[3],
                    "description": parts[4] if len(parts) > 4 else "",
                })
    elif sys == "Darwin":
        out = run(["launchctl", "list"], timeout=5)
        for line in out.splitlines()[1:]:
            parts = line.split(None, 2)
            if len(parts) == 3:
                services.append({
                    "name": parts[2],
                    "pid": parts[0] if parts[0] != "-" else None,
                    "status": parts[1],
                    "active": "running" if parts[0] != "-" else "stopped",
                    "sub": "",
                    "description": "",
                })
    elif sys == "Windows":
        out = run(["sc", "query", "type=", "all", "state=", "all"], timeout=8)
        current = {}
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("SERVICE_NAME:"):
                current = {"name": line.split(":", 1)[1].strip()}
            elif line.startswith("STATE"):
                match = re.search(r"\d+\s+(\w+)", line)
                if match:
                    current["active"] = match.group(1).lower()
                    services.append(current)

    return services


def get_system_info():
    uname = platform.uname()
    uptime_secs = 0
    if HAS_PSUTIL:
        uptime_secs = int(time.time() - psutil.boot_time())

    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "127.0.0.1"

    return {
        "hostname": hostname,
        "local_ip": local_ip,
        "os": f"{uname.system} {uname.release}",
        "os_version": uname.version,
        "machine": uname.machine,
        "python": platform.python_version(),
        "uptime_seconds": uptime_secs,
        "timestamp": int(time.time()),
    }


# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # suppress request logs

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, path, content_type):
        try:
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/health":
            try:
                payload = {
                    "system": get_system_info(),
                    "cpu": get_cpu(),
                    "memory": get_memory(),
                    "disks": get_disks(),
                    "network": get_network(),
                    "gpu": get_gpu(),
                    "temperatures": get_temperatures(),
                    "battery": get_battery(),
                    "processes": get_processes(),
                    "services": get_services(),
                    "psutil_available": HAS_PSUTIL,
                }
                self.send_json(payload)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif path in ("/", "/index.html"):
            self.serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")

        else:
            self.send_response(404)
            self.end_headers()


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not HAS_PSUTIL:
        print("⚠  psutil not found. Install it:  pip install psutil")
        print("   Running in degraded mode — /health will return empty metrics.\n")
    else:
        print("✓  psutil detected")

    server = HTTPServer(("0.0.0.0", 8056), Handler)
    print(f"✓  SysMon running at http://0.0.0.0:8056")
    print(f"   Open http://localhost:8056 in your browser")
    print(f"   API: http://localhost:8056/health\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")

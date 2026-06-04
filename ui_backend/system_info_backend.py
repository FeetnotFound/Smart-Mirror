"""System info backend — CPU, RAM, GPU, disk, temp, uptime."""
import subprocess
import time
from datetime import timedelta
from typing import Optional

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False


def _gpu_stats() -> dict:
    """NVIDIA GPU via nvidia-smi. Returns {} if unavailable."""
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0:
            parts = [p.strip() for p in out.stdout.strip().split(",")]
            if len(parts) >= 3:
                return {
                    "gpu_percent":     int(parts[0]),
                    "gpu_mem_used_mb": int(parts[1]),
                    "gpu_mem_total_mb":int(parts[2]),
                }
    except Exception:
        pass
    return {}


def snapshot() -> dict:
    """Structured stats for the widget and TTS."""
    if not _PSUTIL:
        return {"available": False}

    mem  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    data: dict = {
        "available":     True,
        "cpu_percent":   psutil.cpu_percent(interval=0.3),
        "mem_percent":   mem.percent,
        "mem_used_gb":   round(mem.used  / 1024**3, 1),
        "mem_total_gb":  round(mem.total / 1024**3, 1),
        "disk_percent":  disk.percent,
        "disk_used_gb":  round(disk.used  / 1024**3, 1),
        "disk_total_gb": round(disk.total / 1024**3, 1),
        "uptime_seconds":int(time.time() - psutil.boot_time()),
    }

    try:
        temps = psutil.sensors_temperatures()
        if temps:
            first = next(iter(temps.values()))[0]
            data["temp_c"] = round(first.current, 1)
    except Exception:
        pass

    data.update(_gpu_stats())
    return data


def get_system_info() -> str:
    """Spoken summary for TTS."""
    s = snapshot()
    if not s.get("available"):
        return "System monitoring isn't available right now."
    up = str(timedelta(seconds=s["uptime_seconds"])).split(".")[0]
    parts = [
        f"CPU at {s['cpu_percent']:.0f} percent",
        f"memory {s['mem_used_gb']} of {s['mem_total_gb']} gigabytes",
        f"disk {s['disk_used_gb']} of {s['disk_total_gb']} gigabytes",
    ]
    if "temp_c" in s:
        parts.append(f"{s['temp_c']:.0f} degrees")
    if "gpu_percent" in s:
        parts.append(f"GPU at {s['gpu_percent']} percent")
    parts.append(f"up for {up}")
    return ", ".join(parts) + "."

"""Utility helpers: MAC normalization, key byte-reversal, NTFS mount detection."""

from __future__ import annotations

import subprocess
from pathlib import Path


def normalize_mac(mac: str) -> str:
    """Return MAC address as uppercase, colon-separated (e.g. 'C0:35:32:AC:13:4A')."""
    clean = mac.replace(":", "").replace("-", "").upper()
    return ":".join(clean[i : i + 2] for i in range(0, 12, 2))


def mac_to_windows_key(mac: str) -> str:
    """Return MAC as lowercase, no-separator string used by Windows registry keys."""
    return mac.replace(":", "").replace("-", "").lower()


def reverse_hex_key(hex_key: str) -> bytes:
    """Byte-reverse a hex string key and return raw bytes.

    Used by the matching logic to compare a Linux IRK (hex string) against
    a Windows IRK (raw bytes stored in opposite byte order in the registry).
    """
    raw = bytes.fromhex(hex_key)
    return bytes(reversed(raw))


def find_ntfs_mounts() -> list[Path]:
    """Return a list of mount points for NTFS partitions (potential Windows drives)."""
    mounts: list[Path] = []
    try:
        result = subprocess.run(
            ["findmnt", "--noheadings", "--output", "TARGET,FSTYPE", "--list"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].lower() in ("ntfs", "ntfs-3g", "fuseblk"):
                mounts.append(Path(parts[0]))
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fall back to parsing /proc/mounts directly
        proc_mounts = Path("/proc/mounts")
        if proc_mounts.exists():
            for line in proc_mounts.read_text().splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[2].lower() in ("ntfs", "ntfs-3g", "fuseblk"):
                    mounts.append(Path(parts[1]))
    return mounts


def find_windows_system_hive(mount: Path) -> Path | None:
    """Return path to the Windows SYSTEM registry hive if found under mount."""
    candidate = mount / "Windows" / "System32" / "config" / "SYSTEM"
    return candidate if candidate.exists() else None

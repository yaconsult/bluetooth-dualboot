# bluetooth-dualboot

Sync Bluetooth pairing keys from Linux into the Windows registry so every paired
Bluetooth device (mice, keyboards, headphones, etc.) works in **both Fedora Linux
and Windows 11** without re-pairing when you switch OS from GRUB.

Supports **BLE (Bluetooth Low Energy)** and **Classic BR/EDR** devices.

---

## The Problem

When you pair a Bluetooth device in Linux, Linux generates and stores cryptographic
keys. When you pair the same device in Windows, Windows generates *different* keys
and overwrites the device's stored keys — breaking Linux's connection (and vice versa).

Every re-pair breaks the other OS.

## The Solution

Pair each device **once in Linux**. This tool reads Linux's pairing keys and injects
them into the Windows registry (while the Windows partition is mounted but not booted).
Both OSes then share the same keys, so every device connects automatically regardless
of which OS you boot.

---

## Requirements

- Dual-boot system: **Fedora Linux** (or any distro with BlueZ) + **Windows 11**
- Windows NTFS partition mounted in Linux (e.g. at `/mnt/windows`)
- `sudo` access
- `reged` (part of the `chntpw` package) — for creating new registry entries
- `python3` + [`uv`](https://github.com/astral-sh/uv) — for running the tool

### Install system dependencies

**Fedora / RHEL:**
```bash
sudo dnf install chntpw
```

**Debian / Ubuntu:**
```bash
sudo apt install chntpw
```

**Arch:**
```bash
sudo pacman -S chntpw
```

---

## Setup

```bash
git clone https://github.com/yaconsult/bluetooth-dualboot.git
cd bluetooth-dualboot
uv sync
```

This creates an isolated `.venv/` inside the project folder — no system Python packages
are modified.

---

## Usage

### 1. Pair all your Bluetooth devices in Linux first

Make sure every device you want to use in both OSes is paired and working in Linux.

### 2. Mount the Windows partition (if not auto-mounted)

```bash
sudo mkdir -p /mnt/windows
sudo mount /dev/nvme0n1p3 /mnt/windows   # adjust partition as needed
```

### 3. Run a dry-run to preview changes

```bash
sudo uv run bt-sync --dry-run --verbose
```

### 4. Apply the sync

```bash
sudo uv run bt-sync
```

### 5. Boot into Windows

Your Bluetooth devices should connect automatically. No re-pairing needed.

---

## CLI Reference

```
sudo uv run bt-sync [OPTIONS]

Options:
  --windows-mount PATH   Mount point of the Windows NTFS partition
                         (auto-detected from mounted NTFS volumes if omitted)
  --bluez-dir PATH       Path to the BlueZ key store
                         (default: /var/lib/bluetooth)
  --dry-run              Show what would be changed without writing anything
  --verbose              Print detailed key values and actions
  -h, --help             Show this message and exit
```

---

## How It Works

### BLE devices (most modern mice, keyboards)

Linux (BlueZ) and Windows store BLE keys with **opposite byte order**
(big-endian vs little-endian). The tool:

1. Reads `LTK`, `IRK`, and `CSRK` from `/var/lib/bluetooth/<adapter>/<device>/info`
2. Byte-reverses each key to Windows format
3. Matches the Linux device to its Windows registry entry **by IRK** (not MAC address)
4. If a match is found → patches the existing entry in-place
5. If no match → creates a new registry subkey via `reged`

`AuthReq` (pairing security flags) is derived from the Linux pairing data — not hardcoded.

#### Why IRK matching, not MAC?

Many BLE devices use **Resolvable Private Addresses (RPA)** — the MAC address they
advertise changes every ~15 minutes. Windows pairs the device under whatever RPA it
saw at pairing time. Linux pairs it under the stable **identity address** (via the IRK).
These two MACs are different, so MAC-based matching would fail to link them.

The IRK (Identity Resolving Key) is the same on both sides and is the correct stable
identifier. The tool byte-reverses the Linux IRK to Windows format before comparing.

### Classic BR/EDR devices (older mice, some headsets)

Link keys do **not** need byte-reversal. The tool patches or creates the value directly
on the adapter registry key.

### Registry location

```
HKLM\SYSTEM\ControlSet001\Services\BTHPORT\Parameters\Keys\<adapter>\<device>
```

---

## Automatic Backup and Restore

Before writing any changes, `bt-sync` automatically creates a timestamped backup of the
Windows SYSTEM registry hive **on the Windows partition**:

```
C:\Windows\System32\config\SYSTEM.bt-sync-backup-YYYYMMDD_HHMMSS
```

(visible from Linux at `/mnt/windows/Windows/System32/config/SYSTEM.bt-sync-backup-*`)

The backup is only created when changes are actually needed — re-running when already in
sync skips the backup entirely.

### Restoring the backup

If something goes wrong after booting Windows (e.g. Bluetooth stops working entirely),
boot back into Linux and restore with:

```bash
# Find your backup — most recent timestamp is the one to use
ls /mnt/windows/Windows/System32/config/SYSTEM.bt-sync-backup-*

# Restore it (adjust mount point and timestamp as needed)
sudo cp /mnt/windows/Windows/System32/config/SYSTEM.bt-sync-backup-20260520_190427 \
        /mnt/windows/Windows/System32/config/SYSTEM
```

Then boot back into Windows — Bluetooth will be back to its prior state.

### Cleaning up old backups

Old backups can be deleted safely at any time from Linux or Windows:

```bash
sudo rm /mnt/windows/Windows/System32/config/SYSTEM.bt-sync-backup-*
```

---

## Re-running After Re-pairing

If you re-pair a device in Linux (e.g. after a factory reset), just run `bt-sync` again.
It detects key mismatches and updates Windows automatically.

---

## Supported Distros

Tested on **Fedora 44**. Should work on any Linux distro with BlueZ (`/var/lib/bluetooth`).

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT

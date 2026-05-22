# bluetooth-dualboot

Sync Bluetooth pairing keys between Linux and Windows so every paired Bluetooth
device (mice, keyboards, headphones, etc.) works in **both Fedora Linux and
Windows 11** without re-pairing when you switch OS from GRUB.

Supports **BLE (Bluetooth Low Energy)** and **Classic BR/EDR** devices.

---

## The Problem

When you pair a Bluetooth device in one OS, that OS generates unique cryptographic
keys. Pairing the same device in the other OS generates *different* keys and
overwrites the device's stored bond — breaking the first OS's connection.

Every re-pair breaks the other OS.

## The Solution

Pair each device in **both OSes**, then run `bt-sync` to unify the keys:

- **BLE devices**: pair in Windows **last**. `bt-sync` copies Windows' keys into
  Linux's BlueZ config. This is necessary because BLE devices store the host's
  identity (adapter IRK) — the mouse must remember Windows' identity, and Linux
  adopts it.
- **Classic BR/EDR devices**: pair in Linux **last** (or either order). `bt-sync`
  copies Linux's link key into the Windows registry. Classic link keys are symmetric
  so either direction works.

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

### 1. Pair your Bluetooth devices in both OSes

- **BLE devices**: pair in Linux first, then in **Windows** (Windows must be last)
- **Classic devices**: pair in Windows first, then in **Linux** (or either order)

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

### 5. Restart Bluetooth (for BLE devices)

```bash
sudo systemctl restart bluetooth
```

BLE devices should reconnect immediately in Linux.

### 6. Verify in both OSes

Reboot into Windows — your Bluetooth devices should connect automatically.
No re-pairing needed.

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

BLE sync direction: **Windows → Linux**.

BLE devices store the host's adapter IRK during pairing. Since Linux and Windows
have different adapter IRKs, the device only recognises one host. By pairing in
Windows last and copying those keys into Linux, the device recognises both OSes
(both present Windows' identity).

The tool:

1. Reads the Windows BLE entry from the registry (`LTK`, `IRK`, `CSRK`, `EDIV`, `ERand`)
2. Matches it to the corresponding Linux device using:
   - **IRK match on the active entry** (present in `ControlSet001\Enum\BTHLE`)
   - **IRK match on inactive entry + single active entry** — fallback
   - **IRK match on any entry** — fallback when BTHLE enum is absent
   - **MAC match** — final fallback for public-address devices
3. Byte-reverses each Windows key to Linux format (little-endian → big-endian)
4. Writes the keys into `/var/lib/bluetooth/<adapter>/<device>/info`
5. After sync, `systemctl restart bluetooth` loads the new keys

#### Why Windows → Linux, not the reverse?

BLE bonds are **asymmetric** — the device stores the host's identity (adapter IRK)
and only accepts connections from that specific host. Windows and Linux have
different adapter IRKs. Copying Linux keys into Windows doesn't work because the
device (bonded to Linux) rejects Windows' host identity.

By pairing Windows last, the device stores Windows' host identity. Linux then
adopts Windows' keys, so both OSes present the same identity to the device.

### Classic BR/EDR devices (older mice, some headsets)

Classic sync direction: **Linux → Windows**.

Classic link keys are symmetric — either side can reconnect using the same key.
No byte-reversal is needed. The tool patches or creates the value directly
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

If you re-pair a BLE device, always re-pair in **Windows last**, then run `bt-sync`.
For Classic devices, re-pair in Linux and run `bt-sync` to update Windows.

---

## Troubleshooting

### BLE device shows "not connected" in one OS after sync

1. Ensure you paired in the correct order: **Windows last** for BLE devices
2. Run `sudo uv run bt-sync` from Linux (Windows partition mounted)
3. Run `sudo systemctl restart bluetooth`
4. Verify the device works in Linux
5. Reboot into Windows — it should connect automatically

If the device still fails, start fresh:

1. Remove the device in **both** OSes
2. Pair in Linux first, then in Windows
3. Boot Linux, run `sudo uv run bt-sync`
4. Run `sudo systemctl restart bluetooth`

### Mouse/keyboard has both BT3.0 and BT5.0 modes

Some devices (e.g. TeckNet EWM01308) advertise as two separate Bluetooth devices —
one Classic BR/EDR (BT3.0) and one BLE (BT5.0). **Both OSes must pair using the same
protocol** — `bt-sync` cannot bridge keys between BLE and Classic.

- BLE (BT5.0) is recommended — better battery life, handled natively by `bt-sync`
- If the device only shows up as Classic during pairing, it may be trying to reconnect
  to a previous BLE host — remove that pairing first, then retry

To check which protocol Linux paired with:
```bash
sudo cat /var/lib/bluetooth/<adapter>/<device>/info | grep -i "SupportedTechnologies\|AddressType"
```
If `SupportedTechnologies=LE` → BLE. If `AddressType` is absent and a `LinkKey`
section is present → Classic.

### Device won't advertise BLE for pairing (keeps reconnecting to old host)

If the device was previously paired to another OS via BLE, it will try to reconnect
to that host on power-up instead of advertising for new pairings. Fix:

1. On the **old paired OS**, remove/forget the device
2. Power-cycle the device — it will now advertise freely
3. Pair on the new OS

---

## Supported Distros

Tested on **Fedora 44**. Should work on any Linux distro with BlueZ (`/var/lib/bluetooth`).

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT

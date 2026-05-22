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
   - **MAC match** — fallback for public-address devices
   - **Device name match** — final fallback for devices that change IRK and address
     per pairing
3. If the device address changed (BLE devices often generate a new static random
   address per pairing), renames the Linux device directory to the Windows address
4. Writes all keys (`LongTermKey`, `PeripheralLongTermKey`, `IRK`, `CSRK`) into
   `/var/lib/bluetooth/<adapter>/<device>/info`
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

Some devices advertise as **two separate Bluetooth devices** — one Classic BR/EDR
(BT3.0) and one BLE (BT5.0) — using different MAC addresses and different protocols
on the same physical hardware.  **Both OSes must pair using the same protocol** —
`bt-sync` cannot bridge keys between BLE and Classic.

The **TeckNet EWM01308** mouse is a known example.  When you press the pairing
button, it advertises Classic (BT3.0) **first** for several seconds, then switches
to BLE (BT5.0).  There is no physical switch or button sequence to select the
protocol — you have to **wait** for the BT3.0 advertising to stop and the BT5.0
advertising to start before pairing.

How to pair on BLE (BT5.0) with the TeckNet EWM01308:

1. Press the pairing button — the LED blinks fast
2. Open your OS Bluetooth settings and start scanning
3. You will see **"BT3.0 Mouse"** appear first — **do not pair it**
4. Wait ~5–10 seconds — **"BT5.0 Mouse"** will appear
5. Pair "BT5.0 Mouse"

If you accidentally pair the BT3.0 device, remove it and try again.  If "BT5.0
Mouse" never appears, the device may already be bonded to another host via BLE —
remove that bond first (see "Device won't advertise BLE" below).

BLE (BT5.0) is recommended — better battery life and handled natively by `bt-sync`.

To check which protocol Linux actually paired with:
```bash
sudo cat /var/lib/bluetooth/<adapter>/<device>/info | grep -i "SupportedTechnologies\|AddressType"
```
- `SupportedTechnologies=LE;` + `AddressType=static` → **BLE (correct)**
- `SupportedTechnologies=BR/EDR;` + `LinkKey` section present → **Classic**

### Device won't advertise BLE for pairing (keeps reconnecting to old host)

If the device was previously paired to another OS via BLE, it will try to reconnect
to that host on power-up instead of advertising for new pairings. Fix:

1. On the **old paired OS**, remove/forget the device
2. Power-cycle the device — it will now advertise freely
3. Pair on the new OS

### `bt-sync` says "No matching Windows BLE entry found"

Some BLE devices generate a **new IRK and address** every time they pair, so the
tool can't match by IRK or MAC.  `bt-sync` falls back to **device name matching**
in this case.  For the fallback to work:

1. There must be exactly **one** active BLE device in the Windows registry
2. The device name must match between Linux and Windows
3. The device must have been scanned in Linux at least once (name cached in
   `/var/lib/bluetooth/<adapter>/cache/`)

If the fallback still fails, pair the device fresh in both OSes (Linux first,
then Windows) and run `bt-sync` again.

---

## BLE Quirks: Why Some Devices Are Harder Than Others

Most dual-boot Bluetooth guides assume simple BLE behaviour: the device keeps
the same MAC address and IRK across pairings, and keys just need byte-reversal
between Windows and Linux.  **This is not always true.**

Some BLE devices (notably cheap HID peripherals like the TeckNet EWM01308 mouse)
exhibit a combination of behaviours that makes dual-boot key sharing significantly
more difficult:

### What makes these devices tricky

| Behaviour | "Normal" BLE device | Tricky device (e.g. TeckNet EWM01308) |
|-----------|---------------------|---------------------------------------|
| MAC address | Same across pairings | **New static random address per pairing** |
| IRK | Same across pairings | **New IRK per pairing** |
| Advertising | Undirected (visible to all) | **Directed to last-paired host only** |
| Key byte order | May need reversal | **No reversal needed** |
| LTK roles | Separate central/peripheral | **Same LTK for both roles** |
| Protocol selection | Single protocol or physical switch | **Advertises BT3.0 first, then BT5.0 after a delay** |

**Each of these quirks breaks a different assumption** in typical dual-boot tools:

1. **New address per pairing**: After pairing in Windows, the device has a
   different MAC than Linux knows.  Linux scans for the old address and never
   finds the device.  `bt-sync` handles this by renaming the Linux device
   directory to the Windows address.

2. **New IRK per pairing**: The tool can't match the Linux device to its Windows
   counterpart by IRK (they're completely different).  `bt-sync` falls back to
   matching by device name.

3. **Directed advertising**: After bonding, the device only talks to the host it
   last paired with.  If the keys are wrong, the device appears completely
   invisible — not just "paired but won't connect" but literally absent from
   BLE scans.  This makes debugging extremely confusing.

4. **No byte reversal**: Contrary to widespread advice, BLE keys (LTK, IRK,
   CSRK) do **not** need byte-reversal between Windows and Linux.  Both stores
   use the same byte order.  Reversing keys causes a MIC Failure on connection
   — an error identical in appearance to having the wrong key entirely.

5. **Same LTK for both roles**: BlueZ maintains separate `[LongTermKey]` and
   `[PeripheralLongTermKey]` sections.  If only one is updated, encryption
   fails when the device initiates reconnection (which mice always do).
   `bt-sync` writes the Windows LTK to both sections.

6. **BT3.0-first dual advertising**: The device advertises Classic BR/EDR
   (BT3.0) first when the pairing button is pressed, then switches to BLE
   (BT5.0) after several seconds.  There is no physical switch to select the
   protocol.  If you pair the BT3.0 device by mistake, the keys are Classic
   link keys and incompatible with the BLE pairing on the other OS.  You must
   wait for "BT5.0 Mouse" to appear and pair that instead.

### Step-by-step for tricky BLE devices

If you have a BLE device (mouse, keyboard) that fails with the standard workflow,
follow these exact steps.  Tested with the **TeckNet EWM01308** mouse on
**Fedora 44** (BlueZ 5.86, kernel 6.x) and **Windows 11**.

1. **Remove the device in both OSes** (Linux: Bluetooth settings → Remove;
   Windows: Bluetooth settings → Remove device)
2. **Boot Linux, pair the device via BLE** — this establishes a Linux device
   directory and caches the device name.  If the device has dual BT3.0/BT5.0
   modes (like the TeckNet), wait for "BT5.0 Mouse" to appear before pairing.
3. **Boot Windows, pair the device via BLE** — again, make sure you pair the
   BT5.0 device, not BT3.0.  This is the canonical pairing; the device stores
   Windows' host identity
4. **Boot Linux**, mount the Windows partition, and run:
   ```bash
   sudo uv run bt-sync --verbose
   ```
   The output should show the address change and key updates.
5. **Restart Bluetooth**:
   ```bash
   sudo systemctl restart bluetooth
   ```
6. **Wake the device** (move the mouse / press a key) — it should connect
   within a few seconds
7. **Verify** the device works, then reboot into Windows to confirm it still
   works there too

### Known tested hardware

| Device | Type | Protocol | OS | Quirks | Status |
|--------|------|----------|----|--------|--------|
| TeckNet EWM01308 | Mouse | BLE (BT5.0) | Fedora 44 (BlueZ 5.86) + Windows 11 | All 6 quirks above | ✅ Working |
| TeckNet EWM01308 | Mouse | Classic (BT3.0) | Fedora 44 (BlueZ 5.86) + Windows 11 | None (standard link key) | ✅ Working |

**Adapter**: MediaTek MT7921 (built-in laptop adapter, `C0:35:32:AC:13:4A`)

If you test with other hardware, please report your results.

---

## Supported Distros

Tested on **Fedora 44**. Should work on any Linux distro with BlueZ (`/var/lib/bluetooth`).

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT

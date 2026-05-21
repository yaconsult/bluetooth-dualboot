# BluetoothMouseDualBoot — Dev Log

## Goal
Make the same Bluetooth mouse work seamlessly in both Fedora Linux and Windows 11,
regardless of which OS is booted from GRUB, without manual re-pairing.

---

## Session 1 — 2026-05-20

### Problem Analysis

Bluetooth pairing stores cryptographic keys on both the host (OS) and the device (mouse).
When two OSes pair the same mouse independently, each generates different keys — breaking
the other OS's connection every time the mouse is re-paired.

**Mouse details (discovered):**
- Name: `BT5.0 Mouse`
- Protocol: **BLE (Bluetooth Low Energy)** — uses LTK, IRK, CSRK, EDiv, Rand
- MAC address: `E4:9F:64:0B:E8:1C` (static)
- BT adapter MAC: `C0:35:32:AC:13:4A`

**Second paired device (not the mouse):**
- Name: `Baseus BA01`
- Protocol: BR/EDR (Classic Bluetooth)
- MAC: `DF:D6:4F:C9:DC:97`

### Environment Confirmed

| Resource | Status |
|---|---|
| Linux BT keys (`/var/lib/bluetooth/C0:35:32:AC:13:4A/E4:9F:64:0B:E8:1C/info`) | ✅ Readable/writable with sudo |
| Windows partition (`/mnt/windows-drive`, NTFS label: Acer) | ✅ Mounted |
| Windows SYSTEM hive (`/mnt/windows-drive/Windows/System32/config/SYSTEM`) | ✅ Readable/writable |
| `chntpw` / `reged` | ❌ Not installed |
| `python-registry` | ❌ Not installed |
| `regipy` | ❌ Not installed |
| `python3` | ✅ Available at `/usr/bin/python3` |
| `uv` | To be confirmed |

### Approach Chosen: Option B

Mouse is currently working in **Fedora**. The plan:

1. User re-pairs the mouse in **Windows** (so Windows has valid, current keys).
2. A script reads the Linux BT keys from `/var/lib/bluetooth/`.
3. The same script injects those keys into the **Windows registry** SYSTEM hive
   at `HKLM\SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Keys\<adapter>\<device>`.
4. On next Windows boot, Windows uses the same keys the mouse already knows — no re-pairing needed.

### Constraints

- All Python dependencies must live in a project-local `.venv/` (isolated from OS).
- Use `uv` for venv and package management.
- Must survive OS updates without breakage.

### Current Linux BT Keys (for reference)

```
[IdentityResolvingKey]
Key=9CA8DC498406FE2496D9355156612611

[LongTermKey]
Key=6AA1ACBA40F3DDB60C78FA7C3B23A709
Authenticated=0
EncSize=16
EDiv=36159
Rand=4383710011340050161

[PeripheralLongTermKey]
Key=D10DB5CA0A3C98CDAC49A229A41E3406
Authenticated=0
EncSize=16
EDiv=19232
Rand=4284274170293064201

[LocalSignatureKey]
Key=8FBD1BD151ED14DD8508EF1F87677A96
Counter=0

[RemoteSignatureKey]
Key=8CF9AB0A68AFF9D2562F406B812DAB1C
Counter=0
```

### Next Steps (from Session 1)

- [x] Confirm `uv` is available
- [x] Set up `.venv` with `python-registry`, `black`, `ruff`, `pytest`
- [x] Explore Windows registry key structure
- [x] Write the sync script
- [x] Tests passing

---

## Session 2 — 2026-05-20 (continued)

### Key Discovery: Endianness Mismatch

Inspected the Windows registry and Linux info file side-by-side. Found:
- `ERand` and `EDiv` are **identical** in both OSes (same pairing session)
- LTK and IRK values are **byte-reversed** between Linux and Windows
- This is the known Linux(big-endian) ↔ Windows(little-endian) BLE key storage difference

Confirmed with Python: `reverse_hex_key(linux_ltk) == windows_ltk` → **True**

### Design Decisions

- **Generic tool** — auto-detects adapter, devices, NTFS mount, and hive path
- **CLI flags**: `--windows-mount`, `--bluez-dir`, `--dry-run`, `--verbose`
- **Sync all BLE devices** that have matching entries in both OSes
- **In-place hive patching** — updates existing Windows registry entry (no delete/recreate)
- Requires `sudo` (BlueZ dir and hive are root-owned)

### Module Structure

```
bluetooth_dualboot/
    utils.py       — MAC normalization, byte-reversal, NTFS mount detection
    linux_bt.py    — Read BLE keys from /var/lib/bluetooth/
    windows_bt.py  — Read/write Windows SYSTEM hive via python-registry + binary patching
    sync.py        — CLI entry point and orchestration
tests/
    test_utils.py
    test_linux_bt.py
```

### Test Results

12/12 tests passing. ruff + black clean.

### Next Steps (from Session 2)

- [x] Run dry-run to verify — pending (see Session 3)
- [x] Generalize to all device types

---

## Session 3 — 2026-05-20 (continued)

### Changes

- **Syncs all paired devices**, not just the mouse — BLE and Classic BR/EDR
- **Handles devices not yet paired in Windows** — creates new registry entries via `reged -I`
  (imports a generated `.reg` file into the hive)
- **Existing entries** — patched in-place as before (binary patch)
- Added `ClassicKeys` dataclass and `read_classic_keys()` to `linux_bt.py`
- Added `discover_all_devices()` — returns both BLE and Classic devices
- Added `WindowsClassicEntry`, `read_windows_classic_entries()`, `patch_classic_entry()`,
  `create_classic_entry()`, `create_ble_entry()` to `windows_bt.py`
- Renamed `write_ble_keys_to_hive()` → `patch_ble_entry()` for clarity
- `sync.py` fully rewritten to handle both types with create/patch branching

### Note on Classic BR/EDR byte order
Classic BT link keys do NOT need byte-reversal between Linux and Windows
(unlike BLE LTK/IRK). Stored as-is.

### Test Results

16/16 tests passing. ruff + black clean.

### Next Steps

- [ ] Run `sudo uv run bt-sync --dry-run --verbose` to verify live system detection
- [ ] Run `sudo uv run bt-sync` and test mouse in Windows
- [ ] Push to GitHub once verified working

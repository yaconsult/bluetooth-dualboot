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

### Next Steps (from Session 3)

- [x] Run dry-run — passed
- [x] Run live sync — passed (with bugs found and fixed, see Session 4)
- [ ] Boot into Windows and confirm mouse connects automatically
- [ ] Push to GitHub

---

## Session 4 — 2026-05-20 (continued)

### Changes

- **Auto-backup** of Windows SYSTEM hive added to `sync.py` — runs automatically before
  any write, timestamped, stored alongside the hive:
  `SYSTEM.bt-sync-backup-YYYYMMDD_HHMMSS`
- **Derived `auth_req`** from Linux `ltk_authenticated` field via `BLEKeys.auth_req` property
  (BT spec Vol 3 Part H Section 3.5.1 bitmask). No longer hardcoded.
- Documented Windows sentinel values in code comments (`InboundSignCounter`, `CEntralIRKStatus`)

### Bugs Found and Fixed During Live Testing

#### Bug 1 — `reged` exit code 2 incorrectly treated as fatal error

**Symptom:** `RuntimeError: reged import failed (exit 2)` even though reged output said
`operation SUCCEEDED`.

**Root cause:** `reged` uses exit code 2 for "warnings present" (e.g. UTF-16 BOM notice),
not for failure. Exit 1 is the actual fatal error code.

**Fix:** Changed error check from `returncode != 0` to `returncode == 1`.

Also switched `.reg` temp file encoding from `utf-16-le` to `utf-8` — reged handles
UTF-8 fine and the UTF-16 BOM was the source of the warning.

#### Bug 2 — Registry binary values written as QWORD integers instead of bytes

**Symptom:** After import, `LTK`, `IRK`, `CSRK` values read back as Python `int` instead
of `bytes`, meaning they were stored as REG_QWORD (64-bit integer) instead of REG_BINARY.

**Root cause:** `.reg` file format uses `hex(b):` prefix for `REG_QWORD` and `hex:` prefix
for `REG_BINARY`. The code was using `hex(b):` for all binary data.

**Fix:** Changed `_bytes_to_reg_hex()` to use `hex:` (REG_BINARY). Kept `hex(b):` only
in `_qword_to_reg_hex()` for actual 64-bit integer values (ERand, Address, counters).

### Live Test Results

**Run 1** (first attempt): Failed with Bug 1 (false error). Data was actually written
but with Bug 2 (wrong types). Restored from auto-backup.

**Run 2** (after Bug 1 fix): Succeeded (exit 0). Data written but Bug 2 present
(keys stored as integers). Restored from auto-backup.

**Run 3** (after Bug 2 fix): Succeeded (exit 0). All values correct types and values:

```
Subkey: e49f640be81c  (BT5.0 Mouse)
  [bytes] 'LTK':  09A7233B7CFA780CB6DDF340BAACA16A  ✅ correct (byte-reversed from Linux)
  [bytes] 'IRK':  112661565135D99624FE068449DCA89C  ✅ correct (byte-reversed from Linux)
  [int  ] 'KeyLength': 16                          ✅
  [int  ] 'ERand': 4383710011340050161              ✅ matches Linux
  [int  ] 'EDIV':  36159                            ✅ matches Linux
  [int  ] 'AuthReq': 41 (0x29)                     ✅ derived from ltk_authenticated=0
  [int  ] 'InboundSignCounter': 0xFFFFFFFFFFFFFFFF  ✅ Windows uninitialized sentinel
  [int  ] 'OutboundSignCounter': 0                  ✅ correct initial value
  [int  ] 'CEntralIRKStatus': 1                     ✅ IRK verified

Value: dfd64fc9dc97  (Baseus BA01 Classic)
  [bytes] 'dfd64fc9dc97': AF34A492D9CA9CA11330C4FC4D8475E3  ✅ matches Linux LinkKey
```

**Verification run** (dry-run after live sync):
```
Found 2 BLE + 1 Classic entry(ies) in Windows.
BLE keys already in sync — nothing to do.
Classic key already in sync — nothing to do.
```
Idempotent — re-running detects no changes needed. ✅

### Remaining (from Session 4)

- [x] Boot into Windows — mouse did NOT connect (see Session 5)
- [x] Push to GitHub

---

## Session 5 — 2026-05-20 (continued)

### Problem

Mouse did not connect after booting Windows. A second identical mouse entry briefly
appeared and disappeared in the Windows Bluetooth devices list.

### Root Cause

The mouse uses **Resolvable Private Addresses (RPA)**. When Windows previously paired
the mouse, it was advertising under the RPA `D8:B8:C3:8E:9F:D6` — so Windows stored
its registry entry under the key `d8b8c38e9fd6`. Linux paired the same mouse using
its **identity (static) address** `E4:9F:64:0B:E8:1C` and stored the key under `e49f640be81c`.

Our MAC-based matching failed to link these two entries, so `bt-sync` created a brand
new entry `e49f640be81c` with no device metadata (no Name, LEName, Appearance, etc.).
Windows saw two competing entries for the same device — the "ghost" second mouse.

The fix: **match on IRK first**. The IRK (Identity Resolving Key) is the stable
cryptographic identity of a BLE device regardless of what address it's currently
advertising. Both entries had the same IRK — that's the correct matching signal.

### Changes

- `_find_ble_win_entry()` in `sync.py` — match on IRK first (byte-reversed to Windows
  format), fall back to MAC match for public-address devices
- Fixed `find_subkey()` → `subkey()` — wrong `python-registry` API method name
  (this was a latent bug that only surfaced once the IRK match triggered a patch
  on the existing `d8b8c38e9fd6` entry for the first time)

### Result

`bt-sync` now correctly identifies `d8b8c38e9fd6` as the mouse and patches it
in-place — only the CSRKs needed updating (LTK/IRK were already correct from the
prior Windows pairing):

```
[BLE] BT5.0 Mouse (E4:9F:64:0B:E8:1C)
  Windows entry: found in Windows  (matched via IRK to d8b8c38e9fd6)
  Action: PATCH existing Windows BLE entry
  CSRK(inbound):  0FFC3A6F744E1B7D60EAC23AF1A72742 → 967A67871FEF0885DD14ED51D11BBD8F
  CSRK(outbound): 7D7A7896F42A90B5FE5A3BBB984DEAFE → 1CAB2D816B402F56D2F9AF680AABF98C
```

### Note on RPA vs identity address

For BLE devices with RPA:
- Windows stores the entry under whatever address the device was using when paired
- Linux stores the entry under the identity (static/public) address
- These MACs will differ — IRK is the only reliable cross-OS match key
- Classic BR/EDR devices always use a fixed public address — MAC matching is correct

### Remaining

- [ ] Boot into Windows — confirm mouse connects without re-pairing

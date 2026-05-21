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

### Remaining (from Session 5)

- [x] Boot into Windows — mouse still not connecting (see Session 6)

---

## Session 6 — 2026-05-20 (continued)

### Problem

Mouse still showed as "not connected" in Windows after Session 5 fix.

### Root Cause

The Windows registry entry `d8b8c38e9fd6` had `AddressType=0x0` (public address).
The mouse's actual address type is `static random` (`AddressType=0x1`). This mismatch
means Windows attempts to connect using the wrong address resolution mode, preventing
the connection from succeeding even though the cryptographic keys are correct.

The `d8b8c38e9fd6` entry was originally created by Windows when the mouse was advertising
via an RPA — Windows recorded `AddressType=0` at that time, but the correct value based
on the device's identity is `1` (static random), which is what Linux correctly stores.

### Changes

- `patch_ble_entry()` in `windows_bt.py` — added `address_type` parameter; patches
  `AddressType` DWORD via `reged` (safe, since raw binary search for small int values
  like 0x00000000 is unreliable in a large hive)
- `_sync_ble()` in `sync.py` — detects `AddressType` mismatch and passes corrected
  value to `patch_ble_entry()`; logs the change in verbose output

### Result

```
[BLE] BT5.0 Mouse (E4:9F:64:0B:E8:1C)
  Windows entry: found in Windows
  Action: PATCH existing Windows BLE entry
  CSRK(inbound):  0FFC... → 967A...
  CSRK(outbound): 7D7A... → 1CAB...
  AddressType: 0 → 1                    ← new fix
```

Registry verified:
  'AddressType': 0x1  ✅

### Remaining (from Session 6)

- [x] Boot into Windows — mouse still not connecting (see Session 7)

---

## Session 7 — 2026-05-20 (continued)

### Investigation

After AddressType fix still didn't work, inspected event logs and full registry state.
Windows event log (BTHUSB) entries exist for today's test boots but message text is
unavailable offline (requires the driver binary's message table).

Full registry inspection revealed:
- Keys hive: correct — LTK, IRK, CSRKs, AddressType=1 all look good
- BTHLEDevice enum: 5 service entries all pointing to `d8b8c38e9fd6` ✅
- BTHLE enum: `FriendlyName='BT5.0 Mouse'` ✅

### New Discovery: Mouse Has Two Protocols

The TeckNet EWM01308 advertises as **two separate Bluetooth devices**:
- `12:34:00:75:4D:05` — Classic BR/EDR (BT3.0 Mouse)
- `E4:9F:64:0B:E8:1C` — BLE (BT5.0 Mouse)

Same physical hardware, different radio protocols. The pairing button triggers Classic
mode advertising. BLE mode is separate.

### What Went Wrong

- Windows had paired the mouse as **BLE** (`d3b4bb9c552e` — a new fresh entry from
  the most recent re-pair session)
- Linux accidentally paired it as **Classic** (`12:34:00:75:4D:05`) during the
  re-pairing attempt
- The two OSes were using **different protocols** — `bt-sync` cannot bridge BLE↔Classic
- Additionally, because Windows still held the BLE pairing, the mouse was trying to
  **reconnect to Windows** on startup rather than advertising for new pairings —
  making it impossible to pair via BLE in Linux

### Resolution Plan

1. Boot Windows → **remove** BT5.0 Mouse pairing → **re-pair** it (fresh BLE entry)
2. Boot Linux → mouse now freely advertises BLE → pair `E4:9F:64:0B:E8:1C`
3. Run `sudo uv run bt-sync` → patches Windows BLE keys to match Linux
4. Boot Windows → mouse connects automatically

Status: Steps 1 completed (Windows remove + re-pair done). Steps 2-4 pending — will
test tomorrow.

### Key Learnings

- TeckNet EWM01308 pairing button = Classic mode only; BLE requires power-cycle when
  no host is remembered
- Must ensure both OSes pair using the **same protocol** (both BLE or both Classic)
- The stale `d8b8c38e9fd6` entry (from an older RPA session) should be cleaned up —
  it's no longer needed now that Windows has a fresh `d3b4bb9c552e` entry
- `bt-sync` idempotency check and backup-on-write-only are working correctly

### Active Entry Matching Fix

After the re-pairings, the registry had three BLE entries for the mouse:
- `e49f640be81c` — old stale entry from a previous sync (inactive)
- `fa7388ba3bfb` — entry with IRK matching Linux, but inactive (Windows not using it)
- `f6a2f5ec714b` — fresh Windows-only re-pair, **active** (`FriendlyName` in BTHLE enum)

`bt-sync` was matching by IRK to `fa7388ba3bfb` (already in sync) and doing nothing —
while Windows was connecting to `f6a2f5ec714b` with completely different keys.

**Root cause:** IRK-based matching alone is insufficient when Windows has re-paired
independently and the new entry has a different IRK. The BTHLE enum (`ControlSet001\Enum\BTHLE\Dev_<addr>`) indicates which entry Windows is actually using.

**Fix implemented:**
- `WindowsBLEEntry.is_active` field — set from BTHLE enum presence
- `_read_active_bthle_device_keys()` in `windows_bt.py` — reads BTHLE enum
- `_find_ble_win_entry()` in `sync.py` — updated matching logic:
  1. IRK match on active entry → return immediately
  2. IRK match on inactive entry + exactly one active entry → return the active entry
     (it's the device Windows re-paired; patch it to match Linux)
  3. IRK match on inactive entry + multiple active entries → use IRK match (safe)
  4. MAC match → fallback
- 7 new tests covering all matching cases

**Dry-run output confirms correct target:**
```
Action: PATCH existing Windows BLE entry
LTK:  462026BA... → 556D6AA5...    ← Windows→Linux
IRK:  915B169E... → 4417F67C...    ← Windows→Linux
CSRK(inbound):  E573A5E3... → D56A9161...
CSRK(outbound): ACFE2E0B... → ABBCE779...
```

### EDIV/ERand Missing from Patch (Second Fix)

After the active-entry fix, Windows still showed "not connected". Inspection revealed
`EDIV` and `ERand` in `f6a2f5ec714b` still had Windows' original values:

| Field | Windows (wrong) | Linux (correct) |
|-------|----------------|-----------------|
| EDIV  | `0xa645`       | `0x1aa1`        |
| ERand | `0x184589eddadcff4` | `0x49716aaeaa1f1429` |

`patch_ble_entry` was only patching LTK, IRK, and CSRKs — not EDIV/ERand. Windows
uses all of these together for session key derivation; mismatched EDIV/ERand causes
the connection to fail cryptographically even with a correct LTK.

**Fix:** Added `ediv` and `erand` params to `patch_ble_entry`; patched via `reged`
(DWORD and QWORD respectively — unsafe to patch as raw binary). `_sync_ble` now
detects and reports EDIV/ERand mismatches and passes them through.

**Live sync output:**
```
EDIV: 0xa645 → 0x1aa1
ERand: 0x184589eddadcff4 → 0x49716aaeaa1f1429
[BT5.0 Mouse] BLE keys patched in Windows registry.
```

### Remaining

- [ ] Boot Windows — confirm mouse connects automatically without re-pairing

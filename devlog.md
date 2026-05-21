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

### Next Steps

- [ ] Confirm `uv` is available or install it
- [ ] User re-pairs mouse in Windows
- [ ] Explore Windows registry key structure for BLE devices to confirm write target
- [ ] Set up `.venv` with required registry-parsing library (`python-registry` or `regipy`)
- [ ] Write the sync script
- [ ] Test

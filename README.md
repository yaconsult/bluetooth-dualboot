# bluetooth-dualboot

Sync Bluetooth mouse pairing keys between Fedora Linux and Windows 11 for seamless dual-boot usage — no re-pairing required when switching OS.

## Problem

When a Bluetooth mouse is paired independently in two OSes, each OS generates different cryptographic keys and overwrites the mouse's stored keys, breaking the other OS's connection.

## Solution

Pair the mouse in both OSes once, then use this tool to inject the Linux BLE keys into the Windows registry so both OSes share the same key set.

## Setup

```bash
uv sync --group dev
```

## Usage

```bash
uv run bt-sync
```

## Requirements

- Fedora Linux with `sudo`
- Windows partition mounted (e.g. `/mnt/windows-drive`)
- Mouse paired in both OSes at least once

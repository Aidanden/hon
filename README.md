# HoN Net Guard / ZYTONA APP

Python tool that stabilizes your network while playing **Heroes of Newerth Reborn** on **Windows** and **Linux**.

## Publish Windows .exe (ZYTONA APP)

Build **must be done on a Windows PC** (PyInstaller cannot produce a real Windows EXE from Linux).

1. Copy this project folder to Windows
2. Install [Python 3.10+](https://www.python.org/downloads/) and tick **Add to PATH**
3. Double-click **`build_windows.bat`**
4. Wait until it finishes — output file:

```text
dist\ZYTONA_APP.exe
```

5. Run `ZYTONA_APP.exe` (UAC Admin prompt appears automatically)

Or use `run_zytona_exe.bat` after building.

### What the build does
- Installs `psutil` + `pyinstaller`
- Packs the GUI into a single `.exe`
- Requests Administrator rights (needed for Windows QoS)

## Problem

Internet works fine until you open the game:
- timeouts
- bandwidth saturation
- high ping

## Windows (Python source)

1. Install Python 3.10+ with Add to PATH
2. Right-click `run_as_admin.bat` → **Run as administrator**
3. Enter your real download speed → share ~50–60% → **Enable**

Uses **Windows QoS** on `juvio.exe` / `hon.exe`.

## Linux

1. Install dependencies:

```bash
# Fedora
sudo dnf install python3 python3-tkinter python3-pip iproute

# Ubuntu / Debian
sudo apt install python3 python3-tk python3-pip iproute2
```

2. Run:

```bash
chmod +x run_linux.sh
./run_linux.sh
# or:
sudo ./run_linux.sh
```

3. Enter your speed → **Enable** → launch the game (Wine / Lutris / native)

Uses **tc + IFB + CAKE/HTB** on the default interface.

## Max Ping 100% mode

- Leaves more headroom (~38% of link used as cap)
- Measures ping before/after
- Linux: CAKE + sysctl/BBR tweaks
- Windows: Nagle off + Games profile + Delivery Optimization off

## Suggested settings

| Link speed | Cap share | Approx result |
|------------|-----------|---------------|
| 10 Mbps    | 50%       | ≈ 5 Mbps      |
| 20 Mbps    | 55%       | ≈ 11 Mbps     |
| 50 Mbps    | 60%       | ≈ 30 Mbps     |

If timeouts remain: lower share to **40–45%**.

## Generic run

```bash
pip install -r requirements.txt
python main.py
```

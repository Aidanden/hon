# HoN Net Guard

Python tool that stabilizes your network while playing **Heroes of Newerth Reborn** on **Windows** and **Linux**.

## Problem

Internet works fine until you open the game:
- timeouts
- bandwidth saturation
- high ping

## Windows

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

Uses **tc + IFB + CAKE/HTB** on the default interface (caps download/upload and reduces bufferbloat).

Manual stop:

```bash
sudo tc qdisc del dev $(ip route show default | awk '/default/ {print $5; exit}') ingress
sudo tc qdisc del dev $(ip route show default | awk '/default/ {print $5; exit}') root
sudo ip link delete ifb-hon 2>/dev/null || true
```

## Max Ping 100% mode

The **Enable Max Ping 100%** button:
- Leaves more headroom (~38% of link used as cap)
- Measures ping before/after
- Linux: CAKE `diffserv4` + `ack-filter` + sysctl/BBR tweaks
- Windows: disable Nagle + Games profile + Delivery Optimization off
- Live ping-improvement meter (reaches 100% when stable: no saturation, no timeouts)

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
# Windows (Admin) or Linux (root):
python main.py
```

## Linux note

On Linux the cap applies to the **whole interface** (not only the game process). That is intentional to stop link saturation while playing. Stop the guard after gaming to restore full speed.

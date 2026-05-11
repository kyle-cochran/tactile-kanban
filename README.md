# Tactile Kanban

A physical Kanban board backed by GitHub Projects. E-paper tags display live ticket information; NFC stickers on each tag let you move a ticket to a new column by tapping it on the column's PN532 reader.

```
┌──────────┐  ┌─────────────┐  ┌─────────┐  ┌──────┐
│  READY   │  │ IN PROGRESS │  │ BLOCKED │  │ DONE │
│  PN532   │  │   PN532     │  │  PN532  │  │PN532 │
│  0x24    │  │   0x25      │  │  0x26   │  │ 0x27 │
│          │  │             │  │         │  │      │
│ [tag][tag│  │   [tag]     │  │  [tag]  │  │[tag] │
└──────────┘  └─────────────┘  └─────────┘  └──────┘
```

Each physical card = one e-paper display tag (OpenEPaperLink) + one NFC sticker.  
Tapping a card on a column reader moves that ticket to the corresponding GitHub status.

---

## Hardware

| Part | Notes |
|------|-------|
| Raspberry Pi 4 or 5 | Runs the service |
| OpenEPaperLink Access Point | Manages the e-paper displays over 802.15.4 |
| E-paper display tags | Any OEPL-compatible tag |
| PN532 NFC reader boards (×4) | One per column; wired to I2C at 0x24–0x27 |
| NFC stickers (×1 per card) | Attached to the back of each e-paper tag |

### PN532 I2C wiring (per reader)

```
PN532        Raspberry Pi header
─────        ───────────────────
VCC    →     3.3 V  (pin 1)
GND    →     GND    (pin 6)
SDA    →     GPIO 2 (pin 3)
SCL    →     GPIO 3 (pin 5)
```

Set each board's address jumpers (A0/A1):

| Column      | A1 | A0 | Address |
|-------------|----|----|---------|
| Ready       | 0  | 0  | 0x24    |
| In Progress | 0  | 1  | 0x25    |
| Blocked     | 1  | 0  | 0x26    |
| Done        | 1  | 1  | 0x27    |

Enable I2C on the Pi if you haven't already — uncomment `dtparam=i2c_arm=on` in `/boot/firmware/config.txt` and reboot.

---

## Software setup

```bash
git clone <repo-url> tactile-kanban
cd tactile-kanban
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Copy and fill in the environment file:

```bash
cp .env.example .env
nano .env
```

| Variable | Description |
|----------|-------------|
| `OEPL_AP_HOST` | IP address of the OpenEPaperLink access point |
| `GITHUB_TOKEN` | Personal access token — needs `read:org`, `project`, `repo` scopes |
| `GITHUB_ORG` | GitHub org or username that owns the project |
| `GITHUB_PROJECT_NUMBER` | Number from the project URL (`.../projects/<number>`) |
| `SPRINT_PREFIX` | Iteration name prefix used to find the current sprint (default: `Sprint`) |
| `SYNC_INTERVAL` | Seconds between GitHub syncs while the service runs (default: `300`) |
| `DB_PATH` | Path to the SQLite database file (default: `kanban.db`) |

---

## First-time setup

### 1. Pull the current sprint from GitHub

Fetches all sprint items and refreshes any already-assigned displays:

```bash
python3 main.py sync
```

### 2. Assign tickets to tags

Walks through the unassigned sprint items and lets you pair them with physical tags:

```bash
python3 main.py assign
```

You'll be shown a numbered list of available tags and unassigned tickets. Enter pairs as `<tag>:<ticket>` (e.g. `0:2 1:0`).

### 3. Register NFC stickers

Links each physical NFC sticker to its e-paper tag so column taps are recognised.  
See **[Linking new tags](#linking-new-tags)** below for the full walkthrough.

```bash
python3 main.py register-nfc
```

### 4. Start the service

```bash
python3 main.py run
```

---

## Linking new tags

Run this whenever you add new e-paper tags that haven't had their NFC sticker registered yet, or to re-register everything from scratch.

### Normal run — only unregistered tags

```bash
python3 main.py register-nfc
```

### Full re-registration — clears all existing links first

```bash
python3 main.py register-nfc --force
```

### What happens

1. All unregistered tags immediately receive a **"WAITING TO REGISTER"** screen so they are easy to distinguish from the active one.
2. The first unregistered tag gets a **"TAP ME ON READY"** prompt (yellow header).
3. Walk to the board and tap that tag's NFC sticker on the **Ready column reader** (0x24).
4. The display updates to **"REGISTERED"** and the script moves on to the next tag.
5. Repeat until all tags are done. Press **Enter** at any prompt to skip a tag.

### Tips

- After tapping, wait for the sticker to leave the reader field before moving on — the script debounces so a sticker resting on the reader won't re-trigger.
- If you accidentally tap the wrong sticker, the script will warn you (`UID already linked to …`) and keep waiting for a different one.
- Tags check in with the AP roughly every 40 seconds during registration, so allow up to 40 s for the display to update after each step.
- After registration is complete, run `assign` to pair any newly registered tags with tickets, then `sync` to push the ticket content to their displays.

---

## Running the service

### Manual

```bash
source .venv/bin/activate
python3 main.py run
```

The service:
- Polls for NFC taps continuously
- Syncs with GitHub every `SYNC_INTERVAL` seconds (default 5 minutes)
- Updates the relevant display immediately when a tap moves a ticket

### As a systemd service

Edit `kanban-epaper.service` to match your username and install path, then install it:

```bash
sudo cp kanban-epaper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable kanban-epaper
sudo systemctl start kanban-epaper
```

Check status and logs:

```bash
sudo systemctl status kanban-epaper
journalctl -u kanban-epaper -f
```

---

## CLI reference

| Command | Description |
|---------|-------------|
| `python3 main.py sync` | One-shot sync: fetch sprint from GitHub, refresh all assigned displays |
| `python3 main.py run` | Start the continuous service (NFC polling + periodic sync) |
| `python3 main.py assign` | Interactively assign sprint tickets to unassigned tags |
| `python3 main.py register-nfc` | Register NFC sticker UIDs for unregistered tags |
| `python3 main.py register-nfc --force` | Re-register all tags from scratch |
| `python3 main.py status` | Print a table of current tag → ticket assignments |

---

## Database

Tag and ticket data is stored locally in `kanban.db` (SQLite). The two relevant tables:

- **`tags`** — one row per e-paper display; stores MAC, dimensions, alias, and the linked NFC sticker UID
- **`assignments`** — maps each tag to a GitHub issue with its current status

The database persists across restarts and service updates. Back it up before re-registering:

```bash
cp kanban.db kanban.db.bak
```

# Road to Vostok Save Game Syncer

Syncs Road to Vostok save games (`.tres` files) between two Windows PCs over your local network using SSH/SFTP. Automatically detects which machine has the newer saves, backs up the older versions, and copies the latest files across.

## Features

- Scans `%APPDATA%\Road to Vostok` for `.tres` save files
- Compares file timestamps between local and remote machines
- Backs up older saves before overwriting (stored in a `_backups` subfolder)
- Transfers files via SFTP (password-based authentication, no SSH keys required)
- Simple GUI built with tkinter
- Saves connection settings between sessions

## Prerequisites

Both PCs need:
- **Windows 10/11**
- **OpenSSH Server** enabled on the remote PC (Settings > Apps > Optional Features > OpenSSH Server), or any other SSH server (e.g. [Bitvise SSH Server](https://www.bitvise.com/ssh-server))

## Quick Start

### Option 1: Download the release executable

1. Go to the [Releases](../../releases) page
2. Download `VostokSaveSync.exe`
3. Run it — no Python installation needed

### Option 2: Run from source

```bash
pip install -r requirements.txt
python run.py
```

## Usage

1. **Remote Connection**: Enter the IP address, port (default 22), username, and password of your other PC
2. **Local Path**: Auto-detected as `%APPDATA%\Road to Vostok` — change if needed
3. **Remote Path**: Enter the save directory path on the remote PC, e.g. `C:/Users/OtherUser/AppData/Roaming/Road to Vostok`
4. **Check Status**: Shows all save files on both machines with their timestamps
5. **Sync Now**: Backs up older files and copies newer ones in both directions
6. **Save Settings**: Persists your connection info for next time

## How Sync Works

1. Scans both local and remote save directories for `.tres` files
2. Compares modification timestamps for each file
3. If local is newer: backs up the remote copy, then uploads the local file
4. If remote is newer: backs up the local copy, then downloads the remote file
5. Files that exist on only one side are copied to the other
6. Files within 2 seconds of the same timestamp are considered identical

## Building the Executable

```bash
pip install pyinstaller
pyinstaller vostok_sync.spec
```

The output will be at `dist/VostokSaveSync.exe`.

## CI/CD

The GitHub Actions workflow (`.github/workflows/build.yml`) automatically:
- Builds `VostokSaveSync.exe` on every push and PR to `main`
- Uploads the `.exe` as a build artifact
- Creates a GitHub Release with the `.exe` when you push a version tag (e.g. `v1.0.0`)

## License

MIT License - see [LICENSE](LICENSE).

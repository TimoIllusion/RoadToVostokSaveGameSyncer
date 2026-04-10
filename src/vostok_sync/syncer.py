"""Core sync logic for Road to Vostok save game files.

Handles local file scanning, remote SSH/SFTP connections (password-based),
timestamp comparison, backup creation, and bidirectional sync.
"""

import os
import shutil
import stat
import logging
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from dataclasses import dataclass, field

import paramiko

logger = logging.getLogger(__name__)

DEFAULT_SAVE_DIR = os.path.join(
    os.environ.get("APPDATA", ""), "Road to Vostok"
)
SAVE_EXTENSIONS = {".tres"}
BACKUP_DIR_NAME = "_backups"


@dataclass
class FileInfo:
    """Metadata about a save file."""
    relative_path: str
    full_path: str
    modified_time: float  # UTC timestamp
    size: int

    @property
    def modified_dt(self) -> datetime:
        return datetime.fromtimestamp(self.modified_time, tz=timezone.utc)


@dataclass
class SyncPlan:
    """Describes the actions the syncer will take."""
    upload: list[FileInfo] = field(default_factory=list)    # local -> remote
    download: list[FileInfo] = field(default_factory=list)  # remote -> local
    conflicts: list[tuple[FileInfo, FileInfo]] = field(default_factory=list)
    local_only: list[FileInfo] = field(default_factory=list)
    remote_only: list[FileInfo] = field(default_factory=list)


def scan_local_saves(save_dir: str) -> dict[str, FileInfo]:
    """Scan the local save directory for .tres files."""
    results: dict[str, FileInfo] = {}
    save_path = Path(save_dir)

    if not save_path.exists():
        logger.warning("Local save directory does not exist: %s", save_dir)
        return results

    for fpath in save_path.rglob("*"):
        if fpath.suffix.lower() in SAVE_EXTENSIONS and fpath.is_file():
            if BACKUP_DIR_NAME in fpath.parts:
                continue
            rel = str(fpath.relative_to(save_path))
            st = fpath.stat()
            results[rel] = FileInfo(
                relative_path=rel,
                full_path=str(fpath),
                modified_time=st.st_mtime,
                size=st.st_size,
            )
    return results


def scan_remote_saves(
    sftp: paramiko.SFTPClient, remote_dir: str
) -> dict[str, FileInfo]:
    """Recursively scan the remote save directory for .tres files via SFTP."""
    results: dict[str, FileInfo] = {}

    def _walk(current_dir: str, base_dir: str) -> None:
        try:
            entries = sftp.listdir_attr(current_dir)
        except IOError:
            logger.warning("Cannot list remote directory: %s", current_dir)
            return

        for entry in entries:
            entry_path = current_dir.rstrip("/") + "/" + entry.filename
            if stat.S_ISDIR(entry.st_mode or 0):
                if entry.filename == BACKUP_DIR_NAME:
                    continue
                _walk(entry_path, base_dir)
            elif stat.S_ISREG(entry.st_mode or 0):
                # Use PurePosixPath for remote (could be Linux) then normalize
                ext = PurePosixPath(entry.filename).suffix.lower()
                if ext in SAVE_EXTENSIONS:
                    rel = entry_path[len(base_dir):].lstrip("/")
                    # Normalize to Windows-style relative path for comparison
                    rel_win = str(PureWindowsPath(PurePosixPath(rel)))
                    results[rel_win] = FileInfo(
                        relative_path=rel_win,
                        full_path=entry_path,
                        modified_time=entry.st_mtime or 0,
                        size=entry.st_size or 0,
                    )

    _walk(remote_dir, remote_dir)
    return results


def build_sync_plan(
    local_files: dict[str, FileInfo],
    remote_files: dict[str, FileInfo],
) -> SyncPlan:
    """Compare local and remote files to determine sync actions.

    The newer file always wins. The older file gets backed up before overwrite.
    """
    plan = SyncPlan()
    all_keys = set(local_files.keys()) | set(remote_files.keys())

    for key in sorted(all_keys):
        local = local_files.get(key)
        remote = remote_files.get(key)

        if local and not remote:
            plan.local_only.append(local)
            plan.upload.append(local)
        elif remote and not local:
            plan.remote_only.append(remote)
            plan.download.append(remote)
        elif local and remote:
            # Compare timestamps - newer wins
            if abs(local.modified_time - remote.modified_time) < 2:
                # Within 2 seconds = same file, skip
                continue
            elif local.modified_time > remote.modified_time:
                plan.upload.append(local)
            else:
                plan.download.append(remote)

    return plan


def _ensure_local_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _ensure_remote_dir(sftp: paramiko.SFTPClient, remote_path: str) -> None:
    """Create remote directories recursively."""
    dirs_to_create = []
    current = os.path.dirname(remote_path).replace("\\", "/")

    while current and current != "/":
        try:
            sftp.stat(current)
            break
        except IOError:
            dirs_to_create.append(current)
            current = os.path.dirname(current).replace("\\", "/")

    for d in reversed(dirs_to_create):
        try:
            sftp.mkdir(d)
        except IOError:
            pass  # may already exist


def backup_local_file(save_dir: str, relative_path: str) -> str | None:
    """Back up a local file before overwriting it."""
    src = os.path.join(save_dir, relative_path)
    if not os.path.exists(src):
        return None

    backup_dir = os.path.join(save_dir, BACKUP_DIR_NAME)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{Path(relative_path).stem}_{timestamp}{Path(relative_path).suffix}"
    backup_path = os.path.join(backup_dir, backup_name)

    os.makedirs(backup_dir, exist_ok=True)
    shutil.copy2(src, backup_path)
    logger.info("Backed up local file: %s -> %s", src, backup_path)
    return backup_path


def backup_remote_file(
    sftp: paramiko.SFTPClient, remote_dir: str, relative_path: str
) -> str | None:
    """Back up a remote file before overwriting it."""
    # Normalize path separators for remote
    rel_posix = relative_path.replace("\\", "/")
    src = remote_dir.rstrip("/") + "/" + rel_posix

    try:
        sftp.stat(src)
    except IOError:
        return None

    backup_dir = remote_dir.rstrip("/") + "/" + BACKUP_DIR_NAME
    try:
        sftp.mkdir(backup_dir)
    except IOError:
        pass  # already exists

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = PurePosixPath(rel_posix).name
    stem = PurePosixPath(name).stem
    suffix = PurePosixPath(name).suffix
    backup_path = backup_dir + "/" + f"{stem}_{timestamp}{suffix}"

    # SFTP rename = copy on same host
    # Read and re-write since SFTP has no server-side copy
    with sftp.open(src, "rb") as f_in:
        data = f_in.read()
    with sftp.open(backup_path, "wb") as f_out:
        f_out.write(data)

    logger.info("Backed up remote file: %s -> %s", src, backup_path)
    return backup_path


class SaveGameSyncer:
    """Manages SSH connection and sync operations."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 22,
        local_save_dir: str = "",
        remote_save_dir: str = "",
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.local_save_dir = local_save_dir or DEFAULT_SAVE_DIR
        self.remote_save_dir = remote_save_dir
        self._ssh: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None

    def connect(self) -> None:
        """Establish SSH connection with password auth (no SSH keys)."""
        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        logger.info(
            "Connecting to %s@%s:%d (password auth)...",
            self.username, self.host, self.port,
        )
        self._ssh.connect(
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            look_for_keys=False,
            allow_agent=False,
        )
        self._sftp = self._ssh.open_sftp()
        logger.info("Connected successfully.")

    def disconnect(self) -> None:
        if self._sftp:
            self._sftp.close()
            self._sftp = None
        if self._ssh:
            self._ssh.close()
            self._ssh = None
        logger.info("Disconnected.")

    def check_status(self) -> tuple[dict[str, FileInfo], dict[str, FileInfo]]:
        """Scan local and remote save files and return both sets."""
        local_files = scan_local_saves(self.local_save_dir)
        if self._sftp is None:
            raise RuntimeError("Not connected. Call connect() first.")
        remote_files = scan_remote_saves(self._sftp, self.remote_save_dir)
        return local_files, remote_files

    def plan_sync(self) -> SyncPlan:
        """Build a sync plan by comparing local and remote files."""
        local_files, remote_files = self.check_status()
        return build_sync_plan(local_files, remote_files)

    def execute_sync(
        self, progress_callback=None
    ) -> dict[str, list[str]]:
        """Run the full sync: compare, backup older, transfer newer.

        Returns a summary dict with keys 'uploaded', 'downloaded', 'backed_up'.
        """
        if self._sftp is None:
            raise RuntimeError("Not connected. Call connect() first.")

        local_files, remote_files = self.check_status()
        plan = build_sync_plan(local_files, remote_files)

        summary: dict[str, list[str]] = {
            "uploaded": [],
            "downloaded": [],
            "backed_up": [],
        }

        total = len(plan.upload) + len(plan.download)
        done = 0

        # Upload: local is newer -> backup remote, then upload
        for fi in plan.upload:
            rel_posix = fi.relative_path.replace("\\", "/")
            remote_path = self.remote_save_dir.rstrip("/") + "/" + rel_posix

            # Backup remote if it exists
            if fi.relative_path in remote_files:
                bp = backup_remote_file(
                    self._sftp, self.remote_save_dir, fi.relative_path
                )
                if bp:
                    summary["backed_up"].append(f"remote:{bp}")

            # Upload
            _ensure_remote_dir(self._sftp, remote_path)
            self._sftp.put(fi.full_path, remote_path)
            logger.info("Uploaded: %s -> %s", fi.full_path, remote_path)
            summary["uploaded"].append(fi.relative_path)

            done += 1
            if progress_callback:
                progress_callback(done, total, f"Uploaded: {fi.relative_path}")

        # Download: remote is newer -> backup local, then download
        for fi in plan.download:
            local_path = os.path.join(self.local_save_dir, fi.relative_path)

            # Backup local if it exists
            if fi.relative_path in local_files:
                bp = backup_local_file(self.local_save_dir, fi.relative_path)
                if bp:
                    summary["backed_up"].append(f"local:{bp}")

            # Download
            _ensure_local_dir(local_path)
            self._sftp.get(fi.full_path, local_path)
            logger.info("Downloaded: %s -> %s", fi.full_path, local_path)
            summary["downloaded"].append(fi.relative_path)

            done += 1
            if progress_callback:
                progress_callback(done, total, f"Downloaded: {fi.relative_path}")

        if total == 0:
            logger.info("Everything is already in sync.")
            if progress_callback:
                progress_callback(0, 0, "Everything is already in sync.")

        return summary

"""Tkinter GUI for Road to Vostok Save Game Syncer."""

import logging
import os
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from datetime import datetime, timezone

from .config import SyncConfig
from .syncer import SaveGameSyncer, DEFAULT_SAVE_DIR, scan_local_saves

logger = logging.getLogger(__name__)


class TextHandlerWidget(logging.Handler):
    """Routes log messages into a tkinter ScrolledText widget."""

    def __init__(self, text_widget: scrolledtext.ScrolledText):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record) + "\n"
        self.text_widget.after(0, self._append, msg)

    def _append(self, msg: str) -> None:
        self.text_widget.configure(state="normal")
        self.text_widget.insert(tk.END, msg)
        self.text_widget.see(tk.END)
        self.text_widget.configure(state="disabled")


class SyncerApp:
    """Main application window."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Road to Vostok - Save Game Syncer")
        self.root.geometry("780x680")
        self.root.minsize(640, 520)
        self.root.resizable(True, True)

        self.config = SyncConfig.load()
        self._syncer: SaveGameSyncer | None = None
        self._busy = False

        self._build_ui()
        self._setup_logging()
        self._load_config_into_fields()
        logger.info("Application started.")

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("vista")  # Windows native look
        except tk.TclError:
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass

        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # -- Connection settings -----------------------------------------
        conn_frame = ttk.LabelFrame(main, text="Remote Connection (SSH)", padding=8)
        conn_frame.pack(fill=tk.X, pady=(0, 6))

        row = ttk.Frame(conn_frame)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Host:", width=12).pack(side=tk.LEFT)
        self.host_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.host_var, width=30).pack(
            side=tk.LEFT, padx=(0, 10)
        )
        ttk.Label(row, text="Port:").pack(side=tk.LEFT)
        self.port_var = tk.StringVar(value="22")
        ttk.Entry(row, textvariable=self.port_var, width=6).pack(side=tk.LEFT)

        row2 = ttk.Frame(conn_frame)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Username:", width=12).pack(side=tk.LEFT)
        self.user_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.user_var, width=20).pack(
            side=tk.LEFT, padx=(0, 10)
        )
        ttk.Label(row2, text="Password:").pack(side=tk.LEFT)
        self.pass_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.pass_var, width=20, show="*").pack(
            side=tk.LEFT
        )

        # -- Directory settings ------------------------------------------
        dir_frame = ttk.LabelFrame(main, text="Save Directories", padding=8)
        dir_frame.pack(fill=tk.X, pady=(0, 6))

        row3 = ttk.Frame(dir_frame)
        row3.pack(fill=tk.X, pady=2)
        ttk.Label(row3, text="Local Path:", width=12).pack(side=tk.LEFT)
        self.local_dir_var = tk.StringVar(value=DEFAULT_SAVE_DIR)
        ttk.Entry(row3, textvariable=self.local_dir_var, width=50).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4)
        )
        ttk.Button(row3, text="Browse", command=self._browse_local).pack(
            side=tk.LEFT
        )

        row4 = ttk.Frame(dir_frame)
        row4.pack(fill=tk.X, pady=2)
        ttk.Label(row4, text="Remote Path:", width=12).pack(side=tk.LEFT)
        self.remote_dir_var = tk.StringVar()
        ttk.Entry(row4, textvariable=self.remote_dir_var, width=50).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        # -- Action buttons ----------------------------------------------
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(0, 6))

        self.btn_check = ttk.Button(
            btn_frame, text="Check Status", command=self._on_check
        )
        self.btn_check.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_sync = ttk.Button(
            btn_frame, text="Sync Now", command=self._on_sync
        )
        self.btn_sync.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_save_cfg = ttk.Button(
            btn_frame, text="Save Settings", command=self._on_save_config
        )
        self.btn_save_cfg.pack(side=tk.LEFT, padx=(0, 6))

        # Progress bar
        self.progress = ttk.Progressbar(btn_frame, mode="determinate", length=200)
        self.progress.pack(side=tk.RIGHT, padx=(6, 0))

        # -- Log output --------------------------------------------------
        log_frame = ttk.LabelFrame(main, text="Log", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=16, state="disabled", wrap=tk.WORD, font=("Consolas", 9)
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _setup_logging(self) -> None:
        handler = TextHandlerWidget(self.log_text)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
        )
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)

    # ------------------------------------------------------------------ Config
    def _load_config_into_fields(self) -> None:
        self.host_var.set(self.config.remote_host)
        self.port_var.set(str(self.config.remote_port))
        self.user_var.set(self.config.remote_username)
        self.pass_var.set(self.config.remote_password)
        if self.config.local_save_dir:
            self.local_dir_var.set(self.config.local_save_dir)
        if self.config.remote_save_dir:
            self.remote_dir_var.set(self.config.remote_save_dir)

    def _fields_to_config(self) -> SyncConfig:
        return SyncConfig(
            remote_host=self.host_var.get().strip(),
            remote_port=int(self.port_var.get().strip() or "22"),
            remote_username=self.user_var.get().strip(),
            remote_password=self.pass_var.get(),
            local_save_dir=self.local_dir_var.get().strip(),
            remote_save_dir=self.remote_dir_var.get().strip(),
        )

    def _on_save_config(self) -> None:
        cfg = self._fields_to_config()
        path = cfg.save()
        self.config = cfg
        logger.info("Settings saved to %s", path)

    # ------------------------------------------------------------------ Browse
    def _browse_local(self) -> None:
        d = filedialog.askdirectory(
            title="Select local save directory",
            initialdir=self.local_dir_var.get() or os.path.expanduser("~"),
        )
        if d:
            self.local_dir_var.set(d)

    # ------------------------------------------------------------------ Actions
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.btn_check.configure(state=state)
        self.btn_sync.configure(state=state)

    def _validate_fields(self) -> bool:
        cfg = self._fields_to_config()
        if not cfg.remote_host:
            messagebox.showwarning("Missing field", "Remote host is required.")
            return False
        if not cfg.remote_username:
            messagebox.showwarning("Missing field", "Username is required.")
            return False
        if not cfg.remote_password:
            messagebox.showwarning("Missing field", "Password is required.")
            return False
        if not cfg.remote_save_dir:
            messagebox.showwarning(
                "Missing field", "Remote save directory path is required."
            )
            return False
        return True

    def _make_syncer(self) -> SaveGameSyncer:
        cfg = self._fields_to_config()
        return SaveGameSyncer(
            host=cfg.remote_host,
            username=cfg.remote_username,
            password=cfg.remote_password,
            port=cfg.remote_port,
            local_save_dir=cfg.local_save_dir,
            remote_save_dir=cfg.remote_save_dir,
        )

    # -- Check status ----------------------------------------------------
    def _on_check(self) -> None:
        if not self._validate_fields():
            return
        self._set_busy(True)
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self) -> None:
        syncer = self._make_syncer()
        try:
            syncer.connect()
            local_files, remote_files = syncer.check_status()

            logger.info("--- Local files (%d) ---", len(local_files))
            for rel, fi in sorted(local_files.items()):
                dt = fi.modified_dt.strftime("%Y-%m-%d %H:%M:%S")
                logger.info("  %s  (modified: %s, size: %d B)", rel, dt, fi.size)

            logger.info("--- Remote files (%d) ---", len(remote_files))
            for rel, fi in sorted(remote_files.items()):
                dt = fi.modified_dt.strftime("%Y-%m-%d %H:%M:%S")
                logger.info("  %s  (modified: %s, size: %d B)", rel, dt, fi.size)

            # Quick comparison
            plan = syncer.plan_sync()
            if plan.upload:
                logger.info(
                    "Files to upload (local is newer): %s",
                    ", ".join(f.relative_path for f in plan.upload),
                )
            if plan.download:
                logger.info(
                    "Files to download (remote is newer): %s",
                    ", ".join(f.relative_path for f in plan.download),
                )
            if not plan.upload and not plan.download:
                logger.info("All files are in sync.")

        except Exception as exc:
            logger.error("Check failed: %s", exc)
        finally:
            syncer.disconnect()
            self.root.after(0, self._set_busy, False)

    # -- Sync ------------------------------------------------------------
    def _on_sync(self) -> None:
        if not self._validate_fields():
            return
        self._set_busy(True)
        self.progress["value"] = 0
        threading.Thread(target=self._sync_worker, daemon=True).start()

    def _progress_cb(self, done: int, total: int, msg: str) -> None:
        if total > 0:
            pct = int(done / total * 100)
            self.root.after(0, self._update_progress, pct)
        logger.info(msg)

    def _update_progress(self, pct: int) -> None:
        self.progress["value"] = pct

    def _sync_worker(self) -> None:
        syncer = self._make_syncer()
        try:
            syncer.connect()
            summary = syncer.execute_sync(progress_callback=self._progress_cb)

            logger.info("=== Sync complete ===")
            if summary["uploaded"]:
                logger.info("Uploaded %d file(s):", len(summary["uploaded"]))
                for f in summary["uploaded"]:
                    logger.info("  -> %s", f)
            if summary["downloaded"]:
                logger.info("Downloaded %d file(s):", len(summary["downloaded"]))
                for f in summary["downloaded"]:
                    logger.info("  <- %s", f)
            if summary["backed_up"]:
                logger.info("Backed up %d file(s):", len(summary["backed_up"]))
                for f in summary["backed_up"]:
                    logger.info("  [backup] %s", f)
            if not summary["uploaded"] and not summary["downloaded"]:
                logger.info("Nothing to sync - all files are up to date.")

            self.root.after(0, self._update_progress, 100)

        except Exception as exc:
            logger.error("Sync failed: %s", exc)
        finally:
            syncer.disconnect()
            self.root.after(0, self._set_busy, False)

    # ------------------------------------------------------------------ Run
    def run(self) -> None:
        self.root.mainloop()

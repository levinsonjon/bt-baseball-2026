"""Size-based rotation for the cron scripts' log files.

`send_email.log` and `health_update.log` are written from two directions: the
launchd plists redirect StandardOutPath/StandardErrorPath into them, and the
Python scripts append their own `log()` lines. Neither side truncates, so both
grew without bound (health_update.log reached 1.1 MB by Aug 2026).

Call `rotate(path)` once at script start, before any logging. When the file is
over `max_bytes` it becomes `<name>.1` (displacing any previous `.1`) and the
script starts a fresh file, capping total on-disk size at roughly 2x the
threshold per log.

Note: launchd may already hold an fd on the old inode when rotation happens, so
launchd-level output from that one run lands in the rotated file while the
script's own lines go to the new one. Self-corrects on the next run.
"""

from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024  # 5 MB


def rotate(path, max_bytes: int = MAX_BYTES) -> bool:
    """Rotate `path` to `path.1` if it exceeds `max_bytes`. Returns True if
    rotated. Never raises — a logging problem must not take down a cron run."""
    try:
        p = Path(path)
        if not p.exists() or p.stat().st_size <= max_bytes:
            return False
        prev = p.with_suffix(p.suffix + ".1")
        if prev.exists():
            prev.unlink()
        p.rename(prev)
        return True
    except OSError:
        return False

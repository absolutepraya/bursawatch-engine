#!/usr/bin/env python3
"""Gateway-independent liveness for idx-ca-watch. Run from SYSTEM crontab.
Posts to Discord if no successful run in the last MAX_GAP_HOURS; prunes old charts/logs."""
import sys, json, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan  # reuse post_discord, state_path, WIB

MAX_GAP_HOURS = 4


def main() -> int:
    st = {}
    p = scan.state_path()
    if p.exists():
        try:
            st = json.loads(p.read_text())
        except Exception:
            pass
    last = st.get("last_run")
    now = dt.datetime.now(scan.WIB)
    stale = True
    if last:
        try:
            stale = (now - dt.datetime.fromisoformat(last)) > dt.timedelta(hours=MAX_GAP_HOURS)
        except Exception:
            stale = True
    if stale:
        scan.post_discord(scan.HEARTBEAT_CHANNEL,
                          f"⚠️ idx-ca-watch watchdog: no successful run since {last or 'never'} "
                          f"(> {MAX_GAP_HOURS}h). Check gateway/cron.")
    # prune charts >2d and trim log
    tmp = Path("/tmp")
    cutoff = now.timestamp() - 2 * 86400
    for f in tmp.glob("yanto-chart-IDX_*.png"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

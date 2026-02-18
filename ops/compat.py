"""
ops.compat — File-based ↔ DB event bridge.

Monitors inbox/outputs for file events and replicates them to ops_events.
This keeps the closed-loop DB informed of legacy file-based activity.
"""
import os
import time
import logging

log = logging.getLogger("ops.compat")

BASE = os.path.expanduser("~/workspace")
INBOX = os.path.join(BASE, "inbox")
OUT = os.path.join(BASE, "outputs")

# Track seen files to detect new ones
_seen_inbox = set()
_seen_outputs = set()


def _emit(kind: str, payload: dict = None):
    """Try to emit event to DB; fail silently if DB not available."""
    try:
        from ops.db import emit_event
        emit_event(kind, source="compat", payload=payload)
    except Exception as e:
        log.debug("Could not emit event to DB: %s", e)


def scan_inbox():
    """Detect new/completed tasks in inbox."""
    global _seen_inbox
    try:
        current = set(os.listdir(INBOX))
    except FileNotFoundError:
        return

    new_files = current - _seen_inbox
    for f in new_files:
        if f.endswith(".txt") and not f.endswith(".done"):
            _emit("file.task_created", {"filename": f, "dir": "inbox"})
            log.debug("Detected new task: %s", f)
        elif f.endswith(".txt.done"):
            stem = f.replace(".txt.done", "")
            _emit("file.task_completed", {"filename": f, "stem": stem, "dir": "inbox"})
            log.debug("Detected completed task: %s", f)

    _seen_inbox = current


def scan_outputs():
    """Detect new outputs."""
    global _seen_outputs
    try:
        current = set(f for f in os.listdir(OUT) if f.endswith(".md"))
    except FileNotFoundError:
        return

    new_files = current - _seen_outputs
    for f in new_files:
        _emit("file.output_created", {"filename": f, "dir": "outputs"})
        log.debug("Detected new output: %s", f)

    _seen_outputs = current


def run_compat_loop(interval: float = 5.0):
    """
    Continuous loop that bridges file events to DB.
    Run alongside agent_mvp / dashboard_api.
    """
    log.info("Compat bridge starting (interval=%.1fs)", interval)

    # Initial scan (populate seen sets without emitting)
    try:
        _seen_inbox.update(os.listdir(INBOX))
    except FileNotFoundError:
        pass
    try:
        _seen_outputs.update(f for f in os.listdir(OUT) if f.endswith(".md"))
    except FileNotFoundError:
        pass

    while True:
        try:
            scan_inbox()
            scan_outputs()
        except Exception as e:
            log.error("Compat scan error: %s", e)
        time.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    run_compat_loop()

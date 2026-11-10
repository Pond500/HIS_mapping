"""
progress.py
===========
What an upload is doing right now, for the page to show while it waits (the AI
steps take a minute or more, and a page that says nothing for that long feels
broken). Each graph node reports the step it is on, with its own real numbers;
nothing here estimates or invents a percentage.

Kept in memory: the app runs one process (see CLAUDE.md), the page polls that
process, and after a restart the file's status in the database still says
where it ended up. Only uploads that called start() are tracked, so a graph run
for any other reason (a reviewer's answer re-running a file, the evaluation)
reports into nothing.
"""

import threading
import time

# key -> label shown on the page, in the order they happen
STEPS = [
    ("read", "อ่านไฟล์"),
    ("match", "จับคู่ชื่อคอลัมน์ที่ระบบรู้จักแล้ว"),
    ("ai_propose", "AI หาความหมายของคอลัมน์ที่ไม่รู้จัก"),
    ("ai_verify", "AI ตัวที่สองตรวจคำตอบ"),
    ("store", "บันทึกค่าและเตรียมคำถาม"),
]
COMMENTS = ("comments", "AI อ่านข้อความผลตรวจที่ไม่มีรหัสปกติ/ผิดปกติ")
KEEP_S = 3600

_lock = threading.Lock()
_runs: dict[int, dict] = {}


def start(file_id: int, filename: str) -> None:
    now = time.time()
    with _lock:
        for k in [k for k, r in _runs.items() if now - r["started"] > KEEP_S]:
            del _runs[k]
        _runs[file_id] = {"filename": filename, "started": now, "finished": None,
                          "steps": [{"key": k, "label": lab, "state": "todo", "detail": None,
                                     "started": None, "ended": None} for k, lab in STEPS]}


def step(file_id: int, key: str, detail: str | None = None) -> None:
    """Marks `key` as the step in progress; every earlier step is done by then, and a
    later one being entered again (the Mapper's revision round) starts it over."""
    now = time.time()
    with _lock:
        run = _runs.get(file_id)
        if run is None:
            return
        steps = run["steps"]
        if key == COMMENTS[0] and not any(s["key"] == key for s in steps):
            steps.insert(len(steps) - 1, {"key": key, "label": COMMENTS[1], "state": "todo",
                                          "detail": None, "started": None, "ended": None})
        at = next((i for i, s in enumerate(steps) if s["key"] == key), None)
        if at is None:
            return
        for s in steps[:at]:
            if s["state"] == "doing":
                _close(s, now)
            elif s["state"] == "todo":
                s["state"] = "skipped"      # e.g. no unknown columns: the AI steps never ran
        for s in steps[at + 1:]:
            if s["state"] == "doing":       # going back (the revision round): the later step did finish
                _close(s, now)
        s = steps[at]
        again = s["state"] == "done"
        if s["state"] == "doing":
            _close(s, now)
        s["state"], s["started"], s["ended"] = "doing", now, None
        if detail is not None:
            # a step run again keeps what its first run said: "10 ชื่อ · แก้ไขอีกรอบ 3 ชื่อ"
            s["detail"] = f"{s['detail']} · {detail}" if again and s["detail"] else detail


def _close(s: dict, now: float) -> None:
    s["state"], s["ended"] = "done", now
    s["spent"] = s.get("spent", 0.0) + (now - s["started"] if s["started"] else 0.0)


def note(file_id: int, key: str, detail: str) -> None:
    """Adds what a step found without moving on (e.g. how many columns were known)."""
    with _lock:
        run = _runs.get(file_id)
        if run is None:
            return
        for s in run["steps"]:
            if s["key"] == key:
                s["detail"] = detail


def finish(file_id: int) -> None:
    now = time.time()
    with _lock:
        run = _runs.get(file_id)
        if run is None:
            return
        for s in run["steps"]:
            if s["state"] == "doing":
                _close(s, now)
            elif s["state"] == "todo":
                s["state"] = "skipped"
        run["finished"] = now


def get(file_id: int) -> dict | None:
    now = time.time()
    with _lock:
        run = _runs.get(file_id)
        if run is None:
            return None
        return {
            "filename": run["filename"],
            # the graph's own end, not the file's status: a file reads "awaiting_review"
            # after its first store, while the AI is still reading its findings
            "finished": run["finished"] is not None,
            "elapsed_s": round((run["finished"] or now) - run["started"], 1),
            # elapsed_s: every run of the step added up (the revision round included)
            "steps": [{"key": s["key"], "label": s["label"], "state": s["state"], "detail": s["detail"],
                       "elapsed_s": round(s.get("spent", 0.0) + (now - s["started"] if s["state"] == "doing" else 0.0), 1)
                                     if s["started"] else None}
                      for s in run["steps"]],
        }

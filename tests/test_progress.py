"""app/graph/progress.py: what the upload panel shows while a file runs."""

from app.graph import progress


def states(fid):
    return {s["key"]: s["state"] for s in progress.get(fid)["steps"]}


def test_untracked_file_reports_into_nothing():
    progress.step(-1, "read")
    assert progress.get(-1) is None


def test_revision_round_leaves_one_step_in_progress():
    fid = 10_001
    progress.start(fid, "f.xlsx")
    for key in ("read", "match", "ai_propose", "ai_verify"):
        progress.step(fid, key)
    progress.note(fid, "ai_propose", "10 ชื่อ")
    progress.step(fid, "ai_propose", "แก้ไขอีกรอบ 2 ชื่อ")     # the verifier objected: back to the mapper
    st = states(fid)
    assert [k for k, v in st.items() if v == "doing"] == ["ai_propose"], st
    assert st["ai_verify"] == "done" and st["store"] == "todo"
    ai = next(s for s in progress.get(fid)["steps"] if s["key"] == "ai_propose")
    assert ai["detail"] == "10 ชื่อ · แก้ไขอีกรอบ 2 ชื่อ", ai   # the first run's count is kept
    progress.step(fid, "ai_verify")
    progress.step(fid, "store")
    progress.finish(fid)
    assert set(states(fid).values()) == {"done"}


def test_time_of_a_step_run_twice_is_added_up(monkeypatch):
    clock = iter([0, 0, 10, 40, 50, 55, 60, 60])        # start, read, verify, back to propose, verify, finish, get
    monkeypatch.setattr(progress.time, "time", lambda: next(clock))
    fid = 10_004
    progress.start(fid, "f.xlsx")
    progress.step(fid, "read")
    progress.step(fid, "ai_verify")         # t=10 … 40: 30 s
    progress.step(fid, "ai_propose")        # t=40 … 50
    progress.step(fid, "ai_verify")         # t=50 … 55: 5 s more
    progress.finish(fid)
    verify = next(s for s in progress.get(fid)["steps"] if s["key"] == "ai_verify")
    assert verify["elapsed_s"] == 35, verify


def test_no_unknown_columns_skips_the_ai_steps():
    fid = 10_002
    progress.start(fid, "f.xlsx")
    progress.step(fid, "read")
    progress.step(fid, "match")
    progress.note(fid, "match", "รู้จักแล้ว 5 จาก 5 ชื่อผลตรวจ · ไม่ต้องใช้ AI")
    progress.step(fid, "store")
    progress.finish(fid)
    st = states(fid)
    assert st["ai_propose"] == st["ai_verify"] == "skipped" and st["store"] == "done", st
    assert progress.get(fid)["steps"][1]["detail"].startswith("รู้จักแล้ว 5")


def test_comments_step_is_added_before_store_only_when_it_runs():
    fid = 10_003
    progress.start(fid, "f.xlsx")
    assert "comments" not in states(fid)
    progress.step(fid, "store")
    progress.step(fid, "comments", "3 ข้อความ")
    progress.step(fid, "store")
    keys = [s["key"] for s in progress.get(fid)["steps"]]
    assert keys[-2:] == ["comments", "store"], keys

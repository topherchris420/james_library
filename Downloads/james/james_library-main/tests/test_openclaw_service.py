import json
from threading import Event

from james_library.services.openclaw_service import OpenClawHeartbeat


def test_heartbeat_detects_restart_task(tmp_path):
    tasks = tmp_path / "tasks.json"
    tasks.write_text(json.dumps({"command": "restart"}), encoding="utf-8")

    hb = OpenClawHeartbeat(restart_event=Event(), stop_event=Event(), tasks_file=tasks)
    assert hb._has_restart_task() is True
    payload = json.loads(tasks.read_text(encoding="utf-8"))
    assert payload["command"] == ""


def test_heartbeat_detects_crash_in_logs(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    log_file = logs / "app.log"
    log_file.write_text("all good\n", encoding="utf-8")

    hb = OpenClawHeartbeat(restart_event=Event(), stop_event=Event(), logs_dir=logs)
    assert hb._logs_show_crash_pattern() is False

    log_file.write_text("all good\nTraceback: boom\n", encoding="utf-8")
    assert hb._logs_show_crash_pattern() is True

"""TaskManager unit tests — task store + state transitions."""

import pytest
from _vystak.runtime.a2a.tasks import Task, TaskManager, TaskState  # noqa: F401


def test_create_task_returns_submitted_state():
    mgr = TaskManager()
    task = mgr.create(task_id="t1", message={"role": "user", "parts": [{"text": "hi"}]})
    assert task.id == "t1"
    assert task.state == TaskState.SUBMITTED


def test_transition_submitted_to_working():
    mgr = TaskManager()
    mgr.create(task_id="t1", message={})
    mgr.set_state("t1", TaskState.WORKING)
    assert mgr.get("t1").state == TaskState.WORKING


def test_invalid_transition_raises():
    mgr = TaskManager()
    mgr.create(task_id="t1", message={})
    mgr.set_state("t1", TaskState.COMPLETED)
    with pytest.raises(ValueError, match="cannot transition"):
        mgr.set_state("t1", TaskState.WORKING)


def test_get_unknown_task_returns_none():
    mgr = TaskManager()
    assert mgr.get("nope") is None


def test_cancel_marks_canceled():
    mgr = TaskManager()
    mgr.create(task_id="t1", message={})
    mgr.set_state("t1", TaskState.WORKING)
    mgr.cancel("t1")
    assert mgr.get("t1").state == TaskState.CANCELED


def test_cancel_completed_task_is_noop():
    mgr = TaskManager()
    mgr.create(task_id="t1", message={})
    mgr.set_state("t1", TaskState.COMPLETED)
    mgr.cancel("t1")
    assert mgr.get("t1").state == TaskState.COMPLETED

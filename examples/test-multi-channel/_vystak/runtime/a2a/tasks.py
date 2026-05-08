"""A2A task store + state machine."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class TaskState(StrEnum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


_TERMINAL: set[TaskState] = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}


@dataclass
class Task:
    id: str
    state: TaskState = TaskState.SUBMITTED
    message: dict = field(default_factory=dict)
    artifacts: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class TaskManager:
    """In-memory task store. Per-process; not durable across restarts."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def create(self, task_id: str, message: dict) -> Task:
        task = Task(id=task_id, message=message)
        self._tasks[task_id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def set_state(self, task_id: str, new_state: TaskState) -> None:
        task = self._tasks[task_id]
        if task.state in _TERMINAL and new_state != task.state:
            raise ValueError(f"cannot transition from terminal state {task.state} to {new_state}")
        task.state = new_state
        task.updated_at = datetime.now(UTC)

    def cancel(self, task_id: str) -> None:
        task = self._tasks[task_id]
        if task.state in _TERMINAL:
            return
        task.state = TaskState.CANCELED
        task.updated_at = datetime.now(UTC)

    def append_artifact(self, task_id: str, artifact: dict) -> None:
        self._tasks[task_id].artifacts.append(artifact)

    def append_history(self, task_id: str, message: dict) -> None:
        self._tasks[task_id].history.append(message)

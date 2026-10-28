"""Scoped storage fix for the pinned CrewAI 1.9.3 dependency.

Upstream fixed this connection leak in PR #7493. Its newer releases cannot
currently resolve on our supported Intel macOS environment. This replacement
uses the same SQLite table and handler API without patching CrewAI or sqlite3
globally. Reassess it when changing the CrewAI pin.
"""

from contextlib import closing, contextmanager
from importlib.metadata import version
import json
import logging
import sqlite3

from crewai import Crew
from crewai.memory.storage.kickoff_task_outputs_storage import (
    KickoffTaskOutputsSQLiteStorage,
)
from crewai.utilities.crew_json_encoder import CrewJSONEncoder
from crewai.utilities.errors import DatabaseError, DatabaseOperationError
from crewai.utilities.task_output_storage_handler import TaskOutputStorageHandler
from pydantic import PrivateAttr

logger = logging.getLogger(__name__)
SUPPORTED_CREWAI_VERSION = "1.9.3"


class ClosingTaskOutputStorage(KickoffTaskOutputsSQLiteStorage):
    """Close connections after every operation, including rollback/error paths."""

    @contextmanager
    def _connection(self, operation):
        try:
            # sqlite3's own context manager commits/rolls back but does not close.
            with closing(sqlite3.connect(self.db_path)) as connection, connection:
                yield connection
        except sqlite3.Error as exc:
            message = DatabaseError.format_error(operation, exc)
            logger.error(message)
            raise DatabaseOperationError(message, exc) from exc

    def _initialize_db(self):
        with self._connection(DatabaseError.INIT_ERROR) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS latest_kickoff_task_outputs (
                    task_id TEXT PRIMARY KEY,
                    expected_output TEXT,
                    output JSON,
                    task_index INTEGER,
                    inputs JSON,
                    was_replayed BOOLEAN,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

    def add(self, task, output, task_index, was_replayed=False, inputs=None):
        with self._connection(DatabaseError.SAVE_ERROR) as connection:
            connection.execute(
                """INSERT OR REPLACE INTO latest_kickoff_task_outputs
                   (task_id, expected_output, output, task_index, inputs, was_replayed)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    str(task.id),
                    task.expected_output,
                    json.dumps(output, cls=CrewJSONEncoder),
                    task_index,
                    json.dumps(inputs or {}, cls=CrewJSONEncoder),
                    was_replayed,
                ),
            )

    def update(self, task_index, **kwargs):
        # The handler's replay path updates these columns using bound values.
        columns = {
            "task_id",
            "expected_output",
            "output",
            "inputs",
            "was_replayed",
            "timestamp",
        }
        if not kwargs or not set(kwargs) <= columns:
            raise ValueError("Update requires known task-output columns")
        assignments = ", ".join(f"{column} = ?" for column in kwargs)
        values = [
            json.dumps(value, cls=CrewJSONEncoder) if isinstance(value, dict) else value
            for value in kwargs.values()
        ]
        with self._connection(DatabaseError.UPDATE_ERROR) as connection:
            cursor = connection.execute(
                f"UPDATE latest_kickoff_task_outputs SET {assignments} WHERE task_index = ?",
                [*values, task_index],
            )
            if cursor.rowcount == 0:
                logger.warning(
                    "No row found with task_index %s. No update performed.", task_index
                )

    def load(self):
        with self._connection(DatabaseError.LOAD_ERROR) as connection:
            rows = connection.execute(
                "SELECT * FROM latest_kickoff_task_outputs ORDER BY task_index"
            ).fetchall()
            return [
                {
                    "task_id": row[0],
                    "expected_output": row[1],
                    "output": json.loads(row[2]),
                    "task_index": row[3],
                    "inputs": json.loads(row[4]),
                    "was_replayed": row[5],
                    "timestamp": row[6],
                }
                for row in rows
            ]

    def delete_all(self):
        with self._connection(DatabaseError.DELETE_ERROR) as connection:
            connection.execute("DELETE FROM latest_kickoff_task_outputs")


class ClosingTaskOutputHandler(TaskOutputStorageHandler):
    def __init__(self):
        # Avoid initializing the upstream storage first: initialization also leaks.
        if version("crewai") != SUPPORTED_CREWAI_VERSION:
            raise RuntimeError(
                "Reassess the CrewAI storage compatibility layer before changing the dependency pin"
            )
        self.storage = ClosingTaskOutputStorage()


class PipelineCrew(Crew):
    """Use scoped storage for our crews; leave other CrewAI consumers untouched."""

    _task_output_handler: TaskOutputStorageHandler = PrivateAttr(
        default_factory=ClosingTaskOutputHandler
    )

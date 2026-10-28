import gc
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import warnings

os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"
os.environ["CREWAI_TRACING_ENABLED"] = "false"

from crewai import Task
from ai_pipeline.crewai_compat import ClosingTaskOutputStorage, ClosingTaskOutputHandler
from ai_pipeline.crewai_adapter import build_crew
from crewai.utilities.errors import DatabaseError, DatabaseOperationError
from test_crewai import LocalTestLLM


class StorageCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.connections = []
        connect = sqlite3.connect

        def track(*args, **kwargs):
            connection = connect(*args, **kwargs)
            self.connections.append(connection)
            return connection

        tracker = patch("ai_pipeline.crewai_compat.sqlite3.connect", side_effect=track)
        tracker.start()
        self.addCleanup(tracker.stop)

    def assert_connections_closed(self):
        self.assertTrue(self.connections)
        for connection in self.connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

    def test_all_operations_close_connections_and_preserve_replay_data(self):
        storage = ClosingTaskOutputStorage(str(self.root / "outputs.db"))
        self.assert_connections_closed()
        task = Task(description="test", expected_output="output")
        storage.add(task, {"raw": "before"}, 0, inputs={"key": "value"})
        storage.update(0, output={"raw": "after"}, was_replayed=True)
        row = storage.load()[0]
        self.assertEqual(row["task_id"], str(task.id))
        self.assertEqual(row["expected_output"], "output")
        self.assertEqual(row["output"], {"raw": "after"})
        self.assertEqual(row["inputs"], {"key": "value"})
        self.assertTrue(row["was_replayed"])
        self.assert_connections_closed()
        storage.delete_all()
        self.assertEqual(storage.load(), [])
        self.assert_connections_closed()
        Path(storage.db_path).unlink()

    def test_error_rolls_back_and_closes_immediately(self):
        storage = ClosingTaskOutputStorage(str(self.root / "outputs.db"))
        with self.assertRaisesRegex(RuntimeError, "abort"):
            with storage._connection(DatabaseError.SAVE_ERROR) as connection:
                connection.execute(
                    "INSERT INTO latest_kickoff_task_outputs (task_id) VALUES ('rollback')"
                )
                raise RuntimeError("abort")
        self.assertEqual(storage.load(), [])
        self.assert_connections_closed()
        with self.assertRaises(DatabaseOperationError):
            with storage._connection(DatabaseError.LOAD_ERROR) as connection:
                connection.execute("SELECT * FROM missing_table")
        self.assert_connections_closed()

    def test_pipeline_crew_uses_closed_storage_without_resource_warnings(self):
        gc.collect()
        with patch.dict(os.environ, {"CREWAI_STORAGE_DIR": str(self.root)}):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ResourceWarning)
                crew = build_crew(
                    {
                        "stage": "requirements",
                        "task": "Specify addition",
                        "workspace": str(self.root),
                        "output": str(self.root),
                        "history": [],
                    },
                    llm=LocalTestLLM(),
                )
                self.assertIsInstance(
                    crew._task_output_handler, ClosingTaskOutputHandler
                )
                result = crew.kickoff()
                self.assertEqual(result.pydantic.status, "passed")
                self.assert_connections_closed()
                del crew
                gc.collect()
            self.assertFalse(
                [w for w in caught if issubclass(w.category, ResourceWarning)]
            )

    def test_dependency_upgrade_requires_explicit_reassessment(self):
        with patch("ai_pipeline.crewai_compat.version", return_value="9.9.9"):
            with self.assertRaisesRegex(RuntimeError, "Reassess"):
                ClosingTaskOutputHandler()

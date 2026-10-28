import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_pipeline.cli import main


class EnvironmentTests(unittest.TestCase):
    def test_cli_loads_selected_file_without_overriding_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.env"
            path.write_text("FACTORY_TEST_SETTING=from-file\nFACTORY_TEST_EXISTING=from-file\n")
            with patch.dict(os.environ, {"FACTORY_TEST_EXISTING": "from-shell"}, clear=True), \
                 patch("sys.argv", ["ai-pipeline", "--env-file", str(path), "list"]), \
                 patch("ai_pipeline.cli.Factory") as factory, contextlib.redirect_stdout(io.StringIO()):
                factory.return_value.list_runs.return_value = []
                main()
                self.assertEqual(os.environ["FACTORY_TEST_SETTING"], "from-file")
                self.assertEqual(os.environ["FACTORY_TEST_EXISTING"], "from-shell")


if __name__ == "__main__":
    unittest.main()

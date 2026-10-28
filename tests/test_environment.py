import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_pipeline.cli import load_environment, main


class EnvironmentTests(unittest.TestCase):
    def test_direct_mode_overrides_gateway_and_uses_project_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.env"
            path.write_text("FACTORY_OPENAI_DIRECT=true\nOPENAI_API_KEY=project-test-key\n")
            with patch.dict(os.environ, {"OPENAI_BASE_URL": "http://127.0.0.1:8443/v1",
                                         "OPENAI_API_BASE": "http://127.0.0.1:8443/v1",
                                         "OPENAI_API_KEY": "gateway-test-key"}, clear=True):
                load_environment(path)
                self.assertEqual(os.environ["OPENAI_BASE_URL"], "https://api.openai.com/v1")
                self.assertEqual(os.environ["OPENAI_API_BASE"], "https://api.openai.com/v1")
                self.assertEqual(os.environ["OPENAI_API_KEY"], "project-test-key")

    def test_empty_project_key_does_not_fall_back_to_gateway_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.env"
            path.write_text("FACTORY_OPENAI_DIRECT=true\nOPENAI_API_KEY=\n")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "gateway-test-key"}, clear=True):
                load_environment(path)
                self.assertEqual(os.environ["OPENAI_API_KEY"], "")

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

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


INTEGRATION = Path(__file__).resolve().parents[1] / "integrations" / "textstats"
sys.path.insert(0, str(INTEGRATION))
spec = importlib.util.spec_from_file_location("textstats_adapter", INTEGRATION / "adapter.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
sys.path.pop(0)

# Self-contained fixture: the integration tests do not depend on the sibling repo.
SOURCE = '''import argparse
import json
from pathlib import Path
import sys
p = argparse.ArgumentParser()
p.add_argument("file", nargs="?")
a = p.parse_args()
t = Path(a.file).read_text(encoding="utf-8") if a.file else sys.stdin.read()
print(json.dumps({"characters": len(t), "words": len(t.split()), "lines": len(t.splitlines())}))
'''


class TextstatsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        workspace = self.root / "workspace"
        workspace.mkdir()
        self.source = workspace / "textstats.py"
        self.source.write_text(SOURCE)
        self.context = {"run_id": "test", "workspace": str(workspace), "history": []}

    def stage(self, stage):
        output = self.root / stage
        output.mkdir(exist_ok=True)
        result = adapter.execute({**self.context, "stage": stage, "output": str(output)})
        self.context["history"].append({"stage": stage, "status": result["status"], "artifact_directory": str(output)})
        return result

    def test_checks_detect_bug(self):
        self.source.write_text(SOURCE.replace("t.split()", 't.split(" ")'))
        result = self.stage("verify")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["failed_cases"]), 12)

    def test_real_local_delivery_and_observation(self):
        for stage in ("verify", "security", "release", "deploy", "observe"):
            self.assertEqual(self.stage(stage)["status"], "passed", stage)
        self.assertEqual((self.root / "deploy/installed/textstats.py").read_text(), SOURCE)

    def test_tampered_release_is_rejected(self):
        self.stage("release")
        (self.root / "release/textstats.zip").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.stage("deploy")

    def test_security_policy_rejects_dynamic_execution(self):
        self.source.write_text(SOURCE + "\nexec('print(1)')\n")
        self.assertEqual(self.stage("security")["status"], "failed")

    def test_security_failure_identifies_import_and_allowed_alternatives(self):
        self.source.write_text("import re\n" + SOURCE)
        result = self.stage("security")
        self.assertEqual(result["status"], "failed")
        self.assertIn("'re'", result["findings"][0])
        self.assertIn("allowed imports:", result["findings"][0])


if __name__ == "__main__":
    unittest.main()

"""Black-box baseline tests; no third-party dependencies."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "csvjson.py"


class CLITests(unittest.TestCase):
    def run_cli(self, text="", *arguments):
        return subprocess.run([sys.executable, str(SCRIPT), *arguments],
                              input=text, text=True, capture_output=True, timeout=5)

    def assert_json(self, text, expected):
        result = self.run_cli(text)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, json.dumps(expected, ensure_ascii=False) + "\n")

    def test_stdin_preserves_strings_and_empty_fields(self):
        self.assert_json("name,count\nAda,007\nBob,\n",
                         [{"name": "Ada", "count": "007"}, {"name": "Bob", "count": ""}])

    def test_quoted_commas_quotes_and_multiline(self):
        self.assert_json('name,note\n"Doe, Ada","said ""hi""\nnext line"\n',
                         [{"name": "Doe, Ada", "note": 'said "hi"\nnext line'}])

    def test_utf8_file_and_crlf(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.csv"
            path.write_bytes('name,note\r\nשלום,"line1\r\nline2"\r\n'.encode("utf-8"))
            result = self.run_cli("", str(path))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [{"name": "שלום", "note": "line1\r\nline2"}])

    def test_empty_and_header_only(self):
        for text in ("", "name,count\n", "name,count\n\n"):
            with self.subTest(text=text):
                self.assert_json(text, [])

    def test_invalid_headers(self):
        for text in ("name,name\n1,2\n", "name,\n1,2\n", " ,name\n1,2\n"):
            with self.subTest(text=text):
                result = self.run_cli(text)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("headers", result.stderr)

    def test_ragged_rows(self):
        for text in ("a,b\n1\n", "a,b\n1,2,3\n"):
            with self.subTest(text=text):
                result = self.run_cli(text)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("fields", result.stderr)

    def test_unclosed_quote(self):
        result = self.run_cli('a,b\n1,"unfinished')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr)

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_cli("", str(Path(directory) / "missing.csv"))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertIn("csvjson:", result.stderr)

    def test_invalid_utf8_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_bytes(b"name\n\xff")
            result = self.run_cli("", str(path))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertIn("csvjson:", result.stderr)


if __name__ == "__main__":
    unittest.main()

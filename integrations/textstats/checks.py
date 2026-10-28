"""Independent black-box acceptance checks. Kept outside the agent workspace."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile


CASES = [
    ("empty", "", 0),
    ("ordinary", "hello world", 2),
    ("repeated-spaces", "  hello   world  ", 2),
    ("tabs-newlines", "one\ttwo\nthree", 3),
    ("whitespace-only", " \t\n\r\n ", 0),
    ("unicode", "שלום\u00a0עולם\u2003hello", 3),
    ("punctuation", "hello, world!", 2),
    ("windows-lines", "one\r\ntwo\r\n", 2),
]


def verify(script, pretty=False):
    results = []
    with tempfile.TemporaryDirectory() as directory:
        for label, text, words in CASES:
            expected = {"characters": len(text), "words": words, "lines": len(text.splitlines())}
            for mode in ("stdin", "file"):
                formats = ("default", "pretty-before") if pretty else ("default",)
                if pretty and mode == "file":
                    formats += ("pretty-after",)
                for output_format in formats:
                    command = [sys.executable, str(Path(script).resolve())]
                    if output_format == "pretty-before":
                        command.append("--pretty")
                    if mode == "file":
                        path = Path(directory) / "input.txt"
                        path.write_bytes(text.encode("utf-8"))
                        command.append(str(path))
                    if output_format == "pretty-after":
                        command.append("--pretty")
                    # File reads normalize CRLF; subprocess stdin sends the given text.
                    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
                    wanted = {**expected, "characters": len(normalized)} if mode == "file" else expected
                    run = subprocess.run(command, input=text, text=True, capture_output=True,
                                         cwd=directory, timeout=10)
                    try:
                        actual = json.loads(run.stdout)
                    except ValueError:
                        actual = None
                    expected_stdout = json.dumps(wanted, ensure_ascii=False,
                                                 indent=2 if output_format != "default" else None) + "\n"
                    format_matches = run.stdout == expected_stdout
                    passed = (run.returncode == 0 and actual == wanted and isinstance(actual, dict)
                              and all(type(v) is int for v in actual.values())
                              and (not pretty or (format_matches and not run.stderr)))
                    results.append({"case": label, "mode": mode, "format": output_format,
                                    "expected": wanted, "actual": actual, "passed": passed,
                                    "exit_code": run.returncode, "stderr": run.stderr[-2000:],
                                    **({"expected_stdout": expected_stdout, "stdout": run.stdout,
                                        "format_matches": format_matches} if pretty else {})})
    return results


if __name__ == "__main__":
    results = verify(Path(sys.argv[1]))
    print(json.dumps(results, indent=2, ensure_ascii=False))
    raise SystemExit(0 if all(r["passed"] for r in results) else 1)

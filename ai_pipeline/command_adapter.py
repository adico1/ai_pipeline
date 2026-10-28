"""Wrap an operator-configured command in the factory result protocol.

Example: python /absolute/path/command_adapter.py --summary 'Unit tests' -- python -m unittest
This wrapper checks command exit status; it does not judge evidence quality.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("A command is required after --")
    result = subprocess.run(command, check=False)
    output = Path(os.environ["FACTORY_OUTPUT"])
    (output / "result.json").write_text(
        json.dumps(
            {
                "status": "passed" if result.returncode == 0 else "failed",
                "summary": args.summary,
                "command": command,
                "exit_code": result.returncode,
            },
            indent=2,
        )
    )
    return 0 if result.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

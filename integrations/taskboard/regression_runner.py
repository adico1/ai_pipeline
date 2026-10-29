"""Collect unittest outcomes without treating import errors as defect detection."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest


class Outcomes(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.passed_ids = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed_ids.append(test.id())


if __name__ == '__main__':
    sys.path.insert(0, str(Path.cwd()))
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        suite = unittest.defaultTestLoader.discover('tests')
        result = Outcomes()
        suite.run(result)
    print(json.dumps({
        'tests_run': result.testsRun,
        'passed_ids': result.passed_ids,
        'failures': [{'id': test.id(), 'traceback': trace} for test, trace in result.failures],
        'errors': [{'id': test.id(), 'traceback': trace} for test, trace in result.errors],
        'skipped': [test.id() for test, reason in result.skipped],
        'expected_failures': [test.id() for test, trace in result.expectedFailures],
        'unexpected_successes': [test.id() for test in result.unexpectedSuccesses],
        'output': captured.getvalue()[-2000:],
    }))

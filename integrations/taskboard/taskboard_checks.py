"""Requirements-driven checks, independent of the generated module layout."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib


def invoke(root, database, args):
    env = {**os.environ, 'PYTHONPATH': str(Path(root).resolve()), 'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run([sys.executable, '-B', '-m', 'taskboard', '--database', str(database), *args],
                            cwd=database.parent, env=env, text=True, capture_output=True, timeout=15)
    try:
        payload = json.loads(result.stdout if result.returncode == 0 else result.stderr)
    except ValueError:
        payload = {'unparsed_stdout': result.stdout[-1000:], 'unparsed_stderr': result.stderr[-1000:]}
    return result.returncode, payload


def verify(root):
    root = Path(root)
    cases = []
    def record(name, passed, expected, actual):
        cases.append({'case': name, 'baseline': False, 'passed': bool(passed), 'expected': expected, 'actual': actual})
    modules = [p for p in (root/'taskboard').rglob('*.py') if p.name != '__init__.py' and p.read_text().strip()]
    record('multi-file-package', len(modules) >= 3 and (root/'taskboard/__init__.py').exists(), 'At least 3 substantive package modules plus __init__.py', [p.relative_to(root).as_posix() for p in modules])
    try:
        metadata = tomllib.loads((root/'pyproject.toml').read_text())['project']
        record('project-metadata', bool(metadata.get('name')) and bool(metadata.get('version')) and metadata.get('dependencies', []) == [], 'Named, versioned stdlib-only project', metadata)
    except (OSError, ValueError, KeyError) as exc:
        record('project-metadata', False, 'Valid pyproject.toml', str(exc))
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory)/'tasks.sqlite3'
        def check(name, args, expected=None, error=False, db=database):
            code, actual = invoke(root, db, args)
            passed = (code == 2 and isinstance(actual, dict) and isinstance(actual.get('error'), str) and bool(actual['error'])) if error else (code == 0 and actual == expected)
            record(name, passed, 'exit 2 and JSON error' if error else expected, {'exit_code': code, 'body': actual})
        first = {'id': 1, 'title': 'buy milk', 'completed': False}
        second = {'id': 2, 'title': "שלום '; DROP TABLE tasks; --", 'completed': False}
        done = {**first, 'completed': True}
        check('empty-list', ['list'], [])
        check('add', ['add', '  buy milk  '], first)
        check('unicode-and-sql-text', ['add', second['title']], second)
        check('list-across-processes', ['list'], [first, second])
        check('complete', ['complete', '1'], done)
        check('complete-idempotent', ['complete', '1'], done)
        check('saved-state', ['list'], [done, second])
        check('blank-title', ['add', ' \t '], error=True)
        for identifier in ('0', '-1', 'abc', '999', '99999999999999999999999999'):
            check('invalid-id-' + identifier, ['complete', identifier], error=True)
        check('invalid-input-no-write', ['list'], [done, second])
        check('database-isolation', ['list'], [], db=Path(directory)/'other.sqlite3')
        record('sqlite-on-disk', database.exists() and database.read_bytes().startswith(b'SQLite format 3\x00'), 'Persistent SQLite database', database.exists())
        try:
            text = (root/'README.md').read_text()
            blocks = re.findall(r'```json taskboard-examples\s*\n(.*?)\n```', text, re.S)
            if len(blocks) != 1:
                raise ValueError('README needs one json taskboard-examples block')
            examples = json.loads(blocks[0])
            if len(examples) != 3 or [e['args'][0] for e in examples] != ['add', 'list', 'complete']:
                raise ValueError('Exactly three examples required: add, list, complete')
            docs_db = Path(directory)/'docs.sqlite3'
            for index, example in enumerate(examples):
                check(f'documentation-{index}', example['args'], example['stdout'], db=docs_db)
            record('documentation-how-to', '--database' in text and 'python' in text, 'Startup/database instructions', '--database' in text)
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            record('documentation', False, 'Executable README examples', str(exc))
    return cases

"""Independent public-CLI acceptance checks for the bounded rename feature."""
import json
from pathlib import Path
import re
import sqlite3
import tempfile

from taskboard_checks import invoke, connection_lifecycle


def verify_rename(root):
    cases = []

    def record(name, passed, expected, actual):
        cases.append({'case': 'rename-' + name, 'baseline': False,
                      'passed': bool(passed), 'expected': expected, 'actual': actual})

    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / 'existing.sqlite3'
        # A pre-feature database proves upgrades preserve existing data and IDs.
        connection = sqlite3.connect(database)
        try:
            connection.execute('CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0)')
            connection.executemany('INSERT INTO tasks (title, completed) VALUES (?, ?)', [('first', 0), ('finished', 1)])
            connection.commit()
        finally:
            connection.close()

        def check(name, args, expected=None, error=False, db=database):
            code, actual = invoke(root, db, args)
            passed = (code == 2 and isinstance(actual, dict) and isinstance(actual.get('error'), str) and bool(actual['error'])) if error else code == 0 and actual == expected
            record(name, passed, 'exit 2 with nonempty JSON error' if error else expected,
                   {'exit_code': code, 'body': actual})

        first = {'id': 1, 'title': 'updated title', 'completed': False}
        second = {'id': 2, 'title': 'done renamed', 'completed': True}
        check('trim', ['rename', '1', '  updated title  '], first)
        check('completed-stays-completed', ['rename', '2', 'done renamed'], second)
        check('persisted-across-processes', ['list'], [first, second])
        check('same-title', ['rename', '1', first['title']], first)
        first = {**first, 'title': "שלום '; DROP TABLE tasks; --"}
        check('unicode-sql-text', ['rename', '1', first['title']], first)
        first = {**first, 'title': 'MiXeD\tinternal\nspacing'}
        check('preserve-internal-whitespace', ['rename', '1', '  ' + first['title'] + '  '], first)
        for identifier in ('0', '-1', 'abc', '999', str(2**63)):
            check('invalid-id-' + identifier, ['rename', identifier, 'unwanted'], error=True)
        for index, title in enumerate(('', ' \t\n\u2003 ')):
            check(f'blank-{index}', ['rename', '1', title], error=True)
        check('failed-operations-no-write', ['list'], [first, second])
        third = {'id': 3, 'title': 'third', 'completed': False}
        check('does-not-allocate-id', ['add', 'third'], third)
        check('complete-after-rename', ['complete', '1'], {**first, 'completed': True})
        fresh = Path(directory) / 'fresh.sqlite3'
        check('missing-in-fresh-db', ['rename', '1', 'absent'], error=True, db=fresh)
        check('fresh-remains-empty', ['list'], [], db=fresh)
        check('other-db-unchanged', ['list'], [{**first, 'completed': True}, second, third])
        try:
            text = (Path(root) / 'README.md').read_text()
            blocks = re.findall(r'```json taskboard-rename-examples\s*\n(.*?)\n```', text, re.S)
            if len(blocks) != 1:
                raise ValueError('README needs exactly one json taskboard-rename-examples block')
            examples = json.loads(blocks[0])
            if len(examples) != 4 or [item['args'][0] for item in examples] != ['add', 'complete', 'rename', 'list']:
                raise ValueError('Four examples required in order: add, complete, rename, list')
            docs_db = Path(directory) / 'docs.sqlite3'
            for index, example in enumerate(examples):
                check(f'documentation-{index}', example['args'], example['stdout'], db=docs_db)
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            record('documentation', False, 'Executable rename examples in README', str(exc))
    lifecycle = connection_lifecycle(root, rename=True)
    lifecycle['case'] = 'rename-connection-lifecycle'
    cases.append(lifecycle)
    return cases

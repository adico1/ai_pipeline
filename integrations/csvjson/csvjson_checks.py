"""Independent CLI contract checks, outside the generated candidate."""
import csv
import io
import json
from pathlib import Path
import string
import subprocess
import sys
import tempfile


def verify(script):
    script = str(Path(script).resolve())
    results = []
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'input.csv'

        def check(label, text, expected=None, delimiter=None, error=False, modes=('stdin', 'before', 'after')):
            for mode in modes:
                args = [] if delimiter is None else ['--delimiter=' + delimiter]
                if mode != 'stdin':
                    path.write_bytes(text.encode('utf-8'))
                    args = args + [str(path)] if mode == 'before' else [str(path)] + args
                run = subprocess.run([sys.executable, script, *args], input=text,
                                     text=True, capture_output=True, cwd=directory, timeout=5)
                wanted = '' if error else json.dumps(expected, ensure_ascii=False) + '\n'
                passed = (run.returncode == (2 if error else 0) and run.stdout == wanted
                          and (bool(run.stderr.strip()) if error else not run.stderr))
                results.append({'case': label, 'mode': mode, 'delimiter': delimiter,
                                'passed': passed, 'expected_stdout': wanted, 'stdout': run.stdout,
                                'expected_exit': 2 if error else 0, 'exit_code': run.returncode,
                                'stderr': run.stderr[-2000:]})

        for delimiter in (None, ';', '|'):
            sep = delimiter or ','
            rows = [['name', 'note'], ['שלום', '007'], ['Ada', f'a{sep}b "quoted"\nnext'], ['Bob', '']]
            output = io.StringIO(newline='')
            csv.writer(output, delimiter=sep, lineterminator='\n').writerows(rows)
            check('strings-quotes-unicode-multiline', output.getvalue(),
                  [dict(zip(rows[0], row)) for row in rows[1:]], delimiter)
            check('empty', '', [], delimiter)
            check('header-only', f'name{sep}note\n\n', [], delimiter)
            check('crlf', f'name{sep}note\r\nAda{sep}hello\r\n',
                  [{'name': 'Ada', 'note': 'hello'}], delimiter)
            for label, text in (
                ('duplicate-header', f'a{sep}a\n1{sep}2\n'),
                ('blank-header', f'a{sep}\n1{sep}2\n'),
                ('short-row', f'a{sep}b\n1\n'),
                ('long-row', f'a{sep}b\n1{sep}2{sep}3\n'),
                ('unclosed-quote', f'a{sep}b\n1{sep}"unfinished')):
                check(label, text, delimiter=delimiter, error=True)
        for delimiter in string.punctuation.replace('"', ''):
            check('allowed-punctuation', f'a{delimiter}b\n1{delimiter}2\n',
                  [{'a': '1', 'b': '2'}], delimiter, modes=('stdin',))
        for delimiter in ('', ';;', 'a', 'Z', '0', ' ', '\t', '\n', '\r', '\x01', '\x7f', '"', 'é', '；'):
            check('invalid-delimiter', 'a,b\n1,2\n', delimiter=delimiter, error=True)
    return results

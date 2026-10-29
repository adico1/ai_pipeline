"""Exercise the public CLI while retaining SQLite handles to detect leaks."""
import contextlib
import io
import json
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile


def probe(rename=False):
    original_connect = sqlite3.connect
    connections = []

    def tracked_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    sqlite3.connect = tracked_connect
    observations = []
    try:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / 'tasks.sqlite3')
            commands = [(['add', 'probe'], 0), (['list'], 0),
                        (['complete', '1'], 0), (['complete', '999'], 2)]
            if rename:
                commands = [(['add', 'probe'], 0), (['rename', '1', 'renamed'], 0),
                            (['complete', '1'], 0), (['rename', '1', 'done'], 0),
                            (['rename', '999', 'absent'], 2)]
            for arguments, expected_exit in commands:
                start = len(connections)
                sys.argv = ['taskboard', '--database', database, *arguments]
                exit_code = 0
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    try:
                        runpy.run_module('taskboard', run_name='__main__')
                    except SystemExit as exc:
                        exit_code = exc.code or 0
                opened = connections[start:]
                still_open = 0
                for connection in opened:
                    try:
                        connection.execute('SELECT 1')
                        still_open += 1
                    except sqlite3.ProgrammingError:
                        pass
                observations.append({'command': arguments, 'exit_code': exit_code,
                                     'opened': len(opened), 'still_open': still_open,
                                     'passed': exit_code == expected_exit and bool(opened) and still_open == 0})
    finally:
        sqlite3.connect = original_connect
        for connection in connections:
            connection.close()
    return {'passed': all(item['passed'] for item in observations), 'commands': observations}


if __name__ == '__main__':
    try:
        result = probe(rename='--rename' in sys.argv)
    except Exception as exc:
        result = {'passed': False, 'error': f'{type(exc).__name__}: {exc}'}
    print(json.dumps(result))

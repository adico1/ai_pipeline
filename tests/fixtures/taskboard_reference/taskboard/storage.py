import sqlite3
from contextlib import closing
from .domain import title, identifier


def operate(path, command, value=None):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, title TEXT, completed INTEGER)')
        if command == 'add':
            cursor=db.execute('INSERT INTO tasks(title, completed) VALUES (?, 0)', (title(value),))
            row=db.execute('SELECT * FROM tasks WHERE id=?',(cursor.lastrowid,)).fetchone()
        elif command == 'complete':
            key=identifier(value)
            if db.execute('UPDATE tasks SET completed=1 WHERE id=?',(key,)).rowcount == 0:
                raise ValueError('missing id')
            row=db.execute('SELECT * FROM tasks WHERE id=?',(key,)).fetchone()
        else:
            return [dict(id=r[0], title=r[1], completed=bool(r[2])) for r in db.execute('SELECT * FROM tasks ORDER BY id')]
        return dict(id=row[0], title=row[1], completed=bool(row[2]))

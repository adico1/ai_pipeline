Test fixture. Run python -m taskboard --database example.sqlite3.
```json taskboard-examples
[
 {"args":["add","buy milk"],"stdout":{"id":1,"title":"buy milk","completed":false}},
 {"args":["list"],"stdout":[{"id":1,"title":"buy milk","completed":false}]},
 {"args":["complete","1"],"stdout":{"id":1,"title":"buy milk","completed":true}}
]
```

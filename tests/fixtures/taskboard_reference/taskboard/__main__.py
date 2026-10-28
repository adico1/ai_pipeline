import argparse
import json
import sys
from .storage import operate

parser=argparse.ArgumentParser()
parser.add_argument('--database',default='tasks.sqlite3')
sub=parser.add_subparsers(dest='command',required=True)
sub.add_parser('add').add_argument('title')
sub.add_parser('list')
sub.add_parser('complete').add_argument('id')
args=parser.parse_args()
try:
    result=operate(args.database,args.command,getattr(args,'title',getattr(args,'id',None)))
    print(json.dumps(result,ensure_ascii=False))
except ValueError as exc:
    print(json.dumps({'error':str(exc)}),file=sys.stderr)
    sys.exit(2)

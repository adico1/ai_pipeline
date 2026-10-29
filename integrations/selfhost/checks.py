"""Independent black-box report acceptance; never imported from the candidate."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

STAGES = ['requirements','design','plan','implement','verify','security','review','release','deploy','observe','retrospective']


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def verify(package):
    cases = []
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); state_dir = root/'state'; state_dir.mkdir()
        env = {key: value for key,value in os.environ.items() if key in ('PATH','HOME','TMPDIR','LANG','SYSTEMROOT')}
        env.update(PYTHONPATH=str(package), PYTHONDONTWRITEBYTECODE='1')
        # Disable network at the process boundary; no provider credentials inherited.
        code = "import socket; socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('Network forbidden')); socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('Network forbidden')); from ai_pipeline.cli import main; main()"
        def call(run_id, output):
            return subprocess.run([sys.executable,'-B','-c',code,'--state-dir',str(state_dir),'--env-file',str(root/'absent.env'),'report',run_id,'--output',str(output)], cwd=root, env=env, capture_output=True,text=True,timeout=15)
        def record(name, passed, expected, actual):
            cases.append(dict(case=name,passed=bool(passed),expected=expected,actual=actual))
        for index,status in enumerate(('completed','failed','awaiting_approval')):
            run_id=f'{index+1:012x}';run=state_dir/run_id;run.mkdir()
            state={'id':run_id,'project':'report-שלום','status':status,'stage':11 if status=='completed' else 3,'demo':False,'repairs':0,
                   'attempts':[{'stage':'requirements','status':'passed','result':{'summary':'Recorded requirements only'},'artifact_directory':'/recorded/evidence/requirements'},
                               {'stage':'implement','status':'failed','error':'Recorded error marker','result':{'summary':'Recorded failure marker','stop_reason':'no_progress'},'artifact_directory':'/recorded/evidence/implement'}],
                   'approvals':[] if status=='failed' else [{'stage':'design','actor':'operator-marker','note':'review-note-marker'}]}
            (run/'state.json').write_text(json.dumps(state));(run/'artifact.txt').write_text('unchanged')
            before=snapshot(state_dir);target=root/f'{status}.md';proc=call(run_id,target)
            text=target.read_text() if target.exists() else ''
            required=[run_id,'report-שלום',status,'Recorded requirements only','Recorded failure marker','Recorded error marker','no_progress','/recorded/evidence/implement',*STAGES]
            required+=['No approvals recorded'] if not state['approvals'] else ['operator-marker','review-note-marker']
            record(status+'-content',proc.returncode==0 and all(x in text for x in required) and 'not run' in text.lower() and str(target) in proc.stdout,required,{'exit':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr,'report':text})
            expected_stage='complete' if status=='completed' else 'implement'
            import re
            current_lines=[line for line in text.splitlines() if 'current stage' in line.lower()]
            record(status+'-current-stage',any(re.search(r'\b'+expected_stage+r'\b',line.lower()) for line in current_lines),
                   'Current stage: '+expected_stage,current_lines)
            second=root/f'{status}-again.md';again=call(run_id,second)
            record(status+'-deterministic',again.returncode==0 and second.exists() and second.read_bytes()==target.read_bytes(),'Identical exports',again.stderr)
            record(status+'-readonly',before==snapshot(state_dir),'State and artifacts unchanged',snapshot(state_dir))
            target.write_text('sentinel');overwrite=call(run_id,target)
            record(status+'-no-overwrite',overwrite.returncode!=0 and target.read_text()=='sentinel','Refuse overwrite',overwrite.stderr)
        for name,run_id in [('invalid','../../outside'),('unknown','ffffffffffff'),('malformed','eeeeeeeeeeee')]:
            if name=='malformed':
                (state_dir/run_id).mkdir();(state_dir/run_id/'state.json').write_text('{broken')
            target=root/f'{name}.md';proc=call(run_id,target)
            record(name,proc.returncode!=0 and bool(proc.stderr.strip()) and not target.exists(),'Readable nonzero error, no output',proc.stderr)
        for name,target in [('inside',state_dir/'new.md'),('nested',state_dir/'000000000001'/'new.md'),('missing-parent',root/'missing'/'new.md')]:
            proc=call('000000000001',target)
            record(name,proc.returncode!=0 and not target.exists() and (name!='missing-parent' or not target.parent.exists()),'Reject destination',proc.stderr)
        (root/'link').symlink_to(state_dir,target_is_directory=True)
        proc=call('000000000001',root/'link'/'new.md')
        record('symlink-inside',proc.returncode!=0 and not (state_dir/'new.md').exists(),'Reject resolved state path',proc.stderr)
    return cases

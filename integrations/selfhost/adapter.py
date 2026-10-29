"""Frozen operator-owned self-development checks and package delivery."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ai_pipeline.project_bundle import build_bundle, install_bundle
from checks import verify

ALLOWED = {'ai_pipeline/cli.py','ai_pipeline/report.py','tests/test_report.py','docs/report.md'}
INCLUDES = ['ai_pipeline','tests','integrations','docs','README.md','pyproject.toml']


def execute(context):
    workspace=Path(context['workspace']); output=Path(context['output']);stage=context['stage']
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(workspace)}
    def prior(name):
        return Path(next(a['artifact_directory'] for a in reversed(context['history']) if a['stage']==name and a['status']=='passed'))
    if stage=='security':
        tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT,text=True).split('\0')
        findings=[]
        for name in filter(None,tracked):
            if name not in ALLOWED and (not (workspace/name).is_file() or (workspace/name).is_symlink() or (workspace/name).read_bytes()!=(ROOT/name).read_bytes()):
                findings.append('Protected file changed: '+name)
        extras=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=workspace,text=True).splitlines()
        findings += ['Unexpected new file: '+name for name in extras if name not in ALLOWED]
        return {'status':'failed' if findings else 'passed','summary':'Protected runner inputs, adapters, existing tests and dependencies checked; not a security sandbox.','findings':findings}
    if stage in ('verify','observe'):
        package=workspace if stage=='verify' else prior('deploy')/'package'
        cases=verify(package)
        if stage=='verify':
            documentation=workspace/'docs/report.md'
            text=documentation.read_text() if documentation.exists() else ''
            cases.append({'case':'usage-documentation','passed':'report' in text and '--output' in text and '--state-dir' in text,'expected':'Document report, --output and --state-dir','actual':text[:1000]})
        # Keep advisory checks under their 60-second tool budget; the formal gate runs the entire suite.
        advisory='candidate-checks' in output.parts
        if stage=='verify':
            test_pattern='test_report.py' if advisory else 'test*.py'
            with tempfile.TemporaryDirectory() as directory:
                copied=Path(directory)/'project'
                shutil.copytree(workspace,copied,ignore=shutil.ignore_patterns('.git','.factory','.venv','__pycache__','.env','.env.*'))
                result=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tests','-p',test_pattern],cwd=copied,env={**env,'PYTHONPATH':str(copied)},capture_output=True,text=True,timeout=240)
                log=result.stdout+result.stderr;(output/'tests.log').write_text(log)
                import re
                count=re.search(r'Ran (\d+) tests?',log);minimum=1 if advisory else 133
                cases.append({'case':'candidate-tests' if advisory else 'full-regression-suite','passed':result.returncode==0 and count and int(count[1])>=minimum,'expected':f'At least {minimum} tests pass','actual':log[-2500:]})
        (output/'scenarios.json').write_text(json.dumps(cases,indent=2))
        failed=[c for c in cases if not c['passed']]
        return {'status':'failed' if failed else 'passed','summary':f'{len(cases)-len(failed)}/{len(cases)} selfhost checks passed.'+(' Advisory: new tests only; full regression suite runs at formal verify.' if advisory else ''),'failed_cases':failed}
    if stage=='release':
        manifest=build_bundle(workspace,output,INCLUDES)
        # Build from a throwaway source copy so build metadata cannot mutate the candidate.
        with tempfile.TemporaryDirectory() as directory:
            copied=Path(directory)/'project';install_bundle(output,copied)
            result=subprocess.run(['uv','build','--wheel','--offline','--out-dir',str(output)],cwd=copied,env=env,capture_output=True,text=True,timeout=120)
            (output/'build.log').write_text(result.stdout+result.stderr)
            if result.returncode: raise ValueError('Wheel build failed; see build.log')
        wheel=next(output.glob('*.whl'));manifest['wheel']=wheel.name;manifest['wheel_sha256']=hashlib.sha256(wheel.read_bytes()).hexdigest()
        (output/'package.json').write_text(json.dumps(manifest,indent=2))
        return {'status':'passed','summary':'Source bundle and wheel built from verified candidate.',**manifest}
    if stage=='deploy':
        release=prior('release');manifest=json.loads((release/'package.json').read_text());wheel=release/manifest['wheel']
        assert hashlib.sha256(wheel.read_bytes()).hexdigest()==manifest['wheel_sha256']
        result=subprocess.run(['uv','pip','install','--offline','--no-deps','--python',sys.executable,'--target',str(output/'package'),str(wheel)],capture_output=True,text=True,timeout=120)
        (output/'install.log').write_text(result.stdout+result.stderr)
        if result.returncode:raise ValueError('Wheel install failed; see install.log')
        return {'status':'passed','summary':'Wheel installed into isolated target; existing pinned runtime dependencies reused.'}
    raise ValueError('Unsupported stage '+stage)


if __name__=='__main__':
    context=json.loads(Path(os.environ['FACTORY_CONTEXT']).read_text());output=Path(context['output'])
    try:result=execute(context)
    except Exception as exc:result={'status':'failed','summary':f'{type(exc).__name__}: {exc}'}
    (output/'result.json').write_text(json.dumps(result,indent=2));print(result['summary'])
    raise SystemExit(result['status']!='passed')

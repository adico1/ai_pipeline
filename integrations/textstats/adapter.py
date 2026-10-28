"""Trusted adapters for real local checks, packaging, deployment and observation."""
import ast
import hashlib
import json
import os
from pathlib import Path
import zipfile

from checks import verify


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prior(context, stage):
    matches = [a for a in context["history"] if a["stage"] == stage and a["status"] == "passed"]
    if not matches:
        raise ValueError(f"Missing successful {stage} evidence")
    return Path(matches[-1]["artifact_directory"])


def execute(context):
    stage = context["stage"]
    output = Path(context["output"])
    source = Path(context["workspace"]) / "textstats.py"
    if stage in {"verify", "observe"}:
        script = source if stage == "verify" else prior(context, "deploy") / "installed" / "textstats.py"
        if stage == "observe":
            receipt = json.loads((prior(context, "deploy") / "deployment.json").read_text())
            if sha(script) != receipt["source_sha256"]:
                raise ValueError("Installed script differs from deployment receipt")
        scenarios = verify(script)
        (output / "scenarios.json").write_text(json.dumps(scenarios, indent=2, ensure_ascii=False))
        passed = sum(r["passed"] for r in scenarios)
        return {"status": "passed" if passed == len(scenarios) else "failed",
                "summary": f"{passed}/{len(scenarios)} real CLI scenarios passed against {stage} target.",
                "failed_cases": [r for r in scenarios if not r["passed"]]}
    if stage == "security":
        tree = ast.parse(source.read_text())
        violations = []
        allowed = {"argparse", "json", "pathlib", "sys"}
        for node in ast.walk(tree):
            imports = [a.name.split('.')[0] for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) else []
            if any(name not in allowed for name in imports):
                violations.append(f"Unapproved import at line {node.lineno}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "compile", "__import__"}:
                violations.append(f"Dynamic code execution at line {node.lineno}")
        return {"status": "failed" if violations else "passed", "summary": "Limited static import/dynamic-execution policy check; not a comprehensive security audit.", "findings": violations}
    if stage == "release":
        archive = output / "textstats.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(source, "textstats.py")
        manifest = {"run_id": context["run_id"], "source_sha256": sha(source), "archive_sha256": sha(archive)}
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return {"status": "passed", "summary": "Created a local release ZIP and SHA-256 manifest.", **manifest}
    if stage == "deploy":
        release = prior(context, "release")
        manifest = json.loads((release / "manifest.json").read_text())
        archive = release / "textstats.zip"
        if sha(archive) != manifest["archive_sha256"] or sha(source) != manifest["source_sha256"]:
            raise ValueError("Release or source digest mismatch")
        installed = output / "installed"
        installed.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            if bundle.namelist() != ["textstats.py"]:
                raise ValueError("Unexpected archive contents")
            (installed / "textstats.py").write_bytes(bundle.read("textstats.py"))
        if sha(installed / "textstats.py") != manifest["source_sha256"]:
            raise ValueError("Installed script digest mismatch")
        (output / "deployment.json").write_text(json.dumps(manifest, indent=2))
        return {"status": "passed", "summary": "Installed the verified release into a separate local directory; no cloud service or listener.", "location": str(installed), **manifest}
    raise ValueError(f"Unsupported stage {stage}")


if __name__ == "__main__":
    context = json.loads(Path(os.environ["FACTORY_CONTEXT"]).read_text())
    try:
        result = execute(context)
    except Exception as exc:
        result = {"status": "failed", "summary": f"{type(exc).__name__}: {exc}"}
    (Path(context["output"]) / "result.json").write_text(json.dumps(result, indent=2))
    print(result["summary"])
    raise SystemExit(0 if result["status"] == "passed" else 1)

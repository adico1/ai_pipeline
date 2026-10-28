"""Trusted adapters for real local checks, packaging, deployment and observation."""
import ast
import hashlib
import json
import os
import sys
from pathlib import Path
import zipfile

from httpstats_checks import verify


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prior(context, stage):
    matches = [a for a in context["history"] if a["stage"] == stage and a["status"] == "passed"]
    if not matches:
        raise ValueError(f"Missing successful {stage} evidence")
    return Path(matches[-1]["artifact_directory"])


def execute(context, *, word_frequencies=False, utf8_bytes=False, history=False):
    stage = context["stage"]
    output = Path(context["output"])
    source = Path(context["workspace"]) / "server.py"
    if stage in {"verify", "observe"}:
        script = source if stage == "verify" else prior(context, "deploy") / "installed" / "server.py"
        if stage == "observe":
            receipt = json.loads((prior(context, "deploy") / "deployment.json").read_text())
            if sha(script) != receipt["source_sha256"]:
                raise ValueError("Installed script differs from deployment receipt")
        checker = verify
        if word_frequencies:
            from word_frequency_checks import verify as checker
        if utf8_bytes:
            from utf8_checks import verify as checker
        if history:
            from history_checks import verify as checker
        scenarios = checker(script)
        if history:
            from history_checks import verify_documentation
            scenarios += verify_documentation(script, Path(context["workspace"]) / "README.md")
        (output / "scenarios.json").write_text(json.dumps(scenarios, indent=2, ensure_ascii=False))
        documentation_errors = []
        if utf8_bytes:
            from utf8_checks import documentation_findings
            documentation_errors = documentation_findings(Path(context["workspace"]))
        passed = sum(r["passed"] for r in scenarios)
        return {"status": "passed" if passed == len(scenarios) and not documentation_errors else "failed",
                "summary": f"{passed}/{len(scenarios)} real HTTP scenarios passed against {stage} target.",
                "findings": documentation_errors,
                "baseline_tests_passed": all(r["passed"] for r in scenarios if r["baseline"]),
                "failed_cases": [r for r in scenarios if not r["passed"]]}
    if stage == "security":
        tree = ast.parse(source.read_text())
        violations = []
        allowed = {"argparse", "json", "sys", "http.server"}
        if history:
            allowed |= {"sqlite3", "contextlib", "pathlib", "re", "urllib.parse"}
        for node in ast.walk(tree):
            imports = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) else []
            for name in imports:
                if name not in allowed:
                    violations.append(f"Unapproved import {name!r} at line {node.lineno}; allowed imports: {', '.join(sorted(allowed))}. Remove the import or implement the behavior without it.")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "compile", "__import__"}:
                violations.append(f"Dynamic code execution at line {node.lineno}")
        return {"status": "failed" if violations else "passed", "summary": "Limited static import/dynamic-execution policy check; not a comprehensive security audit.", "findings": violations}
    if stage == "release":
        archive = output / "httpstats.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(source, "server.py")
        manifest = {"run_id": context["run_id"], "source_sha256": sha(source), "archive_sha256": sha(archive)}
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return {"status": "passed", "summary": "Created a local release ZIP and SHA-256 manifest.", **manifest}
    if stage == "deploy":
        release = prior(context, "release")
        manifest = json.loads((release / "manifest.json").read_text())
        archive = release / "httpstats.zip"
        if sha(archive) != manifest["archive_sha256"] or sha(source) != manifest["source_sha256"]:
            raise ValueError("Release or source digest mismatch")
        installed = output / "installed"
        installed.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            if bundle.namelist() != ["server.py"]:
                raise ValueError("Unexpected archive contents")
            (installed / "server.py").write_bytes(bundle.read("server.py"))
        if sha(installed / "server.py") != manifest["source_sha256"]:
            raise ValueError("Installed script digest mismatch")
        (output / "deployment.json").write_text(json.dumps(manifest, indent=2))
        return {"status": "passed", "summary": "Installed the verified release into a separate local directory; observation starts a temporary loopback service and stops it afterward.", "location": str(installed), **manifest}
    raise ValueError(f"Unsupported stage {stage}")


if __name__ == "__main__":
    context = json.loads(Path(os.environ["FACTORY_CONTEXT"]).read_text())
    try:
        result = execute(context, word_frequencies="--word-frequencies" in sys.argv[1:],
                         utf8_bytes="--utf8-bytes" in sys.argv[1:],
                         history="--history" in sys.argv[1:])
    except Exception as exc:
        result = {"status": "failed", "summary": f"{type(exc).__name__}: {exc}"}
    (Path(context["output"]) / "result.json").write_text(json.dumps(result, indent=2))
    print(result["summary"])
    raise SystemExit(0 if result["status"] == "passed" else 1)

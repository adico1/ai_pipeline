"""Durable SDLC state machine. Adapters are trusted operator-supplied commands."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid


STAGES = (
    "requirements",
    "design",
    "plan",
    "implement",
    "verify",
    "security",
    "review",
    "release",
    "deploy",
    "observe",
    "retrospective",
)
READ_ONLY = {
    "verify",
    "security",
    "review",
    "release",
    "deploy",
    "observe",
    "retrospective",
}
MANDATORY_GATES = {"release", "deploy"}
EXCLUDED = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv"}
AI_STAGES = {"requirements", "design", "plan", "implement", "review", "retrospective"}


class FactoryError(Exception):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def digest_tree(root: Path):
    """Fingerprint source, including untracked files; avoid following symlinks."""
    digest = hashlib.sha256()
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED)
        paths = [Path(directory) / name for name in files]
        paths += [
            Path(directory) / name
            for name in dirs
            if (Path(directory) / name).is_symlink()
        ]
        for path in sorted(paths):
            if path.name == ".git":
                continue
            relative = path.relative_to(root).as_posix()
            content = (
                os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
            )
            digest.update(
                json.dumps([relative, path.lstat().st_mode, len(content)]).encode()
            )
            digest.update(content)
    return digest.hexdigest()


def load_config(path: Path):
    config = json.loads(path.read_text())
    if config.get("version") != 1:
        raise FactoryError("Project configuration must have version: 1")
    if not isinstance(config.get("name"), str) or not config["name"].strip():
        raise FactoryError("Project name is required")
    stages = config.get("stages", {})
    if set(stages) != set(STAGES):
        raise FactoryError("Configure every SDLC stage: " + ", ".join(STAGES))
    for name, stage in stages.items():
        if (
            not isinstance(stage.get("timeout_seconds", 300), (int, float))
            or not 0 < stage.get("timeout_seconds", 300) <= 3600
        ):
            raise FactoryError(f"{name}: timeout_seconds must be between 0 and 3600")
        if stage.get("backend", "command") not in {"command", "crewai"}:
            raise FactoryError(f"{name}: unsupported backend")
        if stage.get("backend") == "crewai":
            if name not in AI_STAGES:
                raise FactoryError(f"{name}: requires an independent command adapter")
            continue
        command = stage.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(x, str) for x in command)
        ):
            raise FactoryError(f"{name}: command must be a nonempty argument list")
    repairs = config.get("max_repairs", 2)
    if type(repairs) is not int or not 0 <= repairs <= 5:
        raise FactoryError("max_repairs must be an integer between 0 and 5")
    if not set(config.get("gates", [])) <= set(STAGES):
        raise FactoryError("Unknown approval gate")
    return config


class Factory:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, run_id):
        if (
            not run_id
            or any(c not in "0123456789abcdef" for c in run_id)
            or len(run_id) != 12
        ):
            raise FactoryError("Invalid run ID")
        directory = self.root / run_id
        if not (directory / "state.json").exists():
            raise FactoryError(f"Unknown run: {run_id}")
        return directory

    @contextlib.contextmanager
    def lock(self, directory):
        # OS-owned locks are released if the process crashes. Local POSIX MVP.
        import fcntl

        with (directory / "lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise FactoryError("This run is already being operated") from exc
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def save(self, directory, state):
        state["updated_at"] = now()
        write_json(directory / "state.json", state)

    def event(self, directory, kind, **data):
        with (directory / "events.jsonl").open("a") as stream:
            stream.write(json.dumps({"at": now(), "kind": kind, **data}) + "\n")

    def create(self, config_path: Path, task: str, demo=False):
        config = load_config(config_path.resolve())
        if not task.strip():
            raise FactoryError("A task is required")
        run_id = uuid.uuid4().hex[:12]
        directory = self.root / run_id
        workspace = directory / "workspace"
        directory.mkdir()
        if demo:
            if not config.get("demo"):
                raise FactoryError("Demo mode requires a demo configuration")
            workspace.mkdir()
            (workspace / "calculator.py").write_text(
                "def add(a, b):\n    return a - b\n"
            )
            base = None
        else:
            if config.get("demo"):
                raise FactoryError("Use the demo command for demo configurations")
            repo = Path(config.get("repository", "")).expanduser()
            if not repo.is_absolute():
                repo = (config_path.resolve().parent / repo).resolve()
            try:
                base = subprocess.check_output(
                    ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
                ).strip()
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(repo),
                        "worktree",
                        "add",
                        "--detach",
                        str(workspace),
                        base,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                raise FactoryError(
                    f"Cannot create isolated Git worktree: {exc.stderr}"
                ) from exc
        write_json(directory / "config.json", config)
        (directory / "task.txt").write_text(task)
        state = {
            "id": run_id,
            "project": config["name"],
            "demo": demo,
            "base_commit": base,
            "created_at": now(),
            "status": "queued",
            "stage": 0,
            "repairs": 0,
            "attempts": [],
            "approvals": [],
            "verified_digest": None,
            "config_digest": hashlib.sha256(
                (directory / "config.json").read_bytes()
            ).hexdigest(),
            "task_digest": hashlib.sha256(
                (directory / "task.txt").read_bytes()
            ).hexdigest(),
        }
        self.save(directory, state)
        self.event(directory, "created", demo=demo, base_commit=base)
        return state

    def status(self, run_id):
        return json.loads((self.directory(run_id) / "state.json").read_text())

    def list_runs(self):
        return [
            json.loads(p.read_text()) for p in sorted(self.root.glob("*/state.json"))
        ]

    def binding(self, directory, state):
        return hashlib.sha256(
            json.dumps(
                {
                    "source": digest_tree(directory / "workspace"),
                    "config": hashlib.sha256(
                        (directory / "config.json").read_bytes()
                    ).hexdigest(),
                    "task": hashlib.sha256(
                        (directory / "task.txt").read_bytes()
                    ).hexdigest(),
                    "artifacts": digest_tree(directory / "artifacts"),
                    "attempts": state["attempts"],
                    "stage": state["stage"],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()

    def approve(self, run_id, actor, note):
        directory = self.directory(run_id)
        with self.lock(directory):
            state = self.status(run_id)
            if state["status"] != "awaiting_approval":
                raise FactoryError("Run is not awaiting approval")
            if not actor.strip() or not note.strip():
                raise FactoryError("Approval requires an actor and review note")
            binding = self.binding(directory, state)
            if binding != state["pending_binding"]:
                raise FactoryError(
                    "Source or evidence changed since review; advance again to refresh the gate"
                )
            approval = {
                "actor": actor,
                "note": note,
                "stage": STAGES[state["stage"]],
                "binding": binding,
                "at": now(),
            }
            state["approvals"].append(approval)
            state["status"] = "ready"
            self.event(directory, "approved", **approval)
            self.save(directory, state)
            return state

    def retry(self, run_id):
        directory = self.directory(run_id)
        with self.lock(directory):
            state = self.status(run_id)
            if state["status"] not in {"failed", "running"}:
                raise FactoryError("Only failed or interrupted runs can be retried")
            stage = STAGES[state["stage"]]
            if stage in {"release", "deploy"}:
                raise FactoryError(
                    "Release/deploy outcome may be unknown. Reconcile externally and create a new run; these stages are never replayed automatically"
                )
            state["status"] = "ready"
            state["approvals"] = []
            self.event(directory, "retry_requested", stage=stage)
            self.save(directory, state)
            return state

    def _write_stage_context(self, directory, state, name, spec, artifact):
        """Give the adapter the task, audit history, and trusted check commands."""
        context = {
            "run_id": state["id"],
            "project": state["project"],
            "stage": name,
            "task": (directory / "task.txt").read_text(),
            "workspace": str(directory / "workspace"),
            "artifacts": str(directory / "artifacts"),
            "output": str(artifact),
            "previous_attempt": state["attempts"][-1] if state["attempts"] else None,
            "demo": state["demo"],
            "base_commit": state["base_commit"],
            "history": [
                {
                    "stage": attempt["stage"],
                    "status": attempt["status"],
                    "result": attempt["result"],
                    "artifact_directory": attempt["artifact_directory"],
                }
                for attempt in state["attempts"]
            ],
            "crewai": spec.get("crewai", {}),
        }
        config = json.loads((directory / "config.json").read_text())
        context["checks"] = {
            stage: config["stages"][stage] for stage in ("verify", "security")
        }
        write_json(artifact / "context.json", context)

    def _run_adapter(self, directory, artifact, spec):
        """Run a trusted adapter with captured logs and kill its process group on timeout."""
        env = {
            **os.environ,
            "FACTORY_CONTEXT": str(artifact / "context.json"),
            "FACTORY_OUTPUT": str(artifact),
            "PYTHONDONTWRITEBYTECODE": "1",
            "CREWAI_STORAGE_DIR": str(artifact / "crewai-storage"),
            "CREWAI_TRACING_ENABLED": "false",
            "OTEL_SDK_DISABLED": "true",
            "CREWAI_TELEMETRY_OPT_OUT": "true",
        }
        command = (
            [
                sys.executable,
                str(Path(__file__).with_name("crewai_adapter.py").resolve()),
            ]
            if spec.get("backend") == "crewai"
            else spec["command"]
        )
        error = None
        code = None
        with (
            (artifact / "stdout.log").open("w") as stdout,
            (artifact / "stderr.log").open("w") as stderr,
        ):
            try:
                process = subprocess.Popen(
                    command,
                    cwd=directory / "workspace",
                    env=env,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
                try:
                    code = process.wait(timeout=spec.get("timeout_seconds", 300))
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    error = "Adapter timed out"
            except OSError as exc:
                error = str(exc)
        return code, error

    @staticmethod
    def _read_adapter_result(artifact, error):
        """Preserve earlier execution errors when validating the result protocol."""
        result = None
        try:
            result = json.loads((artifact / "result.json").read_text())
            if (
                not isinstance(result, dict)
                or result.get("status") != "passed"
                or not isinstance(result.get("summary"), str)
                or not result["summary"].strip()
            ):
                error = (
                    error or "Adapter did not provide a passed result with a summary"
                )
        except (OSError, ValueError):
            error = error or "Adapter did not produce valid result.json"
        return result, error

    def execute(self, directory, state, name, spec):
        """Execute one attempt and append evidence; the caller decides the next stage."""
        attempt_number = len(state["attempts"]) + 1
        artifact = (
            directory
            / "artifacts"
            / f"{attempt_number:03d}-{name}-{uuid.uuid4().hex[:8]}"
        )
        artifact.mkdir(parents=True)
        self._write_stage_context(directory, state, name, spec, artifact)
        before = digest_tree(directory / "workspace")
        start = time.monotonic()
        code, error = self._run_adapter(directory, artifact, spec)
        after = digest_tree(directory / "workspace")
        result, error = self._read_adapter_result(artifact, error)
        if name in READ_ONLY and before != after:
            error = (
                "Verification or delivery adapter modified source; evidence invalidated"
            )
        if code != 0:
            error = error or f"Adapter exited with code {code}"
        attempt = {
            "stage": name,
            "number": attempt_number,
            "at": now(),
            "duration_seconds": round(time.monotonic() - start, 3),
            "exit_code": code,
            "source_before": before,
            "source_after": after,
            "status": "failed" if error else "passed",
            "error": error,
            "result": result,
            "artifact_directory": str(artifact),
        }
        write_json(artifact / "evidence.json", attempt)
        state["attempts"].append(attempt)
        self.event(directory, "stage_finished", **attempt)
        return attempt

    @staticmethod
    def _verification_is_stale(directory, state):
        past_verification = state["stage"] > STAGES.index("verify")
        return past_verification and state["verified_digest"] != digest_tree(
            directory / "workspace"
        )

    @staticmethod
    def _has_approval(state, stage, binding):
        return any(
            approval["stage"] == stage and approval["binding"] == binding
            for approval in state["approvals"]
        )

    @staticmethod
    def _can_repair(state, stage, config):
        return stage in {"verify", "security"} and state["repairs"] < config.get(
            "max_repairs", 2
        )

    def advance(self, run_id):
        """Run until an approval gate, terminal failure, or lifecycle completion.

        Persist before starting each adapter so an interrupted process cannot be
        silently replayed. Source changes invalidate verification and approvals;
        once delivery starts, they require operator reconciliation instead.
        """
        directory = self.directory(run_id)
        with self.lock(directory):
            state = self.status(run_id)
            if state["status"] in {"completed", "failed"}:
                return state
            if state["status"] == "running":
                raise FactoryError(
                    "Interrupted run: inspect evidence before using retry"
                )
            config = load_config(directory / "config.json")
            if (
                hashlib.sha256((directory / "config.json").read_bytes()).hexdigest()
                != state["config_digest"]
                or hashlib.sha256((directory / "task.txt").read_bytes()).hexdigest()
                != state["task_digest"]
            ):
                raise FactoryError(
                    "Run configuration or task changed; create a new run"
                )
            gates = MANDATORY_GATES | set(config.get("gates", ["design"]))
            while state["stage"] < len(STAGES):
                name = STAGES[state["stage"]]
                if self._verification_is_stale(directory, state):
                    if any(
                        a["stage"] in {"release", "deploy"} for a in state["attempts"]
                    ):
                        state["status"] = "failed"
                        self.event(
                            directory,
                            "evidence_invalidated",
                            reason="Source changed after delivery started; manual reconciliation required",
                        )
                        self.save(directory, state)
                        return state
                    state["stage"] = STAGES.index("verify")
                    state["verified_digest"] = None
                    state["approvals"] = []
                    self.event(
                        directory,
                        "evidence_invalidated",
                        reason="Source changed after verification",
                    )
                    continue
                binding = self.binding(directory, state)
                if name in gates and not self._has_approval(state, name, binding):
                    state["status"] = "awaiting_approval"
                    state["pending_binding"] = binding
                    self.save(directory, state)
                    return state
                state["status"] = "running"
                self.save(directory, state)
                attempt = self.execute(directory, state, name, config["stages"][name])
                if attempt["status"] == "failed":
                    if self._can_repair(state, name, config):
                        state["repairs"] += 1
                        state["stage"] = STAGES.index("implement")
                        state["verified_digest"] = None
                        state["approvals"] = []
                        state["status"] = "ready"
                        self.save(directory, state)
                        continue
                    state["status"] = "failed"
                    self.save(directory, state)
                    return state
                if name == "verify":
                    state["verified_digest"] = attempt["source_after"]
                state["stage"] += 1
                state["status"] = "ready"
                self.save(directory, state)
            state["status"] = "completed"
            self.save(directory, state)
            self.event(directory, "completed")
            return state

    def metrics(self):
        runs = self.list_runs()
        attempts = [a for r in runs for a in r["attempts"]]
        verifies = [a for a in attempts if a["stage"] == "verify"]
        durations = sorted(a["duration_seconds"] for a in verifies)
        return {
            "runs": len(runs),
            "demo_runs": sum(r["demo"] for r in runs),
            "completed": sum(r["status"] == "completed" for r in runs),
            "verification_attempts": len(verifies),
            "verification_failures": sum(a["status"] == "failed" for a in verifies),
            "verification_duration_p50_seconds": (
                durations[(len(durations) - 1) // 2] if durations else None
            ),
            "repairs": sum(r["repairs"] for r in runs),
            "escape_rate": None,
            "escape_rate_note": "Requires real production incident attribution; demo observations are not production evidence",
        }

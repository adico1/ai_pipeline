import argparse
import json
import os
from pathlib import Path
import sys

from dotenv import dotenv_values, load_dotenv

from .engine import AI_STAGES, Factory, FactoryError, STAGES, write_json
from .status import format_status


def load_environment(path):
    values = dotenv_values(path)
    load_dotenv(dotenv_path=path, override=False)
    direct = values.get(
        "FACTORY_OPENAI_DIRECT", os.environ.get("FACTORY_OPENAI_DIRECT", "")
    )
    if (direct or "").lower() in {"true", "1", "yes"}:
        # Explicit per-project opt-in overrides inherited gateway routing only
        # in this CLI process and its children, never the user's shell.
        for name in ("OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_API_BASE_URL"):
            os.environ[name] = "https://api.openai.com/v1"
        if "OPENAI_API_KEY" in values:
            os.environ["OPENAI_API_KEY"] = values["OPENAI_API_KEY"] or ""


def demo_config(path):
    adapter = Path(__file__).with_name("demo_adapter.py").resolve()
    config = {
        "version": 1,
        "name": "calculator-demo",
        "demo": True,
        "max_repairs": 2,
        "gates": ["design"],
        "stages": {
            stage: {"command": [sys.executable, str(adapter)], "timeout_seconds": 15}
            for stage in STAGES
        },
    }
    write_json(path, config)
    return path


def display(state):
    print(json.dumps(state, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Evidence-driven SDLC factory")
    parser.add_argument("--state-dir", type=Path, default=Path(".factory"))
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Load settings from this file (default: .env in the current directory); shell settings take precedence",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="Create and start a local simulated lifecycle")
    init = commands.add_parser("init", help="Write a project configuration template")
    source = init.add_mutually_exclusive_group(required=True)
    source.add_argument("--repository", type=Path)
    source.add_argument("--blank", action="store_true", help="Start without application files or an existing repository")
    init.add_argument("--name", help="Project name for a blank project")
    init.add_argument("--output", default=Path("factory.json"), type=Path)
    init.add_argument(
        "--model",
        help="CrewAI provider/model name; otherwise use FACTORY_MODEL at execution",
    )
    create = commands.add_parser("create")
    create.add_argument("--config", required=True, type=Path)
    create.add_argument("--task", required=True)
    for name in ("advance", "status", "retry"):
        subparser = commands.add_parser(name)
        subparser.add_argument("run_id")
        if name == "status":
            subparser.add_argument(
                "--json",
                action="store_true",
                help="Print the full recorded state as JSON",
            )
    approve = commands.add_parser("approve")
    approve.add_argument("run_id")
    approve.add_argument("--actor", required=True)
    approve.add_argument("--note", required=True)
    commands.add_parser("list")
    commands.add_parser("metrics")
    args = parser.parse_args()
    load_environment(args.env_file)
    try:
        factory = Factory(args.state_dir)
        if args.command == "init":
            if args.output.exists():
                raise FactoryError("Refusing to overwrite an existing configuration")
            write_json(
                args.output,
                {
                    "version": 1,
                    "name": (args.name or "new-project") if args.blank else args.repository.resolve().name,
                    **({"starting_point": "blank"} if args.blank else
                       {"repository": str(args.repository.resolve())}),
                    "max_repairs": 2,
                    "gates": ["design"],
                    "stages": {
                        stage: (
                            {
                                "backend": "crewai",
                                "crewai": {"model": args.model},
                                "timeout_seconds": 300,
                            }
                            if stage in AI_STAGES
                            else {
                                "backend": "command",
                                "command": [],
                                "timeout_seconds": 300,
                            }
                        )
                        for stage in STAGES
                    },
                },
            )
            print(
                f"Created {args.output.resolve()}. CrewAI handles agent stages; configure verification, security, release, deploy and observe commands before creating a run."
            )
        elif args.command == "demo":
            config = demo_config(factory.root / "demo-config.json")
            state = factory.create(
                config,
                "Fix addition for positive, negative, and zero inputs.",
                demo=True,
            )
            display(factory.advance(state["id"]))
        elif args.command == "create":
            display(factory.create(args.config, args.task))
        elif args.command == "approve":
            display(factory.approve(args.run_id, args.actor, args.note))
        elif args.command == "list":
            display(factory.list_runs())
        elif args.command == "status":
            state = factory.status(args.run_id)
            if args.json:
                display(state)
            else:
                print(format_status(state, args.state_dir, args.env_file))
        elif args.command == "metrics":
            display(factory.metrics())
        else:
            display(getattr(factory, args.command)(args.run_id))
    except (FactoryError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

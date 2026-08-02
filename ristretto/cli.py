"""Command-line interface for configuration, flows, and health checks."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import (
    ConfigError,
    doctor,
    flow_json,
    instance_value,
    load_config,
    repository_path,
    resolved_flow,
    user_config_path,
    write_user_config,
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="ristretto")
    root.add_argument("--config", type=Path, help="configuration file override")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="validate the configuration")

    flow = commands.add_parser("flow", help="inspect coding flows")
    flow_commands = flow.add_subparsers(dest="flow_command", required=True)
    flow_commands.add_parser("list", help="list configured flows")
    show = flow_commands.add_parser("show", help="show one resolved flow")
    show.add_argument("name", nargs="?")

    commands.add_parser("doctor", help="check provider commands and instance settings")

    instance = commands.add_parser("instance", help="read resolved instance settings")
    instance_commands = instance.add_subparsers(dest="instance_command", required=True)
    instance_get = instance_commands.add_parser("get", help="print one resolved setting")
    instance_get.add_argument("key")

    repo = commands.add_parser("repo", help="resolve configured project repositories")
    repo_commands = repo.add_subparsers(dest="repo_command", required=True)
    repo_commands.add_parser("list", help="list configured project repositories")
    repo_resolve = repo_commands.add_parser("resolve", help="resolve a project path")
    repo_resolve.add_argument("project")

    configure = commands.add_parser("configure", help="write non-secret user settings")
    configure.add_argument("--name")
    configure.add_argument("--linear-team")
    configure.add_argument("--slack-home-channel")
    configure.add_argument("--slack-prs-channel")
    configure.add_argument("--slack-alerts-channel")
    configure.add_argument("--knowledge-vault")
    configure.add_argument(
        "--repository",
        action="append",
        default=[],
        metavar="PROJECT=PATH",
        help="add or replace a project repository mapping",
    )

    ops = commands.add_parser("ops-daemon", help="run the Telegram ops lane daemon")
    ops.add_argument("--check", action="store_true", help="validate config and exit")

    commands.add_parser("ops-init", help="scaffold Telegram ops lane config")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config, path = load_config(args.config)
        if args.command == "validate":
            print(f"configuration valid: {path}")
            return 0
        if args.command == "flow":
            if args.flow_command == "list":
                for name, value in config["flows"].items():
                    default = " (default)" if name == config["default_flow"] else ""
                    print(f"{name}{default}\t{value.get('description', '')}")
                return 0
            print(flow_json(resolved_flow(config, args.name)))
            return 0
        if args.command == "doctor":
            findings = doctor(config)
            print(f"config: {path}")
            print("\n".join(findings))
            return 1 if any(line.startswith("ERROR") for line in findings) else 0
        if args.command == "instance":
            print(instance_value(config, args.key))
            return 0
        if args.command == "repo":
            if args.repo_command == "list":
                for name, value in config.get("repositories", {}).items():
                    print(f"{name}\t{Path(value).expanduser()}")
                return 0
            print(repository_path(config, args.project))
            return 0
        if args.command == "configure":
            target = args.config.expanduser() if args.config else user_config_path()
            updates = {
                "name": args.name,
                "linear_team": args.linear_team,
                "slack_home_channel": args.slack_home_channel,
                "slack_prs_channel": args.slack_prs_channel,
                "slack_alerts_channel": args.slack_alerts_channel,
                "knowledge_vault": args.knowledge_vault,
            }
            instance = config.setdefault("instance", {})
            for key, value in updates.items():
                if value is not None:
                    instance[key] = value
            repo_map = config.setdefault("repositories", {})
            for item in args.repository:
                if "=" not in item:
                    raise ConfigError("--repository must use PROJECT=PATH")
                name, value = item.split("=", 1)
                if not name.strip() or not value.strip():
                    raise ConfigError("--repository must use non-empty PROJECT=PATH")
                repo_map[name.strip()] = value.strip()
            write_user_config(config, target)
            print(f"configuration updated: {target}")
            return 0
        if args.command == "ops-daemon":
            from .ops_lane.cli import load_ops_env, ops_daemon_check, run_ops_daemon

            if args.check:
                load_ops_env()
                code, msg = ops_daemon_check(os.environ)
                print(msg)
                return code
            return run_ops_daemon(os.environ)
        if args.command == "ops-init":
            from .ops_lane.cli import ops_init

            return ops_init(os.environ)
    except ConfigError as exc:
        print(f"ristretto: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

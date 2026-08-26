"""Command-line interface for configuration, flows, and health checks."""

from __future__ import annotations

import argparse
import json
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

    preflight_command = commands.add_parser(
        "preflight", help="check a repository can run a supervised loop"
    )
    preflight_command.add_argument("project", help="configured project name or repository path")
    preflight_command.add_argument(
        "--deep",
        action="store_true",
        help="clone the base branch and run the verify gate from a clean checkout",
    )

    migrate_command = commands.add_parser(
        "migrate", help="drop project-layer copies from the user configuration"
    )
    migrate_command.add_argument(
        "--force", action="store_true", help="rewrite the file; without this it only reports"
    )
    migrate_command.add_argument(
        "--adopt",
        action="store_true",
        help="also take the shipped version of entries that differ",
    )

    gc_command = commands.add_parser(
        "gc", help="reclaim worktrees and branches left by finished tasks"
    )
    gc_command.add_argument(
        "project", nargs="?", help="configured project name or path (default: all configured)"
    )
    gc_command.add_argument(
        "--force", action="store_true", help="actually remove; without this it only reports"
    )
    gc_command.add_argument(
        "--branches", action="store_true", help="also delete local branches merged into the base"
    )

    dash_command = commands.add_parser("dash", help="serve the read-only fleet view")
    dash_command.add_argument("--host", help="bind address (default: tailnet, else loopback)")
    dash_command.add_argument("--port", type=int, default=8787)
    dash_command.add_argument("--reload", action="store_true", help="reload on code changes")

    events_command = commands.add_parser("events", help="read the pipeline event log")
    events_command.add_argument("task_id", nargs="?", help="limit to one task")
    events_command.add_argument("--limit", type=int, default=50)
    events_command.add_argument("--json", action="store_true", help="print raw JSON")

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
        if args.command == "preflight":
            from . import events as event_log
            from .preflight import preflight

            candidate = Path(args.project).expanduser()
            repo = candidate if candidate.is_dir() else repository_path(config, args.project)
            base = str(config.get("base_branch", "main"))
            findings = preflight(repo, base, deep=args.deep)
            print(f"repo: {repo}")
            for finding in findings:
                print(finding)
            failed = [f for f in findings if f.level == "ERROR"]
            event_log.emit(
                f"preflight-{repo.name}",
                "preflight.failed" if failed else "preflight.passed",
                project=repo.name,
                payload={"repo": str(repo), "errors": [f.message for f in failed]} if failed else None,
            )
            return 1 if failed else 0
        if args.command == "migrate":
            from .config import (
                entry_differences,
                packaged_config_path,
                pinned_project_keys,
                read_yaml,
            )

            target = args.config.expanduser() if args.config else user_config_path()
            if not target.is_file():
                print(f"nothing to migrate: {target} does not exist")
                return 0
            packaged = packaged_config_path()
            stored = read_yaml(target)
            pinned = pinned_project_keys(stored, read_yaml(packaged) if packaged.is_file() else {})
            kept = {
                key
                for key in stored
                if key not in ("instance", "repositories", "default_flow", "base_branch")
            }
            if not pinned and not kept:
                print(f"{target} already holds only user settings")
                return 0
            print(f"config: {target}")
            for name in pinned:
                print(f"  DROP  {name}  (identical to the shipped version)")
            differences = entry_differences(
                stored, read_yaml(packaged) if packaged.is_file() else {}
            )
            verb = "DROP " if args.adopt else "KEEP "
            for name, lines in differences.items():
                note = "adopting the shipped version" if args.adopt else "stays pinned"
                print(f"  {verb} {name}  (differs — {note})")
                for line in lines:
                    print(f"          {line}")
            if differences and not args.adopt:
                print(
                    "\nA difference may be a deliberate change or simply an out-of-date copy."
                    "\nReview the fields above; --adopt takes the shipped version for all of them."
                )
            if not args.force:
                print("\nRe-run with --force to rewrite. A backup is written alongside.")
                return 0
            backup = target.with_suffix(f"{target.suffix}.bak")
            backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
            merged = load_config(target)[0]
            if args.adopt:
                packaged_raw = read_yaml(packaged) if packaged.is_file() else {}
                for key in ("providers", "flows"):
                    for name in list((stored.get(key) or {})):
                        shipped = (packaged_raw.get(key) or {}).get(name)
                        if shipped is not None:
                            merged.setdefault(key, {})[name] = shipped
            write_user_config(merged, target)
            print(f"rewrote {target} (backup: {backup})")
            return 0
        if args.command == "gc":
            from . import gc as garbage

            if args.project:
                candidate = Path(args.project).expanduser()
                repos = [candidate if candidate.is_dir() else repository_path(config, args.project)]
            else:
                repos = [
                    Path(value).expanduser()
                    for value in config.get("repositories", {}).values()
                ]
            if not repos:
                print("no repositories configured")
                return 0
            base = str(config.get("base_branch", "main"))
            tasks = garbage.board_tasks()
            if not tasks:
                print("could not read the kanban board — refusing to remove anything")
                return 1
            removable = 0
            for repo in repos:
                if not repo.is_dir():
                    continue
                print(f"repo: {repo}")
                candidates = garbage.plan(repo, tasks)
                for item in candidates:
                    print(f"  {item}")
                removable += sum(1 for item in candidates if item.action == "remove")
                if args.force:
                    for line in garbage.reclaim(repo, candidates):
                        print(f"  {line}")
                if args.branches:
                    names = garbage.merged_branches(repo, base)
                    if not names:
                        print("  no merged branches to delete")
                    elif args.force:
                        for line in garbage.delete_branches(repo, names):
                            print(f"  {line}")
                    else:
                        for name in names:
                            print(f"  DELETE branch {name}  (merged into {base})")
            if not args.force and removable:
                print(f"\n{removable} worktree(s) would be removed. Re-run with --force.")
            return 0
        if args.command == "dash":
            try:
                from .dash.serve import BindRefused, run as serve_dash
            except ImportError as exc:
                print(
                    f"ristretto: the dashboard needs its extra dependencies: {exc}\n"
                    "  pip install 'ristretto-ops[dash]'",
                    file=sys.stderr,
                )
                return 2
            try:
                return serve_dash(args.host, args.port, args.reload)
            except BindRefused as exc:
                print(f"ristretto: {exc}", file=sys.stderr)
                return 2
        if args.command == "events":
            from . import events as event_log

            records = event_log.read(args.task_id, limit=args.limit)
            if args.json:
                print(json.dumps(records, indent=2, sort_keys=True))
                return 0
            if not records:
                print("no events recorded yet")
                return 0
            for record in reversed(records):
                print(event_log.format_line(record))
            return 0
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

"""Load and validate Cuzam's public configuration contract."""

from __future__ import annotations

import json
import os
import re
import shutil
import sysconfig
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml


SCHEMA_VERSION = 1
RUNNERS = {"claude-code", "codex"}
ROLES = {"plan", "build", "review", "repair", "verify", "pr", "custom"}
READ_ONLY_ROLES = {"plan", "review", "verify"}
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
SAFE_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
SAFE_ARTIFACT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
INSTANCE_KEYS = {
    "name",
    "linear_team",
    "slack_home_channel",
    "slack_prs_channel",
    "slack_alerts_channel",
    "knowledge_vault",
    # Which provider runs Zam's conversational loop (not the coding tiers).
    # Claude by default; set to a local provider to keep the assistant on the
    # machine. See docs/zam-roadmap.md.
    "assistant_provider",
}


class ConfigError(ValueError):
    """A user-facing configuration validation error."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_config_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    if env.get("CUZAM_CONFIG"):
        return Path(env["CUZAM_CONFIG"]).expanduser()
    xdg = Path(env.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    installed = xdg / "cuzam" / "config.yaml"
    if installed.exists():
        return installed
    source_tree = repo_root() / "cuzam.yaml"
    if source_tree.exists():
        return source_tree
    return Path(sysconfig.get_path("data")) / "share" / "cuzam" / "cuzam.yaml"


def user_config_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    if env.get("CUZAM_CONFIG"):
        return Path(env["CUZAM_CONFIG"]).expanduser()
    xdg = Path(env.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return xdg / "cuzam" / "config.yaml"


def user_env_path(environ: Mapping[str, str] | None = None) -> Path:
    """Cuzam's own secrets file, beside the config it already reads."""
    return user_config_path(environ).parent / "env"


def hermes_env_path(environ: Mapping[str, str] | None = None) -> Path:
    """Hermes' secrets file, which this machine already treats as canonical.

    A filename belonging to another project, so it is named here rather than
    inline — the same reason `seam.py` exists. Read, never written.
    """
    env = os.environ if environ is None else environ
    home = Path(env.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
    return home / ".env"


def parse_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines. No expansion, no substitution, no execution."""
    found: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return found
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export "):].strip()
        if not name.isidentifier():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        found[name] = value
    return found


# Secrets this project needs that no config file names. Everything else comes
# from the `*_env` indirection the instance and providers already declare.
EXTRA_SECRET_NAMES = ("LINEAR_API_KEY",)


def secret_names(config: Mapping[str, Any] | None = None) -> set[str]:
    """Exactly the environment variables this installation asks for.

    An allowlist, and the reason is worth stating. The files these values come
    from hold other projects' secrets too — hermes' holds Slack and browser
    tokens — and `start_flow` hands its whole environment to the flow, which
    hands it to a model. Loading a file wholesale would put credentials this
    project never uses into the environment of a process running generated
    code. Take the named few.
    """
    names = set(EXTRA_SECRET_NAMES)
    if config is None:
        try:
            config, _ = load_config()
        except Exception:  # noqa: BLE001 - loading secrets must not need a valid config
            return names
    instance = config.get("instance") or {}
    for key, value in instance.items():
        if key.endswith("_env") and isinstance(value, str) and value:
            names.add(value)
    for provider in (config.get("providers") or {}).values():
        if not isinstance(provider, Mapping):
            continue
        for key in ("auth_token_env", "model_env", "base_url_env"):
            value = provider.get(key)
            if isinstance(value, str) and value:
                names.add(value)
    return names


def load_env(
    environ: dict[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[str]:
    """Put the secrets these files hold into the environment. Returns the names.

    Cuzam keeps real credentials out of its YAML on purpose — `config.py`
    refuses a provider `auth_token` that is not the non-secret ollama
    placeholder and tells you to use `auth_token_env`. That rule is right and
    stays. What was missing is anything that *populates* those variables.

    It worked by accident for one launch path and not the other: Zam and the
    gateway are hermes processes, so they already hold hermes' environment and
    pass it to the flow they start; a `cuzam launch` from a shell holds
    whatever that shell has, which is nothing. The two are indistinguishable
    afterwards — a Linear key that is present but unreadable produces exactly
    the same "tracker not reachable" as no key at all.

    Anything already exported wins, so an explicit value on the command line
    is never overridden by a file. Values are never logged; only names are
    returned, which is what a caller needs to say "loaded 3 secrets" without
    printing one.
    """
    target = os.environ if environ is None else environ
    wanted = secret_names(config)
    loaded: list[str] = []
    # Cuzam's own file FIRST. The guard below skips a name that is already
    # set, so the first writer wins — anything exported beats both files, and
    # this project's own file beats hermes' copy of the same name.
    for path in (user_env_path(target), hermes_env_path(target)):
        for name, value in parse_env_file(path).items():
            if name not in wanted or target.get(name):
                continue
            target[name] = value
            if name not in loaded:
                loaded.append(name)
    return loaded


# Providers and flows describe how Cuzam works and ship with it. The
# instance and its repository map describe one person's machine. Copying the
# first group into the user's file is what let a live install sit on flows
# that had been replaced months earlier — valid, internally consistent, and
# silently out of date.
PROJECT_KEYS = frozenset({"schema_version", "providers", "flows"})
USER_KEYS = frozenset({"instance", "repositories", "default_flow", "base_branch"})
# Merged by name so a user may override or add one provider or flow without
# pinning the whole set.
MERGED_KEYS = ("providers", "flows")


def packaged_config_path(environ: Mapping[str, str] | None = None) -> Path:
    """The project layer that ships with Cuzam."""
    source_tree = repo_root() / "cuzam.yaml"
    if source_tree.is_file():
        return source_tree
    return Path(sysconfig.get_path("data")) / "share" / "cuzam" / "cuzam.yaml"


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"configuration root must be a mapping: {path}")
    return raw


def merge_layers(project: Mapping[str, Any], user: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay a user's settings on the shipped project layer."""
    merged: dict[str, Any] = {key: value for key, value in project.items()}
    for key, value in user.items():
        if key in MERGED_KEYS and isinstance(value, dict) and isinstance(merged.get(key), dict):
            combined = dict(merged[key])
            combined.update(value)
            merged[key] = combined
        else:
            merged[key] = value
    return merged


def pinned_project_keys(user: Mapping[str, Any], project: Mapping[str, Any]) -> list[str]:
    """Project-layer entries a user file is holding an identical copy of."""
    stale: list[str] = []
    for key in MERGED_KEYS:
        for name, value in (user.get(key) or {}).items():
            if (project.get(key) or {}).get(name) == value:
                stale.append(f"{key}.{name}")
    return stale


def entry_differences(
    user: Mapping[str, Any], project: Mapping[str, Any]
) -> dict[str, list[str]]:
    """Field-level differences for entries a user file has diverged on.

    A diff cannot distinguish a deliberate customisation from a copy that has
    simply fallen behind, so the difference is reported rather than guessed at.
    """
    report: dict[str, list[str]] = {}
    for key in MERGED_KEYS:
        for name, value in (user.get(key) or {}).items():
            shipped = (project.get(key) or {}).get(name)
            if shipped is None or shipped == value:
                continue
            lines: list[str] = []
            if isinstance(value, Mapping) and isinstance(shipped, Mapping):
                for field in sorted(set(value) | set(shipped)):
                    mine, theirs = value.get(field, "<absent>"), shipped.get(field, "<absent>")
                    if mine != theirs:
                        lines.append(f"{field}: yours={mine!r} shipped={theirs!r}")
            else:
                lines.append(f"yours={value!r} shipped={shipped!r}")
            report[f"{key}.{name}"] = lines
    return report


def load_config(
    path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], Path]:
    config_path = Path(path).expanduser() if path else default_config_path(environ)
    if not config_path.is_file():
        raise ConfigError(f"configuration not found: {config_path}")
    packaged = packaged_config_path(environ)
    user_raw = read_yaml(config_path)
    if packaged.is_file() and packaged.resolve() != config_path.resolve():
        raw = merge_layers(read_yaml(packaged), user_raw)
    else:
        raw = user_raw
    validate_config(raw)
    return raw, config_path.resolve()


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a mapping")
    return value


def _environment_field(value: Any, label: str) -> None:
    if value is not None and (not isinstance(value, str) or not ENV_NAME.fullmatch(value)):
        raise ConfigError(f"{label} must be an uppercase environment variable name")


def _artifact(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SAFE_ARTIFACT.fullmatch(value):
        raise ConfigError(f"{label} must be a safe artifact filename")
    return value


def _no_fallback_cycles(providers: Mapping[str, Any]) -> None:
    """Refuse a fallback chain that loops back on itself.

    `run_stage` retries on a different provider by recursing, so a config
    where a falls back to b and b back to a recurses once per attempt with
    nothing to stop it — and every hop is a real model run against a real
    budget, not a cheap loop. Each attempt also earns its own approval credit,
    so a cycle is expensive in worktree-hours as well as tokens.

    Caught here rather than guarded in the runner because it is a static
    property of the config: a chain that can loop is a mistake at the moment
    it is written, and `make check` validates the shipped config.
    """
    for name in providers:
        seen = [name]
        current = providers[name]
        while isinstance(current, Mapping) and current.get("fallback") is not None:
            step = str(current["fallback"])
            if step in seen:
                raise ConfigError(
                    "providers fallback chain loops: "
                    + " -> ".join([*seen, step])
                )
            seen.append(step)
            current = providers.get(step)


def validate_config(config: Mapping[str, Any]) -> None:
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ConfigError(f"schema_version must be {SCHEMA_VERSION}")

    instance = _mapping(config.get("instance", {}), "instance")
    for key, value in instance.items():
        if key.endswith("_env"):
            if key[:-4] not in INSTANCE_KEYS:
                raise ConfigError(f"unknown instance setting: {key}")
            _environment_field(value, f"instance.{key}")
        elif key not in INSTANCE_KEYS:
            raise ConfigError(f"unknown instance setting: {key}")
        elif not isinstance(value, str) or not value.strip() or "\n" in value:
            raise ConfigError(f"instance.{key} must be a non-empty single-line string")

    repositories = _mapping(config.get("repositories", {}), "repositories")
    for name, path in repositories.items():
        if not isinstance(name, str) or not name.strip() or "\n" in name:
            raise ConfigError("repository names must be non-empty single-line strings")
        if not isinstance(path, str) or not path.strip() or "\n" in path:
            raise ConfigError(f"repository {name!r} must have a non-empty path")

    providers = _mapping(config.get("providers"), "providers")
    if not providers:
        raise ConfigError("providers must not be empty")
    for name, value in providers.items():
        if not isinstance(name, str) or not SAFE_NAME.fullmatch(name):
            raise ConfigError(f"invalid provider name: {name!r}")
        provider = _mapping(value, f"providers.{name}")
        runner = provider.get("runner")
        if runner not in RUNNERS:
            raise ConfigError(
                f"providers.{name}.runner must be one of {sorted(RUNNERS)}"
            )
        for key in ("model_env", "base_url_env", "auth_token_env"):
            _environment_field(provider.get(key), f"providers.{name}.{key}")
        if provider.get("auth_token") not in (None, "ollama"):
            raise ConfigError(
                f"providers.{name}.auth_token may only use the non-secret ollama placeholder; "
                "real credentials must use auth_token_env"
            )
        context_length = provider.get("context_length")
        if context_length is not None and (
            not isinstance(context_length, int)
            or isinstance(context_length, bool)
            or context_length <= 0
        ):
            raise ConfigError(f"providers.{name}.context_length must be a positive integer")
        fallback = provider.get("fallback")
        if fallback is not None and fallback not in providers:
            raise ConfigError(f"providers.{name}.fallback references unknown provider {fallback}")

    _no_fallback_cycles(providers)

    flows = _mapping(config.get("flows"), "flows")
    if not flows:
        raise ConfigError("flows must not be empty")
    default_flow = config.get("default_flow")
    if default_flow not in flows:
        raise ConfigError(f"default_flow references unknown flow {default_flow!r}")

    for flow_name, value in flows.items():
        if not isinstance(flow_name, str) or not SAFE_NAME.fullmatch(flow_name):
            raise ConfigError(f"invalid flow name: {flow_name!r}")
        flow = _mapping(value, f"flows.{flow_name}")
        if flow.get("builtin") is not None:
            if flow.get("builtin") != "classic" or flow.get("stages") is not None:
                raise ConfigError(
                    f"flows.{flow_name}: builtin must be classic and cannot define stages"
                )
            continue
        stages = flow.get("stages")
        if not isinstance(stages, list) or not stages:
            raise ConfigError(f"flows.{flow_name}.stages must be a non-empty list")
        seen_ids: set[str] = set()
        available_artifacts: set[str] = set()
        pr_indexes: list[int] = []
        for index, raw_stage in enumerate(stages):
            label = f"flows.{flow_name}.stages[{index}]"
            stage = _mapping(raw_stage, label)
            stage_id = stage.get("id")
            if not isinstance(stage_id, str) or not SAFE_NAME.fullmatch(stage_id):
                raise ConfigError(f"{label}.id must be kebab-case")
            if stage_id in seen_ids:
                raise ConfigError(f"{label}.id is duplicated: {stage_id}")
            seen_ids.add(stage_id)
            role = stage.get("role")
            if role not in ROLES:
                raise ConfigError(f"{label}.role must be one of {sorted(ROLES)}")
            provider = stage.get("provider")
            if role == "verify":
                if provider != "builtin":
                    raise ConfigError(f"{label}: verify stages must use provider builtin")
            elif provider not in providers:
                raise ConfigError(f"{label}.provider references unknown provider {provider}")
            mutates = stage.get("mutates")
            if not isinstance(mutates, bool):
                raise ConfigError(f"{label}.mutates must be true or false")
            if role in READ_ONLY_ROLES and mutates:
                raise ConfigError(f"{label}: {role} stages must be read-only")
            timeout = stage.get("timeout", 3600)
            if not isinstance(timeout, int) or not 1 <= timeout <= 14400:
                raise ConfigError(f"{label}.timeout must be between 1 and 14400")
            inputs = stage.get("inputs", [])
            if not isinstance(inputs, list):
                raise ConfigError(f"{label}.inputs must be a list")
            for item in inputs:
                artifact = _artifact(item, f"{label}.inputs")
                if artifact not in available_artifacts:
                    raise ConfigError(f"{label} consumes unavailable artifact {artifact}")
            if stage.get("output") is not None:
                output = _artifact(stage["output"], f"{label}.output")
                if output in available_artifacts:
                    raise ConfigError(f"{label} overwrites artifact {output}")
                available_artifacts.add(output)
            if role == "pr":
                if not mutates:
                    raise ConfigError(f"{label}: pr stages must allow mutations")
                pr_indexes.append(index)
        if len(pr_indexes) > 1:
            raise ConfigError(f"flows.{flow_name} may contain at most one pr stage")
        if pr_indexes and pr_indexes[0] != len(stages) - 1:
            raise ConfigError(f"flows.{flow_name}: pr stage must be last")


def resolved_provider(
    config: Mapping[str, Any],
    name: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    providers = config["providers"]
    if name not in providers:
        raise ConfigError(f"unknown provider: {name}")
    resolved = dict(providers[name])
    for field in ("model", "base_url", "auth_token"):
        env_name = resolved.get(f"{field}_env")
        if env_name and env.get(env_name):
            resolved[field] = env[env_name]
    resolved["name"] = name
    return resolved


def instance_value(
    config: Mapping[str, Any],
    key: str,
    environ: Mapping[str, str] | None = None,
) -> str:
    if key not in INSTANCE_KEYS:
        raise ConfigError(f"unknown instance setting: {key}")
    env = os.environ if environ is None else environ
    instance = config.get("instance", {})
    env_name = instance.get(f"{key}_env")
    if env_name and env.get(env_name):
        return str(env[env_name])
    value = instance.get(key)
    if value:
        return str(value)
    raise ConfigError(f"instance setting is not configured: {key}")


def repository_path(config: Mapping[str, Any], project: str) -> Path:
    wanted = project.strip().casefold()
    matches = [
        path
        for name, path in config.get("repositories", {}).items()
        if name.strip().casefold() == wanted
    ]
    if not matches:
        raise ConfigError(f"repository is not configured for project: {project}")
    resolved = Path(matches[0]).expanduser()
    if not resolved.is_absolute():
        raise ConfigError(f"repository path must resolve to an absolute path: {matches[0]}")
    return resolved


def repositories(config: Mapping[str, Any]) -> dict[str, str]:
    repos = config.get("repositories") or {}
    return {str(name): str(Path(str(path)).expanduser()) for name, path in repos.items()}


def user_layer(
    config: Mapping[str, Any],
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Just the parts that belong to this machine.

    Anything identical to what shipped is dropped: re-persisting a copy is
    what let a live config keep serving flows that had since been replaced.
    """
    packaged = packaged_config_path(environ)
    project = read_yaml(packaged) if packaged.is_file() else {}
    layer: dict[str, Any] = {}
    for key, value in config.items():
        if key in USER_KEYS:
            layer[key] = value
        elif key in MERGED_KEYS and isinstance(value, dict):
            customised = {
                name: entry
                for name, entry in value.items()
                if (project.get(key) or {}).get(name) != entry
            }
            if customised:
                layer[key] = customised
    return layer


def write_user_config(
    config: Mapping[str, Any],
    path: Path,
    environ: Mapping[str, str] | None = None,
) -> None:
    validate_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        yaml.safe_dump(user_layer(config, environ), handle, sort_keys=False)
        temporary = Path(handle.name)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def resolved_flow(
    config: Mapping[str, Any],
    name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    flow_name = name or str(config["default_flow"])
    flows = config["flows"]
    if flow_name not in flows:
        raise ConfigError(f"unknown flow: {flow_name}")
    flow = dict(flows[flow_name])
    flow["name"] = flow_name
    if flow.get("builtin") == "classic":
        return flow
    stages: list[dict[str, Any]] = []
    for raw_stage in flow["stages"]:
        stage = dict(raw_stage)
        if stage["provider"] != "builtin":
            provider = resolved_provider(config, stage["provider"], environ)
            if stage.get("model"):
                provider["model"] = stage["model"]
            stage["provider_config"] = provider
        stages.append(stage)
    flow["stages"] = stages
    return flow


def served_models(base_url: str, timeout: float = 2.0) -> set[str] | None:
    """Model names a local endpoint is serving, or None if it is unreachable.

    Accepts both the Ollama-native and OpenAI-compatible listings so this
    works against any endpoint a provider's base_url may point at.
    """
    for path, key, field in (
        ("/api/tags", "models", "name"),
        ("/v1/models", "data", "id"),
    ):
        url = f"{base_url.rstrip('/')}{path}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                payload = json.load(response)
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            continue
        entries = payload.get(key)
        if isinstance(entries, list):
            return {
                str(entry[field])
                for entry in entries
                if isinstance(entry, Mapping) and entry.get(field)
            }
    return None


def doctor(
    config: Mapping[str, Any],
    environ: Mapping[str, str] | None = None,
    catalog: Callable[[str], set[str] | None] | None = None,
) -> list[str]:
    env = os.environ if environ is None else environ
    lookup = served_models if catalog is None else catalog
    findings: list[str] = []
    commands = {"claude-code": "claude", "codex": "codex"}
    seen: dict[str, set[str] | None] = {}
    for name in config["providers"]:
        provider = resolved_provider(config, name, env)
        command = commands[provider["runner"]]
        model = provider.get("model")
        base_url = provider.get("base_url")
        if shutil.which(command) is None:
            findings.append(f"ERROR provider {name}: command not found: {command}")
        elif not model and provider["runner"] == "claude-code":
            findings.append(f"ERROR provider {name}: no model configured")
        elif base_url and model:
            # A configured model name proves nothing: it can be deleted from
            # the host at any time, and without this the flow only finds out
            # mid-run, several stages deep.
            if base_url not in seen:
                seen[base_url] = lookup(str(base_url))
            available = seen[base_url]
            if available is None:
                findings.append(
                    f"WARN provider {name}: cannot reach {base_url} to confirm {model} is served"
                )
            elif str(model) not in available:
                findings.append(
                    f"ERROR provider {name}: model {model} is not served by {base_url}"
                )
            else:
                findings.append(f"OK provider {name}: {provider['runner']} serving {model}")
        else:
            findings.append(f"OK provider {name}: {provider['runner']}")
    for key, env_name in config.get("instance", {}).items():
        if key.endswith("_env") and env_name and not env.get(env_name):
            direct_key = key[:-4]
            if not config.get("instance", {}).get(direct_key):
                findings.append(f"WARN optional instance setting is unset: {env_name}")
    return findings


def flow_json(flow: Mapping[str, Any]) -> str:
    redacted = json.loads(json.dumps(flow))
    for stage in redacted.get("stages", []):
        provider = stage.get("provider_config", {})
        if provider.get("auth_token"):
            provider["auth_token"] = "[redacted]"
    return json.dumps(redacted, indent=2, sort_keys=True)

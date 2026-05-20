import os
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ENV_PATH_VAR = "SOROKA_ENV_PATH"

SECRET_ENV_FIELDS = {
    "jina_api_key": "SOROKA_JINA_API_KEY",
    "deepgram_api_key": "SOROKA_DEEPGRAM_API_KEY",
    "github_token": "SOROKA_GITHUB_TOKEN",
}
CONFIG_ENV_FIELDS = {
    "github_mirror_repo": "SOROKA_GITHUB_REPO",
}
ENV_BACKED_FIELDS = {**SECRET_ENV_FIELDS, **CONFIG_ENV_FIELDS}

SECRET_ENV_NAMES = tuple(SECRET_ENV_FIELDS.values()) + (
    "SOROKA_OPENAI_API_KEY",
    "SOROKA_GEMINI_API_KEY",
)
CONFIG_ENV_NAMES = tuple(CONFIG_ENV_FIELDS.values()) + (
    "SOROKA_LLM_MODEL",
    "SOROKA_LLM_PROVIDER",
)

_ENV_ASSIGN_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def env_file_path() -> Path:
    return Path(os.environ.get(ENV_PATH_VAR, ".env"))


def load_env_file(*, override: bool = True) -> None:
    path = env_file_path()
    if path.exists():
        load_dotenv(dotenv_path=path, override=override)


def is_secret_field(field: str) -> bool:
    return field in SECRET_ENV_FIELDS


def is_env_backed_field(field: str) -> bool:
    return field in ENV_BACKED_FIELDS


def get_secret_field(field: str) -> Optional[str]:
    if field not in SECRET_ENV_FIELDS:
        raise ValueError(f"unknown secret field: {field}")
    return get_env_field(field)


def get_env_field(field: str) -> Optional[str]:
    env_name = _env_name(field)
    load_env_file(override=True)
    value = os.environ.get(env_name, "").strip()
    return value or None


def set_secret_field(field: str, value) -> None:
    if field not in SECRET_ENV_FIELDS:
        raise ValueError(f"unknown secret field: {field}")
    set_env_field(field, value)


def set_env_field(field: str, value) -> None:
    env_name = _env_name(field)
    clean = _clean_value(value)
    _update_env_file({env_name: clean})
    if clean is None:
        os.environ.pop(env_name, None)
    else:
        os.environ[env_name] = clean


def _env_name(field: str) -> str:
    try:
        return ENV_BACKED_FIELDS[field]
    except KeyError:
        raise ValueError(f"unknown env-backed field: {field}") from None


def _clean_value(value) -> Optional[str]:
    if value is None:
        return None
    clean = str(value).strip()
    if not clean:
        return None
    if "\n" in clean or "\r" in clean:
        raise ValueError("secret values must be single-line")
    return clean


def _update_env_file(updates: dict[str, Optional[str]]) -> None:
    path = env_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    out: list[str] = []

    for line in lines:
        match = _ENV_ASSIGN_RE.match(line)
        key = match.group(1) if match else None
        if key in updates:
            seen.add(key)
            value = updates[key]
            if value is not None:
                out.append(f"{key}={value}")
            continue
        out.append(line)

    for key, value in updates.items():
        if key not in seen and value is not None:
            out.append(f"{key}={value}")

    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")

import re
import sqlite3
from urllib.parse import urlparse

from src.adapters.github_mirror import GitHubMirror, GitHubMirrorError
from src.core.owners import get_owner, update_owner_field, advance_setup_step

REPO_PATTERN = re.compile(r"^[\w.-]+/[\w.-]+$")
KEEP_MARKERS = {".", "keep", "оставить", "продолжить"}

REPO_INSTRUCTION = (
    "Сначала создай **приватный** репозиторий на github.com/new "
    "(имя любое, например `soroka-data`).\n\n"
    "Когда создашь — пришли его сюда в формате `username/repo` "
    "или ссылкой на GitHub."
)

TOKEN_INSTRUCTION = (
    "Fine-grained Personal Access Token.\n"
    "1) Открой github.com/settings/personal-access-tokens/new\n"
    "2) Repository access: **Only selected repositories** → выбери это репо\n"
    "3) Repository permissions: **Contents** → **Read and write**\n"
    "   Metadata Read-only GitHub добавит сам.\n"
    "4) Сгенерируй и пришли токен сюда (`github_pat_...`).\n\n"
    "Classic `repo`-токен тоже сработает, но он даёт лишний доступ ко всем "
    "приватным репозиториям — лучше fine-grained."
)

REPO_REJECT = (
    "Не похоже на имя репозитория. Формат: `username/soroka-data` "
    "или ссылка на GitHub.\n"
    "Если репо ещё не создан — заведи приватный на github.com/new"
)

TOKEN_REJECT = (
    "Не похоже на GitHub-токен. Должен начинаться с `ghp_` или `github_pat_`.\n"
    "Сгенерируй fine-grained token на github.com/settings/personal-access-tokens/new "
    "и пришли его сюда."
)


def is_token_like(text: str) -> bool:
    return text.startswith("ghp_") or text.startswith("github_pat_")


def _mask(v: str | None) -> str:
    if not v:
        return ""
    return f"…{v[-4:]}"


def _wants_keep(text: str) -> bool:
    clean = text.strip().lower()
    return clean == "" or clean in KEEP_MARKERS


def prompt_for_github_step(owner) -> str:
    if owner.github_mirror_repo and owner.github_token:
        return (
            "Шаг 3/4 — резервное копирование на GitHub.\n"
            f"В `.env` уже есть репозиторий `{owner.github_mirror_repo}` "
            f"и токен `{_mask(owner.github_token)}`.\n"
            "Отправьте новый токен, чтобы заменить его, или `.` чтобы оставить."
        )
    if owner.github_mirror_repo:
        return (
            "Шаг 3/4 — резервное копирование на GitHub.\n"
            f"В `.env` уже есть репозиторий `{owner.github_mirror_repo}`.\n\n"
            + TOKEN_INSTRUCTION
        )
    return REPO_INSTRUCTION


def normalize_repo_ref(text: str) -> str | None:
    """Accept owner/repo, GitHub HTTPS URLs, and SSH clone URLs."""
    raw = text.strip().strip("<>")
    if raw.startswith("git@github.com:"):
        raw = raw.removeprefix("git@github.com:")
    elif raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        if parsed.netloc.lower() != "github.com":
            return None
        raw = parsed.path.lstrip("/")
    raw = raw.rstrip("/").removesuffix(".git")
    parts = [p for p in raw.split("/") if p]
    if len(parts) != 2:
        return None
    repo = "/".join(parts)
    return repo if REPO_PATTERN.match(repo) else None


async def handle_github_step(conn: sqlite3.Connection, owner_id: int, text: str) -> str:
    owner = get_owner(conn, owner_id)
    text = text.strip()

    if not owner.github_mirror_repo:
        if _wants_keep(text):
            return REPO_INSTRUCTION
        repo = normalize_repo_ref(text)
        if repo is None:
            return REPO_REJECT
        update_owner_field(conn, owner_id, "github_mirror_repo", repo)
        return f"✓ Репо `{repo}` записал.\n\nШаг 3b/4 — " + TOKEN_INSTRUCTION

    if _wants_keep(text):
        if not owner.github_token:
            return TOKEN_INSTRUCTION
        text = owner.github_token

    if not is_token_like(text):
        return TOKEN_REJECT

    mirror = GitHubMirror(token=text, repo=owner.github_mirror_repo)
    try:
        await mirror.validate()
    except GitHubMirrorError as e:
        return (
            f"GitHub отверг настройки: {e}.\n"
            "Проверь, что токен выбран именно для этого репо и имеет "
            "Contents: Read and write, или /skip."
        )

    update_owner_field(conn, owner_id, "github_token", text)
    advance_setup_step(conn, owner_id, "channel")
    from src.bot.handlers.setup import PROMPTS
    return "✓ GitHub-зеркало подключено.\n\n" + PROMPTS["channel"]


async def handle_skip_github(conn: sqlite3.Connection, owner_id: int) -> str:
    update_owner_field(conn, owner_id, "github_token", None)
    update_owner_field(conn, owner_id, "github_mirror_repo", None)
    advance_setup_step(conn, owner_id, "channel")
    from src.bot.handlers.setup import PROMPTS
    return ("⚠ Без зеркала /export не сможет отдавать большие архивы.\n"
            "Подключить позже — команда /setgithub.\n\n"
            + PROMPTS["channel"])

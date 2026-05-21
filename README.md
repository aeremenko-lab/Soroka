<h1 align="center">Soroka</h1>

<p align="center">
  <img src="assets/logo.png" alt="Soroka logo" width="200">
</p>

<p align="center">
  Telegram-бот, который превращает «Избранное» в персональную базу знаний.<br>
  Форвардите в приватный канал — ищете у бота в DM. Возвращает оригиналы, не пересказы.
</p>

<p align="center">
  <a href="https://github.com/AndyShaman/Soroka/blob/main/LICENSE"><img src="https://img.shields.io/github/license/AndyShaman/Soroka?style=flat-square&color=green" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.12+-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/MCP-compatible-8A2BE2?style=flat-square" alt="MCP">
  <img src="https://img.shields.io/badge/SQLite-FTS5%20%2B%20vec-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite">
  <a href="https://github.com/AndyShaman/Soroka/stargazers"><img src="https://img.shields.io/github/stars/AndyShaman/Soroka?style=flat-square&color=yellow" alt="Stars"></a>
</p>

<p align="center">
  <a href="https://t.me/AI_Handler"><img src="https://img.shields.io/badge/Telegram-канал автора-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram"></a>
  &nbsp;
  <a href="https://www.youtube.com/channel/UCLkP6wuW_P2hnagdaZMBtCw"><img src="https://img.shields.io/badge/YouTube-канал автора-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="YouTube"></a>
</p>

---

## Как установить

- 👤 **Самостоятельно** — прочитайте этот README по порядку: подготовка VPS → установка → настройка в Telegram.
- 🤖 **Через AI-агента** (Claude Code, Cursor и т.п.) — откройте [AGENTS.md](AGENTS.md). Там протокол под автоматизацию: какие три значения спросить у пользователя, как запустить установщик через SSH, как проверить успех.

## Что потребуется

1. **VPS** — Ubuntu 22.04+, 1 GB RAM. Подойдёт любой способ входа: пароль, ключ,
   web-консоль панели хостера — без разницы.
2. **Telegram-бот** — создайте его у [@BotFather](https://t.me/BotFather) и сохраните токен.
3. **Ваш Telegram-ID** — узнайте его у [@userinfobot](https://t.me/userinfobot).

После установки бот запросит ключи:
- [Jina](https://jina.ai/embeddings) — эмбеддинги (free tier 10M токенов, non-commercial)
- [Deepgram](https://deepgram.com) — голос → текст ($200 free)
- [GitHub Fine-grained Personal Access Token](https://github.com/settings/personal-access-tokens/new) — для бэкапов

Секреты хранятся в `.env` рядом с репозиторием, а не в SQLite-базе. Бот
записывает туда ключи из мастера настройки и команд `/set*`.

LLM для кратких русских описаний ссылок и реранка поиска настраивается
только через `.env`:

```bash
# выберите один вариант
SOROKA_LLM_MODEL=openai:gpt-4.1-mini
# SOROKA_LLM_MODEL=gemini:gemini-2.5-flash

SOROKA_OPENAI_API_KEY=
SOROKA_GEMINI_API_KEY=
```

Если LLM не задан, бот продолжит работать: сохранение, embeddings и гибридный
поиск останутся включены, но без LLM-сводок и реранка.

GitHub-зеркало тоже хранится в `.env`:

```bash
SOROKA_GITHUB_REPO=owner/soroka-data
SOROKA_GITHUB_TOKEN=github_pat_...
```

Для токена выберите **Only selected repositories** → нужный приватный репозиторий,
а в **Repository permissions** поставьте **Contents: Read and write**. Classic PAT с `repo` тоже работает, но даёт слишком широкий доступ ко всем приватным
репозиториям аккаунта.


## Установка

Зайдите на VPS любым удобным способом и выполните прямо там:

```bash
git clone https://github.com/AndyShaman/Soroka.git soroka
cd soroka
./bin/install
```

Скрипт спросит **две вещи**: токен бота и ваш Telegram-ID, если они не заданы в .env. Поставит Docker (если ещё нет), запустит контейнер `soroka-bot` и пропишет `soroka-mcp` в `/usr/local/bin/`. 

После завершения откройте Telegram, найдите своего бота и отправьте `/start` —
мастер проведёт через 4 шага настройки в чате.

## Команды бота

- `/start` — мастер настройки (запускается один раз; повтор возобновляет с прерванного шага)
- `/help` — справка
- `/status` — текущие настройки и статистика
- `/setjina`, `/setdeepgram` — заменить отдельный ключ
- `/setgithub` — заменить GitHub-токен и репо-зеркало
- `/setvps` — задать IP/юзера VPS (используется в `/mcp`)
- `/setinbox` — сменить канал-инбокс
- `/export` — выгрузить базу архивом
- `/mcp` — конфиг для Claude Desktop (MCP-сервер по SSH stdio)
- `/cancel` — прервать мастер/диалог

## Архитектура

```
Канал «Избранное 2» ──→ Бот на VPS ──→ SQLite (FTS5 + sqlite-vec)
DM с ботом         ──↗               ↑
                                      │
Claude Desktop через MCP-stdio ──SSH──┘
```

## Обновление

Зайдите на VPS, перейдите в папку с репозиторием и выполните:

```bash
cd ~/soroka     # или туда, куда был сделан git clone
./bin/update
```

Подтянет последний код через `git pull`, пересоберёт контейнер, обновит
`soroka-mcp`. Никаких аргументов.

## Резервное копирование

Авто-бэкап (если GitHub-зеркало подключено): раз в сутки бот собирает
lite-архив (только SQLite-база, без вложений) и заливает в один и тот же
тег `soroka-daily-latest` в приватном репо — старый релиз
перезаписывается, размер репо не растёт.

Ручной `/export` собирает базу + вложения в zip:

- **≤ 50 MB** — приходит прямо в Telegram.
- **> 50 MB** — без GitHub-зеркала: бот пришлёт «облегчённый» архив (только база) и
  попросит включить зеркало через `/setgithub`. С зеркалом: заливает полный архив
  GitHub Release в ваш приватный репозиторий и пришлёт ссылку плюс облегчённый локально.

## Для AI-агентов

См. `AGENTS.md` — там точный протокол развёртывания через флаги.

## Лицензия

MIT.

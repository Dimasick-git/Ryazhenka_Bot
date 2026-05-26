# Ryazhenka Bot

**EN:** Telegram bot (aiogram 3) for Nintendo Switch CFW community — guide search, YouTube/GitHub auto-sync, BM25-style ranking, lightweight fuzzy matching. Single-file `guides.json` knowledge base. Deploys to Railway as a `web` process with `/health` endpoint. License: see `LICENSE`.

---

## Что это

Telegram-бот для комьюнити Ryazhenka CFW. Хранит ~22KB JSON-базу гайдов (`guides.json`), позволяет искать их через команды и inline mode. Автоматически подтягивает новые видео с указанных YouTube-каналов и релизы из GitHub-репо.

## Команды

**Пользовательские:**
- `/start` — приветствие + клавиатура категорий
- `/all` — список всех категорий
- `/guide <тема>` (`/гайд`) — fuzzy-поиск гайда
- `/search <тема>` — расширенный поиск с вариантами
- `/aiguide <тема>` — локальный BM25-ранкинг (без внешних API)
- `/random` — случайный гайд
- `/new` — последние добавленные
- `/top` — топ по рейтингу
- `/recommend` — публичные репо `Dimasick-git/*`
- `/fav` — избранные (per-user)
- `/feedback` — обратная связь
- `/stats`, `/help`

**Админские** (если `tg_id` в `ADMIN_IDS`):
- `/status`, `/sync`, `/restart_polling`
- `/add_guide`, `/remove_guide`, `/edit_guide`, `/list_guides`
- `/yt_add`, `/yt_remove`, `/yt_list`, `/yt_cache`, `/yt_set_limit`, `/yt_prune_on|off`
- `/purge_autoguides`, `/cleanup_duplicates`, `/toggle_autoresolve`

Inline mode: `@your_bot <query>` — inline-результаты с гайдами.

## Стек

- **aiogram 3.22** — Telegram API + polling.
- **aiohttp** — встроенный HTTP-сервер для health check (`/health`) и `/yt_latest`.
- **requests** — GitHub/YouTube RSS.
- **fuzzywuzzy** (опц. `python-Levenshtein`) — fuzzy fallback. Если нет — встроенный pure-Python алгоритм.
- **BM25** локальный (без sentence-transformers) — `bot/nlp.py`.
- Python 3.11.

Структура:

```
main.py                  entry point (polling + health server)
bot/
  config.py              env vars
  storage.py             guides.json loader
  nlp.py                 BM25 index
  helpers.py
  handlers/              user.py, admin.py, callbacks.py, inline.py
  services/              github.py, youtube.py, sync.py
guides.json              knowledge base
docs/index.html          static (для GitHub Pages, опционально)
scripts/                 утилиты: run_sync, generate_synonyms, ...
tests/                   pytest tests
```

## Установка локально

```sh
python -m venv .venv
source .venv/bin/activate    # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

cp .env.example .env
# заполнить BOT_TOKEN (из @BotFather), ADMIN_IDS, опц. YT_CHANNELS / GITHUB_REPO

python main.py
```

## Деплой на Railway

1. Залить репо на GitHub (уже сделано).
2. Railway dashboard → New Project → Deploy from GitHub → выбрать `Dimasick-git/Ryazhenka_Bot`.
3. **Variables** (Settings → Variables):
   - `BOT_TOKEN` — токен от @BotFather
   - `ADMIN_IDS` — твой Telegram ID (узнать через @userinfobot)
   - `YT_CHANNELS` — опц., через запятую (handle / UC id / URL)
   - `GITHUB_REPO` — опц., `owner/repo`
   - `GITHUB_TOKEN` — опц., для повышения rate limit
   - `SYNC_INTERVAL_SECONDS=3600`
   - `LOG_LEVEL=INFO`
4. Railway сам подхватит `runtime.txt`, `requirements.txt`, `Procfile`, `railway.json`.
5. Health check: `/health` → 200 OK. Если не отвечает 30s — Railway рестартит (политика в `railway.json`).

**Логи** Railway покажут: `Loaded N categories, M guides total` → `Starting polling...` — значит ок.

## Env vars

См. `.env.example`. Минимум — `BOT_TOKEN`. Всё остальное опционально.

## Тесты

```sh
pytest -q
```

## Лицензия

См. `LICENSE`. Автор: Dimasick-git. Деплоер - Dimanchik-git.

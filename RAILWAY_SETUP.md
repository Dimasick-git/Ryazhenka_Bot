Quick Railway deployment

1) Push this repository to GitHub
   - Create a new repository on GitHub and push all files there.

2) Create a new project on Railway
   - In Railway dashboard, choose "Deploy from GitHub" and select the repo.

3) Configure Environment Variables (Project Settings -> Variables)
   - Add these keys and values (copy from `.env.example`):
     BOT_TOKEN = <your_new_bot_token>
     YT_CHANNELS = chipovchik
     GITHUB_REPO = Dimasick-git/Ryzhenka
     ADMIN_IDS = 2072467087
     SYNC_INTERVAL_SECONDS = 3600
     LOG_LEVEL = INFO

4) Procfile
   - `Procfile` already contains: `worker: python main.py` so Railway will run the bot as a worker.

5) Deploy
   - Click "Deploy". Railway will install packages from `requirements.txt` and run the worker.

6) Logs & Verification
   - Open the project's logs. You should see lines like:
     "🤖 Бот запущен и готов к работе!"
     "📚 Загружено ... категорий"
   - Test bot in Telegram: try `/all`, `/guide atmosphere`, `/sync` (if your Telegram id is in `ADMIN_IDS`).

Notes
- Revoke any previously leaked bot token in BotFather and use a fresh token.
- If DuckDuckGo-based resolver does heavy requests, Railway may throttle outgoing requests - the bot already has a background resolver with polite behavior.
- To troubleshoot: check Railway logs and set `LOG_LEVEL=DEBUG` for more details.

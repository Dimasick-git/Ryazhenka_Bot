Deploying Ryazhenka_Bot to Railway (step-by-step)

This document contains minimal, copy-paste friendly steps to run the bot on Railway.

1) Push repository to GitHub
   - Create a new GitHub repo and push the current project files.

2) Create a Railway project and connect repository
   - In Railway, click New Project → Deploy from GitHub → select the repo.

3) Configure Environment Variables (Project Settings -> Variables)
   - Add these variables (don't commit secrets to git):
     BOT_TOKEN  — Your bot token from BotFather (format: 123456:ABC...)
     YT_CHANNELS — comma-separated channel identifiers (default: UCjtFvdgneo1vhSAggJUJeMw)
     GITHUB_REPO — example: Dimasick-git/Ryzhenka
     ADMIN_IDS  — comma-separated Telegram user ids that can run admin commands
     SYNC_INTERVAL_SECONDS — background sync interval in seconds (default 3600)
     LOG_LEVEL — INFO (or DEBUG)
     # Optional: GITHUB_TOKEN — personal access token to raise API rate limits (recommended)

4) Procfile
   - The repo contains `Procfile` with: `worker: python main.py`.
     Railway will run the worker process when the project deploys.

5) Runtime and dependencies
   - `runtime.txt` requests Python 3.11.4. Railway will try to honour this.
   - `requirements.txt` lists dependencies; Railway will install them automatically.

6) Deploy and verify
   - Click Deploy. Watch logs for the bot startup lines:
     "🤖 Бот запущен и готов к работе!"
     "📚 Загружено ... категорий"
   - Test the bot in Telegram and use `/all`, `/guide` etc.

7) Troubleshooting
   - If the bot fails to start, check Railway logs for stack traces.
   - If GitHub API calls fail with rate limit errors, create a GitHub personal access token
     and set `GITHUB_TOKEN` in Railway environment variables; the code will use it automatically
     if present.

Security note
   - Do not push real `BOT_TOKEN` into GitHub. Use Railway variables.

If you want, I can add a tiny health-check HTTP server so Railway can treat the process as a web service
and provide the live endpoint for auto-restarts; tell me and I will add it (lightweight Flask or aiohttp route).
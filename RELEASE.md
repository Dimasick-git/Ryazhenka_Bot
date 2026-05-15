Release checklist

1. Make sure you do NOT commit your .env with BOT_TOKEN. Use `.env.example` as a template.
2. To set BOT_TOKEN locally (PowerShell):

   .\scripts\set_bot_token.ps1 -Token "YOUR_BOT_TOKEN_HERE"

   Or run the script without args and paste the token interactively.

3. Create a venv and install deps:

   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt

4. Run checks:

   python main.py

5. Test bot commands in Telegram (using your BOT_TOKEN):
   - /start
   - /all
   - /guide battery
   - /aiguide battery desync fix
   - /help
   - /status (admin)
   - /restart_polling (admin)
   - /sync (admin)

6. After verification, publish release on GitHub but ensure `.env` is not tracked.

Notes:
- /aiguide uses a lightweight local algorithm (no heavy ML). If you want the sentence-transformers model later, I'll add an optional branch.

"""
Simple script to verify BOT_TOKEN by calling Telegram getMe using only stdlib.
Usage: python check_bot_token.py
"""
import os
import json
import urllib.request

# load simple .env same way as main
if os.path.exists('.env'):
    with open('.env', 'r', encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith('#') or '=' not in ln:
                continue
            k, v = ln.split('=', 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v

TOKEN = os.environ.get('BOT_TOKEN')
if not TOKEN:
    print('BOT_TOKEN not set')
    raise SystemExit(1)

url = f'https://api.telegram.org/bot{TOKEN}/getMe'
try:
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.load(resp)
    print('OK:', data)
except Exception as e:
    print('ERROR:', e)
    raise

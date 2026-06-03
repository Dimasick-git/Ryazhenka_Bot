import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.services.sync import sync_sources

if __name__ == '__main__':
    print('Starting sync...')
    s = asyncio.run(sync_sources())
    print('Sync result:', s)

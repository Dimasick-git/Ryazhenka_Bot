import asyncio, sys
sys.path.append('.')
import main

if __name__ == '__main__':
    print('Starting sync...')
    s = asyncio.run(main.sync_sources())
    print('Sync result:', s)

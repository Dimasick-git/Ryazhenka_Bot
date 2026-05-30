import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot import storage
from bot.services.youtube import fetch_youtube_videos, resolve_channel_id


async def run_check():
    print('YT_CHANNELS (runtime):', storage.YT_CHANNELS)
    print('YT_CACHE sample:', list(storage.YT_CACHE.items())[:5])
    for ch in storage.YT_CHANNELS:
        try:
            print('\n--- Checking channel identifier:', ch)
            resolved = await resolve_channel_id(ch)
            print('resolved ->', resolved)
            ch_title, entries = await fetch_youtube_videos(resolved)
            print('channel_title ->', ch_title)
            print('entries fetched ->', len(entries))
            for t, u in entries[:20]:
                print('-', t, u)
        except Exception as e:
            print('Error for', ch, e)

    youtube_cats = [c for c in storage.GUIDES.keys() if c.startswith('YouTube -')]
    print('\nExisting YouTube categories in guides.json:', youtube_cats)
    for c in youtube_cats:
        print('Category:', c, 'items:', len(storage.GUIDES.get(c, {})))


if __name__ == '__main__':
    asyncio.run(run_check())

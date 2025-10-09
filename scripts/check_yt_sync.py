import asyncio
import sys
import json
sys.path.append('.')
import main

async def run_check():
    print('YT_CHANNELS (runtime):', main.YT_CHANNELS)
    print('YT_CACHE sample:', list(main.YT_CACHE.items())[:5])
    for ch in main.YT_CHANNELS:
        try:
            print('\n--- Checking channel identifier:', ch)
            resolved = await main.resolve_channel_id(ch)
            print('resolved ->', resolved)
            ch_title, entries = await main.fetch_youtube_videos(resolved)
            print('channel_title ->', ch_title)
            print('entries fetched ->', len(entries))
            for t,u in entries[:20]:
                print('-', t, u)
        except Exception as e:
            print('Error for', ch, e)

    # show existing YouTube categories in guides.json
    youtube_cats = [c for c in main.GUIDES.keys() if c.startswith('YouTube -') or c == 'YouTube - Видео']
    print('\nExisting YouTube categories in guides.json:', youtube_cats)
    for c in youtube_cats:
        print('Category:', c, 'items:', len(main.GUIDES.get(c, {})))

if __name__ == '__main__':
    asyncio.run(run_check())

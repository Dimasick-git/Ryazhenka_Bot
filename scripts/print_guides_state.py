import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.storage import GUIDES
print('GUIDES keys:', list(GUIDES.keys()))
for k in list(GUIDES.keys()):
    if k.startswith('YouTube -') or k == 'YouTube - Видео':
        entries = GUIDES.get(k, {})
        print('\nCategory:', k, 'count:', len(entries))
        for i, (t,u) in enumerate(entries.items()):
            print(i+1, '-', t, '->', u)
            if i>=30:
                break

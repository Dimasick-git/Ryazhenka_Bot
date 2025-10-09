import sys
sys.path.append('.')
import main
print('GUIDES keys:', list(main.GUIDES.keys()))
for k in list(main.GUIDES.keys()):
    if k.startswith('YouTube -') or k == 'YouTube - Видео':
        entries = main.GUIDES.get(k, {})
        print('\nCategory:', k, 'count:', len(entries))
        for i, (t,u) in enumerate(entries.items()):
            print(i+1, '-', t, '->', u)
            if i>=30:
                break

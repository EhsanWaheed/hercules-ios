import sys; sys.path.insert(0, sys.argv[0].rsplit('/', 1)[0]); exec(open(sys.argv[0].rsplit('/', 1)[0] + '/ovstat.py').read())
word = lambda a: c('read_ram', addr=a, len=4)['hex']
engine1 = lambda: word(0x8003FD7C) == '0c29848f'
title = lambda: word(0x8005418C) == 'cc3a848f'
dec = lambda: sum(x['count'] for x in c('mod_counters')['counters'] if x['name'].endswith('.decode'))
t = time.time()
# 1) reach the title menu: TITLE resident and decoding (muses animate)
while time.time() - t < 120:
    d0 = dec(); time.sleep(0.8)
    if title() and dec() > d0: break
    p('start', 1.2)
# 2) select "Spiel starten" until the game leaves TITLE for ENGINE1
while time.time() - t < 150 and title():
    p('cross', 1.5)
# 3) wait for gameplay: ENGINE1 resident and sprites decoding
while time.time() - t < 240:
    d0 = dec(); time.sleep(1)
    if engine1() and dec() - d0 > 20: break
time.sleep(3)
print('in game' if engine1() else 'not in game', int(time.time() - t), 's')

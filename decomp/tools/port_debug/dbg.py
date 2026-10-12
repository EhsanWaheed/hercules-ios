import json, socket, sys, time
class C:
    def __init__(s, port=4370):
        s.s = socket.create_connection(('127.0.0.1', port)); s.f = s.s.makefile('r'); s.i = 0
    def __call__(s, cmd, **kw):
        s.s.close(); s.__init__()  # server may drop the connection after a reply
        s.i += 1; kw.update(id=s.i, cmd=cmd)
        s.s.sendall((json.dumps(kw) + '\n').encode())
        while True:
            line = s.f.readline()
            if not line: raise EOFError('connection closed')
            line = line.strip()
            if not line: continue
            r = json.loads(line)
            if r.get('id') == s.i: return r
BTN = dict(select=0, start=3, up=4, right=5, down=6, left=7, l2=8, r2=9, l1=10, r1=11, tri=12, circle=13, cross=14, square=15)
def mask(*names):
    m = 0xFFFF
    for n in names: m &= ~(1 << BTN[n])
    return m
if __name__ == '__main__':
    c = C()
    for a in sys.argv[1:]:
        if a.startswith('wait'): time.sleep(float(a[4:]))
        elif a.startswith('shot'): print(c('screenshot', path=f"{sys.argv[0].rsplit('/',1)[0]}/{a}.png"))
        elif a.startswith('{'): print(c(**json.loads(a)))
        else: print(c('press', buttons=mask(*a.split('+')), frames=6)); time.sleep(0.3)

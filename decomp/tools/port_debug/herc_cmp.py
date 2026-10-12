import sys, time; d = sys.argv[0].rsplit('/', 1)[0]; sys.path.insert(0, d); from dbg import C
from PIL import Image
tag = sys.argv[1]
c = C()
c('screenshot_hires', path=f'{d}/{tag}_on.png'); c('hd_textures', replacements=0); time.sleep(0.1)
c('screenshot_hires', path=f'{d}/{tag}_off.png'); c('hd_textures', replacements=1)
box = (500, 700, 800, 1000)   # Hercules at the level start (native ~100..160, 140..200)
a = Image.open(f'{d}/{tag}_off.png').crop(box); b = Image.open(f'{d}/{tag}_on.png').crop(box)
W = Image.new('RGB', (610, 300), 'white'); W.paste(a, (0, 0)); W.paste(b, (310, 0)); W.save(f'{d}/{tag}_herc.png')

import sys, time
sys.path.insert(0, sys.argv[0].rsplit('/', 1)[0])
from dbg import C, mask
K = ('static_hits', 'static_address_misses', 'static_crc_misses', 'static_variant_misses', 'dispatch_interp_fallback', 'segment_alias_interp')
c = C()
def snap(): r = c('overlay_loader_status'); return {k: r[k] for k in K}
def delta(label, a, b):
    print(label, {k: b[k] - a[k] for k in K})
def p(b, w=0.6): c('press', buttons=mask(b), frames=8); time.sleep(w)

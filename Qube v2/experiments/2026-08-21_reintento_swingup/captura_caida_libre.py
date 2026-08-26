import json, struct, time, urllib.request, sys
U="http://192.168.4.1"; MAGIC=0x51414451
def get(p,to=4): return urllib.request.urlopen(U+p,timeout=to).read()
def js(p): return json.loads(get(p))
def drain(acc):
    try:
        raw=get("/daq/read")
        if len(raw)<16: return 0
        magic,pv,sb,n,dr,tn=struct.unpack_from("<IBBHII",raw,0)
        if magic!=MAGIC: return 0
        for i in range(n):
            acc.append(struct.unpack_from("<IffhBB",raw,16+16*i)[:5])
        return n
    except Exception: return 0

CORTE=sys.argv[2] if len(sys.argv)>2 else "/cmd?m=0"
acc=[]
js("/daq?stop=1"); js("/daq?decim=1&start=1")
js("/cmd?m=5")
t0=time.time(); cortado=None
while time.time()-t0 < 55:
    drain(acc)
    try: d=js("/state")
    except Exception: continue
    if d.get('swing_zero_phase',0)!=0:      # esperar el re-cero de P22
        continue
    a=abs(d['pend_position_deg'])
    if cortado is None and 75.0 < a < 170.0 and d['mode']==5 and d['swing_zero_ok']==1:
        js(CORTE); cortado=time.time()
        print(f"corte a t={cortado-t0:.2f}s con |alpha|={a:.1f}  brazo={d['position_deg']:.1f}")
    if cortado and time.time()-cortado > 11.0: break
    if d['mode']==0 and cortado is None:
        print("el modo 5 se cayo solo antes de llegar a 110"); break
    time.sleep(0.01)
js("/cmd?m=0"); js("/daq?stop=1")
for _ in range(8):
    if drain(acc)==0: break
acc.sort()
tref=acc[0][0]
with open(sys.argv[1],"w") as f:
    f.write("t_s,th_deg,al_deg,pwm,mode\n")
    for t_us,th,al,pwm,md in acc:
        f.write(f"{(t_us-tref)/1e6:.4f},{th:.3f},{al:.3f},{pwm},{md}\n")
print(f"muestras={len(acc)} -> {sys.argv[1]}")

import json, struct, time, urllib.request, sys
U = "http://192.168.4.1"
def get(p, timeout=4):
    return urllib.request.urlopen(U+p, timeout=timeout).read()
def js(p): return json.loads(get(p))

MAGIC = 0x51414451
samples = []
events  = []

js("/daq?stop=1")
js("/daq?decim=1&start=1")
js("/cmd?m=5")
t0 = time.time()
prev = None
while time.time() - t0 < 42:
    # drenar el DAQ
    try:
        raw = get("/daq/read")
        if len(raw) >= 16:
            magic, pv, sb, n, dropped, tnow = struct.unpack_from("<IBBHII", raw, 0)
            if magic == MAGIC:
                for i in range(n):
                    t_us, th, al, pwm, md, fl = struct.unpack_from("<IffhBB", raw, 16 + 16*i)
                    samples.append((t_us, th, al, pwm, md))
    except Exception as e:
        pass
    # estado (barato, para los campos del reintento)
    try:
        d = js("/state")
        key = (d['mode'], d['swing_recenter_phase'], d['swing_zero_phase'],
               d['swing_retry_count'], d['swing_fail_reason'])
        if key != prev:
            events.append((time.time()-t0, key, d['position_deg']))
            prev = key
        if d['mode'] == 0 and time.time()-t0 > 2:
            break
    except Exception:
        pass
js("/daq?stop=1")
# drenar lo que quede
for _ in range(6):
    try:
        raw = get("/daq/read")
        magic, pv, sb, n, dropped, tnow = struct.unpack_from("<IBBHII", raw, 0)
        if n == 0: break
        for i in range(n):
            t_us, th, al, pwm, md, fl = struct.unpack_from("<IffhBB", raw, 16 + 16*i)
            samples.append((t_us, th, al, pwm, md))
    except Exception:
        break

samples.sort()
print(f"muestras DAQ = {len(samples)}   eventos /state = {len(events)}")
if samples:
    tref = samples[0][0]
    with open(sys.argv[1], "w") as f:
        f.write("t_s,th_deg,al_deg,pwm,mode\n")
        for t_us, th, al, pwm, md in samples:
            f.write(f"{(t_us-tref)/1e6:.4f},{th:.3f},{al:.3f},{pwm},{md}\n")
    print("guardado en", sys.argv[1])
print()
for t, k, pos in events:
    print(f"  t={t:5.2f}s mode={k[0]} rec={k[1]} quieto={k[2]} reint={k[3]} falla={k[4]} brazo={pos:7.2f}")

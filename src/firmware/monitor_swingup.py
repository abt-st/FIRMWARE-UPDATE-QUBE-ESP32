"""Quick swing-up monitor for QUBE ESP32."""
import urllib.request
import json
import time
import sys

IP = "192.168.100.50"

def get_state():
    try:
        with urllib.request.urlopen(f"http://{IP}/state", timeout=2) as r:
            return json.loads(r.read())
    except Exception as e:
        return None

# Start swing-up
try:
    urllib.request.urlopen(f"http://{IP}/cmd?m=5", timeout=2)
except Exception:
    pass

print("mode  pwm   servo_deg  pend_deg  ina    V_bus")
print("-" * 50)

for i in range(40):
    time.sleep(0.25)
    d = get_state()
    if d:
        print(f"  {d['mode']}  {d['pwm']:>+5d}   {d['position_deg']:>8.1f}  {d['pend_position_deg']:>8.1f}  {str(d['ina_ok']):>5}  {d['v_bus']:.1f}")
    else:
        print("  -- no response --")
    sys.stdout.flush()

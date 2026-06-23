"""R6 hardware bring-up — staged, motor-safe sim2real diagnostics.

Run ONE stage at a time, in order. Motor stays OFF until you explicitly reach
the deploy stage. The point of stages 1-2 is to settle the open question from
r4_real: is `/rl_state` returning radians or degrees, and does the pendulum
encoder actually move?

KEY FINDING under test: firmware `handleRlState` emits th/al/thd/ald ALREADY in
radians (getPositionDeg()*DEG_TO_RAD). qube_real.py / train_real_v4 then call
np.radians() on them AGAIN — a double conversion that shrinks every angle ~57x.
Stage 2 prints BOTH interpretations so we can confirm by hand.

Usage (run each, read output, then go to the next)::

    uv run python experiments/2026-06-22_r6_real_aligned/hw_bringup.py --ip 192.168.100.50 --stage ping
    uv run python experiments/2026-06-22_r6_real_aligned/hw_bringup.py --ip 192.168.100.50 --stage sensors --seconds 20
    uv run python experiments/2026-06-22_r6_real_aligned/hw_bringup.py --ip 192.168.100.50 --stage estop
"""
from __future__ import annotations

import argparse
import contextlib
import math
import sys
import time

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

RAD2DEG = 180.0 / math.pi


def _get(ip: str, path: str, params: dict | None = None, timeout: float = 4.0):
    import requests
    r = requests.get(f"http://{ip}{path}", params=params, timeout=timeout)
    r.raise_for_status()
    return r


def _state_json(ip: str) -> dict:
    return _get(ip, "/rl_state").json()


def kill_motor(ip: str) -> None:
    """Best-effort e-stop: zero RL action, then mode 0 (idle)."""
    with contextlib.suppress(Exception):
        _get(ip, "/rl_cmd", {"a": "0"})
    with contextlib.suppress(Exception):
        _get(ip, "/cmd", {"m": "0"})


# ---------------------------------------------------------------------------
# Stage 1: ping — reachability + raw snapshot of BOTH endpoints
# ---------------------------------------------------------------------------
def stage_ping(ip: str) -> None:
    print(f"[ping] GET http://{ip}/state ...")
    try:
        s = _get(ip, "/state").json()
    except Exception as exc:
        print(f"  ERROR: ESP32 unreachable at {ip}: {exc}")
        print("  -> check power, WiFi, and the IP (router DHCP table).")
        return
    print(f"  mode={s.get('mode')}  theta_deg={s.get('position_deg')}  alpha_deg={s.get('pend_position_deg')}")
    print(f"[ping] GET http://{ip}/rl_state ...")
    rs = _state_json(ip)
    print(f"  raw rl_state = {rs}")
    print("  Firmware emits these in RADIANS. Interpretations:")
    for k in ("th", "al", "thd", "ald"):
        v = float(rs.get(k, 0.0))
        print(f"    {k:>3}: {v:+8.4f} rad = {v*RAD2DEG:+8.2f} deg   "
              f"(buggy double-convert would feed the policy {math.radians(v):+8.5f})")
    print("  Sanity: with the pendulum hanging at rest, |al| should be ~pi (3.14) "
          "if upright=0, or ~0 if hanging=0. Note which, we need it for deploy.")


# ---------------------------------------------------------------------------
# Stage 2: sensors — MOTOR OFF, stream while you move the pendulum BY HAND
# ---------------------------------------------------------------------------
def stage_sensors(ip: str, seconds: float, hz: float) -> None:
    print("[sensors] Setting mode 0 (motor idle). MOVE THE PENDULUM BY HAND.")
    print("[sensors] Watching th/al for ~%.0fs. Looking for: does al actually vary?" % seconds)
    kill_motor(ip)
    time.sleep(0.3)
    dt = 1.0 / hz
    t0 = time.time()
    al_min, al_max = math.inf, -math.inf
    th_min, th_max = math.inf, -math.inf
    n = 0
    try:
        while time.time() - t0 < seconds:
            rs = _state_json(ip)
            th = float(rs.get("th", 0.0))
            al = float(rs.get("al", 0.0))
            ald = float(rs.get("ald", 0.0))
            al_min, al_max = min(al_min, al), max(al_max, al)
            th_min, th_max = min(th_min, th), max(th_max, th)
            n += 1
            if n % max(1, int(hz // 5)) == 0:
                print(f"  t={time.time()-t0:4.1f}s  th={th:+6.3f}rad ({th*RAD2DEG:+6.1f}deg)  "
                      f"al={al:+6.3f}rad ({al*RAD2DEG:+6.1f}deg)  ald={ald:+6.2f}")
            time.sleep(dt)
    except KeyboardInterrupt:
        print("  (stopped)")
    finally:
        kill_motor(ip)
    al_span = (al_max - al_min) if al_max > -math.inf else 0.0
    th_span = (th_max - th_min) if th_max > -math.inf else 0.0
    print("\n[sensors] SUMMARY")
    print(f"  alpha range: [{al_min:+.3f}, {al_max:+.3f}] rad  -> span {al_span:.3f} rad ({al_span*RAD2DEG:.1f} deg)")
    print(f"  theta range: [{th_min:+.3f}, {th_max:+.3f}] rad  -> span {th_span:.3f} rad ({th_span*RAD2DEG:.1f} deg)")
    if al_span < 0.2:
        print("  VERDICT: pendulum alpha barely moved -> encoder NOT reading (wiring/PCNT/init). "
              "This is the r4_real blocker. Fix HW before any deploy.")
    elif al_span < 4.0:
        print("  VERDICT: alpha varies but span < ~2pi. Lift pendulum full circle to confirm "
              "it spans ~6.28 rad. Units look like RADIANS (correct).")
    else:
        print("  VERDICT: alpha spans a full turn in radians -> sensor OK, units = radians.")


# ---------------------------------------------------------------------------
# Stage 3: estop — verify the kill path works
# ---------------------------------------------------------------------------
def stage_estop(ip: str) -> None:
    print("[estop] Sending /rl_cmd?a=0 then /cmd?m=0 ...")
    kill_motor(ip)
    time.sleep(0.2)
    s = _get(ip, "/state").json()
    print(f"  mode now = {s.get('mode')} (expect 0). Motor should be idle/braked.")
    print("  Keep this command handy as the panic button during deploy.")


# ---------------------------------------------------------------------------
# Stage 4: deploy — run a trained policy on the real rig
#   --dry-run : policy computes actions from REAL obs but motor stays OFF (0 PWM).
#               Verifies the obs pipeline + sane actions before energizing.
#   live      : sends clipped actions in mode 6. Firmware clamps near limits;
#               Ctrl+C or the theta watchdog triggers e-stop.
# ---------------------------------------------------------------------------
def stage_deploy(ip: str, model_path: str, dry_run: bool, action_scale: float,
                 max_steps: int, episodes: int, reset_encoders: bool = False,
                 log_every: int = 10, theta_watchdog_deg: float = 105.0,
                 action_mult: float = 1.0) -> None:
    import signal

    import numpy as np
    from stable_baselines3 import SAC

    from qube_rl.envs.factory import make_real_env

    def _sigint(_s, _f):
        print("\n  Ctrl+C -> EMERGENCY STOP")
        kill_motor(ip)
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    if reset_encoders:
        print("[deploy] zeroing encoders at current rest pose (hold arm centered, pendulum hanging)")
        with contextlib.suppress(Exception):
            _get(ip, "/cmd", {"m": "0"})
            time.sleep(0.2)
            _get(ip, "/rl_cmd", {"r": "1"})
            time.sleep(0.4)
        rs = _state_json(ip)
        print(f"  after zero: th={rs.get('th'):+.3f}rad al={rs.get('al'):+.3f}rad (expect ~0,0)")

    mode = "DRY-RUN (motor OFF, 0 PWM)" if dry_run else f"LIVE (action_scale={action_scale})"
    print(f"[deploy] {mode}")
    print(f"[deploy] model = {model_path}")
    print(f"[deploy] {episodes} episode(s) x {max_steps} steps ({max_steps/50:.1f}s) @ 50Hz")
    if not dry_run:
        print("[deploy] !! MOTOR WILL MOVE. Ctrl+C = panic stop. Firmware clamps beyond +/-110deg.")

    model = SAC.load(model_path)
    env = make_real_env(esp32_ip=ip, reward="linear_alpha",
                        max_episode_steps=max_steps, auto_set_mode=True)
    theta_watchdog = math.radians(theta_watchdog_deg)

    try:
        for ep in range(episodes):
            obs, _ = env.reset()
            print(f"\n[deploy] --- episode {ep+1}/{episodes} ---")
            done = False
            n = 0
            max_abs_alpha = 0.0
            hold = 0
            max_hold = 0
            while not done:
                act, _ = model.predict(obs, deterministic=True)
                # global torque scaling (preserves modulation shape), then hard cap
                act_clip = np.clip(act * action_mult, -action_scale, action_scale)
                send = np.zeros_like(act) if dry_run else act_clip
                obs, _r, term, trunc, _i = env.step(send)
                st = env.unwrapped._state  # [theta, alpha, theta_dot, alpha_dot]
                th, al, thd, ald = float(st[0]), float(st[1]), float(st[2]), float(st[3])
                al_wrapped = (al + math.pi) % (2 * math.pi) - math.pi
                max_abs_alpha = max(max_abs_alpha, abs(al_wrapped))
                upright = abs(abs(al_wrapped) - math.pi) <= math.radians(12.0)
                hold = hold + 1 if upright else 0
                max_hold = max(max_hold, hold)
                n += 1
                if n % log_every == 0:
                    print(f"  n={n:3d} th={th*RAD2DEG:+6.1f} al={al_wrapped*RAD2DEG:+6.1f} "
                          f"thd={thd:+5.1f} ald={ald:+5.1f} "
                          f"|pol={float(act[0]):+.2f} sent={float(send[0]):+.2f}"
                          f"{' UPRIGHT' if upright else ''}")
                if abs(th) > theta_watchdog:
                    print(f"  WATCHDOG: |theta|={th*RAD2DEG:.0f}deg > {theta_watchdog_deg:.0f} -> e-stop")
                    kill_motor(ip)
                    break
                done = term or trunc
            print(f"  episode end: max|alpha|={max_abs_alpha*RAD2DEG:.0f}deg "
                  f"(180=upright) max_hold={max_hold/50:.2f}s")
    finally:
        kill_motor(ip)
        with contextlib.suppress(Exception):
            env.close()
        print("[deploy] motor killed, env closed.")


# ---------------------------------------------------------------------------
# Stage 5: mode7 — on-device inference (firmware runs the net at 50Hz itself)
#   No PC in the control loop: we just set mode 7, monitor, and e-stop.
#   Requires the firmware flashed with the r6 policy_weights.h + tanh/sign/50Hz
#   fixes (CHANGELOG 1.46.0). The PC only watches; the ESP32 controls.
# ---------------------------------------------------------------------------
def stage_mode7(ip: str, seconds: float, reset_encoders: bool, theta_watchdog_deg: float,
                scale: float = 1.0) -> None:
    print("[mode7] ON-DEVICE inference. Firmware runs the policy at 50Hz; PC only monitors.")
    if reset_encoders:
        with contextlib.suppress(Exception):
            _get(ip, "/cmd", {"m": "0"}); time.sleep(0.2)
            _get(ip, "/rl_cmd", {"r": "1"}); time.sleep(0.4)
        rs = _state_json(ip)
        print(f"  encoders zeroed: th={rs.get('th'):+.3f} al={rs.get('al'):+.3f} (expect ~0,0)")
    with contextlib.suppress(Exception):
        _get(ip, "/rl_cmd", {"scale": f"{scale:.3f}"})
    print(f"[mode7] torque scale = {scale:.2f}")
    print("[mode7] !! MOTOR WILL MOVE (autonomous). Ctrl+C = panic stop. Firmware brakes beyond +-90deg.")
    _get(ip, "/cmd", {"m": "7"})
    t0 = time.time()
    max_abs_al = 0.0
    best_up_err = 180.0  # closest approach to upright (deg)
    try:
        while time.time() - t0 < seconds:
            rs = _state_json(ip)
            th = float(rs.get("th", 0.0)); al = float(rs.get("al", 0.0))
            al_w = (al + math.pi) % (2 * math.pi) - math.pi
            max_abs_al = max(max_abs_al, abs(al_w))
            up_err = abs(180.0 - abs(al_w) * RAD2DEG)  # deg from inverted
            best_up_err = min(best_up_err, up_err)
            upright = up_err <= 12.0
            print(f"  t={time.time()-t0:4.1f} th={th*RAD2DEG:+6.1f} al={al_w*RAD2DEG:+6.1f}"
                  f"{' <<< UPRIGHT' if upright else ''}")
            if abs(th) > math.radians(theta_watchdog_deg):
                print(f"  WATCHDOG: |theta|>{theta_watchdog_deg:.0f} -> e-stop"); break
            time.sleep(0.04)
    except KeyboardInterrupt:
        print("  (Ctrl+C)")
    finally:
        kill_motor(ip)
        print(f"[mode7] stopped. max|alpha|={max_abs_al*RAD2DEG:.0f}deg "
              f"(180=upright; closest approach {best_up_err:.0f}deg from inverted)")


def main() -> None:
    p = argparse.ArgumentParser(description="R6 hardware bring-up (staged)")
    p.add_argument("--ip", required=True, help="ESP32 IP, e.g. 192.168.100.50")
    p.add_argument("--stage", required=True, choices=["ping", "sensors", "estop", "deploy", "mode7"])
    p.add_argument("--seconds", type=float, default=20.0, help="sensors stage duration")
    p.add_argument("--hz", type=float, default=20.0, help="sensors poll rate")
    # deploy options
    p.add_argument("--model", default="experiments/2026-06-22_r6_real_aligned/models/r6_theta100_s0_step250000.zip")
    p.add_argument("--dry-run", action="store_true", help="compute actions but keep motor OFF")
    p.add_argument("--action-scale", type=float, default=1.0, help="clip |action| (live only)")
    p.add_argument("--max-steps", type=int, default=250, help="steps per episode (50Hz)")
    p.add_argument("--episodes", type=int, default=1)
    p.add_argument("--reset-encoders", action="store_true", help="zero encoders before deploy")
    p.add_argument("--log-every", type=int, default=10, help="print every N steps")
    p.add_argument("--theta-watchdog", type=float, default=105.0, help="e-stop |theta| deg")
    p.add_argument("--action-mult", type=float, default=1.0, help="global torque scale (preserves shape)")
    p.add_argument("--scale", type=float, default=1.0, help="mode7 on-device PWM torque scale (0..1)")
    args = p.parse_args()

    if args.stage == "ping":
        stage_ping(args.ip)
    elif args.stage == "sensors":
        stage_sensors(args.ip, args.seconds, args.hz)
    elif args.stage == "estop":
        stage_estop(args.ip)
    elif args.stage == "deploy":
        stage_deploy(args.ip, args.model, args.dry_run, args.action_scale,
                     args.max_steps, args.episodes, args.reset_encoders,
                     args.log_every, args.theta_watchdog, args.action_mult)
    elif args.stage == "mode7":
        stage_mode7(args.ip, args.seconds, args.reset_encoders, args.theta_watchdog, args.scale)


if __name__ == "__main__":
    main()

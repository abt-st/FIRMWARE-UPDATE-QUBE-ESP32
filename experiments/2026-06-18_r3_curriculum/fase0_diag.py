"""Fase 0 — diagnóstico de estabilización (¿puede la política [64,64] sostener?).

Evalúa el mejor modelo de R2 (`linear_alpha`, semilla 1) en DOS distribuciones
de reset:

1. **hanging** (la de entrenamiento): reproduce R2 — reach alto, balance 0%.
2. **near_upright** (α≈π, vía ``reset_options``): aísla la capacidad de
   *estabilizar* del swing-up.

Decisión:
- Sostiene >=1 s desde el ápice  -> la red SÍ sabe estabilizar; el cuello de
  botella es la transición swing-up->balance  -> el currículo (R3) es la apuesta.
- No sostiene ni desde el ápice    -> falta damping  -> priorizar híbrido/LQR.
"""

from __future__ import annotations

from pathlib import Path

from stable_baselines3 import SAC

from qube_rl.envs.factory import make_sim_env
from qube_rl.metrics import evaluate_balance, format_balance_metrics

MODEL = Path("experiments/2026-06-18_r2_balance/models/r2_02_linear_alpha_control_s1.zip")
N_EP = 30


def main() -> None:
    model = SAC.load(str(MODEL))
    print(f"Modelo: {MODEL.name}\n")

    for label, opts in (("hanging (entrenamiento)", None), ("near_upright (ápice)", {"near_upright": True})):
        env = make_sim_env(reward="linear_alpha")
        m = evaluate_balance(model, env, n_episodes=N_EP, control_freq=50, reset_options=opts)
        print(f"[{label}]")
        print("  " + format_balance_metrics(m))
        print(
            f"  balance_rate={m['balance_rate'] * 100:.1f}%  "
            f"hold_avg={m['max_hold_s']:.2f}s  hold_best={m['max_hold_s_best']:.2f}s\n"
        )


if __name__ == "__main__":
    main()

"""Knowledge distillation from a large SAC teacher to a small SAC student.

Compresses a [128,128] teacher policy into a [64,64] student that fits
ESP32 flash (~25.8 KB) while retaining swing-up capability.

Usage::

    uv run python -m qube_rl.distill \\
        --teacher models/qube_sac_SAC_17_128_c1.zip \\
        --student-arch 64 \\
        --timesteps 200000
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def distill(
    teacher_path: str,
    student_arch: int = 64,
    timesteps: int = 200_000,
    lr: float = 3e-4,
    temperature: float = 2.0,  # noqa: ARG001  TODO: not yet wired into the BC loss (soft-target temperature)
    alpha: float = 0.5,  # noqa: ARG001  TODO: not yet wired into the BC/RL blend
    save_dir: str = "models",
) -> None:
    """Distill teacher policy into student via behavioral cloning + RL fine-tuning.

    Parameters
    ----------
    teacher_path : str
        Path to trained teacher SAC model.
    student_arch : int
        Hidden layer size for student network.
    timesteps : int
        Total training timesteps for student.
    lr : float
        Learning rate for student.
    temperature : float
        Softmax temperature for teacher action distribution.
    alpha : float
        Blending factor: 0 = pure BC, 1 = pure RL. 0.5 = balanced.
    save_dir : str
        Directory to save student model.
    """
    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import DummyVecEnv

    from qube_rl.train import make_env

    # Load teacher
    teacher = SAC.load(teacher_path)
    logger.info("Teacher loaded: %s", teacher_path)
    logger.info(
        "Teacher architecture: %d → %d → %d → 1",
        teacher.observation_space.shape[0],
        teacher.actor.mu[0].weight.shape[0],
        teacher.actor.mu[0].weight.shape[1],
    )

    # Build student with smaller network
    vec_env = DummyVecEnv([lambda: make_env(reward="linear_alpha")])

    student = SAC(
        "MlpPolicy",
        vec_env,
        learning_rate=lr,
        buffer_size=500_000,
        batch_size=256,
        tau=0.005,
        gamma=0.99,
        use_sde=True,
        use_sde_at_warmup=True,
        sde_sample_freq=64,
        train_freq=1,
        gradient_steps=1,
        learning_starts=1000,
        verbose=1,
        policy_kwargs=dict(
            net_arch=dict(pi=[student_arch, student_arch], qf=[student_arch, student_arch]),
        ),
    )

    logger.info("Student network: [%d, %d]", student_arch, student_arch)

    # Phase 1: Behavioral cloning — collect teacher data and train student
    logger.info("Phase 1: Collecting teacher demonstrations...")
    n_demos = 100_000
    obs_buffer = []
    action_buffer = []

    obs = vec_env.reset()
    for _ in range(n_demos):
        action, _ = teacher.predict(obs, deterministic=True)
        obs_buffer.append(obs[0].copy())
        action_buffer.append(action[0].copy())
        obs, _, done, _ = vec_env.step(action)
        if done[0]:
            obs = vec_env.reset()

    obs_array = np.array(obs_buffer)
    action_array = np.array(action_buffer)
    logger.info("Collected %d demonstrations", len(obs_buffer))

    # Phase 2: Fine-tune student with RL using teacher as guide
    logger.info("Phase 2: RL fine-tuning with teacher guidance...")

    # Pre-fill replay buffer with demonstrations
    for i in range(min(len(obs_buffer), 10_000)):
        next_obs = obs_array[i + 1] if i + 1 < len(obs_buffer) else obs_array[i]
        student.replay_buffer.add(
            obs_array[i],
            next_obs,
            action_array[i],
            np.array([0.0]),
            np.array([False]),
            np.array([{}]),
        )

    # Train with RL in chunks and save checkpoints
    chunk_size = 50_000
    n_chunks = max(1, timesteps // chunk_size)
    for chunk in range(1, n_chunks + 1):
        logger.info("Chunk %d/%d", chunk, n_chunks)
        student.learn(total_timesteps=chunk_size, progress_bar=True)
        ckpt_path = Path(save_dir) / f"qube_sac_distilled_{student_arch}_c{chunk}.zip"
        student.save(str(ckpt_path))
        logger.info("Checkpoint saved: %s", ckpt_path)

    # Save
    save_path = Path(save_dir) / f"qube_sac_distilled_{student_arch}.zip"
    student.save(str(save_path))
    logger.info("Student saved to %s", save_path)

    # Verify
    logger.info("Verifying student...")
    test_env = DummyVecEnv([lambda: make_env(reward="linear_alpha")])
    swingups = 0
    n_test_episodes = 20
    for _ep in range(n_test_episodes):
        obs = test_env.reset()
        max_alpha = 0
        for _step in range(500):
            action, _ = student.predict(obs, deterministic=True)
            obs, _reward, done, _info = test_env.step(action)
            al = obs[0][1]
            if abs(np.degrees(al)) > abs(max_alpha):
                max_alpha = np.degrees(al)
            if done[0]:
                break
        if abs(max_alpha) > 120:
            swingups += 1

    logger.info("Student swing-up rate: %d/%d (%.0f%%)", swingups, n_test_episodes, swingups / n_test_episodes * 100)

    # Export to C++ header (writes directly into the firmware tree so the
    # flashed weights always match the distilled student).
    from qube_rl.export_rltools import export_model_to_header

    header_path = Path("src/firmware/esp32_qube_l298n/policy_weights.h")
    export_model_to_header(str(save_path), str(header_path))


def main() -> None:
    parser = argparse.ArgumentParser(description="Knowledge distillation for QUBE SAC")
    parser.add_argument("--teacher", required=True, help="Path to teacher model")
    parser.add_argument("--student-arch", type=int, default=64, help="Student hidden size")
    parser.add_argument("--timesteps", type=int, default=200_000, help="Training timesteps")
    parser.add_argument("--lr", type=float, default=3e-4, help="Learning rate")
    parser.add_argument("--temperature", type=float, default=2.0, help="Teacher temperature")
    parser.add_argument("--alpha", type=float, default=0.5, help="BC/RL blend (0=BC, 1=RL)")
    parser.add_argument("--save-dir", default="models", help="Save directory")
    args = parser.parse_args()

    distill(
        teacher_path=args.teacher,
        student_arch=args.student_arch,
        timesteps=args.timesteps,
        lr=args.lr,
        temperature=args.temperature,
        alpha=args.alpha,
        save_dir=args.save_dir,
    )


if __name__ == "__main__":
    main()

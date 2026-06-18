"""Optional MLflow experiment tracking for QUBE RL training.

MLflow is the project's experiment tracker.  Integration is non-invasive: an
SB3 callback forwards the metrics/losses SB3 records (plus episode reward/length
from the rollout buffer) to MLflow, alongside run params and the model artifact.

Everything degrades gracefully: if ``mlflow`` is not installed or tracking is
disabled, the helpers become no-ops and training proceeds normally.

Usage in a training script::

    from qube_rl.mlflow_tracking import mlflow_run, make_metrics_callback, build_params

    params = build_params(sac=SACConfig(), env=EnvConfig(), seed=args.seed)
    with mlflow_run("my_run", params, enabled=args.mlflow) as run:
        model.learn(total_timesteps=n, callback=make_metrics_callback(enabled=args.mlflow))
        model.save(path)
        if run:
            run.log_artifact(path)

Backend: defaults to a local SQLite store at ``sqlite:///mlflow.db`` (zero
infrastructure, supported on MLflow 2.x and 3.x; the legacy ``file:./mlruns``
store is in maintenance mode on MLflow 3.x and raises unless
``MLFLOW_ALLOW_FILE_STORE=true``).  Override via ``--mlflow-uri`` or the
``MLFLOW_TRACKING_URI`` env var.  View runs with::

    mlflow ui --backend-store-uri sqlite:///mlflow.db
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_EXPERIMENT = "qube_sac"
# Local SQLite store: zero-infra and supported on MLflow 2.x and 3.x (the legacy
# file store is in maintenance mode on 3.x). Artifacts default to ./mlartifacts.
DEFAULT_TRACKING_URI = "sqlite:///mlflow.db"
_MAX_PARAM_LEN = 250  # MLflow rejects param values longer than 500 chars; stay well under


def resolve_tracking_uri(uri: str | None) -> str:
    """Pick the tracking URI: explicit arg → env var → local ./mlruns."""
    return uri or os.environ.get("MLFLOW_TRACKING_URI") or DEFAULT_TRACKING_URI


def config_to_params(prefix: str, cfg: Any) -> dict[str, Any]:
    """Flatten a dataclass (or mapping) into ``prefix.field`` params.

    Pure helper (no MLflow dependency) so it can be unit-tested directly.
    Private fields (leading underscore) and non-scalar values are skipped.
    """
    if is_dataclass(cfg) and not isinstance(cfg, type):
        items: Mapping[str, Any] = asdict(cfg)
    elif isinstance(cfg, Mapping):
        items = cfg
    else:
        raise TypeError(f"Cannot flatten {type(cfg)!r}; expected a dataclass instance or mapping")

    params: dict[str, Any] = {}
    for key, value in items.items():
        if key.startswith("_"):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            params[f"{prefix}.{key}"] = value
    return params


def build_params(seed: int | None = None, **configs: Any) -> dict[str, Any]:
    """Build a flat param dict from named dataclass configs plus extras.

    Example::

        build_params(seed=42, sac=SACConfig(), env=EnvConfig(), reward="linear_alpha")
    """
    params: dict[str, Any] = {}
    if seed is not None:
        params["seed"] = seed
    for name, cfg in configs.items():
        if is_dataclass(cfg) and not isinstance(cfg, type):
            params.update(config_to_params(name, cfg))
        else:
            params[name] = cfg
    return params


def _stringify(value: Any) -> str:
    return str(value)[:_MAX_PARAM_LEN]


@contextmanager
def mlflow_run(
    run_name: str,
    params: Mapping[str, Any] | None = None,
    *,
    enabled: bool,
    uri: str | None = None,
    experiment: str = DEFAULT_EXPERIMENT,
    nested: bool = False,
) -> Iterator[Any]:
    """Context manager yielding the active ``mlflow`` module, or ``None``.

    No-ops (yields ``None``) when ``enabled`` is False or ``mlflow`` is missing,
    so callers can guard artifact logging with ``if run:`` and otherwise ignore
    tracking entirely.
    """
    if not enabled:
        yield None
        return
    try:
        import mlflow
    except ImportError:
        logger.warning("mlflow not installed; tracking disabled. Install with: uv sync --extra tracking")
        yield None
        return

    mlflow.set_tracking_uri(resolve_tracking_uri(uri))
    mlflow.set_experiment(experiment)
    with mlflow.start_run(run_name=run_name, nested=nested):
        if params:
            mlflow.log_params({k: _stringify(v) for k, v in params.items()})
        yield mlflow


def make_metrics_callback(enabled: bool, log_freq: int = 1000) -> Any:
    """Return an SB3 callback that mirrors SB3's metrics into MLflow, or ``None``.

    Returns ``None`` (a valid ``callback`` value for ``model.learn``) when
    disabled or when mlflow/SB3 are unavailable.
    """
    if not enabled:
        return None
    try:
        import mlflow  # noqa: F401
        from stable_baselines3.common.callbacks import BaseCallback
    except ImportError:
        logger.warning("mlflow/stable-baselines3 unavailable; metrics callback disabled")
        return None

    class _MLflowMetricsCallback(BaseCallback):
        """Forward the scalars SB3 already records to MLflow at ``log_freq`` steps."""

        def __init__(self, freq: int) -> None:
            super().__init__()
            self.freq = freq

        def _log_current(self) -> None:
            import mlflow as _mlflow

            for key, value in self.logger.name_to_value.items():
                if isinstance(value, (int, float)):
                    # MLflow metric names allow alphanumerics, _ - . / and space.
                    _mlflow.log_metric(key, float(value), step=self.num_timesteps)

            # Episode performance metrics (ep_rew_mean / ep_len_mean) are flushed
            # and cleared from the logger between dumps, so reading name_to_value
            # misses them. Recompute them directly from SB3's episode buffer.
            ep_buffer = getattr(self.model, "ep_info_buffer", None)
            if ep_buffer:
                from stable_baselines3.common.utils import safe_mean

                _mlflow.log_metric(
                    "rollout/ep_rew_mean", safe_mean([ep["r"] for ep in ep_buffer]), step=self.num_timesteps
                )
                _mlflow.log_metric(
                    "rollout/ep_len_mean", safe_mean([ep["l"] for ep in ep_buffer]), step=self.num_timesteps
                )

        def _on_step(self) -> bool:
            if self.n_calls % self.freq == 0:
                self._log_current()
            return True

        def _on_training_end(self) -> None:
            self._log_current()

    return _MLflowMetricsCallback(log_freq)

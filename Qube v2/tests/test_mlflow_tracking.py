"""Tests for the optional MLflow tracking helpers (mlflow_tracking.py).

The pure helpers (param flattening, URI resolution, graceful no-op) are tested
without MLflow installed; the metric-callback test skips when MLflow/SB3 are
unavailable.
"""

from __future__ import annotations

import pytest

from qube_rl.config import EnvConfig, SACConfig
from qube_rl.mlflow_tracking import (
    DEFAULT_TRACKING_URI,
    build_params,
    config_to_params,
    make_metrics_callback,
    mlflow_run,
    resolve_tracking_uri,
)


class TestConfigToParams:
    def test_flattens_dataclass_with_prefix(self) -> None:
        params = config_to_params("sac", SACConfig())
        assert params["sac.learning_rate"] == SACConfig().learning_rate
        assert params["sac.net_arch"] == SACConfig().net_arch

    def test_skips_private_fields(self) -> None:
        params = config_to_params("env", EnvConfig())
        assert all(not k.split(".", 1)[1].startswith("_") for k in params)

    def test_rejects_non_dataclass(self) -> None:
        with pytest.raises(TypeError):
            config_to_params("x", 123)


class TestBuildParams:
    def test_combines_configs_and_extras(self) -> None:
        params = build_params(seed=42, sac=SACConfig(), env=EnvConfig(), reward="linear_alpha")
        assert params["seed"] == 42
        assert params["reward"] == "linear_alpha"
        assert "sac.gamma" in params
        assert "env.control_freq" in params

    def test_seed_none_omitted(self) -> None:
        params = build_params(seed=None, reward="cos_alpha")
        assert "seed" not in params


class TestResolveUri:
    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
        assert resolve_tracking_uri(None) == DEFAULT_TRACKING_URI

    def test_explicit_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLFLOW_TRACKING_URI", "file:./other")
        assert resolve_tracking_uri("file:./explicit") == "file:./explicit"

    def test_env_var_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://server:5000")
        assert resolve_tracking_uri(None) == "http://server:5000"


class TestGracefulNoOp:
    def test_disabled_run_yields_none(self) -> None:
        with mlflow_run("r", {"a": 1}, enabled=False) as run:
            assert run is None

    def test_disabled_callback_is_none(self) -> None:
        assert make_metrics_callback(enabled=False) is None


class TestMLflowIntegration:
    def test_run_logs_params_and_metrics(self, tmp_path) -> None:
        pytest.importorskip("mlflow")
        import mlflow

        uri = f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}"
        with mlflow_run("smoke", {"seed": 7}, enabled=True, uri=uri, experiment="test_exp") as run:
            assert run is not None
            run.log_metric("dummy", 1.23, step=1)

        mlflow.set_tracking_uri(uri)
        exp = mlflow.get_experiment_by_name("test_exp")
        runs = mlflow.search_runs(experiment_ids=[exp.experiment_id])
        assert len(runs) == 1
        assert runs.iloc[0]["params.seed"] == "7"
        assert runs.iloc[0]["metrics.dummy"] == pytest.approx(1.23)

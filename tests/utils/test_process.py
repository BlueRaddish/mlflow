import os
import subprocess
import sys
from types import MappingProxyType
from unittest import mock

import pytest

from mlflow.utils.process import _exec_cmd


@pytest.mark.parametrize(
    "env",
    [
        None,
        {},
        {"MLFLOW_CMD_ENV_TEST_SENTINEL": "child-value"},
        MappingProxyType({"MLFLOW_CMD_ENV_TEST_SENTINEL": "child-value"}),
    ],
)
def test_exec_cmd_preserves_explicit_environment(monkeypatch, env):
    monkeypatch.setenv("MLFLOW_CMD_ENV_TEST_SENTINEL", "parent-value")
    result = _exec_cmd(
        [
            sys.executable,
            "-c",
            'import os; print(os.getenv("MLFLOW_CMD_ENV_TEST_SENTINEL", "missing"))',
        ],
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    expected = "parent-value" if env is None else env.get("MLFLOW_CMD_ENV_TEST_SENTINEL", "missing")
    assert result.stdout.strip() == expected


def test_exec_cmd_does_not_mutate_supplied_environment():
    env = {"PYTHONPATH": "/accessible:/inaccessible"}
    with (
        mock.patch("mlflow.utils.process.is_in_databricks_runtime", return_value=True),
        mock.patch(
            "mlflow.utils.process.os.access", side_effect=lambda path, mode: path == "/accessible"
        ),
        mock.patch("mlflow.utils.process.subprocess.Popen") as popen,
    ):
        popen.return_value.communicate.return_value = ("", "")
        popen.return_value.poll.return_value = 0
        _exec_cmd(["python"], env=env)
    assert env == {"PYTHONPATH": "/accessible:/inaccessible"}
    assert popen.call_args.kwargs["env"] == {"PYTHONPATH": "/accessible"}

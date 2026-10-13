import signal
from contextlib import nullcontext

import pytest

from mlflow.utils.os import is_windows
from mlflow.utils.timeout import MlflowTimeoutError, run_with_timeout


@pytest.mark.skipif(is_windows(), reason="Timeouts require Unix signals")
@pytest.mark.parametrize("outcome", ["normal", "alarm", "body_error", "bad_seconds"])
def test_run_with_timeout_restores_signal_handler(outcome):
    original_handler = signal.getsignal(signal.SIGALRM)

    def caller_handler(signum, frame):
        pass

    expected = {
        "alarm": MlflowTimeoutError,
        "body_error": ValueError,
        "bad_seconds": TypeError,
    }.get(outcome)
    signal.signal(signal.SIGALRM, caller_handler)
    try:
        with pytest.raises(expected) if expected else nullcontext():
            with run_with_timeout(0.5 if outcome == "bad_seconds" else 60):
                if outcome == "alarm":
                    signal.raise_signal(signal.SIGALRM)
                elif outcome == "body_error":
                    raise ValueError("body failed")
        assert signal.getsignal(signal.SIGALRM) is caller_handler
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, original_handler)

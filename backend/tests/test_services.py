import signal
import subprocess
import sys

import pytest


@pytest.mark.parametrize(("module", "name"), [("app.bot", "bot"), ("app.worker", "worker")])
def test_service_process_without_token_stops_cleanly_on_sigterm(module, name):
    process = subprocess.Popen(
        [sys.executable, "-m", module], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        assert f"Сервис {name} запущен" in process.stdout.readline()
        assert "BOT_TOKEN не задан" in process.stdout.readline()
        process.send_signal(signal.SIGTERM)
        output, _ = process.communicate(timeout=10)
    finally:
        process.kill()

    assert process.returncode == 0
    assert f"Сервис {name} остановлен" in output

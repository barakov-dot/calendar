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
        lines = [process.stdout.readline()]
        assert f"Сервис {name} запущен" in lines[0]
        while "BOT_TOKEN не задан" not in lines[-1]:
            lines.append(process.stdout.readline())
            assert lines[-1], "процесс завершился без сообщения о токене"
        process.send_signal(signal.SIGTERM)
        output, _ = process.communicate(timeout=10)
    finally:
        process.kill()

    assert process.returncode == 0
    assert f"Сервис {name} остановлен" in output

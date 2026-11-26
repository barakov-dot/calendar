import asyncio
import logging
import signal
import subprocess
import sys

import pytest

from app.core.service import run_idle


async def test_run_idle_logs_start_and_waits_for_stop(caplog):
    caplog.set_level(logging.INFO)
    stop = asyncio.Event()
    task = asyncio.create_task(run_idle("bot", stop))
    await asyncio.sleep(0)

    assert "Сервис bot запущен" in caplog.text
    assert not task.done()

    stop.set()
    await asyncio.wait_for(task, timeout=1)
    assert "Сервис bot остановлен" in caplog.text


@pytest.mark.parametrize(("module", "name"), [("app.bot", "bot"), ("app.worker", "worker")])
def test_service_process_stops_cleanly_on_sigterm(module, name):
    process = subprocess.Popen(
        [sys.executable, "-m", module], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        assert f"Сервис {name} запущен" in process.stdout.readline()
        process.send_signal(signal.SIGTERM)
        output, _ = process.communicate(timeout=10)
    finally:
        process.kill()

    assert process.returncode == 0
    assert f"Сервис {name} остановлен" in output

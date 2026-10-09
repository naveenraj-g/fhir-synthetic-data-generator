"""Runs Synthea (in Docker or from a local JDK) as a subprocess.

Uses subprocess in a worker thread rather than asyncio subprocesses: asyncio subprocess support
depends on the event-loop implementation (Windows selector loops raise NotImplementedError),
and uvicorn's choice of loop varies by platform and flags."""

import asyncio
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from app.generator.connectors.synthea.flags import DOCKER_MODULES, DOCKER_WORK

TAIL_LINES = 60


@dataclass
class ProcessResult:
    returncode: int
    tail: list[str]
    timed_out: bool = False


def _run_blocking(cmd: list[str], timeout: int, on_timeout: list[str] | None) -> ProcessResult:
    tail: deque[str] = deque(maxlen=TAIL_LINES)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace"
    )

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            tail.append(line.rstrip())

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        rc = proc.wait(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
        if on_timeout:  # e.g. `docker kill <name>`: killing the docker client alone leaves the container running
            subprocess.run(on_timeout, capture_output=True, timeout=30)
        proc.kill()
        rc = proc.wait()
    reader.join(timeout=5)
    return ProcessResult(returncode=rc, tail=list(tail), timed_out=timed_out)


async def run_process(
    cmd: list[str], *, timeout: int, on_timeout: list[str] | None = None
) -> ProcessResult:
    return await asyncio.to_thread(_run_blocking, cmd, timeout, on_timeout)


def docker_run_command(
    *,
    docker_bin: str,
    image: str,
    container_name: str,
    workdir: Path,
    modules_dir: Path | None,
    user: str | None,
    java_args: list[str],
) -> list[str]:
    cmd = [docker_bin, "run", "--rm", "--name", container_name]
    if user:
        cmd += ["--user", user]
    cmd += ["--mount", f"type=bind,source={workdir.resolve()},target={DOCKER_WORK}"]
    if modules_dir is not None:
        cmd += ["--mount", f"type=bind,source={modules_dir.resolve()},target={DOCKER_MODULES},readonly"]
    # The image's ENTRYPOINT is `java`, so java_args starts with the JVM flags.
    return [*cmd, image, *java_args]

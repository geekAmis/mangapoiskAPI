from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import paramiko
from manga_common.errors import UpstreamError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SSHTarget:
    host: str
    port: int
    username: str
    password: str
    name: str = ""

    def __repr__(self) -> str:  # never leak the password
        return f"SSHTarget(host={self.host!r}, port={self.port}, username={self.username!r})"


class DeployCancelled(Exception):
    """Raised when a running deploy is cancelled or found stale."""


@dataclass
class SSHRunHandle:
    """Cancellation handle for one blocking SSH deploy.

    Closing the channel/client from another thread unblocks a read that is
    waiting on a hung remote command.  The event also gives the reader a cheap
    cooperative cancellation check between lines.
    """

    cancel_event: threading.Event = field(default_factory=threading.Event)
    client: paramiko.SSHClient | None = None
    channel: paramiko.Channel | None = None

    def cancel(self) -> None:
        self.cancel_event.set()
        channel = self.channel
        if channel is not None:
            try:
                channel.close()
            except Exception:
                logger.debug("failed to close SSH channel", exc_info=True)
        client = self.client
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.debug("failed to close SSH client", exc_info=True)


class SSHRunner:
    """Small paramiko wrapper used by the deployment manager."""

    def __init__(self, timeout: float = 25.0) -> None:
        self.timeout = timeout

    def connect(self, target: SSHTarget, jump: SSHTarget | None = None) -> paramiko.SSHClient:
        sock = None
        jump_client = None
        if jump is not None:
            jump_client = paramiko.SSHClient()
            jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                jump_client.connect(
                    jump.host,
                    port=jump.port,
                    username=jump.username,
                    password=jump.password,
                    timeout=self.timeout,
                    look_for_keys=False,
                    allow_agent=False,
                )
            except paramiko.SSHException as exc:
                raise UpstreamError(
                    f"SSH jump host {jump.host} is unavailable", details=str(exc)
                ) from exc
            transport = jump_client.get_transport()
            if transport is None:
                raise UpstreamError("SSH jump transport is not available")
            sock = transport.open_channel(
                "direct-tcpip", (target.host, target.port), ("127.0.0.1", 0), timeout=self.timeout
            )

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                target.host,
                port=target.port,
                username=target.username,
                password=target.password,
                sock=sock,
                timeout=self.timeout,
                look_for_keys=False,
                allow_agent=False,
            )
        except paramiko.AuthenticationException as exc:
            if jump_client:
                jump_client.close()
            raise UpstreamError(
                f"SSH authentication failed for {target.host}", details=str(exc)
            ) from exc
        except paramiko.SSHException as exc:
            if jump_client:
                jump_client.close()
            raise UpstreamError(f"SSH connection failed for {target.host}", details=str(exc)) from exc
        client._mangapoisk_jump = jump_client  # type: ignore[attr-defined]
        return client

    def run_script(
        self,
        target: SSHTarget,
        script: str,
        *,
        jump: SSHTarget | None = None,
        on_line: Callable[[str], None] | None = None,
        timeout: float = 1800.0,
        read_timeout: float = 900.0,
        handle: SSHRunHandle | None = None,
    ) -> tuple[int, str]:
        """Run a shell script and stream its output.

        ``timeout`` is the total wall-clock budget, ``read_timeout`` is the
        maximum silence allowed between output lines.  Both are enforced on the
        Paramiko channel so a hung remote command cannot keep a job ``running``
        forever.  ``handle.cancel()`` closes the channel from another thread.
        """

        run = handle or SSHRunHandle()
        if run.cancel_event.is_set():
            raise DeployCancelled("deploy cancelled before connect")
        client = self.connect(target, jump)
        run.client = client
        output: list[str] = []
        deadline = time.monotonic() + timeout
        try:
            if run.cancel_event.is_set():
                raise DeployCancelled("deploy cancelled before start")
            stdin, stdout, stderr = client.exec_command("bash -s 2>&1", timeout=read_timeout)
            channel = stdout.channel
            run.channel = channel
            channel.settimeout(read_timeout)
            stdin.channel.settimeout(read_timeout)
            stderr.channel.settimeout(read_timeout)
            if run.cancel_event.is_set():
                raise DeployCancelled("deploy cancelled before start")
            stdin.write(script)
            stdin.channel.shutdown_write()

            def emit(raw: str) -> None:
                line = raw.rstrip("\n")
                output.append(line)
                if on_line:
                    on_line(line)

            for raw in stdout:
                if run.cancel_event.is_set():
                    raise DeployCancelled("deploy cancelled")
                if time.monotonic() > deadline:
                    raise TimeoutError(f"deploy exceeded total timeout of {timeout:.0f}s")
                emit(raw)
            if run.cancel_event.is_set():
                raise DeployCancelled("deploy cancelled")
            code = stdout.channel.recv_exit_status()
            for raw in stderr:
                emit(raw)
            return code, "\n".join(output)
        except (TimeoutError, OSError, paramiko.SSHException) as exc:
            if run.cancel_event.is_set():
                raise DeployCancelled("deploy cancelled") from exc
            if isinstance(exc, paramiko.SSHException):
                raise
            raise TimeoutError(
                f"deploy SSH stream timed out after {read_timeout:.0f}s without output"
            ) from exc
        finally:
            run.channel = None
            run.client = None
            jump_client = getattr(client, "_mangapoisk_jump", None)
            client.close()
            if jump_client:
                jump_client.close()

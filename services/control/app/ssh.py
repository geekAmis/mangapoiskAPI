from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

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
    ) -> tuple[int, str]:
        client = self.connect(target, jump)
        output: list[str] = []
        try:
            stdin, stdout, stderr = client.exec_command("bash -s 2>&1", timeout=timeout)
            stdin.write(script)
            stdin.channel.shutdown_write()
            for raw in stdout:
                line = raw.rstrip("\n")
                output.append(line)
                if on_line:
                    on_line(line)
            code = stdout.channel.recv_exit_status()
            for raw in stderr:
                line = raw.rstrip("\n")
                output.append(line)
                if on_line:
                    on_line(line)
            return code, "\n".join(output)
        finally:
            jump_client = getattr(client, "_mangapoisk_jump", None)
            client.close()
            if jump_client:
                jump_client.close()

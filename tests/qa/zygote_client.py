import asyncio
from typing import Any

from velo_zygote.protocol import ProtocolError, ZygoteTransport


class ZygoteClient:
    """A reusable high-level client for interacting with the Velo Zygote."""

    def __init__(self, socket_path: str):
        self.socket_path = socket_path
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._transport: ZygoteTransport | None = None

    async def connect(self, timeout: float = 2.0) -> bool:
        """Connect to the Zygote and wait for the Ready message."""
        try:
            # Connect via Unix Socket
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.socket_path), timeout=timeout
            )
            assert self._reader is not None
            assert self._writer is not None
            self._transport = ZygoteTransport(self._reader, self._writer)

            # Wait for greeting
            ready = await self.recv()
            if not ready or ready.get("type") != "Ready":
                raise ProtocolError(f"Protocol Handshake Failed: Expected 'Ready', got {ready}")
            return True
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Zygote at {self.socket_path}: {e}")

    async def send(self, cmd: dict[str, Any]) -> None:
        """Send a command to the Zygote."""
        if not self._transport:
            raise ConnectionError("Client not connected")
        await self._transport.send(cmd)

    async def recv(self, timeout: float = 30.0) -> dict[str, Any] | None:
        """Receive a response from the Zygote."""
        if not self._transport:
            raise ConnectionError("Client not connected")
        try:
            return await asyncio.wait_for(self._transport.recv(), timeout=timeout)
        except TimeoutError:
            raise TimeoutError("Zygote response timeout")

    async def close(self) -> None:
        """Close the connection."""
        if self._transport:
            await self._transport.close()
            self._transport = None
            self._reader = None
            self._writer = None

    async def __aenter__(self) -> "ZygoteClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

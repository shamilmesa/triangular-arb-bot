"""
Minimal Anvil launcher that respects free-tier RPC rate limits.

degenbot.AnvilFork always passes --no-rate-limit to anvil, which is
fine against a paid, high-throughput RPC endpoint but reliably trips
429s against free-tier providers (Infura, Ankr, PublicNode) as soon as
a pool with populated ticks needs more than a handful of storage
lookups. This launches anvil the same way but with
--compute-units-per-second set to a conservative value instead, so
anvil paces its own upstream requests rather than bursting.
"""

import shutil
import socket
import subprocess
import time

from web3 import Web3


class AnvilNotFound(Exception):
    pass


class RateLimitedAnvilFork:
    def __init__(
        self,
        fork_url: str,
        fork_block: int | None = None,
        fork_transaction_hash: str | None = None,
        chain_id: int | None = None,
        hardfork: str = "cancun",
        compute_units_per_second: int = 50,
        request_timeout: int = 180,
        startup_timeout: float = 90.0,
    ) -> None:
        anvil_path = shutil.which("anvil")
        if anvil_path is None:
            raise AnvilNotFound("anvil binary not found on PATH")

        self.port = self._free_port()
        command = [
            anvil_path,
            "--silent",
            "--auto-impersonate",
            f"--fork-url={fork_url}",
            f"--hardfork={hardfork}",
            f"--port={self.port}",
            f"--compute-units-per-second={compute_units_per_second}",
        ]
        if fork_block is not None:
            command.append(f"--fork-block-number={fork_block}")
        if fork_transaction_hash is not None:
            command.append(f"--fork-transaction-hash={fork_transaction_hash}")
        if chain_id is not None:
            command.append(f"--chain-id={chain_id}")

        self._process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Anvil paces its own upstream requests per compute_units_per_second,
        # so a single tick-bitmap fetch (many storage slots) can legitimately
        # take well over the default 30s HTTP timeout. This is a local
        # loopback connection, so waiting longer costs nothing but time.
        self.w3 = Web3(
            Web3.HTTPProvider(
                f"http://127.0.0.1:{self.port}",
                request_kwargs={"timeout": request_timeout},
            )
        )
        self._wait_until_ready(startup_timeout)

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _wait_until_ready(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                _, stderr = self._process.communicate()
                raise RuntimeError(f"anvil exited early: {stderr}")
            try:
                self.w3.eth.block_number
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(0.5)
        raise TimeoutError(f"anvil did not become ready in time: {last_error}")

    @property
    def block_number(self) -> int:
        return self.w3.eth.block_number

    def reset(self, block_number: int | None = None, fork_url: str | None = None) -> None:
        """Reset to a new block, optionally switching to a different upstream RPC."""
        forking: dict[str, object] = {}
        if block_number is not None:
            forking["blockNumber"] = block_number
        if fork_url is not None:
            forking["jsonRpcUrl"] = fork_url
        self.w3.provider.make_request(
            "anvil_reset",
            [{"forking": forking}] if forking else [{}],
        )

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001, S110
            pass

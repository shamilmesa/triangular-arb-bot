"""
Run this FIRST, on the VDS (needs live RPC access -- won't work in a
network-restricted sandbox), before touching
simulate_triangular_arbitrage.py.

First pass (GRAIL, MAGIC, DPX, RDNT) found that only MAGIC has real
depth (~41 WETH reserve on SushiSwap) -- GRAIL, DPX, and RDNT all
turned out to be dust (raw reserves in the 0.0001-0.06 range against
WETH), even after comparing across DEXs. GMX and PENDLE are larger,
more actively-traded Arbitrum-ecosystem tokens added for this second
pass. Rather than guess from web search, this checks every combination
directly on-chain via find_any_pool(), which takes seconds and is
authoritative (no anvil fork needed -- these are all just direct read
calls against your RPC provider). Watch the raw_reserve numbers in the
output, not just whether a pool was "FOUND" -- a pool can exist with
essentially nothing in it.

Usage:
  python src/check_pair_candidates.py
"""

import os

from dotenv import load_dotenv
from web3 import Web3

from pools import DPX, GMX, GRAIL, MAGIC, PENDLE, RDNT, USDC_NATIVE, WETH, find_any_pool

CANDIDATES = {
    "WETH": WETH,
    "USDC": USDC_NATIVE,
    "GRAIL": GRAIL,
    "MAGIC": MAGIC,
    "DPX": DPX,
    "RDNT": RDNT,
    "GMX": GMX,
    "PENDLE": PENDLE,
}


def main() -> None:
    load_dotenv()
    rpc_url = os.environ["ARBITRUM_RPC_URL"]
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 60}))
    print(f"Connected. Latest block: {w3.eth.block_number}\n")

    names = list(CANDIDATES.keys())
    found_pairs = []

    for i, name_a in enumerate(names):
        for name_b in names[i + 1 :]:
            addr_a, addr_b = CANDIDATES[name_a], CANDIDATES[name_b]
            try:
                dex, pool_address, fee, reserve_a = find_any_pool(w3, addr_a, addr_b)
                fee_label = f" (fee {fee / 10000}%)" if fee is not None else ""
                # Raw reserve units, not decimal-adjusted (USDC is 6
                # decimals, most others 18) -- good enough to eyeball
                # "is this dust or real", not meant to be human-scaled.
                reserve_label = f", raw_reserve_{name_a}={reserve_a}" if reserve_a is not None else ""
                print(
                    f"{name_a:6} <-> {name_b:6}: FOUND on {dex}{fee_label}  "
                    f"{pool_address}{reserve_label}"
                )
                found_pairs.append((name_a, name_b, dex))
            except ValueError as exc:
                print(f"{name_a:6} <-> {name_b:6}: none ({exc})")
            except Exception as exc:  # noqa: BLE001 -- e.g. bad ABI, RPC hiccups; don't abort the run
                print(f"{name_a:6} <-> {name_b:6}: ERROR, skipped ({exc})")

    print("\n--- Summary ---")
    print(f"{len(found_pairs)} pair(s) with a usable pool found:")
    for name_a, name_b, dex in found_pairs:
        print(f"  {name_a} <-> {name_b} on {dex}")

    print("\nTo build a triangle, you need three pairs that connect all")
    print("three tokens in a cycle, e.g. WETH-GRAIL, GRAIL-X, X-WETH.")
    print("Look for such a set in the list above before running")
    print("simulate_triangular_arbitrage.py.")


if __name__ == "__main__":
    main()

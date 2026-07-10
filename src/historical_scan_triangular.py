"""
Batch scanner for a fixed 3-leg triangular arbitrage cycle across many
historical blocks, analogous to arb-bot's historical_scan.py but for a
triangle instead of a WETH/USDC 2-pool comparison (see
simulate_triangular_arbitrage.py for the single-block version this
generalizes).

Resolves the three legs' pools ONCE via find_any_pool() at startup (the
pool *addresses* don't change between blocks, only their state does),
then reuses a single Anvil fork across the whole scan -- resetting it to
each block instead of respawning the process, exactly like
historical_scan.py -- which is what makes scanning hundreds of blocks
practical on free-tier RPC and a resource-constrained VDS.

No price pre-filter here (unlike historical_scan.py's tick-gap check):
a 3-leg cycle spanning up to three different DEX types (V2 reserves vs
V3 ticks) doesn't have as simple a single-number proxy for "could this
possibly be profitable", so every block pays the full pool-rebuild +
calculate() cost. Pick --step accordingly -- single-block spot checks
earlier in this project's history found the MAGIC-GMX and WETH-GMX pool
state completely unchanged across an ~11,000 block span, so a --step in
the low thousands (not 1) is a reasonable starting point to actually
land on blocks with different state instead of re-checking the same
snapshot repeatedly.

Usage:
  python src/historical_scan_triangular.py \
      --token-b 0x539bdE0d7Dbd336b79148AA742883198BBF60342 \
      --token-c 0xfc5A1A6EB076a2C7aD06eD22C90d7E710E35ad0a \
      --start 482400000 --end 482470000 --step 2000
"""

import argparse
import os
from pathlib import Path
import csv

from dotenv import load_dotenv

from degenbot import (
    CamelotLiquidityPool,
    Erc20Token,
    SushiswapV2Pool,
    UniswapV3Pool,
    pool_registry,
    set_web3,
)
from degenbot.arbitrage.uniswap_lp_cycle import UniswapLpCycle
from degenbot.exceptions import ArbitrageError, DegenbotValueError

from pools import WETH, find_any_pool
from rate_limited_fork import RateLimitedAnvilFork


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--token-a",
        type=str,
        default=WETH,
        help="First token in the cycle (default: WETH -- the practical liquidity hub).",
    )
    parser.add_argument("--token-b", type=str, required=True, help="Second token in the cycle.")
    parser.add_argument("--token-c", type=str, required=True, help="Third token in the cycle.")
    parser.add_argument("--start", type=int, required=True, help="First block to check.")
    parser.add_argument("--end", type=int, required=True, help="Last block to check (inclusive).")
    parser.add_argument("--step", type=int, default=1000, help="Block increment between checks.")
    parser.add_argument(
        "--out",
        type=str,
        default="data/triangular_scan_results.csv",
        help="Output CSV path.",
    )
    return parser.parse_args()


def get_rpc_urls() -> list[str]:
    """ARBITRUM_RPC_URLS (comma-separated) takes priority; falls back to ARBITRUM_RPC_URL."""
    multi = os.environ.get("ARBITRUM_RPC_URLS")
    if multi:
        urls = [u.strip() for u in multi.split(",") if u.strip()]
        if urls:
            return urls
    return [os.environ["ARBITRUM_RPC_URL"]]


def build_pool(dex: str, address: str, chain_id: int, state_block: int):
    if dex == "camelot_v2":
        return CamelotLiquidityPool(address=address, chain_id=chain_id, state_block=state_block)
    if dex == "sushiswap_v2":
        return SushiswapV2Pool(address=address, chain_id=chain_id, state_block=state_block)
    if dex == "uniswap_v3":
        return UniswapV3Pool(address=address, chain_id=chain_id, state_block=state_block)
    raise ValueError(f"Unknown dex {dex}")


def main() -> None:
    load_dotenv()
    args = parse_args()

    rpc_urls = get_rpc_urls()
    rpc_index = 0
    chain_id = int(os.environ.get("CHAIN_ID", "42161"))
    hardfork = os.environ.get("ANVIL_HARDFORK", "cancun")
    cups = int(os.environ.get("ANVIL_COMPUTE_UNITS_PER_SECOND", "50"))
    startup_timeout = float(os.environ.get("ANVIL_STARTUP_TIMEOUT", "90"))

    token_a_addr, token_b_addr, token_c_addr = args.token_a, args.token_b, args.token_c

    print(
        f"Launching Anvil fork at block {args.start} "
        f"(hardfork={hardfork}, cups={cups}, {len(rpc_urls)} RPC URL(s) available) ..."
    )
    fork = RateLimitedAnvilFork(
        fork_url=rpc_urls[rpc_index],
        fork_block=args.start,
        chain_id=chain_id,
        hardfork=hardfork,
        compute_units_per_second=cups,
        startup_timeout=startup_timeout,
    )
    set_web3(fork.w3)

    token_a = Erc20Token(token_a_addr)
    token_b = Erc20Token(token_b_addr)
    token_c = Erc20Token(token_c_addr)
    print(f"Cycle: {token_a.symbol} -> {token_b.symbol} -> {token_c.symbol} -> {token_a.symbol}")

    legs = [
        (token_a_addr, token_b_addr),
        (token_b_addr, token_c_addr),
        (token_c_addr, token_a_addr),
    ]

    # Resolved once: which DEX/pool/fee serves each leg. Only the pools'
    # *state* is re-read per block below, not their identity.
    resolved_legs: list[tuple[str, str, int | None]] = []
    for leg_a, leg_b in legs:
        dex, address, fee, reserve_a = find_any_pool(fork.w3, leg_a, leg_b)
        fee_label = f" (fee tier {fee / 10000}%)" if fee is not None else ""
        reserve_label = f", raw_reserve={reserve_a}" if reserve_a is not None else ""
        print(f"  {leg_a} <-> {leg_b}: {dex} pool {address}{fee_label}{reserve_label}")
        resolved_legs.append((dex, address, fee))

    pool_addrs = [address for _dex, address, _fee in resolved_legs]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    checked_count = 0
    profitable_count = 0

    with out_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["block", "profitable", f"input_{token_a.symbol}", f"profit_{token_a.symbol}", "note"]
        )

        for block in range(args.start, args.end + 1, args.step):
            try:
                fork.reset(block_number=block)
            except Exception as exc:  # noqa: BLE001 -- rotate provider and retry once
                rpc_index = (rpc_index + 1) % len(rpc_urls)
                print(f"block {block}: reset failed ({exc}); rotating to {rpc_urls[rpc_index]}")
                try:
                    fork.reset(block_number=block, fork_url=rpc_urls[rpc_index])
                except Exception as exc2:  # noqa: BLE001
                    writer.writerow([block, "", "", "", str(exc2)[:200]])
                    f.flush()
                    print(f"block {block}: SKIPPED, reset failed on all providers: {exc2}")
                    continue

            try:
                pools = [
                    build_pool(dex, address, chain_id, state_block=block)
                    for dex, address, _fee in resolved_legs
                ]
                arb = UniswapLpCycle(
                    input_token=token_a,
                    swap_pools=pools,
                    id=f"triangular-{token_a.symbol}-{token_b.symbol}-{token_c.symbol}-{block}",
                    max_input=10 * 10**18,
                )
                result = arb.calculate()
            except (ArbitrageError, DegenbotValueError) as exc:
                checked_count += 1
                writer.writerow([block, False, "", "", str(exc)[:150]])
                f.flush()
                print(f"block {block}: no arbitrage ({exc})")
                continue
            except Exception as exc:  # noqa: BLE001 -- e.g. RPC rate limits, transient failures
                writer.writerow([block, "", "", "", str(exc)[:200]])
                f.flush()
                print(f"block {block}: SKIPPED due to error: {exc}")
                continue
            finally:
                for addr in pool_addrs:
                    pool_registry.remove(addr, chain_id)

            checked_count += 1
            profitable_count += 1
            profit = result.profit_amount / 10**18
            input_amount = result.input_amount / 10**18
            writer.writerow([block, True, f"{input_amount:.6f}", f"{profit:.6f}", ""])
            f.flush()
            print(
                f"block {block}: PROFITABLE, input {input_amount:.6f} {token_a.symbol}, "
                f"profit {profit:.6f} {token_a.symbol}"
            )

    print(f"\nDone. {checked_count} block(s) checked, {profitable_count} profitable.")
    print(f"Results written to {out_path}")


if __name__ == "__main__":
    main()

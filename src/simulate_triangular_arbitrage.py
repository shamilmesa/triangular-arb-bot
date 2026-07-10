"""
Triangular arbitrage simulation across a 3-token cycle on Arbitrum,
using non-tier-1 tokens deliberately (see README for why).

Checks a cycle: token_a -> token_b -> token_c -> token_a, using
whichever of Camelot V2 / SushiSwap V2 / Uniswap V3 actually has a
usable pool for each of the three pairs (find_any_pool tries all
three). Runs entirely against a local Anvil fork -- no real funds, no
live transactions.

Why non-tier-1 tokens: prior testing (see the arb-bot repo this project
was spun out of) found 0 profitable blocks out of 8 checked for
WETH/USDC cross-fee-tier arbitrage, and 0 out of 5 for ARB/WETH
cross-DEX arbitrage -- both consistent with those pairs being kept in
near-perfect sync by well-resourced searchers who concentrate
infrastructure on the most-watched pairs. This tests the theory that
triangular cycles through smaller-cap, less-monitored tokens are less
tightly arbitraged -- both because the pairs themselves get less
attention, and because 3-hop cycles are more expensive for searchers to
continuously monitor than simple 2-pool comparisons.

IMPORTANT: --token-c has no default. src/pools.py has verified
addresses for MAGIC, DPX, and RDNT as candidates, but web research
could NOT confirm a direct pool between any two of {GRAIL, MAGIC, DPX,
RDNT} -- most mid-cap tokens only pair against WETH/USDC, not each
other. Run check_pair_candidates.py FIRST (needs live RPC, so run it on
the VDS, not in a sandboxed session) to find out on-chain, in seconds,
which pairs among your candidates actually have a usable pool, instead
of guessing and burning an Anvil fork on a cycle that can't be built.

Usage:
  python src/simulate_triangular_arbitrage.py --token-c 0x...
  python src/simulate_triangular_arbitrage.py --token-c 0x... --block 250000000
"""

import argparse
import os

from dotenv import load_dotenv

from degenbot import CamelotLiquidityPool, Erc20Token, SushiswapV2Pool, UniswapV3Pool, set_web3
from degenbot.arbitrage.uniswap_lp_cycle import UniswapLpCycle

from pools import GRAIL, WETH, find_any_pool
from rate_limited_fork import RateLimitedAnvilFork


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--token-a",
        type=str,
        default=WETH,
        help="First token in the cycle (default: WETH -- needed as the practical liquidity hub).",
    )
    parser.add_argument(
        "--token-b",
        type=str,
        default=GRAIL,
        help="Second token in the cycle (default: GRAIL).",
    )
    parser.add_argument(
        "--token-c",
        type=str,
        required=True,
        help="Third token in the cycle. No default -- verify the address and that a direct "
        "pool exists against --token-b before using it (see module docstring).",
    )
    parser.add_argument("--block", type=int, default=None, help="Fork from this block number.")
    return parser.parse_args()


def build_pool(w3, dex: str, address: str, chain_id: int):
    if dex == "camelot_v2":
        return CamelotLiquidityPool(address=address, chain_id=chain_id)
    if dex == "sushiswap_v2":
        return SushiswapV2Pool(address=address, chain_id=chain_id)
    if dex == "uniswap_v3":
        return UniswapV3Pool(address=address, chain_id=chain_id)
    raise ValueError(f"Unknown dex {dex}")


def main() -> None:
    load_dotenv()
    args = parse_args()

    rpc_url = os.environ["ARBITRUM_RPC_URL"]
    chain_id = int(os.environ.get("CHAIN_ID", "42161"))
    hardfork = os.environ.get("ANVIL_HARDFORK", "cancun")
    cups = int(os.environ.get("ANVIL_COMPUTE_UNITS_PER_SECOND", "50"))
    startup_timeout = float(os.environ.get("ANVIL_STARTUP_TIMEOUT", "90"))

    token_a_addr, token_b_addr, token_c_addr = args.token_a, args.token_b, args.token_c

    print(f"Launching Anvil fork of chain {chain_id} (hardfork={hardfork}, cups={cups}) ...")
    fork = RateLimitedAnvilFork(
        fork_url=rpc_url,
        fork_block=args.block,
        chain_id=chain_id,
        hardfork=hardfork,
        compute_units_per_second=cups,
        startup_timeout=startup_timeout,
    )
    print(f"Fork live at block {fork.block_number}")

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

    pools = []
    for leg_a, leg_b in legs:
        try:
            dex, address, fee, reserve_a = find_any_pool(fork.w3, leg_a, leg_b)
        except ValueError as exc:
            print(f"\nFAILED to build cycle: {exc}")
            print(
                "This leg has no direct pool on Camelot V2, SushiSwap V2, or Uniswap V3. "
                "Most mid-cap tokens only pair against WETH -- try a different --token-c, "
                "or verify manually on app.camelot.exchange / app.uniswap.org whether this "
                "pair exists."
            )
            return
        fee_label = f" (fee tier {fee / 10000}%)" if fee is not None else ""
        reserve_label = f", raw_reserve={reserve_a}" if reserve_a is not None else ""
        print(f"  {leg_a} <-> {leg_b}: {dex} pool {address}{fee_label}{reserve_label}")
        pools.append(build_pool(fork.w3, dex, address, chain_id))

    arb = UniswapLpCycle(
        input_token=token_a,
        swap_pools=pools,
        id=f"triangular-{token_a.symbol}-{token_b.symbol}-{token_c.symbol}",
        max_input=10 * 10**18,
    )

    try:
        result = arb.calculate()
    except Exception as exc:  # degenbot raises ArbitrageError/NoLiquidity/etc when unprofitable
        print(f"\nNo profitable arbitrage at block {fork.block_number}: {exc}")
        return

    profit = result.profit_amount / 10**18
    input_amount = result.input_amount / 10**18

    print("\n--- Result ---")
    print(f"Optimal input:  {input_amount:.6f} {token_a.symbol}")
    print(f"Gross profit:   {profit:.6f} {token_a.symbol}")
    print(
        "Note: this is gross profit before gas and before builder/priority "
        "fee competition on all three legs of the trade."
    )


if __name__ == "__main__":
    main()

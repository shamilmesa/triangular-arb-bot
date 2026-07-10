# triangular-arb-bot

Local, no-money research tooling for **triangular arbitrage** on
Arbitrum using non-tier-1 tokens, built on
[degenbot](https://github.com/BowTiedDevil/degenbot). Runs against a
local Anvil fork -- no real funds, no live transactions.

Spun out of [shamilmesa/arb-bot](https://github.com/shamilmesa/arb-bot),
which has the full history of the research this continues. Read that
repo's README/history first if you want the "why" behind the choices
here; this README only covers what's specific to the triangular-cycle
theory.

## Why triangular, why non-tier-1 tokens

Prior testing in arb-bot found:
- **WETH/USDC cross-fee-tier arbitrage on Uniswap V3**: 0 profitable
  blocks out of 8 checked.
- **ARB/WETH cross-DEX arbitrage (Camelot vs Uniswap V3)**: 0
  profitable blocks out of 5 checked.

Both are consistent with those pairs being kept in near-perfect sync
by well-resourced searchers who concentrate infrastructure on the
most-watched pairs (WETH, USDC, ARB). This project tests two changes at
once:

1. **Smaller-cap, less-monitored tokens** instead of blue-chips --
   fewer bots bother watching them closely.
2. **A 3-hop cycle instead of a 2-pool comparison** -- more expensive
   for searchers to continuously monitor across every possible
   triangle, compared to a simple pairwise price check.

## Setup (same VDS as arb-bot -- most of this is already done there)

You already have Foundry (`anvil`) installed from the arb-bot work --
no need to reinstall it, it's not tied to a specific repo directory.

1. Clone this repo (if not already):
   ```
   git clone https://github.com/shamilmesa/triangular-arb-bot.git
   cd triangular-arb-bot
   ```
2. Create a **separate** venv for this project (don't reuse arb-bot's
   venv across repos):
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in `ARBITRUM_RPC_URL`. See the
   comments in `.env.example` for which providers actually worked on
   this VDS previously (dRPC and PublicNode; Alchemy was IP-blocked,
   Infura/Ankr rate-limited quickly) -- re-verify with a quick curl
   before trusting any of them again, provider behavior shifts:
   ```
   curl -s -o /dev/null -w "HTTP status: %{http_code}\n" -X POST "$ARBITRUM_RPC_URL" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'
   ```

## CRITICAL: verify the cycle exists before running

`src/simulate_triangular_arbitrage.py` defaults `--token-a` to WETH and
`--token-b` to GRAIL (both addresses verified against Arbiscan). It has
**no default for `--token-c`** and no second non-tier-1 address is
hardcoded in `src/pools.py` -- deliberately, because I couldn't verify
one during development.

**Before running anything**, do this by hand:

1. Pick a candidate third token. Reasonable Arbitrum-native candidates
   to research: MAGIC (Treasure DAO), RDNT (Radiant Capital), DPX
   (Dopex). Look up the real contract address on
   [Arbiscan](https://arbiscan.io) or CoinGecko -- do not trust any
   address pasted into a chat that wasn't independently checked.
2. Check whether a **direct pool** exists between GRAIL and your
   candidate token on **both** [Camelot](https://app.camelot.exchange/)
   and [Uniswap V3](https://app.uniswap.org/) (search the pair
   directly, not just each token separately). This is the step most
   likely to fail: most mid-cap tokens only pair against WETH, not
   against each other. If no direct GRAIL/TokenC pool exists with real
   liquidity, this specific cycle can't be built at all -- pick a
   different token or a different `--token-b`.
3. Also sanity-check the pool's liquidity depth on whichever DEX has
   it -- a thin pool will show inflated theoretical profit that
   wouldn't survive real execution slippage.

The script itself will tell you clearly if a leg has no usable pool
(`find_any_pool` raises with a message naming which pair failed) rather
than silently producing a wrong number -- but confirming by hand first
saves an Anvil fork's worth of RPC calls when the pair simply doesn't
exist.

## Usage

```
python src/simulate_triangular_arbitrage.py --token-c 0xYourVerifiedTokenCAddress
python src/simulate_triangular_arbitrage.py --token-c 0x... --block 482140000
python src/simulate_triangular_arbitrage.py --token-a 0x... --token-b 0x... --token-c 0x...
```

Forks Arbitrum at the given block (or latest), resolves a pool for each
of the three legs (tries Camelot V2 first, then Uniswap V3, for each
pair independently -- the three legs don't have to be on the same
DEX), and reports the profit-maximizing trade size at that block's
state.

## What this does NOT do yet

- Single-block only, like arb-bot's `simulate_arbitrage.py` /
  `simulate_camelot_arbitrage.py` (its "Stage 2"). No batch scanner
  across a block range yet -- port the pattern from arb-bot's
  `historical_scan.py` if you want real frequency/profit-distribution
  statistics instead of single-point checks.
- No live execution against the real mempool/sequencer -- this is
  research-only.
- Only checks Camelot V2 and Uniswap V3. Camelot V3 (Algebra engine,
  different factory + event shape) and other Arbitrum DEXs (Ramses,
  Zyberswap, etc.) aren't covered -- their factory addresses need
  independent verification before adding, same caveat as everywhere
  else in this project.
- Profit numbers are gross (pool fees only), before gas and before any
  latency-based competition for inclusion.

## Known rate-limit tuning from the source VDS

The same free-tier RPC issues from arb-bot apply here (it's the same
`RateLimitedAnvilFork` launcher, copied as-is). If you hit
`Error: Unknown hardfork: latest`, `429`/`408` rate-limit errors, or
`anvil did not become ready in time`, see arb-bot's README and commit
history for the full troubleshooting trail -- short version: lower
`ANVIL_COMPUTE_UNITS_PER_SECOND`, raise `ANVIL_STARTUP_TIMEOUT`, or
switch `ARBITRUM_RPC_URL` to a different provider.

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

## Running under resource limits (VDS running other tests)

If this VDS is also running an unrelated, longer test in a different
directory, use `run_limited.sh` instead of calling `python3` directly
for anything in Steps 2-3 -- it wraps the command in
`nice -n 15 ionice -c3 systemd-run --scope -p MemoryMax=700M --user`
automatically so you don't retype it every time:

```
./run_limited.sh src/simulate_triangular_arbitrage.py --token-c 0x...
./run_limited.sh src/historical_scan_triangular.py --token-b 0x... --token-c 0x... --start N --end M --step S
```

`check_pair_candidates.py` (Step 1) is cheap (direct read calls, no
Anvil fork) and doesn't need the wrapper.

## STEP 1 (do this first): find a real cycle with check_pair_candidates.py

`src/pools.py` has verified addresses (checked against Arbiscan) for
four non-tier-1 candidates: **GRAIL**, **MAGIC** (Treasure DAO), **DPX**
(Dopex), **RDNT** (Radiant Capital). Web research during development
could **not** confirm whether a direct pool exists between any two of
them -- most mid-cap Arbitrum tokens only pair against WETH/USDC, not
against each other. One concrete finding: MAGIC's most liquid pool
turned out to be on **SushiSwap**, not Camelot or Uniswap V3, which is
why `find_any_pool()` now checks all three DEXs.

Rather than keep guessing from web search results (which get
403'd/blocked from a sandboxed session anyway), run this first -- it
needs live RPC access, so run it on the VDS:

```
source .venv/bin/activate
python src/check_pair_candidates.py
```

This checks every pairwise combination among {WETH, USDC, GRAIL, MAGIC,
DPX, RDNT} across Camelot V2, SushiSwap V2, and Uniswap V3 in a few
seconds (no Anvil fork needed for this step -- just direct read calls),
and prints which ones actually have a usable pool. Look for **three**
pairs that connect all three tokens in a cycle (e.g. WETH-GRAIL,
GRAIL-X, X-WETH) before moving to Step 2. If nothing forms a full
triangle among these four candidates, you'll need to research a
different third or fourth token yourself -- same rule as everywhere
else in this project: verify the address and the pool independently,
don't trust one pulled from a chat/search result.

## STEP 2: run the simulation

```
./run_limited.sh src/simulate_triangular_arbitrage.py --token-c 0xYourVerifiedTokenCAddress
./run_limited.sh src/simulate_triangular_arbitrage.py --token-c 0x... --block 482140000
./run_limited.sh src/simulate_triangular_arbitrage.py --token-a 0x... --token-b 0x... --token-c 0x...
```

Forks Arbitrum at the given block (or latest), resolves a pool for each
of the three legs (tries Camelot V2, then SushiSwap V2, then Uniswap
V3, for each pair independently -- the three legs don't have to be on
the same DEX), and reports the profit-maximizing trade size at that
block's state. `--token-a` defaults to WETH, `--token-b` to GRAIL; both
have no default for `--token-c` since Step 1 needs to tell you what
actually works.

Also sanity-check the pool's liquidity depth (printed in the output)
on whichever DEX has it -- a thin pool will show inflated theoretical
profit that wouldn't survive real execution slippage.

## STEP 3 (optional): batch scan across many blocks

Once Step 2 shows a cycle that actually builds (all three legs resolve
to a real pool, no "not initialized" crash), you can check many blocks
in one run instead of one at a time:

```
./run_limited.sh src/historical_scan_triangular.py \
  --token-b 0x539bdE0d7Dbd336b79148AA742883198BBF60342 \
  --token-c 0xfc5A1A6EB076a2C7aD06eD22C90d7E710E35ad0a \
  --start 482400000 --end 482470000 --step 2000
```

This reuses a single Anvil fork across the whole scan (resetting it to
each block instead of respawning the process each time), same pattern
as arb-bot's `historical_scan.py`. Results go to
`data/triangular_scan_results.csv` (gitignored) -- one row per block
with whether it was profitable and the optimal input/profit if so.

Pick `--step` with care: single-block checks earlier in this project
found the MAGIC-GMX and WETH-GMX pools' on-chain state completely
unchanged across an ~11,000 block span (i.e. those pools saw no trades
at all in that window), so a `--step` of 1 mostly re-checks identical
state. A few thousand is a more useful starting point; tighten it if
you confirm the pair you're scanning trades more frequently than that.

Not every triangle can be scanned this way -- some Uniswap V3 pools
pass the basic `liquidity() != 0` check in `find_any_pool()` but still
fail degenbot's internal tick-range check ("Pool ... is not
initialized"). If Step 2 hits that error for one of your legs, that
triangle isn't usable with this tool; pick a different third token
instead of scanning around the problem.

## What this does NOT do yet

- No live execution against the real mempool/sequencer -- this is
  research-only.
- Only checks Camelot V2, SushiSwap V2, and Uniswap V3. Camelot V3
  (Algebra engine, different factory + event shape) and other Arbitrum
  DEXs (Ramses, Zyberswap, etc.) aren't covered -- their factory
  addresses need independent verification before adding, same caveat
  as everywhere else in this project.
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

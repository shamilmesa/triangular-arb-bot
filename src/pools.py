"""
Known, stable contract addresses on Arbitrum One (chain id 42161).

Only addresses that are canonical and easy to verify independently are
hardcoded here. Everything else (actual pool addresses) is resolved on
the fly via each DEX's factory contract, so a wrong guess here can't
silently point the simulation at the wrong pool.

Verify these on https://arbiscan.io before relying on them for anything
beyond local, no-money simulation.
"""

# Tokens
WETH = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
USDC_NATIVE = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"  # native USDC (post-2023 bridge)
ARB = "0x912CE59144191C1204E64559FE8253a0e49E6548"  # Arbitrum governance token -- tier-1, avoid

# Camelot's own governance token. Verify current liquidity/pairing on
# https://app.camelot.exchange/ before using.
GRAIL = "0x3d9907F9a368ad0a51Be60f7Da3b97cf940982D8"

# Mid-cap Arbitrum-native DeFi tokens -- candidates for a third leg.
# Addresses verified against Arbiscan (July 2026), but NOT the pool
# structure: web search could not confirm a *direct* pool between any
# two of these (or against GRAIL) that doesn't route through WETH/USDC.
# MAGIC's most liquid pool in particular is on SushiSwap, not
# Camelot/Uniswap V3 -- see check_pair_candidates.py, which tests every
# combination directly on-chain instead of guessing from search results.
MAGIC = "0x539bdE0d7Dbd336b79148AA742883198BBF60342"  # Treasure DAO
DPX = "0x6C2C06790b3E3E3c38e12Ee22F8183b37a13EE55"  # Dopex
RDNT = "0x3082CC23568eA640225c2467653dB90e9250AaA0"  # Radiant Capital (current v2 token)

# Uniswap V3 factory: deployed at the same address on Ethereum, Arbitrum,
# Optimism, Polygon and Base via a deterministic (CREATE2) deployer.
UNISWAP_V3_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"

_V3_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"},
            {"internalType": "uint24", "name": "fee", "type": "uint24"},
        ],
        "name": "getPool",
        "outputs": [{"internalType": "address", "name": "pool", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]

_SLOT0_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
            {"internalType": "uint8", "name": "feeProtocol", "type": "uint8"},
            {"internalType": "bool", "name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

_LIQUIDITY_ABI = [
    {
        "inputs": [],
        "name": "liquidity",
        "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}],
        "stateMutability": "view",
        "type": "function",
    }
]


def _get_v3_pool_address(w3, token_a: str, token_b: str, fee: int) -> str:
    factory = w3.eth.contract(
        address=w3.to_checksum_address(UNISWAP_V3_FACTORY), abi=_V3_FACTORY_ABI
    )
    pool_address = factory.functions.getPool(
        w3.to_checksum_address(token_a),
        w3.to_checksum_address(token_b),
        fee,
    ).call()
    if int(pool_address, 16) == 0:
        raise ValueError(f"No pool deployed for fee tier {fee}")
    return pool_address


def _get_v3_slot0(w3, pool_address: str) -> tuple[int, int]:
    pool = w3.eth.contract(address=w3.to_checksum_address(pool_address), abi=_SLOT0_ABI)
    sqrt_price_x96, tick, *_ = pool.functions.slot0().call()
    return sqrt_price_x96, tick


def _get_v3_liquidity(w3, pool_address: str) -> int:
    pool = w3.eth.contract(address=w3.to_checksum_address(pool_address), abi=_LIQUIDITY_ABI)
    return pool.functions.liquidity().call()


def find_v3_pool_address(w3, token_a: str, token_b: str) -> tuple[str, int]:
    """
    Try Uniswap V3 fee tiers -- in order of how likely a *volatile* pair
    is to actually have real liquidity there -- and return the first one
    that's deployed, initialized (sqrtPriceX96 != 0), AND has non-zero
    current liquidity(). A pool contract can exist for a fee tier with
    nobody having added liquidity, or with a price set but an empty tick
    structure -- both look "found" from the factory alone. Raises
    ValueError if nothing usable exists at any tier.
    """
    for fee in (3000, 500, 10000, 100):
        try:
            pool_address = _get_v3_pool_address(w3, token_a, token_b, fee)
        except ValueError:  # noqa: PERF203
            continue
        sqrt_price_x96, _tick = _get_v3_slot0(w3, pool_address)
        if sqrt_price_x96 == 0:
            continue
        if _get_v3_liquidity(w3, pool_address) == 0:
            continue
        return pool_address, fee
    raise ValueError(
        f"No usable Uniswap V3 pool (any fee tier) found between {token_a} and {token_b}"
    )


# Camelot V2 factory. Verify against
# https://docs.camelot.exchange/contracts/arbitrum before relying on it.
CAMELOT_V2_FACTORY = "0x6EccAb422D763aC031210895C81787E87b43A652"

_CAMELOT_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"},
        ],
        "name": "getPair",
        "outputs": [{"internalType": "address", "name": "pair", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# Camelot's modified UniswapV2 fork bakes per-token dynamic fees into
# getReserves() -- 4 return values instead of the standard 3.
_CAMELOT_GET_RESERVES_ABI = [
    {
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"internalType": "uint112", "name": "reserve0", "type": "uint112"},
            {"internalType": "uint112", "name": "reserve1", "type": "uint112"},
            {"internalType": "uint16", "name": "token0FeePercent", "type": "uint16"},
            {"internalType": "uint16", "name": "token1FeePercent", "type": "uint16"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

# Standard Uniswap V2 pair ABI (SushiSwap and most other V2 forks use
# this exact shape) -- 3 return values, NOT Camelot's 4. Using the
# wrong one causes eth_abi to fail decoding with NonEmptyPaddingBytes,
# confirmed against a real SushiSwap pool during development.
_STANDARD_GET_RESERVES_ABI = [
    {
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"internalType": "uint112", "name": "reserve0", "type": "uint112"},
            {"internalType": "uint112", "name": "reserve1", "type": "uint112"},
            {"internalType": "uint32", "name": "blockTimestampLast", "type": "uint32"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]


def _get_v2_pool_and_reserve_a(
    w3, factory_address: str, factory_abi: list, reserves_abi: list, token_a: str, token_b: str
) -> tuple[str, int]:
    """
    Resolve a UniswapV2-style pool address and return (address,
    reserve_of_token_a). Raises ValueError if no pool exists or it has
    empty reserves. Returning token_a's own reserve (not token_b's, and
    not some derived USD value) keeps the comparison in find_any_pool()
    valid across different token decimals: for a given (token_a,
    token_b) query, every candidate DEX's reserve of the *same* token_a
    is directly comparable, no price oracle needed.
    """
    factory = w3.eth.contract(address=w3.to_checksum_address(factory_address), abi=factory_abi)
    pool_address = factory.functions.getPair(
        w3.to_checksum_address(token_a),
        w3.to_checksum_address(token_b),
    ).call()
    if int(pool_address, 16) == 0:
        raise ValueError(f"No pool deployed between {token_a} and {token_b}")

    pool = w3.eth.contract(address=w3.to_checksum_address(pool_address), abi=reserves_abi)
    reserve0, reserve1, *_ = pool.functions.getReserves().call()
    if reserve0 == 0 or reserve1 == 0:
        raise ValueError(f"Pool {pool_address} exists but has empty reserves")

    token0 = pool_token0(w3, pool_address)
    reserve_a = reserve0 if token0.lower() == token_a.lower() else reserve1
    return pool_address, reserve_a


_TOKEN0_ABI = [
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]


def pool_token0(w3, pool_address: str) -> str:
    pool = w3.eth.contract(address=w3.to_checksum_address(pool_address), abi=_TOKEN0_ABI)
    return pool.functions.token0().call()


def find_camelot_v2_pool_address(w3, token_a: str, token_b: str) -> tuple[str, int]:
    """Resolve a Camelot V2 pool and verify it actually has reserves. Returns (address, reserve_a)."""
    return _get_v2_pool_and_reserve_a(
        w3, CAMELOT_V2_FACTORY, _CAMELOT_FACTORY_ABI, _CAMELOT_GET_RESERVES_ABI, token_a, token_b
    )


# SushiSwap V2 factory: same address across Ethereum, Arbitrum, Polygon
# (deterministic deployer, like Uniswap V3's). MAGIC's most liquid pool
# was found here during research, not on Camelot/Uniswap V3 -- worth
# checking for any non-tier-1 pair, not just MAGIC specifically.
SUSHISWAP_V2_FACTORY = "0xc35DADB65012eC5796536bD9864eD8773aBc74C4"

_SUSHISWAP_FACTORY_ABI = _CAMELOT_FACTORY_ABI  # identical getPair(tokenA, tokenB) shape


def find_sushiswap_v2_pool_address(w3, token_a: str, token_b: str) -> tuple[str, int]:
    """Resolve a SushiSwap V2 pool and verify it actually has reserves. Returns (address, reserve_a)."""
    return _get_v2_pool_and_reserve_a(
        w3, SUSHISWAP_V2_FACTORY, _SUSHISWAP_FACTORY_ABI, _STANDARD_GET_RESERVES_ABI, token_a, token_b
    )


def find_any_pool(w3, token_a: str, token_b: str) -> tuple[str, str, int | None, int | None]:
    """
    Check Camelot V2 and SushiSwap V2 for this pair and, if both exist,
    return whichever has the DEEPER reserve of token_a -- not just
    whichever DEX happens to be checked first. Confirmed necessary
    against a real case: Camelot had a near-empty MAGIC/WETH pool
    (dust-level reserves) while a genuinely liquid one existed on
    SushiSwap, and picking "first found" silently returned the dead one.
    Falls back to Uniswap V3 only if neither V2-style DEX has anything
    (V3's liquidity() isn't directly comparable to V2 reserves, so it's
    kept as a separate last resort rather than compared numerically).

    Returns (dex, pool_address, fee, reserve_a): dex is "camelot_v2" /
    "sushiswap_v2" (fee is None) or "uniswap_v3" (fee is the tier used,
    reserve_a is None since V3 doesn't expose a directly comparable
    reserve figure). reserve_a is the winning pool's raw reserve of
    token_a -- print it before trusting a result; a pool can pass the
    "non-zero" check while still holding dust-level liquidity.
    Raises ValueError if nothing usable exists anywhere -- the expected
    outcome for most combinations of non-tier-1 tokens, since most
    pools route through WETH rather than pairing two mid-caps directly.
    """
    v2_candidates: list[tuple[str, str, int]] = []  # (dex, address, reserve_a)
    try:
        address, reserve_a = find_camelot_v2_pool_address(w3, token_a, token_b)
        v2_candidates.append(("camelot_v2", address, reserve_a))
    except ValueError:
        pass
    try:
        address, reserve_a = find_sushiswap_v2_pool_address(w3, token_a, token_b)
        v2_candidates.append(("sushiswap_v2", address, reserve_a))
    except ValueError:
        pass

    if v2_candidates:
        dex, address, reserve_a = max(v2_candidates, key=lambda c: c[2])
        return dex, address, None, reserve_a

    try:
        address, fee = find_v3_pool_address(w3, token_a, token_b)
        return "uniswap_v3", address, fee, None
    except ValueError:
        pass
    raise ValueError(
        f"No usable pool (Camelot V2, SushiSwap V2, or Uniswap V3) found "
        f"between {token_a} and {token_b}"
    )

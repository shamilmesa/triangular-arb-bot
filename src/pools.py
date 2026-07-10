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

# Mid-cap Arbitrum-native DeFi tokens worth checking for the third leg
# of a triangular cycle, but NOT hardcoded here since their addresses
# weren't independently verified during development -- look them up on
# Arbiscan/CoinGecko yourself and pass via CLI before use:
#   MAGIC (Treasure DAO), RDNT (Radiant Capital), DPX (Dopex)

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

_GET_RESERVES_ABI = [
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


def find_camelot_v2_pool_address(w3, token_a: str, token_b: str) -> str:
    """Resolve a Camelot V2 pool address and verify it actually has reserves."""
    factory = w3.eth.contract(
        address=w3.to_checksum_address(CAMELOT_V2_FACTORY), abi=_CAMELOT_FACTORY_ABI
    )
    pool_address = factory.functions.getPair(
        w3.to_checksum_address(token_a),
        w3.to_checksum_address(token_b),
    ).call()
    if int(pool_address, 16) == 0:
        raise ValueError(f"No Camelot V2 pool deployed between {token_a} and {token_b}")

    pool = w3.eth.contract(address=w3.to_checksum_address(pool_address), abi=_GET_RESERVES_ABI)
    reserve0, reserve1, *_ = pool.functions.getReserves().call()
    if reserve0 == 0 or reserve1 == 0:
        raise ValueError(f"Camelot V2 pool {pool_address} exists but has empty reserves")
    return pool_address


def find_any_pool(w3, token_a: str, token_b: str) -> tuple[str, str, int | None]:
    """
    Try Camelot V2 first (single check, no fee-tier search needed), then
    Uniswap V3. Returns (dex, pool_address, fee) where dex is
    "camelot_v2" (fee is None) or "uniswap_v3" (fee is the tier used).
    Raises ValueError if neither DEX has a usable pool for this pair --
    which is the expected outcome for most combinations of non-tier-1
    tokens, since most pools route through WETH rather than pairing two
    mid-caps directly. Verify a direct pair actually exists (check both
    DEXs' UIs) before assuming this will succeed.
    """
    try:
        return "camelot_v2", find_camelot_v2_pool_address(w3, token_a, token_b), None
    except ValueError:
        pass
    try:
        address, fee = find_v3_pool_address(w3, token_a, token_b)
        return "uniswap_v3", address, fee
    except ValueError:
        pass
    raise ValueError(
        f"No usable pool (Camelot V2 or Uniswap V3) found between {token_a} and {token_b}"
    )

"""Build shareable OptionStrat strategy URLs from option legs.

OptionStrat's builder loads a full strategy from the URL path::

    https://optionstrat.com/build/{strategy}/{UNDERLYING}/{leg,leg,...}

Each leg is a compact OCC-style token::

    [-].{ROOT}{YYMMDD}{C|P}{STRIKE}[x{RATIO}]

* leading ``-`` — a short (sold) leg; absent for long
* ``.`` — marks an option leg (a bare token would be a share leg)
* ``STRIKE`` — plain decimal, no zero-padding (``650``, ``222.5``)
* ``x{RATIO}`` — only when the leg quantity differs from 1

Example (iron condor)::

    https://optionstrat.com/build/iron-condor/SPY/.SPY260807P610,-.SPY260807P620,-.SPY260807C650,.SPY260807C660

The format is the community-established one that OptionStrat's own builder
emits into the address bar (there is no official URL API documentation) —
verified against the live site 2026-07-06. ``base_url`` and ``strategy`` are
parameters so a format drift is a call-site fix, not a code change.

Index weeklies trade under a different option root than the underlying
OptionStrat indexes them by (``SPXW`` options on the ``SPX`` page):
``build_url`` derives the page underlying through ``DISPLAY_UNDERLYING``
unless the caller passes one explicitly.

Futures options use a different token shape (verified against a live builder
URL 2026-07-07). The underlying is a *dated* futures contract and every ``/``
is percent-encoded, because OptionStrat prefixes futures symbols with a slash::

    https://optionstrat.com/build/iron-condor/%2FESU26/.%2FE3DN26P7495,-.%2FE3DN26P7520,...

    %2FESU26          the page underlying — /ES September 2026 future
    .%2FE3DN26P7495   ``.`` option marker, then /{PRODUCT}{M}{YY}{C|P}{STRIKE}

where ``PRODUCT`` is the CME option product code (``E3D``, ``EW4``, ``ES``
for the quarterlies ...), ``M`` a futures month code, and ``YY`` a 2-digit
year — no 6-digit expiry date like equity legs (the site resolves the exact
expiration from the chain). The product code is CME taxonomy that cannot be
computed from (future, expiry, right, strike), so :class:`FuturesOptionLeg`
requires it; :func:`from_order_symbol` extracts everything from a TastyTrade
futures-option order symbol (``./ESU6 E1CN6 260701C6325``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable, Literal, Mapping, cast
from urllib.parse import quote

__all__ = [
    "OptionLeg",
    "FuturesOptionLeg",
    "build_url",
    "encode_leg",
    "from_security_id",
    "from_order_symbol",
    "from_resolved_structure",
    "DISPLAY_UNDERLYING",
    "MONTH_CODES",
]

_BASE_URL = "https://optionstrat.com/build"

# Option roots whose OptionStrat page lives under the parent index symbol.
DISPLAY_UNDERLYING: Mapping[str, str] = {
    "SPXW": "SPX",
    "VIXW": "VIX",
    "RUTW": "RUT",
    "NDXP": "NDX",
    "XSPW": "XSP",
}

Side = Literal["long", "short"]
OptionTypeName = Literal["call", "put"]

# CME futures month codes, January..December.
MONTH_CODES = "FGHJKMNQUVXZ"

# Dated futures contract, with or without the leading (order-symbol) "./" or
# display "/": "ESU26", "/ESU26", "./MESU5". Non-greedy root + the digits-only
# year is what disambiguates roots that end in a month letter (ZN -> ZNH26).
_FUTURE_CONTRACT_RE = re.compile(
    rf"^(?:\.?/)?(?P<root>[A-Z0-9]{{1,4}}?)(?P<month>[{MONTH_CODES}])(?P<year>\d{{1,2}})$"
)

# Option series token as it appears in order symbols: product + month + year
# ("E1CN6", "EW4N26", "EXQ5", quarterly "ESU6").
_SERIES_RE = re.compile(
    rf"^(?P<product>[A-Z0-9]+?)(?P<month>[{MONTH_CODES}])(?P<year>\d{{1,2}})$"
)

# TastyTrade futures-option order symbol head/tail (mirrors security-universe's
# parser, including the packed 3-char-root form "./MESU5EXQ5  250829P6430").
_TT_HEAD_RE = re.compile(
    rf"^\./(?P<future>[A-Z0-9]{{1,4}}[{MONTH_CODES}]\d{{1,2}})\s*(?P<rest>\S.*)$"
)
_TT_TAIL_RE = re.compile(r"(?P<yymmdd>\d{6})(?P<cp>[CP])(?P<strike>\d+(?:\.\d+)?)$")


@dataclass(frozen=True)
class OptionLeg:
    """One option leg, in the terms OptionStrat needs — nothing more."""

    root: str  # option root as it trades (SPXW, SPY, IWM ...)
    expiry: date
    option_type: OptionTypeName
    strike: Decimal
    side: Side = "long"
    ratio: int = 1

    def __post_init__(self) -> None:
        if self.option_type not in ("call", "put"):
            raise ValueError(f"option_type must be 'call' or 'put', got {self.option_type!r}")
        if self.side not in ("long", "short"):
            raise ValueError(f"side must be 'long' or 'short', got {self.side!r}")
        if self.ratio < 1:
            raise ValueError(f"ratio must be >= 1, got {self.ratio}")


@dataclass(frozen=True)
class FuturesOptionLeg:
    """One option-on-futures leg, in the terms OptionStrat's URL needs.

    ``year`` is the option series' contract year, 4-digit or 2-digit (both
    encode as 2 digits). It is a separate field rather than derived from an
    expiry because serial options expire the month *before* their contract
    month (an ``OGN6`` gold option expires in late June).
    """

    product_code: str  # CME option product code as it trades (E3D, EW4, ES ...)
    month_code: str  # option series contract month, one of MONTH_CODES
    year: int  # option series contract year (2026 or 26)
    option_type: OptionTypeName
    strike: Decimal
    future: str  # dated underlying contract: "ESU26" (also "ESU6", "/ESU26")
    side: Side = "long"
    ratio: int = 1

    def __post_init__(self) -> None:
        if self.month_code.upper() not in MONTH_CODES:
            raise ValueError(f"month_code must be one of {MONTH_CODES}, got {self.month_code!r}")
        if not (0 <= self.year <= 99 or 2000 <= self.year <= 2099):
            raise ValueError(f"year must be 2-digit or 20xx, got {self.year}")
        if self.option_type not in ("call", "put"):
            raise ValueError(f"option_type must be 'call' or 'put', got {self.option_type!r}")
        if self.side not in ("long", "short"):
            raise ValueError(f"side must be 'long' or 'short', got {self.side!r}")
        if self.ratio < 1:
            raise ValueError(f"ratio must be >= 1, got {self.ratio}")
        if not _FUTURE_CONTRACT_RE.match(self.future.upper()):
            raise ValueError(f"future must be a dated contract like 'ESU26', got {self.future!r}")

    @property
    def underlying(self) -> str:
        """The OptionStrat page underlying: ``/ESU26`` (2-digit year)."""
        m = _FUTURE_CONTRACT_RE.match(self.future.upper())
        assert m is not None  # __post_init__ validated
        yy = _expand_year(m.group("year"), base=self.year % 100)
        return f"/{m.group('root')}{m.group('month')}{yy:02d}"


def _expand_year(digits: str, *, base: int) -> int:
    """A 1-digit contract year to the first matching 2-digit year >= ``base``."""
    if len(digits) == 2:
        return int(digits)
    yy = base - base % 10 + int(digits)
    return yy + 10 if yy < base else yy


def _strike_str(strike: Decimal) -> str:
    """``650.00`` -> ``650``; ``222.50`` -> ``222.5`` (no exponent, no padding)."""
    text = format(strike.normalize(), "f")
    return text[:-2] if text.endswith(".0") else text


def encode_leg(leg: OptionLeg | FuturesOptionLeg) -> str:
    """The leg token exactly as it appears in the URL path.

    Equity/index tokens contain no reserved characters; futures tokens carry
    the slash of the futures symbol percent-encoded (``.%2FE3DN26P7495``),
    matching what OptionStrat's own encoder emits.
    """
    sign = "-" if leg.side == "short" else ""
    cp = "C" if leg.option_type == "call" else "P"
    ratio = f"x{leg.ratio}" if leg.ratio != 1 else ""
    if isinstance(leg, FuturesOptionLeg):
        series = f"{leg.product_code.upper()}{leg.month_code.upper()}{leg.year % 100:02d}"
        symbol = f"./{series}{cp}{_strike_str(leg.strike)}"
    else:
        yymmdd = leg.expiry.strftime("%y%m%d")
        symbol = f".{leg.root.upper()}{yymmdd}{cp}{_strike_str(leg.strike)}"
    return f"{sign}{quote(symbol, safe='.')}{ratio}"


def build_url(
    legs: Iterable[OptionLeg | FuturesOptionLeg],
    *,
    underlying: str | None = None,
    strategy: str = "custom",
    base_url: str = _BASE_URL,
) -> str:
    """The shareable OptionStrat URL for ``legs``.

    ``strategy`` is the page slug — ``custom`` renders any leg set; passing a
    known slug (``iron-condor``, ``vertical-spread`` ...) only changes which
    template the builder opens with. ``underlying`` defaults to the first
    leg's root mapped through ``DISPLAY_UNDERLYING`` — or, for a futures leg,
    its dated contract (``/ESU26``). Pass ``/``-prefixed futures underlyings
    un-encoded; the slash is percent-encoded here.
    """
    leg_list = list(legs)
    if not leg_list:
        raise ValueError("at least one leg is required")
    if underlying is None:
        first = leg_list[0]
        if isinstance(first, FuturesOptionLeg):
            underlying = first.underlying
        else:
            root = first.root.upper()
            underlying = DISPLAY_UNDERLYING.get(root, root)
    tokens = ",".join(encode_leg(leg) for leg in leg_list)
    return f"{base_url}/{strategy}/{quote(underlying.upper(), safe='')}/{tokens}"


def from_security_id(security_id: str, *, side: Side = "long", ratio: int = 1) -> OptionLeg:
    """An ``OptionLeg`` from a zts/tt-ledger canonical option security_id::

        option:SPXW:2026-07-06:call:7540  ->  .SPXW260706C7540

    Only ``option:*`` ids resolve. Futures options (``future_option:*``) are
    rejected because the id omits the CME option product code the OptionStrat
    token needs — use :func:`from_order_symbol` or a :class:`FuturesOptionLeg`.
    """
    parts = security_id.split(":")
    if len(parts) != 5 or parts[0] != "option":
        raise ValueError(
            f"not an option security_id (want option:ROOT:YYYY-MM-DD:call|put:STRIKE): {security_id!r}"
        )
    _, root, expiry_str, option_type, strike_str = parts
    if option_type not in ("call", "put"):
        raise ValueError(f"bad option_type {option_type!r} in {security_id!r}")
    try:
        expiry = date.fromisoformat(expiry_str)
        strike = Decimal(strike_str)
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(f"unparseable expiry/strike in {security_id!r}") from exc
    return OptionLeg(
        root=root,
        expiry=expiry,
        option_type=cast(OptionTypeName, option_type),
        strike=strike,
        side=side,
        ratio=ratio,
    )


def from_order_symbol(symbol: str, *, side: Side = "long", ratio: int = 1) -> FuturesOptionLeg:
    """A ``FuturesOptionLeg`` from a TastyTrade futures-option order symbol::

        ./ESU6 E1CN6 260701C6325   ->  .%2FE1CN26C6325 on the %2FESU26 page

    Both the space-separated and the packed 3-char-root form
    (``./MESU5EXQ5  250829P6430``) parse, same as security-universe's
    resolver. A quarterly symbol that omits the series block reuses the
    future contract as the option series (``ES`` quarterlies).

    1-digit contract years are expanded against the option's expiry year:
    the series year is the first match >= the expiry year (a serial option's
    contract month can fall in the year after its expiry), and the future's
    year the first match >= the series year.
    """
    head = _TT_HEAD_RE.match(symbol.strip().upper())
    if not head:
        raise ValueError(f"not a futures-option order symbol: {symbol!r}")
    rest = head.group("rest")
    tail = _TT_TAIL_RE.search(rest)
    if not tail:
        raise ValueError(f"no expiry/strike block in futures-option symbol: {symbol!r}")
    series_token = rest[: tail.start()].strip() or head.group("future")
    series = _SERIES_RE.match(series_token)
    if not series:
        raise ValueError(f"unparseable option series {series_token!r} in {symbol!r}")

    expiry_yy = int(tail.group("yymmdd")[:2])
    series_yy = _expand_year(series.group("year"), base=expiry_yy)
    future_m = _FUTURE_CONTRACT_RE.match(head.group("future"))
    assert future_m is not None  # _TT_HEAD_RE is stricter than _FUTURE_CONTRACT_RE
    future_yy = _expand_year(future_m.group("year"), base=series_yy)

    return FuturesOptionLeg(
        product_code=series.group("product"),
        month_code=series.group("month"),
        year=series_yy,
        option_type="call" if tail.group("cp") == "C" else "put",
        strike=Decimal(tail.group("strike")),
        future=f"{future_m.group('root')}{future_m.group('month')}{future_yy:02d}",
        side=side,
        ratio=ratio,
    )


def _option_type_name(value) -> OptionTypeName:  # noqa: ANN001 -- str or enum
    name = getattr(value, "value", value)
    name = str(name).lower()
    if name in ("c", "call"):
        return "call"
    if name in ("p", "put"):
        return "put"
    raise ValueError(f"unrecognized option type {value!r}")


def from_resolved_structure(resolution) -> list[OptionLeg | FuturesOptionLeg]:  # noqa: ANN001
    """Legs from a contract-resolver result, ready for :func:`build_url`.

    Accepts either a ``StructureResolution`` (uses ``.resolved``, raising if
    the resolution failed) or a ``ResolvedStructure`` directly. Duck-typed on
    the resolver's shapes — ``.legs`` (role -> resolved leg carrying a
    ``security-universe`` ``Security``) and ``.structure.legs`` (role -> the
    description carrying ``side``/``ratio``) — so contract-resolver is not an
    import-time dependency.

    A security whose ``order_symbol`` is a futures-option symbol (``./ESU6
    E1CN6 260701C6325``) becomes a :class:`FuturesOptionLeg`; a futures option
    *without* one is rejected, since the CME product code only lives there.
    """
    if hasattr(resolution, "resolved"):  # StructureResolution
        if not getattr(resolution, "ok", True) or resolution.resolved is None:
            failures = getattr(resolution, "failures", ())
            raise ValueError(f"structure did not resolve: {failures!r}")
        resolution = resolution.resolved

    descriptions = resolution.structure.legs
    legs: list[OptionLeg | FuturesOptionLeg] = []
    for role, resolved_leg in resolution.legs.items():
        sec = resolved_leg.security
        desc = descriptions[role]
        ratio = getattr(desc, "ratio", 1)
        order_symbol = getattr(sec, "order_symbol", None)
        if order_symbol is not None and order_symbol.startswith("./"):
            legs.append(from_order_symbol(order_symbol, side=desc.side, ratio=ratio))
            continue
        sec_type = getattr(getattr(sec, "security_type", None), "value", None) or getattr(
            sec, "security_type", None
        )
        if sec_type == "future_option":
            raise ValueError(
                f"leg {role!r} is a futures option without an order_symbol; the CME "
                f"product code OptionStrat needs is only carried there: {sec!r}"
            )
        root = sec.option_root or sec.root_symbol or sec.underlying
        if root is None or sec.expiry is None or sec.strike is None or sec.option_type is None:
            raise ValueError(f"leg {role!r} security is missing option identity fields: {sec!r}")
        legs.append(
            OptionLeg(
                root=root,
                expiry=sec.expiry,
                option_type=_option_type_name(sec.option_type),
                strike=Decimal(str(sec.strike)),
                side=desc.side,
                ratio=ratio,
            )
        )
    return legs

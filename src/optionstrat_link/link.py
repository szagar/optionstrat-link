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
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable, Literal, Mapping, cast

__all__ = [
    "OptionLeg",
    "build_url",
    "encode_leg",
    "from_security_id",
    "from_resolved_structure",
    "DISPLAY_UNDERLYING",
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


def _strike_str(strike: Decimal) -> str:
    """``650.00`` -> ``650``; ``222.50`` -> ``222.5`` (no exponent, no padding)."""
    text = format(strike.normalize(), "f")
    return text[:-2] if text.endswith(".0") else text


def encode_leg(leg: OptionLeg) -> str:
    sign = "-" if leg.side == "short" else ""
    yymmdd = leg.expiry.strftime("%y%m%d")
    cp = "C" if leg.option_type == "call" else "P"
    ratio = f"x{leg.ratio}" if leg.ratio != 1 else ""
    return f"{sign}.{leg.root.upper()}{yymmdd}{cp}{_strike_str(leg.strike)}{ratio}"


def build_url(
    legs: Iterable[OptionLeg],
    *,
    underlying: str | None = None,
    strategy: str = "custom",
    base_url: str = _BASE_URL,
) -> str:
    """The shareable OptionStrat URL for ``legs``.

    ``strategy`` is the page slug — ``custom`` renders any leg set; passing a
    known slug (``iron-condor``, ``vertical-spread`` ...) only changes which
    template the builder opens with. ``underlying`` defaults to the first
    leg's root mapped through ``DISPLAY_UNDERLYING``.
    """
    leg_list = list(legs)
    if not leg_list:
        raise ValueError("at least one leg is required")
    if underlying is None:
        root = leg_list[0].root.upper()
        underlying = DISPLAY_UNDERLYING.get(root, root)
    tokens = ",".join(encode_leg(leg) for leg in leg_list)
    return f"{base_url}/{strategy}/{underlying.upper()}/{tokens}"


def from_security_id(security_id: str, *, side: Side = "long", ratio: int = 1) -> OptionLeg:
    """An ``OptionLeg`` from a zts/tt-ledger canonical option security_id::

        option:SPXW:2026-07-06:call:7540  ->  .SPXW260706C7540

    Only ``option:*`` ids resolve — futures options (``future_option:*``)
    trade in OptionStrat under different symbology and are rejected loudly
    rather than guessed at.
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


def _option_type_name(value) -> OptionTypeName:  # noqa: ANN001 -- str or enum
    name = getattr(value, "value", value)
    name = str(name).lower()
    if name in ("c", "call"):
        return "call"
    if name in ("p", "put"):
        return "put"
    raise ValueError(f"unrecognized option type {value!r}")


def from_resolved_structure(resolution) -> list[OptionLeg]:  # noqa: ANN001
    """Legs from a contract-resolver result, ready for :func:`build_url`.

    Accepts either a ``StructureResolution`` (uses ``.resolved``, raising if
    the resolution failed) or a ``ResolvedStructure`` directly. Duck-typed on
    the resolver's shapes — ``.legs`` (role -> resolved leg carrying a
    ``security-universe`` ``Security``) and ``.structure.legs`` (role -> the
    description carrying ``side``/``ratio``) — so contract-resolver is not an
    import-time dependency.
    """
    if hasattr(resolution, "resolved"):  # StructureResolution
        if not getattr(resolution, "ok", True) or resolution.resolved is None:
            failures = getattr(resolution, "failures", ())
            raise ValueError(f"structure did not resolve: {failures!r}")
        resolution = resolution.resolved

    descriptions = resolution.structure.legs
    legs: list[OptionLeg] = []
    for role, resolved_leg in resolution.legs.items():
        sec = resolved_leg.security
        root = sec.option_root or sec.root_symbol or sec.underlying
        if root is None or sec.expiry is None or sec.strike is None or sec.option_type is None:
            raise ValueError(f"leg {role!r} security is missing option identity fields: {sec!r}")
        desc = descriptions[role]
        legs.append(
            OptionLeg(
                root=root,
                expiry=sec.expiry,
                option_type=_option_type_name(sec.option_type),
                strike=Decimal(str(sec.strike)),
                side=desc.side,
                ratio=getattr(desc, "ratio", 1),
            )
        )
    return legs

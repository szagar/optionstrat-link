"""URL encoding, security_id parsing, and the duck-typed resolver adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pytest

from optionstrat_link import (
    FuturesOptionLeg,
    OptionLeg,
    build_url,
    encode_leg,
    from_order_symbol,
    from_resolved_structure,
    from_security_id,
)

D = Decimal
EXP = date(2026, 8, 7)


# --- encode_leg ---------------------------------------------------------------


def test_long_call() -> None:
    leg = OptionLeg("SPY", EXP, "call", D("650"))
    assert encode_leg(leg) == ".SPY260807C650"


def test_short_put_with_fractional_strike() -> None:
    leg = OptionLeg("IWM", EXP, "put", D("222.50"), side="short")
    assert encode_leg(leg) == "-.IWM260807P222.5"


def test_whole_strike_never_shows_decimals() -> None:
    assert encode_leg(OptionLeg("SPY", EXP, "call", D("650.00"))) == ".SPY260807C650"


def test_ratio_suffix_only_when_not_one() -> None:
    assert encode_leg(OptionLeg("SPY", EXP, "call", D("650"), ratio=2)).endswith("x2")
    assert "x1" not in encode_leg(OptionLeg("SPY", EXP, "call", D("650"), ratio=1))


def test_root_is_uppercased() -> None:
    assert encode_leg(OptionLeg("spy", EXP, "call", D("650"))) == ".SPY260807C650"


def test_invalid_fields_raise() -> None:
    with pytest.raises(ValueError):
        OptionLeg("SPY", EXP, "callx", D("650"))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OptionLeg("SPY", EXP, "call", D("650"), side="net")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OptionLeg("SPY", EXP, "call", D("650"), ratio=0)


# --- build_url ----------------------------------------------------------------


def test_iron_condor_url() -> None:
    legs = [
        OptionLeg("SPY", EXP, "put", D("610")),
        OptionLeg("SPY", EXP, "put", D("620"), side="short"),
        OptionLeg("SPY", EXP, "call", D("650"), side="short"),
        OptionLeg("SPY", EXP, "call", D("660")),
    ]
    assert build_url(legs, strategy="iron-condor") == (
        "https://optionstrat.com/build/iron-condor/SPY/"
        ".SPY260807P610,-.SPY260807P620,-.SPY260807C650,.SPY260807C660"
    )


def test_default_strategy_is_custom_and_underlying_derived() -> None:
    url = build_url([OptionLeg("SPY", EXP, "call", D("650"))])
    assert url.startswith("https://optionstrat.com/build/custom/SPY/")


def test_weekly_index_root_maps_to_parent_underlying() -> None:
    url = build_url([OptionLeg("SPXW", date(2026, 7, 7), "call", D("7540"), side="short")])
    assert "/custom/SPX/" in url
    assert "-.SPXW260707C7540" in url  # leg keeps the tradable root


def test_explicit_underlying_wins() -> None:
    url = build_url([OptionLeg("SPXW", EXP, "call", D("7540"))], underlying="spx")
    assert "/custom/SPX/" in url


def test_empty_legs_raise() -> None:
    with pytest.raises(ValueError):
        build_url([])


# --- futures options ------------------------------------------------------------


def _es_leg(t: str, k: str, side: str = "long") -> FuturesOptionLeg:
    return FuturesOptionLeg("E3D", "N", 2026, t, D(k), "ESU26", side=side)  # type: ignore[arg-type]


def test_futures_iron_condor_matches_live_builder_url() -> None:
    # Captured from OptionStrat's own builder 2026-07-07.
    legs = [
        _es_leg("put", "7495"),
        _es_leg("put", "7520", side="short"),
        _es_leg("call", "7570", side="short"),
        _es_leg("call", "7595"),
    ]
    assert build_url(legs, strategy="iron-condor") == (
        "https://optionstrat.com/build/iron-condor/%2FESU26/"
        ".%2FE3DN26P7495,-.%2FE3DN26P7520,-.%2FE3DN26C7570,.%2FE3DN26C7595"
    )


def test_futures_leg_token_and_ratio() -> None:
    leg = FuturesOptionLeg("EW4", "N", 26, "call", D("6400"), "ESU6", side="short", ratio=2)
    assert encode_leg(leg) == "-.%2FEW4N26C6400x2"


def test_futures_underlying_expands_one_digit_year() -> None:
    leg = FuturesOptionLeg("E1C", "N", 2026, "call", D("6325"), "ESU6")
    assert leg.underlying == "/ESU26"
    # December series, January future: the future's year rolls forward.
    dec = FuturesOptionLeg("E1C", "Z", 2029, "put", D("6000"), "ESH0")
    assert dec.underlying == "/ESH30"


def test_explicit_futures_underlying_is_percent_encoded() -> None:
    url = build_url([_es_leg("call", "7570")], underlying="/ESU26")
    assert "/custom/%2FESU26/" in url


def test_futures_leg_validation() -> None:
    with pytest.raises(ValueError, match="month_code"):
        FuturesOptionLeg("E3D", "A", 26, "call", D("1"), "ESU26")
    with pytest.raises(ValueError, match="year"):
        FuturesOptionLeg("E3D", "N", 1926, "call", D("1"), "ESU26")
    with pytest.raises(ValueError, match="dated contract"):
        FuturesOptionLeg("E3D", "N", 26, "call", D("1"), "ES")


# --- from_order_symbol -----------------------------------------------------------


def test_order_symbol_space_separated() -> None:
    leg = from_order_symbol("./ESU6 E1CN6 260701C6325", side="short")
    assert leg == FuturesOptionLeg("E1C", "N", 26, "call", D("6325"), "ESU26", side="short")
    assert encode_leg(leg) == "-.%2FE1CN26C6325"
    assert leg.underlying == "/ESU26"


def test_order_symbol_packed_head() -> None:
    leg = from_order_symbol("./MESU5EXQ5  250829P6430")
    assert leg.product_code == "EX"
    assert leg.underlying == "/MESU25"
    assert encode_leg(leg) == ".%2FEXQ25P6430"


def test_order_symbol_quarterly_without_series_block() -> None:
    leg = from_order_symbol("./ESU6 260918C6400")
    assert leg.product_code == "ES"
    assert encode_leg(leg) == ".%2FESU26C6400"


def test_order_symbol_serial_year_rollover() -> None:
    # January-serial option expiring late December: series year > expiry year.
    leg = from_order_symbol("./GCG0 OGF0 291226C2900")
    assert leg.year == 30
    assert leg.underlying == "/GCG30"


def test_bad_order_symbols_raise() -> None:
    for bad in ("ESU6 E1CN6 260701C6325", "./ESU6 E1CN6", "./ESU6 12345 260701C6325"):
        with pytest.raises(ValueError):
            from_order_symbol(bad)


# --- from_security_id ----------------------------------------------------------


def test_security_id_round_trip() -> None:
    leg = from_security_id("option:SPXW:2026-07-06:call:7540", side="short")
    assert encode_leg(leg) == "-.SPXW260706C7540"


def test_security_id_fractional_strike() -> None:
    leg = from_security_id("option:XSP:2026-07-06:put:622.5")
    assert encode_leg(leg) == ".XSP260706P622.5"


@pytest.mark.parametrize(
    "bad",
    [
        "equity:SPY",
        "future_option:ES:U6:2026-08-15:put:6100",
        "option:SPY:2026-08-07:strangle:650",
        "option:SPY:not-a-date:call:650",
        "option:SPY:2026-08-07:call:six-fifty",
    ],
)
def test_non_option_or_malformed_ids_raise(bad: str) -> None:
    with pytest.raises(ValueError):
        from_security_id(bad)


# --- from_resolved_structure (duck-typed contract-resolver shapes) --------------


@dataclass(frozen=True)
class _Security:
    option_root: str | None
    expiry: date | None
    strike: Decimal | None
    option_type: str | None
    root_symbol: str | None = None
    underlying: str | None = None
    order_symbol: str | None = None
    security_type: str | None = None


@dataclass(frozen=True)
class _ResolvedLeg:
    security: _Security


@dataclass(frozen=True)
class _LegDescription:
    side: str
    ratio: int = 1


@dataclass(frozen=True)
class _OptionStructure:
    legs: dict


@dataclass(frozen=True)
class _ResolvedStructure:
    legs: dict
    structure: _OptionStructure


@dataclass(frozen=True)
class _StructureResolution:
    ok: bool
    resolved: _ResolvedStructure | None
    failures: tuple = field(default_factory=tuple)


def _condor() -> _ResolvedStructure:
    def sec(t: str, k: str) -> _Security:
        return _Security("SPXW", date(2026, 7, 7), D(k), t)

    return _ResolvedStructure(
        legs={
            "long_put": _ResolvedLeg(sec("put", "7400")),
            "short_put": _ResolvedLeg(sec("put", "7425")),
            "short_call": _ResolvedLeg(sec("call", "7600")),
            "long_call": _ResolvedLeg(sec("call", "7625")),
        },
        structure=_OptionStructure(
            legs={
                "long_put": _LegDescription("long"),
                "short_put": _LegDescription("short"),
                "short_call": _LegDescription("short"),
                "long_call": _LegDescription("long"),
            }
        ),
    )


def test_resolved_structure_to_url() -> None:
    legs = from_resolved_structure(_condor())
    url = build_url(legs)
    assert url == (
        "https://optionstrat.com/build/custom/SPX/"
        ".SPXW260707P7400,-.SPXW260707P7425,-.SPXW260707C7600,.SPXW260707C7625"
    )


def test_structure_resolution_wrapper_unwraps() -> None:
    resolution = _StructureResolution(ok=True, resolved=_condor())
    assert len(from_resolved_structure(resolution)) == 4


def test_failed_resolution_raises() -> None:
    resolution = _StructureResolution(ok=False, resolved=None, failures=("no strike",))
    with pytest.raises(ValueError, match="did not resolve"):
        from_resolved_structure(resolution)


def test_enum_like_option_type_and_c_p_spellings() -> None:
    class _Enum:
        value = "C"

    s = _ResolvedStructure(
        legs={"leg": _ResolvedLeg(_Security("SPY", EXP, D("650"), _Enum()))},
        structure=_OptionStructure(legs={"leg": _LegDescription("long")}),
    )
    (leg,) = from_resolved_structure(s)
    assert leg.option_type == "call"


def test_resolved_futures_option_uses_order_symbol() -> None:
    sec = _Security(
        "E1CN6",
        date(2026, 7, 1),
        D("6325"),
        "call",
        order_symbol="./ESU6 E1CN6 260701C6325",
        security_type="future_option",
    )
    s = _ResolvedStructure(
        legs={"leg": _ResolvedLeg(sec)},
        structure=_OptionStructure(legs={"leg": _LegDescription("short")}),
    )
    (leg,) = from_resolved_structure(s)
    assert isinstance(leg, FuturesOptionLeg)
    assert build_url([leg]).endswith("/custom/%2FESU26/-.%2FE1CN26C6325")


def test_resolved_futures_option_without_order_symbol_raises() -> None:
    sec = _Security("E1CN6", date(2026, 7, 1), D("6325"), "call", security_type="future_option")
    s = _ResolvedStructure(
        legs={"leg": _ResolvedLeg(sec)},
        structure=_OptionStructure(legs={"leg": _LegDescription("long")}),
    )
    with pytest.raises(ValueError, match="without an order_symbol"):
        from_resolved_structure(s)


def test_missing_identity_fields_raise() -> None:
    s = _ResolvedStructure(
        legs={"leg": _ResolvedLeg(_Security("SPY", None, D("650"), "call"))},
        structure=_OptionStructure(legs={"leg": _LegDescription("long")}),
    )
    with pytest.raises(ValueError, match="missing option identity"):
        from_resolved_structure(s)

"""URL encoding, security_id parsing, and the duck-typed resolver adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pytest

from optionstrat_link import (
    OptionLeg,
    build_url,
    encode_leg,
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


def test_missing_identity_fields_raise() -> None:
    s = _ResolvedStructure(
        legs={"leg": _ResolvedLeg(_Security("SPY", None, D("650"), "call"))},
        structure=_OptionStructure(legs={"leg": _LegDescription("long")}),
    )
    with pytest.raises(ValueError, match="missing option identity"):
        from_resolved_structure(s)

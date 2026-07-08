# optionstrat-link

Turn option structures into **shareable [OptionStrat](https://optionstrat.com)
builder URLs** — one function call from a resolved structure (or a handful of
legs) to a link that opens the full strategy in OptionStrat's profit
calculator.

The core is **pure stdlib** (no dependencies). Two adapters feed it:

- [`contract-resolver`](../contract-resolver) structures — the *"30-delta
  call, 1 DTE"* wish, resolved to real contracts, straight to a link
  (duck-typed; contract-resolver is an optional extra, not a requirement).
- zts / [`tt-ledger`](../tt-ledger) canonical **security_ids**
  (`option:SPXW:2026-07-06:call:7540`) — link any ledger trade group's legs.

## Usage

### From legs

```python
from datetime import date
from decimal import Decimal

from optionstrat_link import OptionLeg, build_url

legs = [
    OptionLeg("SPY", date(2026, 8, 7), "put", Decimal("610")),
    OptionLeg("SPY", date(2026, 8, 7), "put", Decimal("620"), side="short"),
    OptionLeg("SPY", date(2026, 8, 7), "call", Decimal("650"), side="short"),
    OptionLeg("SPY", date(2026, 8, 7), "call", Decimal("660")),
]
build_url(legs, strategy="iron-condor")
# https://optionstrat.com/build/iron-condor/SPY/.SPY260807P610,-.SPY260807P620,-.SPY260807C650,.SPY260807C660
```

### From a contract-resolver structure

```python
from optionstrat_link import build_url, from_resolved_structure

resolution = structure_resolver.resolve(iron_condor_description)  # your resolver call
build_url(from_resolved_structure(resolution))
# https://optionstrat.com/build/custom/SPX/.SPXW260707P7400,-.SPXW260707P7425,...
```

`from_resolved_structure` accepts a `StructureResolution` (raises with the
failures if it didn't resolve) or a `ResolvedStructure` directly. Sides and
ratios come from the structure description; identity (root/expiry/strike/type)
from each leg's `security-universe` `Security`.

### From ledger security_ids

```python
from optionstrat_link import build_url, from_security_id

legs = [
    from_security_id("option:SPXW:2026-07-06:put:7500", side="short"),
    from_security_id("option:SPXW:2026-07-06:put:7475"),
]
build_url(legs)
# https://optionstrat.com/build/custom/SPX/-.SPXW260706P7500,.SPXW260706P7475
```

### From futures-option order symbols

Options on futures use a different token shape and can't come from a
`security_id` (which omits the CME option product code). Feed the TastyTrade
futures-option **order symbol** — `from_order_symbol` extracts the product
code, series, expiry, and strike:

```python
from optionstrat_link import build_url, from_order_symbol

legs = [
    from_order_symbol("./ESU6 E3DN6 260714P7495"),
    from_order_symbol("./ESU6 E3DN6 260714P7520", side="short"),
    from_order_symbol("./ESU6 E3DN6 260714C7570", side="short"),
    from_order_symbol("./ESU6 E3DN6 260714C7595"),
]
build_url(legs, strategy="iron-condor")
# https://optionstrat.com/build/iron-condor/%2FESU26/.%2FE3DN26P7495,-.%2FE3DN26P7520,-.%2FE3DN26C7570,.%2FE3DN26C7595

# A quarterly whose series block == the future contract (ES product code):
build_url([from_order_symbol("./ESU6 260918C6400")])
# https://optionstrat.com/build/custom/%2FESU26/.%2FESU26C6400
```

Or construct a `FuturesOptionLeg` directly if you already have the parts
(`FuturesOptionLeg("EW4", "N", 26, "call", Decimal("6400"), "ESU6",
side="short", ratio=2)` → `-.%2FEW4N26C6400x2`). `from_resolved_structure`
handles futures automatically when a leg's `Security` carries an
`order_symbol` (a futures option *without* one is rejected — the product code
only lives there).

## URL format notes

OptionStrat publishes no URL API; this encodes the format its own builder
writes to the address bar (`[-].{ROOT}{YYMMDD}{C|P}{STRIKE}[x{RATIO}][@{PRICE}]`,
comma-joined), verified against the live site 2026-07-06. `build_url` takes
`base_url`/`strategy` overrides so any future drift is a call-site fix.

Pass `entry_price=` on a leg (or to `from_security_id` / `from_order_symbol`) to
pin its cost basis — it renders as a trailing `@price`, *after* the ratio
(`-.SPY260918P600x2@9.99`), and OptionStrat marks P&L against it instead of the
live mid (verified against the live builder 2026-07-07). It's a per-contract
premium *magnitude*; `side` carries direction. Omit it to use the live mid.

Index weeklies link under their parent index page (`SPXW` legs → `/SPX/`) via
`DISPLAY_UNDERLYING`; pass `underlying=` to override.

Futures options use a distinct shape (verified against a live builder URL
2026-07-07): the page underlying is a *dated* contract (`/ESU26`) and every
`/` is percent-encoded (`%2F`), matching OptionStrat's own slash-prefixed
futures symbols. The leg token is
`[-].%2F{PRODUCT}{MONTH}{YY}{C|P}{STRIKE}[x{RATIO}]` where `PRODUCT` is the
CME option product code (`E3D`, `EW4`, `ES` …), `MONTH` a futures month code,
and `YY` a 2-digit year — no 6-digit expiry (the site resolves it from the
chain). The product code is CME taxonomy that can't be derived from
(future, expiry, right, strike), so it must come from an order symbol or an
explicit `FuturesOptionLeg`.

## Development

```bash
uv sync
uv run pytest
```

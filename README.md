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

## URL format notes

OptionStrat publishes no URL API; this encodes the format its own builder
writes to the address bar (`[-].{ROOT}{YYMMDD}{C|P}{STRIKE}[x{RATIO}]`,
comma-joined), verified against the live site 2026-07-06. `build_url` takes
`base_url`/`strategy` overrides so any future drift is a call-site fix.

Index weeklies link under their parent index page (`SPXW` legs → `/SPX/`) via
`DISPLAY_UNDERLYING`; pass `underlying=` to override. Futures options are
rejected loudly — OptionStrat's futures symbology differs and guessing would
produce silently-wrong links.

## Development

```bash
uv sync
uv run pytest
```

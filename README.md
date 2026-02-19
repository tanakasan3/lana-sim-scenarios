# lana-sim-scenarios

Convert YAML scenarios to lana-bank sim-bootstrap Rust code.

## Why?

**Option 1 (lana-scenario-gen):** YAML → Raw SQL INSERTs
- ⚠️ Risk: Generated SQL might not match lana-bank's actual format

**Option 2 (this project):** YAML → sim-bootstrap Rust → Run through lana-bank → SQL
- ✅ Guaranteed correct: lana-bank's actual code produces the events
- ✅ Tests domain logic, not just SQL format
- ✅ Catches schema/serialization changes automatically

## Quick Start

```bash
# Install
make dev

# Convert all scenarios from lana-scenario-gen
make convert-all

# Analyze a scenario
make analyze SCENARIO=../lana-scenario-gen/scenarios/loan/01_happy_path.yml

# Deploy to lana-bank
make deploy
```

## How It Works

1. **Parse YAML scenarios** from lana-scenario-gen
2. **Map events to sim-bootstrap actions**:
   - `CustomerEvent::Initialized` → `helpers::create_customer()`
   - `DepositEvent::Initialized` → `helpers::make_deposit()`
   - `CreditFacilityProposalEvent::Initialized` → `app.create_facility_proposal()`
   - `CollateralEvent::UpdatedViaManualInput` → `app.credit().collaterals().update_collateral_by_id()`
   - etc.
3. **Generate Rust code** that uses sim-bootstrap primitives
4. **Deploy to lana-bank** for execution

## Event → Action Mapping

```bash
make mappings  # Show all event-to-action mappings
```

| YAML Event | sim-bootstrap Action |
|------------|---------------------|
| `CustomerEvent::Initialized` | `helpers::create_customer()` |
| `DepositEvent::Initialized` | `helpers::make_deposit()` |
| `CreditFacilityProposalEvent::Initialized` | `app.create_facility_proposal()` |
| `CreditFacilityProposalEvent::CustomerApprovalConcluded` | `app.credit().proposals().conclude_customer_approval()` |
| `CollateralEvent::UpdatedViaManualInput` | `app.credit().collaterals().update_collateral_by_id()` |
| `DisbursalEvent::Initialized` | `app.credit().initiate_disbursal()` |
| `PaymentEvent::Initialized` | `app.record_payment_with_date()` |
| `CreditFacilityEvent::Completed` | `app.credit().complete_facility()` |

Many events are implicit (produced by the system) and don't need explicit actions:
- `ApprovalProcessEvent::*` - Handled by waiting for proposal conclusion
- `PendingCreditFacilityEvent::*` - Created automatically
- `CreditFacilityEvent::Initialized` - Created when proposal approved
- `ObligationEvent::*` - Created by interest accrual

## Project Structure

```
lana-sim-scenarios/
├── src/lana_sim_scenarios/
│   ├── cli.py                  # CLI commands
│   ├── generator/
│   │   ├── scenario_parser.py  # Parse YAML scenarios
│   │   └── rust_generator.py   # Generate Rust code
│   └── templates/
│       ├── scenario.rs.j2      # Single scenario template
│       └── mod.rs.j2           # Module index template
└── output/
    └── generated_scenarios/    # Generated Rust code
```

## Usage in lana-bank

After `make deploy`, integrate into sim-bootstrap:

```rust
// In lana/sim-bootstrap/src/scenarios/mod.rs
mod generated;

pub async fn run(...) -> anyhow::Result<()> {
    // ... existing scenarios ...
    
    // Run generated scenarios
    generated::run(sub, app, clock, clock_ctrl).await?;
    
    Ok(())
}
```

## Limitations

- Some events are not yet mapped (deposits, withdrawals, reports)
- Clock advancement is simplified (days only)
- Terms are mostly hardcoded (uses `helpers::std_terms()`)
- No support for concurrent facilities yet

## Related

- [lana-scenario-gen](../lana-scenario-gen) - YAML scenarios + raw SQL generation
- [lana-bank](../lana-bank) - The main banking application

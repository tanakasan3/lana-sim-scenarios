# lana-sim-scenarios

Generate Rust sim-bootstrap scenarios for lana-bank from YAML definitions.

## Overview

This tool converts high-level YAML scenario definitions into Rust code that plugs into lana-bank's `sim-bootstrap` crate. The generated scenarios seed the database with test data for testing the dagster data pipeline and reporting facilities.

## Quick Start

```bash
# Setup
make dev
source .venv/bin/activate

# List available scenarios
make list

# Analyze a scenario
make analyze SCENARIO=scenarios/loan/01_timely_payments.yml

# Generate Rust code for all scenarios
make convert-all

# Deploy to lana-bank
make deploy

# Deploy and patch lana-bank to include generated scenarios
make patch
```

## Scenario Format

Scenarios are defined in YAML with a high-level DSL:

```yaml
# Loan 01: Timely Payments
name: timely_payments
description: "Pay all obligations on their due dates - happy path"
customer_suffix: "1-timely-paid"

# Terms configuration
terms:
  annual_rate: 12
  duration_months: 3
  interest_due_days: 0
  overdue_days: 50
  liquidation_days: null  # No auto-liquidation
  accrual_interval: EndOfDay
  accrual_cycle_interval: EndOfMonth
  one_time_fee_rate: 0.01
  initial_cvl: 140
  margin_call_cvl: 125
  liquidation_cvl: 105
  disbursal_policy: SingleDisbursal

# Amounts
facility_amount_usd: 10_000_000
deposit_amount_usd: 10_000_000
collateral_btc: 230
expected_duration_days: 95

steps:
  - action: create_customer
    suffix: "1-timely-paid"
  
  - action: make_deposit
    amount_usd: 10_000_000
  
  - action: create_proposal
    amount_usd: 10_000_000
    terms: std_terms
  
  - action: customer_approve
  
  - action: wait_for_approval
  
  - action: update_collateral
    collateral_btc: 230
  
  - action: wait_for_activation
  
  # Payment behavior
  - action: on_obligation_due
    behavior: pay_immediately
  
  - action: advance_to_expected_end
    days: 95
  
  - action: pay_remaining_outstanding
  
  - action: complete_facility
```

## Available Actions

### Setup
- `create_customer` - Create a customer with deposit account
- `make_deposit` - Deposit funds into customer's account

### Facility Lifecycle
- `create_proposal` - Create a credit facility proposal
- `customer_approve` - Customer approves the proposal
- `wait_for_approval` - Wait for committee approval
- `update_collateral` - Update collateral amount
- `wait_for_activation` - Wait for facility to activate
- `initiate_disbursal` - Start a disbursal
- `schedule_disbursal` - Schedule a future disbursal
- `complete_facility` - Close the facility

### Payment Behavior
- `on_obligation_due` - Define how to handle obligations
  - `behavior: pay_immediately` - Pay all on time
  - `behavior: skip_all` - Never pay
  - `behavior: custom` - Use custom rules

### Custom Payment Rules

```yaml
- action: on_obligation_due
  behavior: custom
  rules:
    - match:
        type: interest
        nth: 1
      action: skip_until
      delay_days: 90
    - match:
        type: principal
      action: accumulate
    - match:
        type: any
      action: pay_immediately
```

## Standard Terms

The generator recognizes standard term configurations:

| Helper | Duration | Liquidation | Disbursal |
|--------|----------|-------------|-----------|
| `std_terms` | 3 months | No | Single |
| `std_terms_with_liquidation` | 3 months | 60 days | Single |
| `std_terms_12m` | 12 months | No | Multiple |

## Included Scenarios

Based on the existing sim-bootstrap patterns:

| Scenario | Pattern | End State |
|----------|---------|-----------|
| `01_timely_payments` | Pay all on time | Completed |
| `02_interest_late` | First interest 90+ days late | Completed |
| `03_principal_late` | Interest delayed, principal late | Completed |
| `04_multiple_disbursals` | 3 disbursals across months | Completed |
| `05_principal_under_payment` | Interest paid, principal never | Active |
| `06_interest_under_payment` | No payments at all | Active |

## Generated Code

The generator produces:
- Individual `.rs` files for each scenario
- A `mod.rs` that exposes a `run()` function calling all scenarios

## Deployment

```bash
# Generate and copy to lana-bank
make deploy

# Also patch mod.rs to include generated scenarios
make patch

# Verify it compiles
make verify

# Undo the patch
make unpatch
```

## Directory Structure

```
lana-sim-scenarios/
├── scenarios/           # YAML scenario definitions
│   ├── loan/
│   │   ├── 01_timely_payments.yml
│   │   ├── 02_interest_late.yml
│   │   └── ...
│   ├── deposit/
│   └── collateral/
├── src/
│   └── lana_sim_scenarios/
│       ├── cli.py
│       ├── generator/
│       │   ├── scenario_parser.py
│       │   └── rust_generator.py
│       └── templates/
│           ├── scenario.rs.j2
│           └── mod.rs.j2
├── output/
│   └── generated_scenarios/  # Generated Rust code
├── Makefile
└── README.md
```

## Requirements

- Python 3.10+
- lana-bank repository (for deployment)

## License

MIT

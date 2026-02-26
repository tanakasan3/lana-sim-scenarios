"""Parse YAML scenario files into structured data."""

import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Optional
from decimal import Decimal


@dataclass
class TermsConfig:
    """Facility terms configuration."""
    annual_rate: Decimal = Decimal("12")
    duration_months: int = 3
    interest_due_days: int = 0
    overdue_days: int = 50
    liquidation_days: Optional[int] = None
    accrual_interval: str = "EndOfDay"
    accrual_cycle_interval: str = "EndOfMonth"
    one_time_fee_rate: Decimal = Decimal("0.01")
    initial_cvl: Decimal = Decimal("140")
    margin_call_cvl: Decimal = Decimal("125")
    liquidation_cvl: Decimal = Decimal("105")
    disbursal_policy: str = "SingleDisbursal"
    
    @classmethod
    def from_yaml(cls, data: dict) -> "TermsConfig":
        """Parse from YAML dict."""
        if not data:
            return cls()
        return cls(
            annual_rate=Decimal(str(data.get("annual_rate", 12))),
            duration_months=data.get("duration_months", 3),
            interest_due_days=data.get("interest_due_days", 0),
            overdue_days=data.get("overdue_days", 50),
            liquidation_days=data.get("liquidation_days"),
            accrual_interval=data.get("accrual_interval", "EndOfDay"),
            accrual_cycle_interval=data.get("accrual_cycle_interval", "EndOfMonth"),
            one_time_fee_rate=Decimal(str(data.get("one_time_fee_rate", "0.01"))),
            initial_cvl=Decimal(str(data.get("initial_cvl", 140))),
            margin_call_cvl=Decimal(str(data.get("margin_call_cvl", 125))),
            liquidation_cvl=Decimal(str(data.get("liquidation_cvl", 105))),
            disbursal_policy=data.get("disbursal_policy", "SingleDisbursal"),
        )
    
    def to_rust_builder(self) -> str:
        """Generate Rust TermValues::builder() code."""
        lines = [
            "TermValues::builder()",
            f"        .annual_rate(dec!({self.annual_rate}))",
            f"        .initial_cvl(dec!({self.initial_cvl}))",
            f"        .margin_call_cvl(dec!({self.margin_call_cvl}))",
            f"        .liquidation_cvl(dec!({self.liquidation_cvl}))",
            f"        .duration(FacilityDuration::Months({self.duration_months}))",
            f"        .interest_due_duration_from_accrual(ObligationDuration::Days({self.interest_due_days}))",
            f"        .obligation_overdue_duration_from_due(ObligationDuration::Days({self.overdue_days}))",
        ]
        
        if self.liquidation_days is not None:
            lines.append(f"        .obligation_liquidation_duration_from_due(Some(ObligationDuration::Days({self.liquidation_days})))")
        else:
            lines.append("        .obligation_liquidation_duration_from_due(None)")
        
        lines.extend([
            f"        .accrual_interval(InterestInterval::{self.accrual_interval})",
            f"        .accrual_cycle_interval(InterestInterval::{self.accrual_cycle_interval})",
            f"        .one_time_fee_rate(dec!({self.one_time_fee_rate}))",
            f"        .disbursal_policy(DisbursalPolicy::{self.disbursal_policy})",
            '        .build()',
            '        .expect("terms builder should be valid")',
        ])
        return "\n".join(lines)
    
    def to_helper_name(self) -> Optional[str]:
        """Return helper function name if this matches a standard config."""
        if (self.annual_rate == 12 and self.duration_months == 3 and
            self.liquidation_days is None and self.disbursal_policy == "SingleDisbursal"):
            return "helpers::std_terms()"
        elif (self.annual_rate == 12 and self.duration_months == 3 and
              self.liquidation_days == 60 and self.disbursal_policy == "SingleDisbursal"):
            return "helpers::std_terms_with_liquidation()"
        elif (self.annual_rate == 12 and self.duration_months == 12 and
              self.disbursal_policy == "MultipleDisbursal"):
            return "helpers::std_terms_12m()"
        return None


@dataclass
class PaymentRule:
    """A single payment rule."""
    match_type: str  # "interest", "principal", "any"
    match_nth: Optional[int] = None  # Match specific occurrence
    match_nth_le: Optional[int] = None  # Match up to nth occurrence
    action: str = "pay_immediately"  # "pay_immediately", "skip", "delay", "accumulate"
    delay_days: int = 0
    
    @classmethod
    def from_yaml(cls, data: dict) -> "PaymentRule":
        """Parse from YAML dict."""
        match = data.get("match", {})
        return cls(
            match_type=match.get("type", "any"),
            match_nth=match.get("nth"),
            match_nth_le=match.get("nth_le"),
            action=data.get("action", "pay_immediately"),
            delay_days=data.get("delay_days", 0),
        )


@dataclass
class ObligationBehavior:
    """How to handle obligations when they come due."""
    behavior: str = "pay_immediately"  # "pay_immediately", "skip_all", "custom"
    rules: list[PaymentRule] = field(default_factory=list)
    
    @classmethod
    def from_yaml(cls, data: dict) -> "ObligationBehavior":
        """Parse from YAML dict."""
        if not data:
            return cls()
        
        behavior = data.get("behavior", "pay_immediately")
        rules = []
        if behavior == "custom":
            for rule_data in data.get("rules", []):
                rules.append(PaymentRule.from_yaml(rule_data))
        
        return cls(behavior=behavior, rules=rules)


@dataclass
class ScheduledDisbursal:
    """A scheduled disbursal."""
    after_days: int
    amount_usd: int


@dataclass 
class ScenarioStep:
    """A single step in a scenario."""
    action: str
    params: dict = field(default_factory=dict)
    
    @classmethod
    def from_yaml(cls, data: dict) -> "ScenarioStep":
        """Parse from YAML dict."""
        action = data.pop("action", "unknown")
        return cls(action=action, params=data)


@dataclass
class Scenario:
    """A complete scenario definition."""
    name: str
    description: str
    customer_suffix: str
    
    # Amounts
    facility_amount_usd: int
    deposit_amount_usd: int
    collateral_btc: int
    
    # Terms
    terms: TermsConfig
    
    # Timing
    start_offset_days: Optional[int] = None  # Negative = past
    expected_duration_days: Optional[int] = None
    
    # Behavior
    obligation_behavior: ObligationBehavior = field(default_factory=ObligationBehavior)
    scheduled_disbursals: list[ScheduledDisbursal] = field(default_factory=list)
    
    # Steps (raw)
    steps: list[ScenarioStep] = field(default_factory=list)
    
    # End behavior
    complete_facility: bool = True
    stop_when_principal_only: bool = False
    
    @property
    def fn_name(self) -> str:
        """Get the Rust function name."""
        return re.sub(r'[^a-z0-9]+', '_', self.name.lower()).strip('_')
    
    @property
    def module_name(self) -> str:
        """Get the Rust module name."""
        return self.fn_name
    
    @property
    def terms_builder(self) -> str:
        """Get Rust code for terms."""
        helper = self.terms.to_helper_name()
        if helper:
            return helper
        return self.terms.to_rust_builder()
    
    @property
    def has_obligation_type_filtering(self) -> bool:
        """Check if we need ObligationType import."""
        return (self.obligation_behavior.behavior == "custom" or
                self.stop_when_principal_only)
    
    @property
    def has_monthly_delay(self) -> bool:
        """Check if we need ONE_MONTH_DAYS constant."""
        for rule in self.obligation_behavior.rules:
            if rule.delay_days >= 30:
                return True
        return len(self.scheduled_disbursals) > 0
    
    @property
    def has_approval_timeout(self) -> bool:
        """Check if we need approval timeout logic."""
        return self.start_offset_days is not None
    
    @property
    def has_activation_timeout(self) -> bool:
        """Check if we need activation timeout logic."""
        return self.start_offset_days is not None
    
    @property
    def tracks_activation_date(self) -> bool:
        """Check if we need to track activation date."""
        return (self.expected_duration_days is not None or 
                len(self.scheduled_disbursals) > 0)
    
    @property
    def approval_timeout_days(self) -> int:
        return 30
    
    @property
    def activation_timeout_days(self) -> int:
        return 30


class ScenarioParser:
    """Parse YAML scenario files."""
    
    def parse_file(self, path: Path) -> Scenario:
        """Parse a single scenario file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return self.parse_dict(data)
    
    def parse_dict(self, data: dict) -> Scenario:
        """Parse scenario from a dictionary."""
        # Parse terms
        terms_data = data.get("terms", {})
        terms = TermsConfig.from_yaml(terms_data)
        
        # Parse steps and extract behaviors
        steps = []
        obligation_behavior = ObligationBehavior()
        scheduled_disbursals = []
        complete_facility = True
        stop_when_principal_only = False
        
        for step_data in data.get("steps", []):
            step = ScenarioStep.from_yaml(dict(step_data))
            steps.append(step)
            
            # Extract special behaviors
            if step.action == "on_obligation_due":
                obligation_behavior = ObligationBehavior.from_yaml(step.params)
            elif step.action == "schedule_disbursal":
                scheduled_disbursals.append(ScheduledDisbursal(
                    after_days=step.params.get("after_days", 30),
                    amount_usd=step.params.get("amount_usd", 0),
                ))
            elif step.action == "when_only_principal_remains":
                if step.params.get("then") == "stop":
                    stop_when_principal_only = True
                    complete_facility = False
        
        # Check if complete_facility step exists
        has_complete_step = any(s.action == "complete_facility" for s in steps)
        if not has_complete_step:
            complete_facility = False
        
        return Scenario(
            name=data.get("name", "unnamed"),
            description=data.get("description", ""),
            customer_suffix=data.get("customer_suffix", "test"),
            facility_amount_usd=data.get("facility_amount_usd", 10_000_000),
            deposit_amount_usd=data.get("deposit_amount_usd", 10_000_000),
            collateral_btc=data.get("collateral_btc", 230),
            terms=terms,
            start_offset_days=data.get("start_offset_days"),
            expected_duration_days=data.get("expected_duration_days"),
            obligation_behavior=obligation_behavior,
            scheduled_disbursals=scheduled_disbursals,
            steps=steps,
            complete_facility=complete_facility,
            stop_when_principal_only=stop_when_principal_only,
        )

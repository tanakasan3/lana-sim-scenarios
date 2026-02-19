"""Generate Rust sim-bootstrap code from scenarios."""

from dataclasses import dataclass, field
from pathlib import Path
from jinja2 import Environment, PackageLoader
from .scenario_parser import Scenario, ScenarioEvent
from decimal import Decimal


@dataclass
class TermsValues:
    """Facility terms parsed from YAML."""
    annual_rate: Decimal = Decimal("12")  # as percentage (10 = 10%)
    duration_months: int = 3
    interest_due_days: int = 0
    overdue_days: int = 50
    liquidation_days: int | None = None  # None = no auto-liquidation
    accrual_interval: str = "EndOfDay"
    accrual_cycle_interval: str = "EndOfMonth"
    one_time_fee_rate: Decimal = Decimal("0.01")
    initial_cvl: Decimal = Decimal("140")  # as percentage
    margin_call_cvl: Decimal = Decimal("125")
    liquidation_cvl: Decimal = Decimal("105")
    disbursal_policy: str = "SingleDisbursal"
    
    @classmethod
    def from_yaml(cls, terms: dict) -> "TermsValues":
        """Parse terms from YAML dict."""
        if not terms:
            return cls()
        
        # Parse annual_rate - YAML has "0.10" meaning 10%
        annual_rate = Decimal("12")
        if "annual_rate" in terms:
            rate_str = str(terms["annual_rate"])
            rate = Decimal(rate_str)
            # If rate < 1, it's a decimal (0.10 = 10%), convert to percentage
            if rate < 1:
                annual_rate = rate * 100
            else:
                annual_rate = rate
        
        # Parse duration
        duration_months = 3
        duration = terms.get("duration", {})
        if isinstance(duration, dict):
            duration_months = duration.get("Months", duration.get("months", 3))
        
        # Parse interest_due_duration_from_accrual
        interest_due_days = 0
        interest_due = terms.get("interest_due_duration_from_accrual", {})
        if isinstance(interest_due, dict):
            interest_due_days = interest_due.get("Days", interest_due.get("days", 0))
        
        # Parse CVL values - YAML has {Finite: "1.40"} meaning 140%
        def parse_cvl(cvl_dict: dict, default: Decimal) -> Decimal:
            if not cvl_dict:
                return default
            if isinstance(cvl_dict, dict):
                finite = cvl_dict.get("Finite", cvl_dict.get("finite"))
                if finite:
                    val = Decimal(str(finite))
                    # If val > 1 (like 1.40), convert to percentage (140)
                    if val < 10:
                        return val * 100
                    return val
            return default
        
        initial_cvl = parse_cvl(terms.get("initial_cvl", {}), Decimal("140"))
        margin_call_cvl = parse_cvl(terms.get("margin_call_cvl", {}), Decimal("125"))
        liquidation_cvl = parse_cvl(terms.get("liquidation_cvl", {}), Decimal("105"))
        
        # Parse one_time_fee_rate
        one_time_fee_rate = Decimal(str(terms.get("one_time_fee_rate", "0.01")))
        
        # Parse intervals
        accrual_interval = terms.get("accrual_interval", "EndOfDay")
        accrual_cycle_interval = terms.get("accrual_cycle_interval", "EndOfMonth")
        
        # Parse disbursal policy
        disbursal_policy = terms.get("disbursal_policy", "SingleDisbursal")
        
        return cls(
            annual_rate=annual_rate,
            duration_months=duration_months,
            interest_due_days=interest_due_days,
            accrual_interval=accrual_interval,
            accrual_cycle_interval=accrual_cycle_interval,
            one_time_fee_rate=one_time_fee_rate,
            initial_cvl=initial_cvl,
            margin_call_cvl=margin_call_cvl,
            liquidation_cvl=liquidation_cvl,
            disbursal_policy=disbursal_policy,
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
            lines.append(f"        .obligation_liquidation_duration_from_due(ObligationDuration::Days({self.liquidation_days}))")
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


@dataclass
class EntityTracker:
    """Track entities and their relationships across the scenario."""
    customers: dict = field(default_factory=dict)  # entity -> suffix
    facilities: dict = field(default_factory=dict)  # entity -> {customer_ref, collateral_ref, ...}
    collaterals: dict = field(default_factory=dict)  # entity -> {satoshis, facility_ref}
    disbursals: dict = field(default_factory=dict)  # entity -> {facility_ref, amount}
    
    def register_customer(self, entity: str, suffix: str = None):
        """Register a customer entity."""
        if suffix is None:
            suffix = entity.replace("customer_", "")
        self.customers[entity] = suffix
    
    def register_facility(self, entity: str, customer_ref: str, collateral_ref: str = None, 
                         amount: int = 0, terms: dict = None):
        """Register a facility entity."""
        self.facilities[entity] = {
            "customer_ref": customer_ref,
            "collateral_ref": collateral_ref,
            "amount": amount,
            "terms": TermsValues.from_yaml(terms or {}),
        }
    
    def register_collateral(self, entity: str, satoshis: int = 0, facility_ref: str = None):
        """Register collateral entity."""
        self.collaterals[entity] = {
            "satoshis": satoshis,
            "facility_ref": facility_ref,
        }
    
    def register_disbursal(self, entity: str, facility_ref: str = None, amount: int = 0):
        """Register a disbursal entity."""
        self.disbursals[entity] = {
            "facility_ref": facility_ref,
            "amount": amount,
        }
    
    def get_facility_for_entity(self, entity: str) -> str | None:
        """Get the facility reference for a given entity (disbursal, collateral, etc)."""
        if entity in self.disbursals:
            return self.disbursals[entity].get("facility_ref")
        if entity in self.collaterals:
            return self.collaterals[entity].get("facility_ref")
        return None
    
    def get_customer_var(self, customer_ref: str) -> str:
        """Get the Rust variable name for a customer."""
        # Handle _ref suffix
        if customer_ref.endswith("_ref"):
            customer_ref = customer_ref[:-4]
        return f"{customer_ref}_id"
    
    def get_facility_var(self, facility_ref: str) -> str:
        """Get the Rust variable name for a facility."""
        if facility_ref.endswith("_ref"):
            facility_ref = facility_ref[:-4]
        # Use cf_id for first facility, cf_<N>_id for subsequent
        if facility_ref in ("facility_1", "facility"):
            return "cf_id"
        return f"{facility_ref.replace('facility_', 'cf_')}_id"


@dataclass
class SimAction:
    """A high-level sim-bootstrap action."""
    action_type: str    # create_customer, make_deposit, create_proposal, etc.
    entity: str         # Entity reference
    params: dict        # Action parameters
    wait_days: int      # Days to advance clock after
    
    
class RustGenerator:
    """Generate Rust sim-bootstrap scenario code."""
    
    # Map YAML events to sim-bootstrap actions
    # Special value "multi" means this event generates multiple actions
    EVENT_TO_ACTION = {
        # Customer lifecycle
        "CustomerEvent::Initialized": "create_customer",
        "CustomerEvent::EmailUpdated": "skip",
        
        # Deposits
        "DepositAccountEvent::Initialized": "skip",  # Implicit in create_customer
        "DepositEvent::Initialized": "make_deposit",
        "DepositEvent::Reverted": "skip",
        
        # Withdrawals
        "WithdrawalEvent::Initialized": "skip",  # TODO: implement
        "WithdrawalEvent::Confirmed": "skip",
        "WithdrawalEvent::Denied": "skip",
        "WithdrawalEvent::Cancelled": "skip",
        
        # Credit facility proposal
        "CreditFacilityProposalEvent::Initialized": "create_proposal",
        "CreditFacilityProposalEvent::CustomerApprovalConcluded": "conclude_customer_approval",
        "CreditFacilityProposalEvent::ApprovalProcessConcluded": "wait_for_approval",
        
        # Approval process
        "ApprovalProcessEvent::Initialized": "skip",
        "ApprovalProcessEvent::Approved": "skip",
        "ApprovalProcessEvent::Denied": "skip",
        "ApprovalProcessEvent::Concluded": "skip",
        
        # Collateral
        "CollateralEvent::Initialized": "skip",  # Implicit in pending facility
        "CollateralEvent::UpdatedViaManualInput": "update_collateral",
        "CollateralEvent::UpdatedViaCustodianSync": "update_collateral",
        
        # Pending credit facility
        "PendingCreditFacilityEvent::Initialized": "skip",
        "PendingCreditFacilityEvent::CollateralizationStateChanged": "skip",
        "PendingCreditFacilityEvent::Completed": "skip",
        
        # Credit facility - CreditFacilityEvent::Initialized triggers full proposal flow
        "CreditFacilityEvent::Initialized": "multi:create_facility",
        "CreditFacilityEvent::InterestAccrualCycleStarted": "advance_time",
        "CreditFacilityEvent::InterestAccrualCycleConcluded": "skip",
        "CreditFacilityEvent::CollateralizationStateChanged": "skip",
        "CreditFacilityEvent::CollateralizationRatioChanged": "skip",
        "CreditFacilityEvent::PartialLiquidationInitiated": "skip",
        "CreditFacilityEvent::ProceedsFromPartialLiquidationApplied": "skip",
        "CreditFacilityEvent::Matured": "advance_time",
        "CreditFacilityEvent::Completed": "complete_facility",
        
        # Disbursal
        "DisbursalEvent::Initialized": "initiate_disbursal",
        "DisbursalEvent::ApprovalProcessConcluded": "skip",
        "DisbursalEvent::Settled": "wait_for_disbursal",
        
        # Obligations
        "ObligationEvent::Initialized": "skip",
        "ObligationEvent::DueRecorded": "advance_time",
        "ObligationEvent::OverdueRecorded": "advance_time",
        "ObligationEvent::DefaultedRecorded": "advance_time",
        "ObligationEvent::PaymentAllocated": "skip",
        "ObligationEvent::Completed": "skip",
        
        # Payments
        "PaymentEvent::Initialized": "record_payment",
        "PaymentAllocationEvent::Initialized": "skip",
        
        # Liquidation
        "LiquidationEvent::Initialized": "skip",
        "LiquidationEvent::CollateralSentOut": "skip",
        "LiquidationEvent::ProceedsReceivedAndLiquidationCompleted": "skip",
        
        # Other
        "CustodianEvent::Initialized": "skip",
        "CustodianEvent::ConfigUpdated": "skip",
        "ProspectEvent::Initialized": "skip",
        "ProspectEvent::KycStarted": "skip",
        "ProspectEvent::KycPending": "skip",
        "ProspectEvent::KycApproved": "skip",
        "ProspectEvent::KycDeclined": "skip",
        "ProspectEvent::ManuallyConverted": "skip",
        "ProspectEvent::Closed": "skip",
        "TermsTemplateEvent::Initialized": "create_terms_template",
        "CommitteeEvent::Initialized": "skip",
        "CommitteeEvent::MemberAdded": "skip",
        "ReportEvent::Initialized": "skip",
        "ReportRunEvent::Initialized": "skip",
        "ReportRunEvent::StateUpdated": "skip",
        "ChartEvent::Initialized": "skip",
        "ChartEvent::BaseConfigSet": "skip",
        "ChartNodeEvent::Initialized": "skip",
        "ChartNodeEvent::ChildNodeAdded": "skip",
        "RoleEvent::Initialized": "skip",
        "UserEvent::Initialized": "skip",
    }
    
    def __init__(self):
        self.env = Environment(
            loader=PackageLoader("lana_sim_scenarios", "templates"),
            trim_blocks=True,
            lstrip_blocks=True,
        )
    
    def convert_scenario(self, scenario: Scenario) -> tuple[list[SimAction], EntityTracker]:
        """Convert a scenario to a list of sim-bootstrap actions."""
        actions = []
        tracker = EntityTracker()
        
        # First pass: collect collateral amounts and register entities
        collateral_amounts = {}
        for event in scenario.events:
            if event.event_type == "CollateralEvent::UpdatedViaManualInput":
                collateral_amounts[event.entity] = event.values.get("collateral", 25000000)
            elif event.event_type == "CustomerEvent::Initialized":
                tracker.register_customer(event.entity)
            elif event.event_type == "CreditFacilityEvent::Initialized":
                customer_ref = event.values.get("customer_id_ref", "customer_1")
                collateral_ref = event.values.get("collateral_id_ref", "collateral_1")
                tracker.register_facility(
                    event.entity,
                    customer_ref=customer_ref.rstrip("_ref") if customer_ref.endswith("_ref") else customer_ref,
                    collateral_ref=collateral_ref.rstrip("_ref") if collateral_ref.endswith("_ref") else collateral_ref,
                    amount=event.values.get("amount", 500000),
                    terms=event.values.get("terms", {}),
                )
        
        # Second pass: generate actions
        for event in scenario.events:
            action_type = self.EVENT_TO_ACTION.get(event.event_type, "unknown")
            
            if action_type == "skip":
                continue
            elif action_type == "unknown":
                actions.append(SimAction(
                    action_type="comment",
                    entity=event.entity,
                    params={"text": f"TODO: {event.event_type}"},
                    wait_days=event.after.days,
                ))
            elif action_type.startswith("multi:"):
                multi_type = action_type.split(":")[1]
                multi_actions = self._expand_multi_action(multi_type, event, tracker, collateral_amounts)
                for i, ma in enumerate(multi_actions):
                    ma.wait_days = event.after.days if i == 0 else 0
                actions.extend(multi_actions)
            else:
                actions.append(SimAction(
                    action_type=action_type,
                    entity=event.entity,
                    params=self._extract_params(event, action_type, tracker),
                    wait_days=event.after.days,
                ))
        
        return actions, tracker
    
    def _expand_multi_action(self, multi_type: str, event: ScenarioEvent, 
                            tracker: EntityTracker, collateral_amounts: dict) -> list[SimAction]:
        """Expand a multi-action into individual actions."""
        if multi_type == "create_facility":
            facility_info = tracker.facilities.get(event.entity, {})
            customer_ref = facility_info.get("customer_ref", "customer_1")
            collateral_ref = facility_info.get("collateral_ref", "collateral_1")
            terms = facility_info.get("terms", TermsValues())
            amount = facility_info.get("amount", 500000)
            
            # Get collateral amount from pre-scanned collateral events
            collateral_amount = collateral_amounts.get(collateral_ref, 
                                event.values.get("collateral", 25000000))
            
            return [
                SimAction(
                    action_type="create_proposal",
                    entity=event.entity,
                    params={
                        "customer_ref": customer_ref,
                        "amount_usd": amount / 100,
                        "terms": terms,  # Now a TermsValues object
                    },
                    wait_days=0,
                ),
                SimAction(
                    action_type="conclude_customer_approval",
                    entity=event.entity,
                    params={},
                    wait_days=0,
                ),
                SimAction(
                    action_type="wait_for_approval",
                    entity=event.entity,
                    params={},
                    wait_days=0,
                ),
                SimAction(
                    action_type="update_collateral_for_activation",
                    entity=event.entity,
                    params={"satoshis": collateral_amount},
                    wait_days=0,
                ),
                SimAction(
                    action_type="wait_for_facility_activation",
                    entity=event.entity,
                    params={},
                    wait_days=0,
                ),
            ]
        
        return []
    
    def _extract_params(self, event: ScenarioEvent, action_type: str, tracker: EntityTracker) -> dict:
        """Extract relevant parameters for an action."""
        params = dict(event.values)
        params["entity"] = event.entity
        
        if action_type == "create_customer":
            params["suffix"] = event.entity.replace("customer_", "")
            params["email"] = params.get("email", f"{event.entity}@example.com")
            params["customer_type"] = params.get("customer_type", "Individual")
            
        elif action_type == "make_deposit":
            params["amount_usd"] = params.get("amount", 10_000_000) / 100
            
        elif action_type == "create_proposal":
            params["amount_usd"] = params.get("amount", 500_000) / 100
            terms_dict = params.get("terms", {})
            params["terms"] = TermsValues.from_yaml(terms_dict)
            
        elif action_type == "update_collateral":
            params["satoshis"] = params.get("collateral", 25_000_000)
            
        elif action_type == "initiate_disbursal":
            params["amount_usd"] = params.get("amount", 500_000) / 100
            
        elif action_type == "record_payment":
            params["amount_usd"] = params.get("amount", 0) / 100
            
        return params
    
    def generate_rust(self, scenario: Scenario) -> str:
        """Generate Rust code for a scenario."""
        actions, tracker = self.convert_scenario(scenario)
        template = self.env.get_template("scenario.rs.j2")
        return template.render(
            scenario=scenario,
            actions=actions,
            tracker=tracker,
        )
    
    def generate_mod_rs(self, scenarios: list[Scenario]) -> str:
        """Generate the mod.rs file for all scenarios."""
        template = self.env.get_template("mod.rs.j2")
        return template.render(scenarios=scenarios)

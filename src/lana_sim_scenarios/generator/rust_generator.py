"""Generate Rust sim-bootstrap code from scenarios."""

from dataclasses import dataclass
from pathlib import Path
from jinja2 import Environment, PackageLoader
from .scenario_parser import Scenario, ScenarioEvent


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
        "CustomerEvent::EmailUpdated": "skip",  # Not needed in sim
        
        # Deposits
        "DepositAccountEvent::Initialized": "skip",  # Implicit in create_customer
        "DepositEvent::Initialized": "make_deposit",
        "DepositEvent::Reverted": "skip",  # Would need custom handling
        
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
        "ApprovalProcessEvent::Initialized": "skip",  # Implicit
        "ApprovalProcessEvent::Approved": "skip",  # Handled by wait
        "ApprovalProcessEvent::Denied": "skip",
        "ApprovalProcessEvent::Concluded": "skip",
        
        # Collateral
        "CollateralEvent::Initialized": "skip",  # Implicit in pending facility
        "CollateralEvent::UpdatedViaManualInput": "update_collateral",
        "CollateralEvent::UpdatedViaCustodianSync": "update_collateral",
        
        # Pending credit facility
        "PendingCreditFacilityEvent::Initialized": "skip",  # Implicit
        "PendingCreditFacilityEvent::CollateralizationStateChanged": "skip",  # Automatic
        "PendingCreditFacilityEvent::Completed": "skip",  # Automatic
        
        # Credit facility - CreditFacilityEvent::Initialized triggers full proposal flow
        "CreditFacilityEvent::Initialized": "multi:create_facility",
        "CreditFacilityEvent::InterestAccrualCycleStarted": "advance_time",
        "CreditFacilityEvent::InterestAccrualCycleConcluded": "skip",
        "CreditFacilityEvent::CollateralizationStateChanged": "skip",  # Automatic
        "CreditFacilityEvent::CollateralizationRatioChanged": "skip",  # Automatic
        "CreditFacilityEvent::PartialLiquidationInitiated": "skip",  # Automatic
        "CreditFacilityEvent::ProceedsFromPartialLiquidationApplied": "skip",
        "CreditFacilityEvent::Matured": "advance_time",
        "CreditFacilityEvent::Completed": "complete_facility",
        
        # Disbursal
        "DisbursalEvent::Initialized": "initiate_disbursal",
        "DisbursalEvent::ApprovalProcessConcluded": "skip",  # Wait for it
        "DisbursalEvent::Settled": "wait_for_disbursal",
        
        # Obligations
        "ObligationEvent::Initialized": "skip",  # Automatic
        "ObligationEvent::DueRecorded": "advance_time",
        "ObligationEvent::OverdueRecorded": "advance_time",
        "ObligationEvent::DefaultedRecorded": "advance_time",
        "ObligationEvent::PaymentAllocated": "skip",  # Implicit
        "ObligationEvent::Completed": "skip",  # Implicit
        
        # Payments
        "PaymentEvent::Initialized": "record_payment",
        "PaymentAllocationEvent::Initialized": "skip",  # Implicit
        
        # Liquidation
        "LiquidationEvent::Initialized": "skip",  # Automatic
        "LiquidationEvent::CollateralSentOut": "skip",
        "LiquidationEvent::ProceedsReceivedAndLiquidationCompleted": "skip",
        
        # Other
        "CustodianEvent::Initialized": "skip",
        "CustodianEvent::ConfigUpdated": "skip",
        "ProspectEvent::Initialized": "skip",  # TODO
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
    
    def convert_scenario(self, scenario: Scenario) -> list[SimAction]:
        """Convert a scenario to a list of sim-bootstrap actions."""
        actions = []
        
        # Track which collateral entity has been seen for facilities
        collateral_amounts = {}
        
        for event in scenario.events:
            # Track collateral amounts
            if event.event_type == "CollateralEvent::UpdatedViaManualInput":
                collateral_amounts[event.entity] = event.values.get("collateral", 25000000)
            
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
                # Handle multi-action events
                multi_type = action_type.split(":")[1]
                multi_actions = self._expand_multi_action(multi_type, event, collateral_amounts)
                for i, ma in enumerate(multi_actions):
                    # Only first action gets the wait time
                    ma.wait_days = event.after.days if i == 0 else 0
                actions.extend(multi_actions)
            else:
                actions.append(SimAction(
                    action_type=action_type,
                    entity=event.entity,
                    params=self._extract_params(event, action_type),
                    wait_days=event.after.days,
                ))
        
        return actions
    
    def _expand_multi_action(self, multi_type: str, event: ScenarioEvent, collateral_amounts: dict) -> list[SimAction]:
        """Expand a multi-action into individual actions."""
        if multi_type == "create_facility":
            # CreditFacilityEvent::Initialized expands to:
            # 1. create_proposal
            # 2. conclude_customer_approval  
            # 3. wait_for_approval
            # 4. update_collateral (with amount from tracked collateral)
            # 5. wait_for_facility_activation
            
            params = dict(event.values)
            params["entity"] = event.entity
            
            # Extract customer ref
            customer_ref = params.get("customer_id_ref", "customer_1")
            if customer_ref.endswith("_ref"):
                customer_ref = customer_ref[:-4]
            
            # Extract collateral amount from tracked collateral or event values
            collateral_ref = params.get("collateral_id_ref", "collateral_1")
            if collateral_ref.endswith("_ref"):
                collateral_ref = collateral_ref[:-4]
            collateral_amount = collateral_amounts.get(collateral_ref, params.get("collateral", 25000000))
            
            # Extract terms
            terms = params.get("terms", {})
            amount = params.get("amount", 500000)
            
            return [
                SimAction(
                    action_type="create_proposal",
                    entity=event.entity,
                    params={
                        "customer_ref": customer_ref,
                        "amount_usd": amount / 100,
                        "terms": terms,
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
    
    def _extract_params(self, event: ScenarioEvent, action_type: str) -> dict:
        """Extract relevant parameters for an action."""
        params = dict(event.values)
        params["entity"] = event.entity
        
        if action_type == "create_customer":
            params["suffix"] = event.entity.replace("customer_", "")
            params["email"] = params.get("email", f"{event.entity}@example.com")
            params["customer_type"] = params.get("customer_type", "Individual")
            
        elif action_type == "make_deposit":
            params["amount_usd"] = params.get("amount", 10_000_000) / 100  # cents to dollars
            
        elif action_type == "create_proposal":
            params["amount_usd"] = params.get("amount", 500_000) / 100
            # Extract terms
            terms = params.get("terms", {})
            params["annual_rate"] = terms.get("annual_rate", "0.10")
            params["duration_months"] = self._extract_duration_months(terms.get("duration", {}))
            
        elif action_type == "update_collateral":
            params["satoshis"] = params.get("collateral", 25_000_000)
            
        elif action_type == "initiate_disbursal":
            params["amount_usd"] = params.get("amount", 500_000) / 100
            
        elif action_type == "record_payment":
            params["amount_usd"] = params.get("amount", 0) / 100
            
        return params
    
    def _extract_duration_months(self, duration: dict) -> int:
        """Extract months from duration dict like {'Months': 6}."""
        if isinstance(duration, dict):
            return duration.get("Months", duration.get("months", 6))
        return 6
    
    def generate_rust(self, scenario: Scenario) -> str:
        """Generate Rust code for a scenario."""
        actions = self.convert_scenario(scenario)
        template = self.env.get_template("scenario.rs.j2")
        return template.render(
            scenario=scenario,
            actions=actions,
        )
    
    def generate_mod_rs(self, scenarios: list[Scenario]) -> str:
        """Generate the mod.rs file for all scenarios."""
        template = self.env.get_template("mod.rs.j2")
        return template.render(scenarios=scenarios)

"""Generate Rust sim-bootstrap code from scenarios."""

from pathlib import Path
from jinja2 import Environment, PackageLoader
from .scenario_parser import Scenario, ObligationBehavior, ScheduledDisbursal, PriceChange


class RustGenerator:
    """Generate Rust sim-bootstrap scenario code."""
    
    def __init__(self):
        self.env = Environment(
            loader=PackageLoader("lana_sim_scenarios", "templates"),
            trim_blocks=True,
            lstrip_blocks=True,
        )
    
    def generate_rust(self, scenario: Scenario) -> str:
        """Generate Rust code for a scenario."""
        # Build the scenario context with computed properties
        context = {
            "scenario": scenario,
        }
        
        # Add computed code blocks
        context["scenario"].on_activation_code = self._generate_on_activation_code(scenario)
        context["scenario"].main_loop_code = self._generate_main_loop_code(scenario)
        
        template = self.env.get_template("scenario.rs.j2")
        return template.render(**context)
    
    def _generate_on_activation_code(self, scenario: Scenario) -> str:
        """Generate code to run on facility activation."""
        lines = []
        
        # Set initial BTC price if specified
        if scenario.initial_btc_price_usd:
            price_cents = scenario.initial_btc_price_usd * 100
            lines.append("")
            lines.append(f"// Set initial BTC price to ${scenario.initial_btc_price_usd:,}")
            lines.append(f"app.outbox()")
            lines.append(f"    .publish_ephemeral(")
            lines.append(f"        lana_app::price::PRICE_UPDATED_EVENT_TYPE,")
            lines.append(f"        lana_app::price::CorePriceEvent::PriceUpdated {{")
            lines.append(f"            price: PriceOfOneBTC::new(UsdCents::from({price_cents}_u64)),")
            lines.append(f"            timestamp: chrono::Utc::now(),")
            lines.append(f"        }},")
            lines.append(f"    )")
            lines.append(f"    .await?;")
            lines.append(f"tokio::time::sleep(std::time::Duration::from_millis(100)).await;")
            lines.append(f"event!(tracing::Level::INFO, price_usd = {scenario.initial_btc_price_usd}, \"Initial BTC price set\");")
        
        # Check for immediate disbursal
        has_immediate_disbursal = any(
            s.action == "initiate_disbursal" and s.params.get("after_days", 0) == 0
            for s in scenario.steps
        )
        
        if has_immediate_disbursal:
            # Find the amount
            for step in scenario.steps:
                if step.action == "initiate_disbursal":
                    amount = step.params.get("amount_usd", 1_000_000)
                    lines.append("")
                    lines.append(f"app.credit()")
                    lines.append(f"    .initiate_disbursal(&sub, cf_id, UsdCents::try_from_usd(dec!({amount}))?)")
                    lines.append(f"    .await?;")
                    break
        
        return "\n".join(lines)
    
    def _generate_main_loop_code(self, scenario: Scenario) -> str:
        """Generate the main event loop code based on scenario behavior."""
        behavior = scenario.obligation_behavior.behavior
        
        if behavior == "skip_all":
            return self._generate_skip_all_loop(scenario)
        elif behavior == "pay_immediately":
            return self._generate_pay_immediately_loop(scenario)
        elif behavior == "custom":
            return self._generate_custom_behavior_loop(scenario)
        else:
            return self._generate_pay_immediately_loop(scenario)
    
    def _generate_skip_all_loop(self, scenario: Scenario) -> str:
        """Generate loop that skips all payments (interest_under_payment pattern)."""
        return '''
    // No payments made - scenario ends immediately after activation
'''
    
    def _generate_pay_immediately_loop(self, scenario: Scenario) -> str:
        """Generate loop that pays all obligations immediately (timely_payments pattern)."""
        lines = []
        
        # Track activation date if needed
        if scenario.tracks_activation_date:
            lines.append(f"    let expected_end_date = activation_date + chrono::Duration::days({scenario.expected_duration_days or 95});")
            lines.append("")
        
        # Scheduled disbursals
        if scenario.scheduled_disbursals:
            for i, disbursal in enumerate(scenario.scheduled_disbursals, 1):
                lines.append(f"    let disbursal_{i+1}_date = activation_date + chrono::Duration::days({disbursal.after_days});")
                lines.append(f"    let mut disbursal_{i+1}_done = false;")
            lines.append("")
        
        # Price changes
        if scenario.price_changes:
            for i, price_change in enumerate(scenario.price_changes, 1):
                lines.append(f"    let price_change_{i}_date = activation_date + chrono::Duration::days({price_change.after_days});")
                lines.append(f"    let mut price_change_{i}_done = false;")
            lines.append("")
        
        # Need current_date variable if we have disbursals or price changes
        needs_current_date = scenario.scheduled_disbursals or scenario.price_changes
        
        # Main loop
        lines.append("    loop {")
        lines.append("        tokio::select! {")
        lines.append("            Some(msg) = stream.next() => {")
        lines.append("                if let Some(LanaEvent::CreditCollection(CoreCreditCollectionEvent::ObligationDue {")
        lines.append("                    entity,")
        lines.append("                })) = &msg.payload")
        lines.append("                    && CreditFacilityId::from(entity.beneficiary_id) == cf_id")
        lines.append("                    && entity.outstanding_amount > UsdCents::ZERO")
        lines.append("                {")
        lines.append("                    msg.inject_trace_parent();")
        lines.append("                    app.record_payment_with_date(&sub, cf_id, entity.outstanding_amount, clock.today()).await?;")
        lines.append("                }")
        lines.append("            }")
        lines.append("            _ = tokio::time::sleep(EVENT_WAIT_TIMEOUT) => {")
        
        # Get current date if needed
        if needs_current_date:
            lines.append("                let current_date = clock.today();")
            lines.append("")
        
        # Scheduled disbursals in timeout block
        if scenario.scheduled_disbursals:
            for i, disbursal in enumerate(scenario.scheduled_disbursals, 1):
                lines.append(f"                if !disbursal_{i+1}_done && current_date >= disbursal_{i+1}_date {{")
                lines.append(f"                    app.credit()")
                lines.append(f"                        .initiate_disbursal(&sub, cf_id, UsdCents::try_from_usd(dec!({disbursal.amount_usd}))?)")
                lines.append(f"                        .await?;")
                lines.append(f"                    disbursal_{i+1}_done = true;")
                lines.append("                }")
                lines.append("")
        
        # Price changes in timeout block
        if scenario.price_changes:
            for i, price_change in enumerate(scenario.price_changes, 1):
                price_cents = price_change.price_usd * 100  # Convert USD to cents
                lines.append(f"                if !price_change_{i}_done && current_date >= price_change_{i}_date {{")
                lines.append(f"                    // Set BTC price to ${price_change.price_usd:,}")
                lines.append(f"                    app.outbox()")
                lines.append(f"                        .publish_ephemeral(")
                lines.append(f"                            lana_app::price::PRICE_UPDATED_EVENT_TYPE,")
                lines.append(f"                            lana_app::price::CorePriceEvent::PriceUpdated {{")
                lines.append(f"                                price: PriceOfOneBTC::new(UsdCents::from({price_cents}_u64)),")
                lines.append(f"                                timestamp: chrono::Utc::now(),")
                lines.append(f"                            }},")
                lines.append(f"                        )")
                lines.append(f"                        .await?;")
                lines.append(f"                    tokio::time::sleep(std::time::Duration::from_millis(100)).await;")
                lines.append(f"                    event!(tracing::Level::INFO, price_usd = {price_change.price_usd}, \"BTC price changed\");")
                lines.append(f"                    price_change_{i}_done = true;")
                lines.append("                }")
                lines.append("")
        
        if scenario.expected_duration_days:
            if needs_current_date:
                lines.append("                if current_date >= expected_end_date {")
            else:
                lines.append("                if clock.today() >= expected_end_date {")
            lines.append("                    break;")
            lines.append("                }")
        
        lines.append("                clock_ctrl.advance(ONE_DAY).await;")
        lines.append("            }")
        lines.append("        }")
        lines.append("    }")
        
        if scenario.complete_facility:
            lines.append("")
            lines.append("    // Pay remaining and complete")
            lines.append("    loop {")
            lines.append("        let facility = app")
            lines.append("            .credit()")
            lines.append("            .facilities()")
            lines.append("            .find_by_id(&sub, cf_id)")
            lines.append("            .await?")
            lines.append('            .expect("facility exists");')
            lines.append("")
            lines.append("        if facility.interest_accrual_cycle_in_progress().is_some() {")
            lines.append("            tokio::time::sleep(EVENT_WAIT_TIMEOUT).await;")
            lines.append("            continue;")
            lines.append("        }")
            lines.append("")
            lines.append("        let total_outstanding = app.credit().outstanding(&facility).await?;")
            lines.append("        if total_outstanding.is_zero() {")
            lines.append("            break;")
            lines.append("        }")
            lines.append("")
            lines.append("        app.record_payment_with_date(&sub, cf_id, total_outstanding, clock.today())")
            lines.append("            .await?;")
            lines.append("        tokio::time::sleep(EVENT_WAIT_TIMEOUT).await;")
            lines.append("    }")
            lines.append("")
            lines.append("    let _facility = app.credit().complete_facility(&sub, cf_id).await?;")
        
        return "\n".join(lines)
    
    def _generate_custom_behavior_loop(self, scenario: Scenario) -> str:
        """Generate loop with custom payment behavior."""
        behavior = scenario.obligation_behavior
        rules = behavior.rules
        
        # Determine the pattern
        has_interest_skip = any(r.match_type == "interest" and r.action in ("skip", "skip_until", "delay") for r in rules)
        has_principal_skip = any(r.match_type == "principal" and r.action in ("skip", "accumulate") for r in rules)
        has_delay = any(r.delay_days > 0 for r in rules)
        
        if has_principal_skip and not has_interest_skip:
            return self._generate_principal_skip_loop(scenario)
        elif has_interest_skip and has_delay:
            return self._generate_interest_delay_loop(scenario)
        elif has_delay:
            return self._generate_delay_loop(scenario)
        else:
            return self._generate_pay_immediately_loop(scenario)
    
    def _generate_principal_skip_loop(self, scenario: Scenario) -> str:
        """Generate loop that pays interest but skips principal (principal_under_payment pattern)."""
        lines = []
        
        lines.append("    let mut principal_remaining = UsdCents::ZERO;")
        lines.append("    let mut scenario_done = false;")
        lines.append("")
        lines.append("    while !scenario_done {")
        lines.append("        tokio::select! {")
        lines.append("            Some(msg) = stream.next() => {")
        lines.append("                if let Some(LanaEvent::CreditCollection(CoreCreditCollectionEvent::ObligationDue {")
        lines.append("                    entity,")
        lines.append("                })) = &msg.payload")
        lines.append("                    && CreditFacilityId::from(entity.beneficiary_id) == cf_id")
        lines.append("                    && entity.outstanding_amount > UsdCents::ZERO")
        lines.append("                {")
        lines.append("                    msg.inject_trace_parent();")
        lines.append("")
        lines.append("                    if entity.obligation_type == ObligationType::Interest {")
        lines.append("                        let _ = app.record_payment_with_date(&sub, cf_id, entity.outstanding_amount, clock.today())")
        lines.append("                            .await;")
        lines.append("                    } else {")
        lines.append("                        // Accumulate principal - don't pay")
        lines.append("                        principal_remaining += entity.outstanding_amount;")
        lines.append("                    }")
        lines.append("                }")
        lines.append("            }")
        lines.append("            _ = tokio::time::sleep(EVENT_WAIT_TIMEOUT) => {")
        lines.append("                clock_ctrl.advance(ONE_DAY).await;")
        lines.append("")
        lines.append("                if principal_remaining > UsdCents::ZERO {")
        lines.append("                    let facility = app.credit().facilities().find_by_id(&sub, cf_id).await?.unwrap();")
        lines.append("                    let total_outstanding = app.credit().outstanding(&facility).await?;")
        lines.append("")
        lines.append("                    if total_outstanding == principal_remaining {")
        lines.append("                        scenario_done = true;")
        lines.append("                    }")
        lines.append("                }")
        lines.append("            }")
        lines.append("        }")
        lines.append("    }")
        lines.append("")
        lines.append("    event!(")
        lines.append("        tracing::Level::INFO,")
        lines.append("        facility_id = %cf_id,")
        lines.append("        principal_outstanding = %principal_remaining,")
        lines.append('        "Scenario completed - facility active with unpaid principal"')
        lines.append("    );")
        
        return "\n".join(lines)
    
    def _generate_interest_delay_loop(self, scenario: Scenario) -> str:
        """Generate loop that delays first interest payment (interest_late pattern)."""
        behavior = scenario.obligation_behavior
        delay_days = 90  # Default
        for rule in behavior.rules:
            if rule.match_type == "interest" and rule.delay_days > 0:
                delay_days = rule.delay_days
                break
        
        lines = []
        
        lines.append(f"    let expected_end_date = activation_date + chrono::Duration::days({scenario.expected_duration_days or 200});")
        lines.append("")
        lines.append("    let mut first_interest_amount: Option<UsdCents> = None;")
        lines.append("    let mut first_interest_due_date: Option<chrono::NaiveDate> = None;")
        lines.append("    let mut first_interest_paid = false;")
        lines.append("")
        lines.append("    loop {")
        lines.append("        clock_ctrl.advance(ONE_DAY).await;")
        lines.append("        let current_date = clock.today();")
        lines.append("")
        lines.append("        loop {")
        lines.append("            tokio::select! {")
        lines.append("                Some(msg) = stream.next() => {")
        lines.append("                    if let Some(LanaEvent::CreditCollection(CoreCreditCollectionEvent::ObligationDue {")
        lines.append("                        entity,")
        lines.append("                    })) = &msg.payload")
        lines.append("                        && CreditFacilityId::from(entity.beneficiary_id) == cf_id")
        lines.append("                        && entity.outstanding_amount > UsdCents::ZERO")
        lines.append("                    {")
        lines.append("                        msg.inject_trace_parent();")
        lines.append("")
        lines.append("                        if entity.obligation_type == ObligationType::Interest")
        lines.append("                            && first_interest_amount.is_none()")
        lines.append("                        {")
        lines.append("                            // Skip first interest - save for later")
        lines.append("                            first_interest_amount = Some(entity.outstanding_amount);")
        lines.append("                            first_interest_due_date = Some(current_date);")
        lines.append("                        } else {")
        lines.append("                            // Pay all others immediately")
        lines.append("                            app.record_payment_with_date(&sub, cf_id, entity.outstanding_amount, current_date)")
        lines.append("                                .await?;")
        lines.append("                        }")
        lines.append("                    }")
        lines.append("                }")
        lines.append("                _ = tokio::time::sleep(EVENT_WAIT_TIMEOUT) => {")
        lines.append("                    break;")
        lines.append("                }")
        lines.append("            }")
        lines.append("        }")
        lines.append("")
        lines.append(f"        // Pay first interest after {delay_days} days")
        lines.append("        if !first_interest_paid")
        lines.append("            && let (Some(amount), Some(due_date)) = (first_interest_amount, first_interest_due_date)")
        lines.append(f"            && (current_date - due_date).num_days() > {delay_days}")
        lines.append("        {")
        lines.append("            app.record_payment_with_date(&sub, cf_id, amount, current_date)")
        lines.append("                .await?;")
        lines.append("            first_interest_paid = true;")
        lines.append("        }")
        lines.append("")
        lines.append("        if current_date >= expected_end_date {")
        lines.append("            break;")
        lines.append("        }")
        lines.append("    }")
        
        if scenario.complete_facility:
            lines.append("")
            lines.append("    // Pay remaining and complete")
            lines.append("    loop {")
            lines.append("        let facility = app")
            lines.append("            .credit()")
            lines.append("            .facilities()")
            lines.append("            .find_by_id(&sub, cf_id)")
            lines.append("            .await?")
            lines.append('            .expect("facility exists");')
            lines.append("")
            lines.append("        if facility.interest_accrual_cycle_in_progress().is_some() {")
            lines.append("            tokio::time::sleep(EVENT_WAIT_TIMEOUT).await;")
            lines.append("            continue;")
            lines.append("        }")
            lines.append("")
            lines.append("        let total_outstanding = app.credit().outstanding(&facility).await?;")
            lines.append("        if total_outstanding.is_zero() {")
            lines.append("            break;")
            lines.append("        }")
            lines.append("")
            lines.append("        app.record_payment_with_date(&sub, cf_id, total_outstanding, clock.today())")
            lines.append("            .await?;")
            lines.append("        tokio::time::sleep(EVENT_WAIT_TIMEOUT).await;")
            lines.append("    }")
            lines.append("")
            lines.append("    let _facility = app.credit().complete_facility(&sub, cf_id).await?;")
        
        return "\n".join(lines)
    
    def _generate_delay_loop(self, scenario: Scenario) -> str:
        """Generate loop with general delay pattern (principal_late pattern)."""
        # This is the most complex pattern - simplified version
        return self._generate_pay_immediately_loop(scenario)
    
    def generate_mod_rs(self, scenarios: list[Scenario]) -> str:
        """Generate the mod.rs file for all scenarios."""
        template = self.env.get_template("mod.rs.j2")
        return template.render(scenarios=scenarios)

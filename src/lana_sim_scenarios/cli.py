"""CLI for lana-sim-scenarios."""

import click
import shutil
from pathlib import Path

from .generator import ScenarioParser, RustGenerator, Scenario


@click.group()
def cli():
    """Convert YAML scenarios to lana-bank sim-bootstrap Rust code."""
    pass


@cli.command()
@click.argument("scenario_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Output .rs file path")
def convert(scenario_path: str, output: str | None):
    """Convert a single YAML scenario to Rust code."""
    parser = ScenarioParser()
    generator = RustGenerator()
    
    scenario = parser.parse_file(Path(scenario_path))
    rust_code = generator.generate_rust(scenario)
    
    if output:
        Path(output).write_text(rust_code)
        click.echo(f"Generated: {output}")
    else:
        click.echo(rust_code)


@cli.command("convert-all")
@click.argument("scenarios_dir", type=click.Path(exists=True))
@click.argument("output_dir", type=click.Path())
@click.option("--clean", is_flag=True, help="Clean output directory first")
def convert_all(scenarios_dir: str, output_dir: str, clean: bool):
    """Convert all YAML scenarios to Rust code."""
    parser = ScenarioParser()
    generator = RustGenerator()
    
    scenarios_path = Path(scenarios_dir)
    output_path = Path(output_dir)
    
    if clean and output_path.exists():
        shutil.rmtree(output_path)
    
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Find all YAML files
    yaml_files = sorted(scenarios_path.rglob("*.yml"))
    
    click.echo(f"Converting {len(yaml_files)} scenarios...")
    
    scenarios: list[Scenario] = []
    failed = []
    
    for yaml_file in yaml_files:
        try:
            scenario = parser.parse_file(yaml_file)
            scenarios.append(scenario)
            
            # Generate Rust file
            rust_code = generator.generate_rust(scenario)
            rust_file = output_path / f"{scenario.module_name}.rs"
            rust_file.write_text(rust_code)
            
            click.echo(f"  ✓ {yaml_file.name} → {rust_file.name}")
        except Exception as e:
            failed.append((yaml_file.name, str(e)))
            click.echo(f"  ✗ {yaml_file.name}: {e}")
    
    # Generate mod.rs
    if scenarios:
        mod_rs = generator.generate_mod_rs(scenarios)
        mod_file = output_path / "mod.rs"
        mod_file.write_text(mod_rs)
    
    click.echo(f"\nGenerated {len(scenarios)} scenario modules")
    if failed:
        click.echo(f"Failed: {len(failed)}")
    click.echo(f"Output: {output_path}")


@cli.command()
@click.argument("scenario_path", type=click.Path(exists=True))
def analyze(scenario_path: str):
    """Analyze a scenario and show the parsed structure."""
    parser = ScenarioParser()
    
    scenario = parser.parse_file(Path(scenario_path))
    
    click.echo(f"Scenario: {scenario.name}")
    click.echo(f"Description: {scenario.description}")
    click.echo(f"Customer suffix: {scenario.customer_suffix}")
    click.echo(f"")
    click.echo("Amounts:")
    click.echo(f"  Facility: ${scenario.facility_amount_usd:,}")
    click.echo(f"  Deposit: ${scenario.deposit_amount_usd:,}")
    click.echo(f"  Collateral: {scenario.collateral_btc} BTC")
    click.echo("")
    click.echo("Terms:")
    click.echo(f"  Duration: {scenario.terms.duration_months} months")
    click.echo(f"  Annual rate: {scenario.terms.annual_rate}%")
    click.echo(f"  Disbursal policy: {scenario.terms.disbursal_policy}")
    click.echo(f"  Helper: {scenario.terms.to_helper_name() or '(custom)'}")
    click.echo("")
    click.echo("Behavior:")
    click.echo(f"  Obligation handling: {scenario.obligation_behavior.behavior}")
    if scenario.obligation_behavior.rules:
        click.echo("  Rules:")
        for rule in scenario.obligation_behavior.rules:
            click.echo(f"    - match {rule.match_type}: {rule.action}")
            if rule.delay_days:
                click.echo(f"      delay: {rule.delay_days} days")
    click.echo(f"  Complete facility: {scenario.complete_facility}")
    if scenario.start_offset_days:
        click.echo(f"  Start offset: {scenario.start_offset_days} days")
    if scenario.expected_duration_days:
        click.echo(f"  Expected duration: {scenario.expected_duration_days} days")
    click.echo("")
    click.echo(f"Steps: {len(scenario.steps)}")
    for i, step in enumerate(scenario.steps, 1):
        click.echo(f"  {i:2}. {step.action}")


@cli.command("list-scenarios")
@click.argument("scenarios_dir", type=click.Path(exists=True), default="scenarios")
def list_scenarios(scenarios_dir: str):
    """List all available scenarios."""
    parser = ScenarioParser()
    scenarios_path = Path(scenarios_dir)
    
    yaml_files = sorted(scenarios_path.rglob("*.yml"))
    
    click.echo(f"Found {len(yaml_files)} scenarios:\n")
    
    for yaml_file in yaml_files:
        try:
            scenario = parser.parse_file(yaml_file)
            rel_path = yaml_file.relative_to(scenarios_path)
            click.echo(f"  {rel_path}")
            click.echo(f"    → {scenario.name}: {scenario.description[:60]}...")
        except Exception as e:
            click.echo(f"  {yaml_file} (error: {e})")


@cli.command("show-rust")
@click.argument("scenario_path", type=click.Path(exists=True))
def show_rust(scenario_path: str):
    """Show generated Rust code for a scenario."""
    parser = ScenarioParser()
    generator = RustGenerator()
    
    scenario = parser.parse_file(Path(scenario_path))
    rust_code = generator.generate_rust(scenario)
    
    click.echo(rust_code)


def main():
    cli()


if __name__ == "__main__":
    main()

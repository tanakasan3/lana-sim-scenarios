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
            click.echo(f"  ✗ {yaml_file.name}: {e}")
    
    # Generate mod.rs
    mod_rs = generator.generate_mod_rs(scenarios)
    mod_file = output_path / "mod.rs"
    mod_file.write_text(mod_rs)
    
    click.echo(f"\nGenerated {len(scenarios)} scenario modules")
    click.echo(f"Output: {output_path}")
    click.echo(f"\nTo use: copy to lana-bank/lana/sim-bootstrap/src/scenarios/generated/")


@cli.command()
@click.argument("scenario_path", type=click.Path(exists=True))
def analyze(scenario_path: str):
    """Analyze a scenario and show the sim-bootstrap actions."""
    parser = ScenarioParser()
    generator = RustGenerator()
    
    scenario = parser.parse_file(Path(scenario_path))
    actions = generator.convert_scenario(scenario)
    
    click.echo(f"Scenario: {scenario.name}")
    click.echo(f"Description: {scenario.description}")
    click.echo(f"Start: {scenario.start_time}")
    click.echo(f"Events: {len(scenario.events)}")
    click.echo(f"\nActions ({len(actions)}):")
    
    for i, action in enumerate(actions, 1):
        wait_info = f" (wait {action.wait_days}d)" if action.wait_days else ""
        click.echo(f"  {i:2}. {action.action_type}: {action.entity}{wait_info}")


@cli.command("list-mappings")
def list_mappings():
    """List all event-to-action mappings."""
    generator = RustGenerator()
    
    click.echo("Event → Action Mappings:\n")
    
    by_action = {}
    for event, action in sorted(generator.EVENT_TO_ACTION.items()):
        if action not in by_action:
            by_action[action] = []
        by_action[action].append(event)
    
    for action in sorted(by_action.keys()):
        click.echo(f"{action}:")
        for event in sorted(by_action[action]):
            click.echo(f"  - {event}")
        click.echo()


def main():
    cli()


if __name__ == "__main__":
    main()

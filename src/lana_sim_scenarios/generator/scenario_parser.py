"""Parse YAML scenario files into structured data."""

import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any


@dataclass
class ScenarioEvent:
    """A single event in a scenario."""
    event_type: str      # e.g., "CustomerEvent::Initialized"
    entity: str          # e.g., "customer_1"
    after: timedelta     # Time offset from previous event
    values: dict         # Event-specific values
    
    @property
    def enum_name(self) -> str:
        """Get the enum name (e.g., 'CustomerEvent')."""
        return self.event_type.split("::")[0]
    
    @property
    def variant_name(self) -> str:
        """Get the variant name (e.g., 'Initialized')."""
        return self.event_type.split("::")[1]


@dataclass
class Scenario:
    """A complete scenario definition."""
    name: str
    description: str
    seed: int
    start_time: datetime
    events: list[ScenarioEvent] = field(default_factory=list)
    
    @property
    def fn_name(self) -> str:
        """Get the Rust function name."""
        # Convert to snake_case
        return re.sub(r'[^a-z0-9]+', '_', self.name.lower()).strip('_')
    
    @property
    def module_name(self) -> str:
        """Get the Rust module name."""
        return self.fn_name


class ScenarioParser:
    """Parse YAML scenario files."""
    
    def parse_file(self, path: Path) -> Scenario:
        """Parse a single scenario file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return self.parse_dict(data)
    
    def parse_dict(self, data: dict) -> Scenario:
        """Parse scenario from a dictionary."""
        events = []
        for event_def in data.get("events", []):
            events.append(self._parse_event(event_def))
        
        return Scenario(
            name=data.get("name", "unnamed"),
            description=data.get("description", ""),
            seed=data.get("seed", 0),
            start_time=self._parse_datetime(data.get("start_time", "2024-01-01T09:00:00Z")),
            events=events,
        )
    
    def _parse_event(self, event_def: dict) -> ScenarioEvent:
        """Parse a single event definition."""
        return ScenarioEvent(
            event_type=event_def["event"],
            entity=event_def["entity"],
            after=self._parse_duration(event_def.get("after", "0m")),
            values=event_def.get("values", {}),
        )
    
    def _parse_duration(self, duration_str: str) -> timedelta:
        """Parse duration string like '24h', '30d', '5m'."""
        if not duration_str:
            return timedelta()
        
        match = re.match(r"(\d+)([smhd])", duration_str)
        if not match:
            return timedelta()
        
        value = int(match.group(1))
        unit = match.group(2)
        
        if unit == "s":
            return timedelta(seconds=value)
        elif unit == "m":
            return timedelta(minutes=value)
        elif unit == "h":
            return timedelta(hours=value)
        elif unit == "d":
            return timedelta(days=value)
        
        return timedelta()
    
    def _parse_datetime(self, dt_str: str) -> datetime:
        """Parse ISO datetime string."""
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))

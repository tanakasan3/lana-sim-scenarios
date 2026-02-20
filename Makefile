.PHONY: help dev install clean convert-all analyze lint test

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
CLI := $(VENV)/bin/lana-sim

# Paths
SCENARIO_GEN_REPO := ../lana-scenario-gen
LANA_BANK_REPO := ../lana-bank
OUTPUT_DIR := output/generated_scenarios

help:
	@echo "lana-sim-scenarios - Convert YAML to sim-bootstrap Rust"
	@echo ""
	@echo "Usage:"
	@echo "  make dev            Create venv and install"
	@echo "  make convert-all    Convert all scenarios from lana-scenario-gen"
	@echo "  make analyze        Analyze scenario mappings"
	@echo "  make deploy         Copy generated code to lana-bank"
	@echo "  make patch          Deploy + patch lana-bank to call generated scenarios"
	@echo "  make unpatch        Remove patch from lana-bank"
	@echo "  make clean          Remove venv and outputs"
	@echo ""
	@echo "Single scenario:"
	@echo "  make convert SCENARIO=path/to/scenario.yml"

dev: $(VENV)/bin/activate
	@echo "✓ Dev environment ready. Activate with: source $(VENV)/bin/activate"

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	@touch $(VENV)/bin/activate

# Convert single scenario
convert: $(VENV)/bin/activate
ifndef SCENARIO
	@echo "Error: SCENARIO not set"
	@echo "Usage: make convert SCENARIO=path/to/scenario.yml"
	@exit 1
endif
	$(CLI) convert $(SCENARIO)

# Convert all scenarios from lana-scenario-gen
convert-all: $(VENV)/bin/activate
	@if [ ! -d "$(SCENARIO_GEN_REPO)/scenarios" ]; then \
		echo "Error: $(SCENARIO_GEN_REPO)/scenarios not found"; \
		echo "Clone lana-scenario-gen first"; \
		exit 1; \
	fi
	$(CLI) convert-all $(SCENARIO_GEN_REPO)/scenarios $(OUTPUT_DIR) --clean
	@echo ""
	@echo "Generated Rust code in: $(OUTPUT_DIR)/"
	@ls -la $(OUTPUT_DIR)/

# Analyze a scenario
analyze: $(VENV)/bin/activate
ifndef SCENARIO
	@echo "Analyzing first loan scenario..."
	$(CLI) analyze $(SCENARIO_GEN_REPO)/scenarios/loan/01_happy_path.yml
else
	$(CLI) analyze $(SCENARIO)
endif

# List event mappings
mappings: $(VENV)/bin/activate
	$(CLI) list-mappings

# Deploy to lana-bank
deploy: $(VENV)/bin/activate convert-all
	@if [ ! -d "$(LANA_BANK_REPO)/lana/sim-bootstrap/src/scenarios" ]; then \
		echo "Error: $(LANA_BANK_REPO) not found"; \
		exit 1; \
	fi
	@mkdir -p $(LANA_BANK_REPO)/lana/sim-bootstrap/src/scenarios/generated
	cp -r $(OUTPUT_DIR)/* $(LANA_BANK_REPO)/lana/sim-bootstrap/src/scenarios/generated/
	@echo "✓ Deployed to $(LANA_BANK_REPO)/lana/sim-bootstrap/src/scenarios/generated/"

# Patch lana-bank to call generated scenarios
SCENARIOS_MOD := $(LANA_BANK_REPO)/lana/sim-bootstrap/src/scenarios/mod.rs

patch: deploy
	@if grep -q "mod generated;" "$(SCENARIOS_MOD)"; then \
		echo "Already patched"; \
	else \
		echo "Patching $(SCENARIOS_MOD)..."; \
		sed -i '/^mod timely_payments;/a mod generated;' "$(SCENARIOS_MOD)"; \
		awk '/interest_under_payment_scenario.*\)$$/{found=1} found && /\.await\?;/{print; print "    generated::run(sub, app, clock, clock_ctrl).await?;"; found=0; next} 1' \
			"$(SCENARIOS_MOD)" > "$(SCENARIOS_MOD).tmp" && mv "$(SCENARIOS_MOD).tmp" "$(SCENARIOS_MOD)"; \
		echo "✓ Patched lana-bank to include generated scenarios"; \
	fi

# Undo patch
unpatch:
	@if grep -q "mod generated;" "$(SCENARIOS_MOD)"; then \
		echo "Removing patch from $(SCENARIOS_MOD)..."; \
		sed -i '/^mod generated;$$/d' "$(SCENARIOS_MOD)"; \
		sed -i '/generated::run(sub, app, clock, clock_ctrl)/d' "$(SCENARIOS_MOD)"; \
		echo "✓ Removed generated scenario integration"; \
	else \
		echo "Not patched, nothing to undo"; \
	fi

# Lint
lint: $(VENV)/bin/activate
	$(VENV)/bin/ruff check src/
	$(VENV)/bin/black --check src/

# Format
fmt: $(VENV)/bin/activate
	$(VENV)/bin/black src/
	$(VENV)/bin/ruff check --fix src/

# Clean
clean:
	rm -rf $(VENV)
	rm -rf $(OUTPUT_DIR)
	rm -rf dist/ build/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

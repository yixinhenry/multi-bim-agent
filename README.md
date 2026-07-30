# BIM Multi-Agent IFC Collaboration Platform

An experimental multi-agent IFC collaboration platform for BIM AI security
research. It provides isolated Client, Project Manager, ARC, STR, and MEP
conversations and records deviations from prompt-declared role boundaries.

## Current capabilities

- Current `ARC.ifc`, `STR.ifc`, and `MEP.ifc` files per project
- Optional `Cost.csv` and `Schedule.csv` with audited summary, query, and IFC mapping tools
- Isolated main conversations and task-specific specialist conversations
- Persistent Project Manager delegation to ARC, STR, and MEP Agents
- Structured task status, result, error, Agent, and target-file records
- Single-discipline and federated That Open Fragments views
- IFC selection context mapped back to GlobalId and STEP id
- `read_ifc`, `query_ifc`, `edit_ifc`, and `run_clash_detection` tools
- Isolated ifcMCP edit sessions with function documentation and audit; no function permission list
- World-coordinate AABB clash-candidate detection across uploaded discipline models
- Deduplicated clash Issues linked to remediation tasks
- Project-and-identity-specific editable system prompts
- Prompt-controlled internal Agent boundaries with `boundary_violation` audit records
- Pytest coverage for storage, delegation, ifcMCP isolation, and CSV tools

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Run the automated checks:

```bash
pytest -q
```

Set `DEEPSEEK_API_KEY` in `.env`, then build the Viewer:

```bash
cd viewer
npm install
npm run build
cd ..
```

Run the platform:

```bash
streamlit run app.py
```

Project management and Viewer features remain usable without a model API key.

## Research boundary

The application keeps fixed user routing and Viewer model scope. Internal Agent
tool boundaries are prompt-controlled: calls execute and are written to
`audit_events`, including `boundary_violation`. This is an experimental system.

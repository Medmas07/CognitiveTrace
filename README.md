# Behavior User Collecting

Behavior User Collecting is a desktop-plus-browser instrumentation project for collecting behavioral data, transforming it into window features, and building temporal transition graphs.

The repository currently centers on [`cognitive_system/`](cognitive_system/README.md), which contains:

- a Windows system agent for app focus, keyboard, mouse, notification, system, and dual-task collection
- a Chrome extension (`browser_agent_v2/`) for browser-side activity
- a feature engineering pipeline that produces window features and event-based temporal graphs
- a Tkinter viewer that shows one session as a table of window graphs

## What This Project Produces

For each session, the runtime collectors can write raw CSV streams such as:

- `behavior.csv`
- `keyboard.csv`
- `mouse.csv`
- `dual_task.csv`
- `notification.csv`
- `system_metrics.csv`
- `labels.csv`

The analysis pipeline then generates:

- `features/features_<window>.csv`
- `graph/nodes.csv`
- `graph/edges.csv`
- `graph/temporal_edges.csv`
- `graph/windows/<window>/...`
- `graph/communities.csv` when clustering is available

## Important Graph Note

The graph system is now a true temporal transition graph:

- nodes represent user states such as app, domain, or URL
- edges come from sequential events: `event[i] -> event[i+1]`
- windows are used only for slicing and feature extraction
- windows are never graph nodes

## Repository Layout

```text
Behavior User Collecting/
|- README.md
|- Architecture.md
|- cognitive_system/
|  |- README.md
|  |- HOW_TO_RUN.md
|  |- requirements.txt
|  |- setup.py
|  |- data/
|  |- browser_agent_v2/
|  |- system_agent/
|  `- feature_engineering/
`- .env.example
```

## Quick Start

From the repository root:

```powershell
cd cognitive_system
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Start the collector:

```powershell
.\.venv\Scripts\python system_agent\main.py
```

Run the analysis pipeline for a completed session:

```powershell
.\.venv\Scripts\python -m feature_engineering.pipeline <session_id> --graph-node-level app
```

Open the window-graph viewer:

```powershell
.\.venv\Scripts\python -m feature_engineering.graph_viewer --session-id <session_id> --window-label 30s
```

## Documentation

- Runtime and module overview: [cognitive_system/README.md](cognitive_system/README.md)
- Step-by-step usage: [cognitive_system/HOW_TO_RUN.md](cognitive_system/HOW_TO_RUN.md)
- Full architecture and diagrams: [Architecture.md](Architecture.md)

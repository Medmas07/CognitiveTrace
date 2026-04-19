# Local Behavior Collection to InfluxDB v2

This project contains two collectors that write raw behavioral events directly to InfluxDB v2 using line protocol (no JSON storage layer):

- `system_agent/`: desktop app focus/switch collector in Python
- `extension/`: Chrome extension for browser tab/scroll tracking with idle detection (5 min inactivity)

## 1) Configure Environment

1. Copy `.env.example` to `.env`.
2. Fill in:
   - `INFLUX_URL`
   - `INFLUX_TOKEN`
   - `INFLUX_ORG`
   - `INFLUX_BUCKET`

For the extension, copy the same env file into `extension/.env`:

```powershell
Copy-Item .env extension/.env
```

## 2) Run System Agent

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r system_agent/requirements.txt
python system_agent/main.py
# Optional bounded session (example: 45 minutes)
python system_agent/main.py --session-minutes 45
```

## 3) Load Chrome Extension

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select the `extension/` folder.

## 4) Verify in InfluxDB

You can verify writes in Influx Data Explorer or with Flux:

```flux
from(bucket: "YOUR_BUCKET")
  |> range(start: -15m)
  |> filter(fn: (r) => r._measurement == "behavior_events")
  |> sort(columns: ["_time"], desc: true)
```

## Event Tags and Fields

Common tags:
- `user_id` (`u1`)
- `source_type` (`app` or `tab`)
- `event_type` (`focus`, `switch`, `idle`, `scroll`)

Additional tags:
- System agent: `app_name`
- Browser agent: `domain`

Common fields include:
- `duration`
- `scroll_delta`
- `scroll_depth`

## Parameters of system agent
### InfluxBatchClient

url=influx_url
Adresse de ton InfluxDB (ex: http://localhost:8086).

token=influx_token
Jeton d’authentification pour écrire dans InfluxDB.

org=influx_org
Nom de l’organisation InfluxDB.

bucket=influx_bucket
Nom du bucket où les points sont stockés.

batch_size=100
Dès que le buffer atteint 100 événements, envoi immédiat vers InfluxDB.

flush_interval=3.0
Même si le batch n’a pas 100 événements, il force un envoi toutes les 3 secondes.

max_retries=3
Si l’envoi échoue (réseau/API), il réessaie jusqu’à 3 fois.

request_timeout=10.0
Chaque requête HTTP attend max 10 secondes avant timeout.

### BehaviorCollector

influx_client=influx_client
Le collector utilise ce client pour pousser les événements vers InfluxDB.

user_id="u1"
Identifiant utilisateur écrit en tag dans chaque événement.

poll_interval=0.5
Toutes les 0,5 secondes, il vérifie quelle app est active (Chrome, Code, etc.).

emit_interval=30.0
S’il n’y a pas de switch, il génère un événement toutes les 30 secondes pour l’app courante.

merge_flush_threshold=30.0
Il fusionne les segments continus d’une même app, puis les flush quand la durée fusionnée atteint 30s (ou plus tôt si switch/shutdown).

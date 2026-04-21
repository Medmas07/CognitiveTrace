1. Start InfluxDB


cd cognitive_system
docker compose up -d
2. Install Python deps


python setup.py
3. Start the system agent


.venv/Scripts/python system_agent/main.py
4. Load the extension in Chrome: chrome://extensions → Developer mode → Load unpacked → select browser_agent_v2/

5. Start a session — type s in the terminal. The popup shows live elapsed/remaining time (sourced exclusively from the system agent). At session end, a new browser tab opens with the full questionnaire.

Key architecture rules enforced:

Session timing lives only in session_manager.py — extension never computes it
Questionnaire opens as a full browser tab (open_questionnaire → chrome.tabs.create)
One event = one CSV row + one InfluxDB point, written atomically
Extension state survives service-worker restarts via chrome.storage.session
Scroll events are accumulated per-tab and flushed only on scroll pause or tab hide
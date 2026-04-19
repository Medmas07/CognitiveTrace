const USER_ID = "u1";
const SOURCE_TYPE = "tab";
const MEASUREMENT = "behavior_events";

const FLUSH_INTERVAL_MS = 3000;
const HEARTBEAT_INTERVAL_MS = 30000;
const IDLE_THRESHOLD_MS = 5 * 60 * 1000;
const MAX_BATCH_SIZE = 100;
const MAX_BUFFER_EVENTS = 3000;
const MAX_RETRIES = 3;
const RETRY_BASE_DELAY_MS = 1000;
const INTEGER_FIELDS = new Set(["scroll_delta"]);

const REQUIRED_ENV_KEYS = [
  "INFLUX_URL",
  "INFLUX_TOKEN",
  "INFLUX_ORG",
  "INFLUX_BUCKET"
];

const eventBuffer = [];
const activeTabByWindow = new Map();

let influxConfig = null;
let flushInProgress = false;
let lastFlushMs = Date.now();

const configLoadPromise = loadInfluxConfig();

function nowNs() {
  return `${BigInt(Date.now()) * 1000000n}`;
}

function parseEnvText(text) {
  const env = {};
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }

    const separatorIndex = trimmed.indexOf("=");
    if (separatorIndex <= 0) {
      continue;
    }

    const key = trimmed.slice(0, separatorIndex).trim();
    let value = trimmed.slice(separatorIndex + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    env[key] = value;
  }
  return env;
}

function hasRequiredConfig(config) {
  return REQUIRED_ENV_KEYS.every((key) => Boolean(config[key]));
}

async function loadInfluxConfig() {
  try {
    const envResponse = await fetch(chrome.runtime.getURL(".env"), {
      cache: "no-store"
    });
    if (envResponse.ok) {
      const envText = await envResponse.text();
      const parsed = parseEnvText(envText);
      if (hasRequiredConfig(parsed)) {
        influxConfig = parsed;
        console.log("Influx config loaded from extension .env");
        return;
      }
    }
  } catch (error) {
    console.warn("Unable to read extension .env:", error);
  }

  const stored = await chrome.storage.local.get(REQUIRED_ENV_KEYS);
  if (hasRequiredConfig(stored)) {
    influxConfig = stored;
    console.log("Influx config loaded from chrome.storage.local");
    return;
  }

  console.error(
    "Influx config missing. Provide extension/.env or save required keys in chrome.storage.local."
  );
}

function extractDomain(url) {
  if (!url) {
    return "unknown";
  }
  try {
    const parsed = new URL(url);
    return parsed.hostname || "unknown";
  } catch (_error) {
    return "unknown";
  }
}

function escapeMeasurement(value) {
  return value.replace(/\\/g, "\\\\").replace(/,/g, "\\,").replace(/ /g, "\\ ");
}

function escapeTag(value) {
  return value
    .replace(/\\/g, "\\\\")
    .replace(/,/g, "\\,")
    .replace(/ /g, "\\ ")
    .replace(/=/g, "\\=");
}

function escapeFieldKey(value) {
  return value.replace(/\\/g, "\\\\").replace(/,/g, "\\,").replace(/ /g, "\\ ");
}

function formatFieldValue(key, value) {
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      return "0";
    }
    if (INTEGER_FIELDS.has(key)) {
      return `${Math.trunc(value)}i`;
    }
    return `${Number(value)}`;
  }

  const text = String(value)
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"');
  return `"${text}"`;
}

function createEvent(domain, eventType, metrics = {}) {
  const safeDomain = domain || "unknown";
  const safeMetrics = {
    duration: Number(metrics.duration || 0),
    scroll_delta: Number(metrics.scroll_delta || 0),
    scroll_depth: Number(metrics.scroll_depth || 0)
  };

  return {
    timestamp_ns: nowNs(),
    tags: {
      user_id: USER_ID,
      source_type: SOURCE_TYPE,
      domain: safeDomain,
      event_type: eventType
    },
    fields: safeMetrics
  };
}

function logEventToConsole(event, details = {}) {
  const eventType = event?.tags?.event_type || "unknown";
  const domain = event?.tags?.domain || "unknown";
  console.info("[Behavior Browser Agent]", {
    event_type: eventType,
    domain,
    tab_id: details.tab_id ?? null,
    window_id: details.window_id ?? null,
    tab_title: details.tab_title ?? "",
    tab_url: details.tab_url ?? "",
    duration: Number(event?.fields?.duration || 0),
    scroll_delta: Number(event?.fields?.scroll_delta || 0),
    scroll_depth: Number(event?.fields?.scroll_depth || 0)
  });
}

function toLineProtocol(event) {
  const measurement = escapeMeasurement(MEASUREMENT);
  const tags = Object.entries(event.tags)
    .map(([key, value]) => `${escapeTag(key)}=${escapeTag(String(value))}`)
    .join(",");

  const fields = Object.entries(event.fields)
    .map(([key, value]) => `${escapeFieldKey(key)}=${formatFieldValue(key, value)}`)
    .join(",");

  return `${measurement},${tags} ${fields} ${event.timestamp_ns}`;
}

function enqueueEvent(event, details = {}) {
  eventBuffer.push(event);
  logEventToConsole(event, details);

  if (eventBuffer.length > MAX_BUFFER_EVENTS) {
    eventBuffer.splice(0, eventBuffer.length - MAX_BUFFER_EVENTS);
  }

  const elapsed = Date.now() - lastFlushMs;
  if (eventBuffer.length >= MAX_BATCH_SIZE || elapsed >= FLUSH_INTERVAL_MS) {
    void flushBuffer();
  }
}

async function writePayload(payload) {
  if (!influxConfig) {
    return false;
  }

  const writeUrl =
    `${influxConfig.INFLUX_URL.replace(/\/$/, "")}/api/v2/write` +
    `?org=${encodeURIComponent(influxConfig.INFLUX_ORG)}` +
    `&bucket=${encodeURIComponent(influxConfig.INFLUX_BUCKET)}` +
    "&precision=ns";

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt += 1) {
    try {
      const response = await fetch(writeUrl, {
        method: "POST",
        headers: {
          Authorization: `Token ${influxConfig.INFLUX_TOKEN}`,
          "Content-Type": "text/plain; charset=utf-8"
        },
        body: payload
      });

      if (response.ok) {
        return true;
      }

      const message = await response.text();
      console.warn(
        `Influx write failed (${attempt}/${MAX_RETRIES})`,
        response.status,
        message
      );
    } catch (error) {
      console.warn(`Influx connection error (${attempt}/${MAX_RETRIES})`, error);
    }

    if (attempt < MAX_RETRIES) {
      const delay = RETRY_BASE_DELAY_MS * Math.pow(2, attempt - 1);
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }

  return false;
}

async function flushBuffer() {
  if (flushInProgress || eventBuffer.length === 0) {
    return;
  }

  flushInProgress = true;

  try {
    await configLoadPromise;
    if (!influxConfig) {
      return;
    }

    const batch = eventBuffer.splice(0, eventBuffer.length);
    if (batch.length === 0) {
      return;
    }

    const payload = batch.map(toLineProtocol).join("\n");
    const ok = await writePayload(payload);
    if (!ok) {
      eventBuffer.unshift(...batch);
      if (eventBuffer.length > MAX_BUFFER_EVENTS) {
        eventBuffer.splice(0, eventBuffer.length - MAX_BUFFER_EVENTS);
      }
    } else {
      lastFlushMs = Date.now();
    }
  } finally {
    flushInProgress = false;
  }
}

function emitDurationHeartbeat() {
  const now = Date.now();

  for (const [windowId, state] of activeTabByWindow.entries()) {
    if (!state) {
      continue;
    }

    const elapsedSec = Math.max((now - state.started_at_ms) / 1000, 0);
    if (elapsedSec < 1) {
      continue;
    }
    const inactiveMs = now - (state.last_activity_ms || state.started_at_ms);
    const eventType = inactiveMs >= IDLE_THRESHOLD_MS ? "idle" : "focus";

    enqueueEvent(
      createEvent(state.domain, eventType, {
        duration: elapsedSec
      }),
      {
        tab_id: state.tab_id,
        window_id: windowId,
        tab_title: state.title || "",
        tab_url: state.url || ""
      }
    );

    state.started_at_ms = now;
    activeTabByWindow.set(windowId, state);
  }
}

async function bootstrapActiveTabs() {
  const tabs = await chrome.tabs.query({ active: true });
  const now = Date.now();
  for (const tab of tabs) {
    if (tab.windowId === chrome.windows.WINDOW_ID_NONE || tab.id == null) {
      continue;
    }
    activeTabByWindow.set(tab.windowId, {
      tab_id: tab.id,
      domain: extractDomain(tab.url),
      url: tab.url || "",
      title: tab.title || "",
      started_at_ms: now,
      last_activity_ms: now
    });
  }
}

async function handleTabActivated(activeInfo) {
  const tab = await chrome.tabs.get(activeInfo.tabId);
  const now = Date.now();
  const domain = extractDomain(tab.url);
  const previous = activeTabByWindow.get(activeInfo.windowId);

  if (previous && previous.tab_id !== activeInfo.tabId) {
    const elapsedSec = Math.max((now - previous.started_at_ms) / 1000, 0);

    enqueueEvent(
      createEvent(previous.domain, "switch", {
        duration: elapsedSec
      }),
      {
        tab_id: previous.tab_id,
        window_id: activeInfo.windowId,
        tab_title: previous.title || "",
        tab_url: previous.url || ""
      }
    );
  }

  activeTabByWindow.set(activeInfo.windowId, {
    tab_id: activeInfo.tabId,
    domain,
    url: tab.url || "",
    title: tab.title || "",
    started_at_ms: now,
    last_activity_ms: now
  });

  enqueueEvent(createEvent(domain, "focus", { duration: 0 }), {
    tab_id: activeInfo.tabId,
    window_id: activeInfo.windowId,
    tab_title: tab.title || "",
    tab_url: tab.url || ""
  });
}

function handleTabUpdated(tabId, changeInfo, tab) {
  if (!tab.active || !changeInfo.url) {
    return;
  }

  const current = activeTabByWindow.get(tab.windowId);
  if (!current || current.tab_id !== tabId) {
    return;
  }

  const newDomain = extractDomain(changeInfo.url);
  if (newDomain === current.domain) {
    return;
  }

  const now = Date.now();
  const elapsedSec = Math.max((now - current.started_at_ms) / 1000, 0);

  enqueueEvent(
    createEvent(current.domain, "switch", {
      duration: elapsedSec
    }),
    {
      tab_id: tabId,
      window_id: tab.windowId,
      tab_title: current.title || "",
      tab_url: current.url || ""
    }
  );

  current.domain = newDomain;
  current.url = tab.url || changeInfo.url || "";
  current.title = tab.title || "";
  current.started_at_ms = now;
  current.last_activity_ms = now;
  activeTabByWindow.set(tab.windowId, current);

  enqueueEvent(createEvent(newDomain, "focus", { duration: 0 }), {
    tab_id: tabId,
    window_id: tab.windowId,
    tab_title: current.title || "",
    tab_url: current.url || ""
  });
}

function handleTabRemoved(tabId, removeInfo) {
  const current = activeTabByWindow.get(removeInfo.windowId);
  if (!current || current.tab_id !== tabId) {
    return;
  }

  const now = Date.now();
  const elapsedSec = Math.max((now - current.started_at_ms) / 1000, 0);

  enqueueEvent(
    createEvent(current.domain, "switch", {
      duration: elapsedSec
    }),
    {
      tab_id: tabId,
      window_id: removeInfo.windowId,
      tab_title: current.title || "",
      tab_url: current.url || ""
    }
  );

  activeTabByWindow.delete(removeInfo.windowId);
}

chrome.tabs.onActivated.addListener((activeInfo) => {
  void handleTabActivated(activeInfo);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  handleTabUpdated(tabId, changeInfo, tab);
});

chrome.tabs.onRemoved.addListener((tabId, removeInfo) => {
  handleTabRemoved(tabId, removeInfo);
});

chrome.runtime.onMessage.addListener((message, sender) => {
  if (!sender.tab || sender.tab.id == null) {
    return;
  }

  const tabId = sender.tab.id;
  const windowId = sender.tab.windowId;
  const tabUrl = sender.tab.url || message?.url || "";
  const tabTitle = sender.tab.title || "";
  const domain = extractDomain(tabUrl);
  const current = activeTabByWindow.get(windowId);
  if (current && current.tab_id === tabId) {
    current.url = tabUrl;
    current.title = tabTitle;
    activeTabByWindow.set(windowId, current);
  }

  if (message?.type === "page_interrupt") {
    if (current && current.tab_id === tabId) {
      const now = Date.now();
      const elapsedSec = Math.max((now - current.started_at_ms) / 1000, 0);
      current.last_activity_ms = now;
      if (elapsedSec >= 1) {
        enqueueEvent(
          createEvent(current.domain, "focus", { duration: elapsedSec }),
          {
            tab_id: tabId,
            window_id: windowId,
            tab_title: tabTitle,
            tab_url: tabUrl
          }
        );
      }
      current.started_at_ms = now;
      activeTabByWindow.set(windowId, current);
    }
    return;
  }

  if (message?.type !== "page_activity") {
    return;
  }

  const scrollDelta = Number(message.scroll_delta || 0);
  const scrollDepth = Number(message.scroll_depth || 0);
  if (scrollDelta !== 0 || scrollDepth > 0) {
    if (current && current.tab_id === tabId) {
      current.last_activity_ms = Date.now();
      activeTabByWindow.set(windowId, current);
    }
    enqueueEvent(
      createEvent(domain, "scroll", {
        scroll_delta: scrollDelta,
        scroll_depth: scrollDepth
      }),
      {
        tab_id: tabId,
        window_id: windowId,
        tab_title: tabTitle,
        tab_url: tabUrl
      }
    );
  }
});

chrome.runtime.onInstalled.addListener(() => {
  void bootstrapActiveTabs();
});

chrome.runtime.onStartup.addListener(() => {
  void bootstrapActiveTabs();
});

void bootstrapActiveTabs();

setInterval(() => {
  void flushBuffer();
}, FLUSH_INTERVAL_MS);

setInterval(() => {
  emitDurationHeartbeat();
}, HEARTBEAT_INTERVAL_MS);

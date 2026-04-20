/**
 * Popup controller.
 *
 * Extension pages support ES modules natively — no bundler needed here.
 * Communicates with the service worker via chrome.runtime.sendMessage.
 *
 * InfluxDB credentials are stored in chrome.storage.local (never hardcoded).
 * The settings panel lets the researcher enter them once; they persist across
 * browser restarts.
 */

const STORAGE_CONFIG_KEY = 'influx_config';

// ── DOM refs ──────────────────────────────────────────────────────────────────
const dot          = document.getElementById('state-dot');
const statusPanel  = document.getElementById('status-panel');
const startForm    = document.getElementById('start-form');
const btnStart     = document.getElementById('btn-start');
const btnStop      = document.getElementById('btn-stop');
const inpDur       = document.getElementById('inp-duration');
const inpUid       = document.getElementById('inp-uid');
const statusState  = document.getElementById('status-state');
const statusSid    = document.getElementById('status-sid');
const statusTime   = document.getElementById('status-time');
const errorMsg     = document.getElementById('error-msg');

// Settings panel
const btnToggle    = document.getElementById('btn-toggle-settings');
const settingsPane = document.getElementById('settings-panel');
const cfgUrl       = document.getElementById('cfg-url');
const cfgToken     = document.getElementById('cfg-token');
const cfgOrg       = document.getElementById('cfg-org');
const cfgBucket    = document.getElementById('cfg-bucket');
const btnSaveCfg   = document.getElementById('btn-save-cfg');
const cfgSavedMsg  = document.getElementById('cfg-saved-msg');
const tokenBadge   = document.getElementById('token-status');

// ── State ─────────────────────────────────────────────────────────────────────
let statusInterval = null;

// ── Init ──────────────────────────────────────────────────────────────────────
loadConfig().then(renderConfig);
refreshStatus();

// ── Event listeners ────────────────────────────────────────────────────────────
btnStart.addEventListener('click',     onStartClick);
btnStop.addEventListener('click',      onStopClick);
btnToggle.addEventListener('click',    toggleSettings);
btnSaveCfg.addEventListener('click',   onSaveConfig);

// ── Session functions ─────────────────────────────────────────────────────────

async function onStartClick() {
  clearError();

  const cfg = await loadConfig();
  if (!cfg.TOKEN) {
    showError('InfluxDB token is not set. Open ⚙ settings below.');
    settingsPane.style.display = 'block';
    cfgToken.focus();
    return;
  }

  const duration = parseInt(inpDur.value, 10);
  const userId   = inpUid.value.trim() || 'anonymous';

  if (!duration || duration < 1 || duration > 180) {
    showError('Duration must be 1–180 minutes.');
    return;
  }

  btnStart.disabled = true;

  const res = await send({
    type:    'START_SESSION',
    payload: { duration_minutes: duration, user_id: userId },
  });

  if (res?.ok) {
    refreshStatus();
    startPolling();
  } else {
    showError('Could not start session. Check the service worker.');
    btnStart.disabled = false;
  }
}

async function onStopClick() {
  btnStop.disabled = true;
  await send({ type: 'STOP_SESSION' });
  stopPolling();
  refreshStatus();
  btnStop.disabled = false;
}

async function refreshStatus() {
  const status = await send({ type: 'GET_STATUS' });
  if (!status) return;

  const active = ['running', 'hidden', 'background', 'idle'].includes(status.state);

  dot.className = `dot ${status.state}`;

  if (active) {
    startForm.style.display = 'none';
    btnStop.style.display   = 'block';
    statusPanel.classList.add('visible');

    statusState.textContent = status.state;
    statusSid.textContent   = status.session_id
      ? status.session_id.slice(0, 8) + '…'
      : '—';

    if (status.session_start_ms && status.session_duration_ms) {
      const remaining = Math.max(
        0,
        status.session_duration_ms - (Date.now() - status.session_start_ms),
      );
      statusTime.textContent = formatDuration(remaining);
    }

    startPolling();
  } else {
    startForm.style.display = '';
    btnStop.style.display   = 'none';
    btnStart.disabled       = false;
    statusPanel.classList.remove('visible');
    stopPolling();
  }
}

function startPolling() {
  if (statusInterval) return;
  statusInterval = setInterval(refreshStatus, 3_000);
}

function stopPolling() {
  if (!statusInterval) return;
  clearInterval(statusInterval);
  statusInterval = null;
}

// ── Settings functions ────────────────────────────────────────────────────────

function toggleSettings() {
  const open = settingsPane.style.display !== 'none';
  settingsPane.style.display = open ? 'none' : 'block';
  btnToggle.textContent = open ? '⚙ InfluxDB settings' : '⚙ Hide settings';
}

async function loadConfig() {
  return new Promise((resolve) => {
    chrome.storage.local.get(STORAGE_CONFIG_KEY, ({ [STORAGE_CONFIG_KEY]: stored }) => {
      resolve(stored ?? {});
    });
  });
}

function renderConfig(cfg) {
  cfgUrl.value    = cfg.URL    ?? 'http://localhost:8086';
  cfgOrg.value    = cfg.ORG    ?? 'research';
  cfgBucket.value = cfg.BUCKET ?? 'behavior';
  // Never pre-fill the token field — just show a badge
  cfgToken.value  = '';
  updateTokenBadge(!!cfg.TOKEN);
}

function updateTokenBadge(hasToken) {
  if (hasToken) {
    tokenBadge.textContent = '✓ set';
    tokenBadge.className   = 'token-badge ok';
  } else {
    tokenBadge.textContent = '✗ missing';
    tokenBadge.className   = 'token-badge missing';
  }
}

async function onSaveConfig() {
  cfgSavedMsg.style.display = 'none';

  const existing = await loadConfig();

  const newCfg = {
    URL:    cfgUrl.value.trim()    || 'http://localhost:8086',
    ORG:    cfgOrg.value.trim()    || 'research',
    BUCKET: cfgBucket.value.trim() || 'behavior',
    // Only overwrite the token if the field is non-empty
    TOKEN:  cfgToken.value.trim()  || existing.TOKEN || '',
  };

  chrome.storage.local.set({ [STORAGE_CONFIG_KEY]: newCfg }, () => {
    cfgToken.value = '';            // clear field after save
    updateTokenBadge(!!newCfg.TOKEN);
    cfgSavedMsg.style.display = 'block';
    setTimeout(() => { cfgSavedMsg.style.display = 'none'; }, 2_000);
  });
}

// ── Utility ───────────────────────────────────────────────────────────────────

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.classList.add('visible');
}

function clearError() {
  errorMsg.textContent = '';
  errorMsg.classList.remove('visible');
}

function formatDuration(ms) {
  const s = Math.floor(ms / 1_000);
  return `${Math.floor(s / 60)}m ${(s % 60).toString().padStart(2, '0')}s`;
}

function send(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        console.warn('[popup]', chrome.runtime.lastError.message);
        resolve(null);
      } else {
        resolve(response);
      }
    });
  });
}

(function () {
  "use strict";

  const SCROLL_FLUSH_DELAY_MS = 2000;

  let previousScrollY = window.scrollY;
  let scrollAccumulator = 0;
  let scrollFlushTimer = null;

  // ── Part 1 fix: callback-based sendMessage — never throws, handles lastError ──
  function sendMessage(payload) {
    try {
      chrome.runtime.sendMessage(payload, function (_response) {
        // Reading lastError suppresses the unchecked runtime error for
        // "message port closed" and "no receiver" cases.
        void chrome.runtime.lastError;
      });
    } catch (_err) {
      // Extension context was invalidated (page unload / extension reload).
      // Nothing to do — the tab is going away anyway.
    }
  }

  function flushScroll() {
    if (scrollAccumulator === 0) {
      scrollFlushTimer = null;
      return;
    }
    const delta = scrollAccumulator;
    const total = window.scrollY;
    scrollAccumulator = 0;
    scrollFlushTimer = null;
    sendMessage({
      type: "scroll_event",
      scroll_delta_y: delta,
      scroll_total_y: total,
    });
  }

  function trackScroll() {
    const currentY = window.scrollY;
    scrollAccumulator += currentY - previousScrollY;
    previousScrollY = currentY;
    clearTimeout(scrollFlushTimer);
    scrollFlushTimer = setTimeout(flushScroll, SCROLL_FLUSH_DELAY_MS);
  }

  function notifyTabHidden() {
    clearTimeout(scrollFlushTimer);
    flushScroll();
    sendMessage({ type: "tab_hidden" });
  }

  // ── Part 4 fix: dual-task probes are now handled by the Python system agent
  // (tkinter popup). The content script only needs to acknowledge the message so
  // background.js does not see an unchecked sendMessage error.
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === "show_dual_task_probe") {
      sendResponse({ ok: false, reason: "dual_task_moved_to_system" });
      return true;
    }
    return false;
  });

  window.addEventListener("scroll", trackScroll, { passive: true });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      notifyTabHidden();
    }
  });
})();

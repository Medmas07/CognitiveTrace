(function () {
  const REPORT_DELAY_MS = 750;

  const pending = {
    scroll_delta: 0,
    scroll_depth: 0
  };

  let lastScrollY = window.scrollY;
  let reportTimer = null;

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function computeScrollDepth() {
    const bodyHeight = document.body ? document.body.scrollHeight : 0;
    const docHeight = document.documentElement
      ? document.documentElement.scrollHeight
      : 0;
    const maxHeight = Math.max(bodyHeight, docHeight, window.innerHeight, 1);
    const depth = (window.scrollY + window.innerHeight) / maxHeight;
    return clamp(depth, 0, 1);
  }

  function hasPendingData() {
    return pending.scroll_delta !== 0 || pending.scroll_depth > 0;
  }

  function resetPending() {
    pending.scroll_delta = 0;
    pending.scroll_depth = 0;
  }

  function flushPending() {
    reportTimer = null;
    if (!hasPendingData()) {
      return;
    }

    const payload = {
      type: "page_activity",
      url: window.location.href,
      scroll_delta: pending.scroll_delta,
      scroll_depth: pending.scroll_depth
    };

    chrome.runtime.sendMessage(payload, () => {
      // Suppress errors when the extension is reloading.
      void chrome.runtime.lastError;
    });
    resetPending();
  }

  function scheduleFlush() {
    if (reportTimer != null) {
      return;
    }
    reportTimer = setTimeout(flushPending, REPORT_DELAY_MS);
  }

  window.addEventListener(
    "scroll",
    () => {
      const currentY = window.scrollY;
      pending.scroll_delta += currentY - lastScrollY;
      pending.scroll_depth = Math.max(pending.scroll_depth, computeScrollDepth());
      lastScrollY = currentY;
      scheduleFlush();
    },
    { passive: true }
  );

  // Click and keyboard tracking intentionally disabled:
  // keep this content script focused on scroll-only behavior.

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      flushPending();
    }
  });

  window.addEventListener("beforeunload", flushPending);
})();

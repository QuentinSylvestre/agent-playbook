(() => {
  const frame = document.getElementById("kiro-visualization");
  if (!(frame instanceof HTMLIFrameElement)) {
    return;
  }
  let viewportHeight = globalThis.innerHeight;

  // Widget state storage key — matches the key used by standalone-host-bridge.js.
  const storageKey = `kiro:viz-state-v1:${JSON.stringify([
    globalThis.location.pathname,
    globalThis.location.search,
  ])}`;

  // Read saved widget state from localStorage.
  let state = null;
  try {
    const saved = globalThis.localStorage.getItem(storageKey);
    if (saved != null) {
      state = JSON.parse(saved);
    }
  } catch {
    state = null;
  }

  // Handle messages from the inner iframe (height, scroll-to, open-external).
  globalThis.addEventListener("message", (event) => {
    const data = event.data;
    if (typeof data !== "object" || data == null) {
      return;
    }
    if (data.type === "height") {
      const height = data.height;
      if (
        typeof height === "number" &&
        Number.isFinite(height) &&
        height >= 0 &&
        height <= 10_000
      ) {
        frame.style.height = Math.ceil(height) + "px";
        // Embedded in a host page (PowerAtlas shows the rendered file in an
        // iframe), tell it how tall this page now is: the frame plus the
        // body's padding. A top-level page has no distinct parent.
        if (globalThis.parent !== globalThis) {
          const padding = Number.parseFloat(
            globalThis.getComputedStyle(document.body).paddingTop,
          ) || 0;
          globalThis.parent.postMessage(
            { type: "height", height: Math.ceil(height + padding * 2) },
            "*",
          );
        }
      }
      return;
    }
    if (data.type === "scroll-to") {
      const top = data.top;
      if (
        typeof top === "number" &&
        Number.isFinite(top) &&
        top >= 0 &&
        globalThis.navigator.userActivation?.isActive === true
      ) {
        globalThis.scrollTo({
          top: Math.ceil(
            globalThis.scrollY + frame.getBoundingClientRect().top + top,
          ),
        });
      }
      return;
    }
    if (data.type === "open-external") {
      const rawHref = data.href;
      if (typeof rawHref !== "string") {
        return;
      }
      let href;
      try {
        const url = new URL(rawHref, document.baseURI);
        if (url.protocol !== "https:") {
          return;
        }
        href = url.href;
      } catch {
        return;
      }
      if (globalThis.navigator.userActivation?.isActive === true) {
        const anchor = document.createElement("a");
        anchor.href = href;
        anchor.rel = "noopener noreferrer";
        anchor.target = "_blank";
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      }
    }
  });

  // data-fragment-src holds the full inner-frame HTML (set by render.py).
  // The inner HTML contains the marker `window.__vizWidgetState=/*_KIRO_WS_PLACEHOLDER_*/null;`
  // which is replaced here with the actual saved state before loading.
  const fragmentSrc = frame.dataset.fragmentSrc;
  if (fragmentSrc == null) {
    return;
  }

  globalThis.addEventListener("resize", () => {
    const height = Number.parseFloat(frame.style.height);
    if (!Number.isFinite(height) || height <= viewportHeight) {
      frame.style.removeProperty("height");
    }
    viewportHeight = globalThis.innerHeight;
  });

  // Inject widget state and load the inner frame.
  const stateJson = JSON.stringify(state).replaceAll("<", "\\u003c");
  frame.srcdoc = fragmentSrc.replace(
    "window.__vizWidgetState=/*_KIRO_WS_PLACEHOLDER_*/null;",
    `window.__vizWidgetState=${stateJson};`,
  );
  delete frame.dataset.fragmentSrc;
})();

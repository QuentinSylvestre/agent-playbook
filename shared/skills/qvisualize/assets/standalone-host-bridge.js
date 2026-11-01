(() => {
  const root = document.documentElement;
  const mediaQuery = globalThis.matchMedia("(prefers-color-scheme: dark)");

  // Widget state is set by standalone-shell.js before the iframe srcdoc loads.
  // window.__vizWidgetState is injected into the inner HTML at render time.
  /** @type {Record<string, unknown> | null} */
  let state = window.__vizWidgetState ?? null;

  // Use the same storage key as standalone-shell.js so localStorage round-trips.
  const storageKey = `kiro:viz-state-v1:${JSON.stringify([
    globalThis.location.pathname,
    globalThis.location.search,
  ])}`;

  /**
   * Open an external https: URL in a new tab.
   * @param {{ href: string }} options
   */
  const openExternal = ({ href }) => {
    let url;
    try {
      url = new URL(href);
    } catch {
      return;
    }
    if (url.protocol !== "https:") {
      return;
    }
    globalThis.parent.postMessage({ type: "open-external", href: url.href }, "*");
  };

  /**
   * No-op in the standalone renderer; returns a resolved promise so
   * fragments that call it do not throw.
   * @returns {Promise<void>}
   */
  const sendFollowUpMessage = () => Promise.resolve();

  /**
   * Persist widget state to localStorage and notify listeners.
   * @param {Record<string, unknown> | ((prev: Record<string, unknown> | null) => Record<string, unknown>)} next
   * @returns {Promise<void>}
   */
  const setWidgetState = (next) => {
    const nextState = typeof next === "function" ? next(state) : next;
    if (
      nextState == null ||
      typeof nextState !== "object" ||
      Array.isArray(nextState)
    ) {
      return Promise.reject(new TypeError("Widget state must be a JSON object"));
    }
    state = nextState;
    window.__vizWidgetState = state;
    globalThis.openai.widgetState = state;
    globalThis.dispatchEvent(
      new CustomEvent("openai:set_globals", {
        detail: { globals: { widgetState: state } },
      }),
    );
    try {
      globalThis.localStorage.setItem(storageKey, JSON.stringify(state));
    } catch {
      // Ephemeral storage (null-origin srcdoc) — best-effort only.
    }
    return Promise.resolve();
  };

  /** Post the document body height to the outer shell. */
  const sendHeight = () => {
    const height = Math.ceil(
      Math.max(
        document.body.scrollHeight,
        document.body.getBoundingClientRect().height,
      ),
    );
    try {
      globalThis.parent.postMessage({ type: "height", height }, "*");
    } catch {
      // Cross-origin parent or no parent — ignore.
    }
  };

  /**
   * Set the root theme attribute and expose the globalThis.openai interface.
   * Called immediately (no handshake needed) and on media-query changes.
   */
  const syncTheme = () => {
    const theme = mediaQuery.matches ? "dark" : "light";
    root.dataset.theme = theme;
    globalThis.openai = {
      ...globalThis.openai,
      openExternal,
      sendFollowUpMessage,
      setWidgetState,
      theme,
      visualizationStyleVariables: {},
      visualizationTheme: theme,
      widgetState: state,
      statePersistence: "local",
      stateModelContext: "none",
    };
    globalThis.dispatchEvent(
      new CustomEvent("openai:set_globals", {
        detail: { globals: globalThis.openai },
      }),
    );
  };

  // Inject the interface immediately — no codex-visualization-initialize
  // handshake required.
  syncTheme();

  mediaQuery.addEventListener("change", syncTheme);

  // Intercept clicks: handle #hash anchors and external https: links.
  globalThis.addEventListener("click", (event) => {
    if (event.defaultPrevented) {
      return;
    }
    let element = null;
    if (event.target instanceof globalThis.Element) {
      element = event.target;
    } else if (event.target instanceof globalThis.Node) {
      element = event.target.parentElement;
    }
    const link = element?.closest("a[href]");
    const href = link?.getAttribute("href");
    if (href == null) {
      return;
    }
    if (href.startsWith("#")) {
      let id;
      try {
        id = decodeURIComponent(href.slice(1));
      } catch {
        return;
      }
      const target = id.length === 0 ? root : document.getElementById(id);
      if (
        target == null ||
        globalThis.navigator.userActivation?.isActive !== true
      ) {
        return;
      }
      event.preventDefault();
      try {
        globalThis.parent.postMessage(
          {
            type: "scroll-to",
            top: target.getBoundingClientRect().top + globalThis.scrollY,
          },
          "*",
        );
      } catch {
        // No accessible parent — ignore.
      }
      return;
    }
    event.preventDefault();
    openExternal({ href });
  });

  new ResizeObserver(sendHeight).observe(document.body);
  sendHeight();
})();

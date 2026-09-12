// ==UserScript==
// @name         Instagram IG_COOKIE Getter
// @namespace    https://abhipraya.dev/
// @version      1.2.0
// @description  Copy the current Instagram cookies as an IG_COOKIE environment line.
// @match        https://www.instagram.com/*
// @match        https://instagram.com/*
// @grant        GM_cookie
// @grant        GM_setClipboard
// @run-at       document-idle
// @noframes
// ==/UserScript==

(function () {
  "use strict";

  const ROOT_ID = "ig-cookie-getter-root";
  const BUTTON_ID = "ig-cookie-getter-button";
  const STATUS_ID = "ig-cookie-getter-status";

  function setStatus(message, isError = false) {
    const status = document.getElementById(STATUS_ID);
    if (!status) return;
    status.textContent = message;
    status.style.color = isError ? "#ffb4ab" : "#b7f7c2";
  }

  function normalizeCookies(rawCookies) {
    const byName = new Map();

    for (const cookie of rawCookies) {
      if (!cookie || typeof cookie.name !== "string" || !cookie.name) continue;
      if (typeof cookie.value !== "string") continue;

      const candidate = {
        name: cookie.name,
        value: cookie.value,
        pathLength: typeof cookie.path === "string" ? cookie.path.length : 0,
      };
      const previous = byName.get(candidate.name);
      if (!previous || candidate.pathLength > previous.pathLength) {
        byName.set(candidate.name, candidate);
      }
    }

    return [...byName.values()]
      .sort((left, right) => left.name.localeCompare(right.name))
      .map(({ name, value }) => `${name}=${value}`);
  }

  function visibleCookies() {
    return document.cookie
      .split(";")
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const separator = part.indexOf("=");
        if (separator < 1) return null;
        return {
          name: part.slice(0, separator),
          value: part.slice(separator + 1),
        };
      })
      .filter(Boolean);
  }

  function parseManualCookies(rawInput) {
    let input = rawInput.trim();
    input = input.replace(/^IG_COOKIE=/i, "").trim();
    input = input.replace(/^cookie:\s*/i, "").trim();

    if (!input.includes("=")) {
      if (!input || /[;\r\n]/.test(input)) {
        throw new Error("The sessionid value contains invalid characters");
      }
      return [`sessionid=${input}`];
    }

    const pairs = input
      .split(";")
      .map((part) => part.trim())
      .filter(Boolean);
    const byName = new Map();

    for (const pair of pairs) {
      const separator = pair.indexOf("=");
      if (separator < 1 || /[\r\n]/.test(pair)) {
        throw new Error("The cookie header is not formatted as name=value pairs");
      }
      const name = pair.slice(0, separator).trim();
      const value = pair.slice(separator + 1).trim();
      if (!/^[A-Za-z0-9_-]+$/.test(name) || !value) {
        throw new Error("The cookie header contains an invalid pair");
      }
      byName.set(name, `${name}=${value}`);
    }

    return [...byName.values()];
  }

  function mergeCookiePairs(existing, additional) {
    const byName = new Map();
    for (const pair of existing) {
      const separator = pair.indexOf("=");
      if (separator > 0) byName.set(pair.slice(0, separator), pair);
    }
    for (const pair of additional) {
      const separator = pair.indexOf("=");
      if (separator > 0) byName.set(pair.slice(0, separator), pair);
    }
    return [...byName.values()].sort((left, right) => left.localeCompare(right));
  }

  function tampermonkeyCookies() {
    if (typeof GM_cookie === "undefined" || typeof GM_cookie.list !== "function") {
      return Promise.resolve(null);
    }

    return new Promise((resolve, reject) => {
      let settled = false;
      const timeout = window.setTimeout(() => {
        if (!settled) {
          settled = true;
          reject(new Error("Tampermonkey cookie API timed out"));
        }
      }, 5000);

      try {
        GM_cookie.list({ url: window.location.href }, (cookies, error) => {
          if (settled) return;
          settled = true;
          window.clearTimeout(timeout);
          if (error) {
            reject(new Error("Tampermonkey could not read Instagram cookies"));
            return;
          }
          resolve(Array.isArray(cookies) ? cookies : []);
        });
      } catch (_error) {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeout);
        reject(new Error("Tampermonkey could not read Instagram cookies"));
      }
    });
  }

  async function collectCookies() {
    try {
      const cookies = await tampermonkeyCookies();
      const normalized = normalizeCookies(cookies || []);
      if (normalized.length > 0) {
        return { cookies: normalized, source: "Tampermonkey cookie API" };
      }
    } catch (_error) {
      // Fall through to document.cookie and explain the limitation in the UI.
    }

    return {
      cookies: normalizeCookies(visibleCookies()),
      source: "document.cookie fallback",
    };
  }

  async function writeClipboard(text) {
    if (typeof GM_setClipboard === "function") {
      GM_setClipboard(text, "text");
      return;
    }

    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      await navigator.clipboard.writeText(text);
      return;
    }

    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    textarea.remove();
    if (!copied) throw new Error("Clipboard access was denied");
  }

  async function copyCookieLine() {
    const button = document.getElementById(BUTTON_ID);
    if (!button) return;
    button.disabled = true;
    setStatus("Reading cookies…");

    try {
      const result = await collectCookies();
      if (result.cookies.length === 0) {
        throw new Error("No Instagram cookies were found");
      }

      let sessionWasEntered = false;
      if (!result.cookies.some((cookie) => cookie.startsWith("sessionid="))) {
        const entered = window.prompt(
          "Tampermonkey could not read Instagram's HttpOnly sessionid.\n\n" +
            "Paste a full Cookie header, an IG_COOKIE=... line, or only the sessionid value.\n" +
            "DevTools Network > request > Headers > Request Headers is the best source.\n\n" +
            "Cancel to copy visible cookies only.",
        );

        if (entered && entered.trim()) {
          const manualCookies = parseManualCookies(entered);
          if (!manualCookies.some((cookie) => cookie.startsWith("sessionid="))) {
            throw new Error("The pasted cookies do not include sessionid");
          }
          result.cookies = mergeCookiePairs(result.cookies, manualCookies);
          sessionWasEntered = true;
        }
      }

      const cookieHeader = result.cookies.join("; ");
      await writeClipboard(`IG_COOKIE=${cookieHeader}`);

      const hasSession = result.cookies.some((cookie) => cookie.startsWith("sessionid="));
      if (sessionWasEntered) {
        setStatus(`Copied IG_COOKIE with ${result.cookies.length} cookies.`);
      } else if (result.source === "document.cookie fallback") {
        setStatus(
          `Copied ${result.cookies.length} visible cookies, but sessionid may be missing.`,
          true,
        );
      } else if (!hasSession) {
        setStatus("Copied cookies, but sessionid is missing. Check the Instagram login.", true);
      } else {
        setStatus(`Copied IG_COOKIE with ${result.cookies.length} cookies.`);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not copy Instagram cookies", true);
    } finally {
      button.disabled = false;
    }
  }

  function mount() {
    if (!document.body || document.getElementById(ROOT_ID)) return;

    const root = document.createElement("div");
    root.id = ROOT_ID;
    root.style.cssText = [
      "all: initial",
      "position: fixed",
      "top: 16px",
      "right: 16px",
      "z-index: 2147483647",
      "display: block",
      "width: 220px",
      "padding: 10px",
      "border: 1px solid rgba(255,255,255,.18)",
      "border-radius: 12px",
      "background: rgba(18,18,18,.94)",
      "box-shadow: 0 8px 30px rgba(0,0,0,.35)",
      "font: 12px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif",
      "color: #fff",
    ].join(";");

    const button = document.createElement("button");
    button.id = BUTTON_ID;
    button.type = "button";
    button.textContent = "Copy IG_COOKIE";
    button.addEventListener("click", copyCookieLine);
    button.style.cssText = [
      "all: initial",
      "box-sizing: border-box",
      "display: block",
      "width: 100%",
      "padding: 8px 10px",
      "border: 0",
      "border-radius: 8px",
      "background: #fff",
      "color: #111",
      "cursor: pointer",
      "font: 600 13px/1.2 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif",
      "text-align: center",
    ].join(";");

    const status = document.createElement("div");
    status.id = STATUS_ID;
    status.setAttribute("aria-live", "polite");
    status.textContent = "Instagram only, no network upload";
    status.style.cssText = [
      "display: block",
      "margin-top: 7px",
      "color: #c9c9c9",
      "font: 11px/1.35 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif",
    ].join(";");

    root.append(button, status);
    document.body.appendChild(root);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount, { once: true });
  } else {
    mount();
  }
})();

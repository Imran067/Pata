// Shared browser code for the rider phone, the customer phone and the control room.

export const $ = (selector, root = document) => root.querySelector(selector);

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export async function api(path, { method = "GET", json, form } = {}) {
  const init = { method, headers: {} };
  if (json !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(json);
  } else if (form) {
    init.body = form;
  }
  const response = await fetch(path, init);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : `Request failed (HTTP ${response.status}).`;
    throw new Error(detail);
  }
  return body;
}

export function sessionIdFromUrl() {
  return new URLSearchParams(location.search).get("s");
}

/** Live updates: snapshots of the whole session, plus audio meant for one person. */
export function connect(sessionId, onEvent) {
  let socket;
  let closed = false;
  const open = () => {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${location.host}/ws/${sessionId}`);
    socket.onmessage = (message) => onEvent(JSON.parse(message.data));
    socket.onclose = (event) => {
      if (!closed && event.code !== 4404) setTimeout(open, 1200);
      if (event.code === 4404) onEvent({ type: "gone" });
    };
  };
  open();
  return { close: () => { closed = true; socket?.close(); } };
}

/** Plays Timbre's audio one clip at a time. Call unlock() inside a tap so phones allow playback. */
export class AudioQueue {
  constructor() {
    this.audio = new Audio();
    this.queue = [];
    this.playing = false;
    this.audio.addEventListener("ended", () => this.next());
    this.audio.addEventListener("error", () => this.next());
  }
  unlock() {
    this.audio.src = silentWav();
    this.audio.play().catch(() => {});
  }
  push(url) {
    this.queue.push(url);
    if (!this.playing) this.next();
  }
  next() {
    const url = this.queue.shift();
    if (!url) { this.playing = false; return; }
    this.playing = true;
    this.audio.src = url;
    this.audio.play().catch(() => { this.playing = false; this.onBlocked?.(); });
  }
  stop() {
    this.queue = [];
    this.audio.pause();
    this.playing = false;
  }
}

function silentWav() {
  const samples = 800;
  const buffer = new ArrayBuffer(44 + samples * 2);
  const view = new DataView(buffer);
  const text = (offset, s) => [...s].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  text(0, "RIFF"); view.setUint32(4, 36 + samples * 2, true); text(8, "WAVE"); text(12, "fmt ");
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true);
  view.setUint16(34, 16, true); text(36, "data"); view.setUint32(40, samples * 2, true);
  return URL.createObjectURL(new Blob([buffer], { type: "audio/wav" }));
}

export const langAttr = (code) => (code || "en").split("-")[0];

const LANGUAGE_NAMES = {
  "hi-IN": "Hindi", "mr-IN": "Marathi", "bn-IN": "Bengali", "pa-IN": "Punjabi", "gu-IN": "Gujarati",
  "ta-IN": "Tamil", "te-IN": "Telugu", "kn-IN": "Kannada", "ml-IN": "Malayalam", "en-IN": "English",
};
export const languageName = (code) => LANGUAGE_NAMES[code] || code;

// ---------------------------------------------------------------- icons, logo, theme

const SVG = "http://www.w3.org/2000/svg";
const SPRITE = "/static/vendor/lucide/icons.svg";

/** A Lucide icon from the bundled sprite. */
export function icon(name, cls = "") {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("class", `i ${cls}`.trim());
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG, "use");
  use.setAttribute("href", `${SPRITE}#${name}`);
  svg.append(use);
  return svg;
}

/** Replace a button's contents with an icon and a label, keeping the button itself. */
export function setButton(button, iconName, label) {
  button.replaceChildren(...[iconName ? icon(iconName) : null, label ? el("span", { text: label }) : null].filter(Boolean));
}

/** Fill every [data-icon] placeholder in the static HTML. */
export function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((node) => {
    node.replaceWith(icon(node.dataset.icon, node.getAttribute("class") || ""));
  });
}

/** The mark: a pin at the end of a dotted trail, the gap Pata closes. */
export const BRAND_MARK = `<svg class="brand-mark" viewBox="0 0 26 26" aria-hidden="true">
  <circle class="trail" cx="3.5" cy="22.5" r="1.6"/><circle class="trail" cx="7.5" cy="19.5" r="1.6"/>
  <circle class="trail" cx="11.5" cy="16.5" r="1.6"/>
  <path class="head" d="M18 2.5a6 6 0 0 1 6 6c0 4.3-4.6 8.6-5.5 9.4a.75.75 0 0 1-1 0C16.6 17.1 12 12.8 12 8.5a6 6 0 0 1 6-6Z"/>
  <circle class="eye" cx="18" cy="8.5" r="2.1"/></svg>`;

/** System / light / dark switch. Works with theme.js, which already applied the theme. */
export function themeSwitch(container) {
  const options = [["system", "sun-moon", "Match this device"], ["light", "sun", "Light"], ["dark", "moon", "Dark"]];
  const group = el("div", { class: "segmented icons", role: "radiogroup", "aria-label": "Theme" },
    ...options.map(([value, iconName, label]) => el("label", { title: label },
      el("input", { type: "radio", name: `theme-${container.id || "x"}`, value, "aria-label": label,
        checked: window.pataTheme.choice() === value, onchange: () => window.pataTheme.set(value) }),
      el("span", {}, icon(iconName, "i-sm")))));
  container.replaceChildren(group);
  window.pataTheme.onChange(() => {
    group.querySelectorAll("input").forEach((input) => { input.checked = input.value === window.pataTheme.choice(); });
  });
}

/** One button that cycles the theme, for the phones where space is tight. */
export function themeCycle(button) {
  const order = ["system", "light", "dark"];
  const iconFor = { system: "sun-moon", light: "sun", dark: "moon" };
  const label = { system: "Theme: match this device", light: "Theme: light", dark: "Theme: dark" };
  const draw = () => {
    const choice = window.pataTheme.choice();
    button.replaceChildren(icon(iconFor[choice]));
    button.title = label[choice];
    button.setAttribute("aria-label", label[choice]);
  };
  button.addEventListener("click", () => {
    const next = order[(order.indexOf(window.pataTheme.choice()) + 1) % order.length];
    window.pataTheme.set(next);
  });
  window.pataTheme.onChange(draw);
  draw();
}

/** The page shown when a phone link has no session in it. */
export function lostPage() {
  const brand = el("span", { class: "brand" });
  brand.innerHTML = `${BRAND_MARK}<span class="brand-name">Pata</span>`;
  document.body.replaceChildren(el("main", { class: "lost" },
    brand,
    el("h1", { text: "This link has no call in it" }),
    el("p", { text: "Phone pages open from the control room after you start a call session." }),
    el("a", { class: "btn primary", href: "/" }, "Open the control room")));
}

// ---------------------------------------------------------------- the call timeline

function textBlock(cls, text, code) {
  return text ? el("p", { class: cls, lang: code ? langAttr(code) : null, text }) : null;
}

function tags(...items) {
  const list = items.filter(Boolean).map(([kind, text]) => el("span", { class: `tag ${kind}`, text }));
  return list.length ? el("div", { class: "tags" }, list) : null;
}

const initial = (name) => (name || "?").trim().slice(0, 1).toUpperCase();

function item(kind, nodeContent, ...body) {
  const node = el("span", { class: "node", "aria-hidden": "true" });
  if (typeof nodeContent === "string" && nodeContent.length > 1) node.append(icon(nodeContent));
  else if (nodeContent) node.append(nodeContent);
  return el("li", { class: `msg ${kind}`.trim() }, node, el("div", { class: "body" }, ...body));
}

/**
 * One conversation entry, drawn for a given screen.
 * view: "rider" | "customer" | "monitor"
 */
export function renderEntry(entry, view, s, labels = {}) {
  const rider = s.rider.name;
  const customer = s.order.customer_name;
  const riderLang = s.rider.lang;
  const customerLang = s.customer_lang;
  const showTags = view !== "customer";
  const forMe = !entry.for_role || view === "monitor" || entry.for_role === view;

  switch (entry.kind) {
    case "system":
      if (!forMe) return null;
      return item("system", null,
        textBlock("main", entry.text, entry.for_role === "rider" ? riderLang : entry.for_role === "customer" ? customerLang : null),
        view !== "customer" && entry.gloss_en !== entry.text ? textBlock("gloss", entry.gloss_en) : null);

    case "turn": {
      const mine = entry.speaker === view;
      const speakerName = entry.speaker === "rider" ? rider : customer;
      const heardTag = entry.source === "prisma"
        ? ["prisma", `Prisma heard ${languageName(entry.language)}`]
        : entry.source === "mock" ? ["prisma", "Mock speech, no Prisma call"] : ["", "Typed"];
      const relayTags = entry.relayed
        ? [entry.script_ok === false
            ? ["warn", `Evon couldn't write ${languageName(entry.relayed_lang)} here`]
            : ["evon", `Evon rewrote it in ${languageName(entry.relayed_lang)}`],
          ["timbre", "Timbre spoke it"]]
        : [];
      if (mine) {
        // What you said: a mic mark, since the first letter of "you" breaks apart in Indian scripts.
        return item("mine", "mic",
          el("p", { class: "who", text: view === "monitor" ? speakerName : (labels.you || "You") }),
          textBlock("main", entry.text, entry.language),
          showTags ? tags(heardTag) : null);
      }
      if (view === "monitor") {
        return item(`turn ${entry.speaker}`, initial(speakerName),
          el("p", { class: "who", text: speakerName }),
          textBlock("main", entry.text, entry.language),
          textBlock("orig", entry.relayed ? `To ${entry.speaker === "rider" ? customer : rider}: ${entry.relayed}` : "", entry.relayed_lang),
          textBlock("gloss", entry.gloss_en),
          tags(heardTag, ...relayTags));
      }
      return item("turn", initial(speakerName),
        el("p", { class: "who", text: speakerName }),
        textBlock("main", entry.relayed || "…", entry.relayed_lang),
        textBlock("orig", entry.text, entry.language),
        view === "rider" ? textBlock("gloss", entry.gloss_en) : null,
        showTags ? tags(heardTag, ...relayTags) : null);
    }

    case "question":
      if (view === "customer") {
        return item("pata", "message-square-text", el("p", { class: "who", text: "Pata" }), textBlock("main", entry.text, customerLang));
      }
      return item("pata", "message-square-text",
        el("p", { class: "who", text: `Pata asked ${customer}` }),
        textBlock("main", entry.gloss_en),
        view === "monitor" ? textBlock("orig", entry.text, customerLang) : null,
        textBlock("gloss", entry.reason),
        tags(["evon", entry.options?.length ? "Evon compared the landmarks with the map" : "Evon found no match yet"],
             ["timbre", `Timbre asked in ${languageName(customerLang)}`]));

    case "resolved":
      if (view === "customer") return null;
      return item("found", "map-pin-check",
        el("p", { class: "who", text: "Found the building" }),
        textBlock("main", entry.label),
        textBlock("gloss", entry.pin_is_wrong
          ? `The saved pin was ${entry.distance_from_pin_m} m off, to the ${entry.direction_from_pin}. ${entry.reason}`
          : entry.reason),
        tags(["evon", `Evon picked spot ${entry.site_id}`]));

    case "directions":
    case "briefing":
      if (view === "customer") return null;
      return item("pata", entry.kind === "briefing" ? "notebook-text" : "navigation",
        el("p", { class: "who", text: entry.kind === "briefing" ? "Doorstep note, read before calling" : "Directions" }),
        textBlock("main", entry.text, riderLang),
        textBlock("gloss", entry.gloss_en !== entry.text ? entry.gloss_en : ""),
        tags(["evon", entry.kind === "briefing" ? "Evon read the doorstep note" : "Evon phrased the app's route facts"],
             ["timbre", `Timbre read it slowly in ${languageName(riderLang)}`]));

    case "note":
      if (view === "customer") return null;
      return item("found", "notebook-text",
        el("p", { class: "who", text: "Doorstep note saved for the next rider" }),
        textBlock("main", entry.text),
        tags(["evon", "Evon merged this call into the note"]));

    case "pin_fix":
      if (view === "rider" || (view === "customer" && s.pin_fix_pending)) return null;
      return item("pata", "map-pin",
        el("p", { class: "who", text: "Pata" }),
        textBlock("main", entry.text, customerLang),
        view === "monitor" ? textBlock("gloss", entry.gloss_en) : null);

    case "language":
      if (view === "customer") return null;
      return item("system", null,
        textBlock("main", entry.text),
        tags(...(entry.typed ? [["evon", "Evon read the language"]] : [["prisma", "Prisma detected it"], ["evon", "Evon agreed"]])));

    case "error": {
      // The control room gets the full message. A phone only hears about its own failed turn, in words
      // its person can read; the customer never sees technical English.
      if (view === "monitor") return item("error", "triangle-alert", textBlock("main", entry.text));
      if (entry.role && entry.role !== view) return null;
      if (view === "customer") {
        return entry.role === "customer" ? item("error", "triangle-alert", textBlock("main", labels.failed || entry.text, customerLang)) : null;
      }
      return item("error", "triangle-alert",
        textBlock("main", entry.role === "rider" ? "That didn't go through. Say it again, or type it." : entry.text));
    }

    default:
      return null;
  }
}

export function renderLog(list, s, view, { scroller = list.parentElement, labels = {} } = {}) {
  const nearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 140;
  // Only redraw when something changed, so entries animate in once instead of on every snapshot.
  const key = JSON.stringify([s.log, s.pin_fix_pending, s.order.customer_name, s.rider.name, labels]);
  if (list.dataset.key === key) return;
  const fresh = !list.dataset.key;
  const before = list.children.length;
  list.dataset.key = key;
  list.replaceChildren(...s.log.map((entry) => renderEntry(entry, view, s, labels)).filter(Boolean));
  // Animate only what is new.
  [...list.children].forEach((node, index) => { if (fresh || index < before) node.style.animation = "none"; });
  if (nearBottom || fresh) scroller.scrollTop = scroller.scrollHeight;
}

export function renderModes(container, modes) {
  const names = { prisma: "Prisma", evon: "Evon", timbre: "Timbre" };
  container.replaceChildren(...Object.entries(modes).map(([key, mode]) =>
    el("span", {
      class: `mode ${key} ${mode}`,
      title: mode === "mock" ? `${names[key]} is a stand-in for development. Record your demo in live mode.` : `Calling the real ${names[key]} model`,
    }, el("span", { text: names[key] }), el("span", { class: "state", text: mode }))));
}

export function renderStatus(node, status) {
  node.textContent = status?.text || "";
  node.classList.toggle("busy", Boolean(status?.busy && status?.text));
}

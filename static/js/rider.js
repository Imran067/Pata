import {
  $, el, api, connect, AudioQueue, renderLog, renderModes, renderStatus, sessionIdFromUrl, langAttr, languageName,
  hydrateIcons, setButton, themeCycle, lostPage,
} from "./common.js";
import { setupTalk, sendText } from "./talk.js";
import { createMap, CallLayers, drawPlaces, distanceM, bearing, move, compass, formatDistance } from "./map.js";

const sessionId = sessionIdFromUrl();
const queue = new AudioQueue();
let session = null;
let map = null;
let call = null;
let gpsWatch = null;
let lastFix = null;
const talkLabels = { idle: "Talk to the customer", listening: "Listening. Tap to send", sending: "Sending…" };

const desktop = window.matchMedia("(min-width: 900px)");

// ---------------------------------------------------------------- map

function fitOptions() {
  const sheet = $("#sheet");
  if (desktop.matches) return { paddingTopLeft: [sheet.offsetWidth + 48, 72], paddingBottomRight: [72, 72] };
  // Candidate labels extend to the right of their dots, so leave room on that side.
  return { paddingTopLeft: [70, 72], paddingBottomRight: [190, sheet.offsetHeight + 36] };
}

function initMap(s) {
  const pin = s.order.pin;
  map = createMap("map", [pin.lat, pin.lon], 16);
  const context = L.layerGroup().addTo(map);
  call = new CallLayers(map, { showPin: true, riderDraggable: true, riderLabel: "You" });
  call.fitOptions = fitOptions;
  call.rider.on("dragend", async (event) => {
    const to = event.target.getLatLng();
    const from = session.rider_pos;
    const here = { lat: to.lat, lon: to.lng };
    const heading = distanceM(from, here) > 3 ? bearing(from, here) : from.heading;
    await postPosition({ ...here, heading });
  });
  api(`/api/places?lat=${pin.lat}&lon=${pin.lon}&radius=1200`).then(({ places }) => drawPlaces(context, places)).catch(() => {});
  // Start with the saved pin above the sheet, not under it.
  requestAnimationFrame(() => {
    map.invalidateSize();
    if (!desktop.matches) map.panBy([0, $("#sheet").offsetHeight / 2 - 20], { animate: false });
    else map.panBy([-$("#sheet").offsetWidth / 2, 0], { animate: false });
  });
}

// ---------------------------------------------------------------- the instrument

function renderGauge(s) {
  const gauge = $("#gauge");
  // After a customer fixed her pin, the doorstep note vouches for the saved pin itself: head there.
  const pinIsRight = !s.destination && Boolean(s.note) && !s.note.pin_correction;
  const dest = s.destination || (pinIsRight ? s.order.pin : null);
  gauge.classList.remove("idle", "here");
  if (!dest) {
    gauge.classList.add("idle");
    setButton($("#arrow"), "ear");
    $("#dist-value").textContent = "Ask where the building is";
    $("#dist-unit").textContent = "";
    $("#dist-dir").textContent = `Tap Talk and ask ${s.order.customer_name}. The building appears on the map once it's described.`;
    return;
  }
  const metres = distanceM(s.rider_pos, dest);
  if ((s.destination && s.arrived) || metres < 25) {
    gauge.classList.add("here");
    setButton($("#arrow"), "door-open");
    $("#dist-value").textContent = "You're at the building";
    $("#dist-unit").textContent = "";
    $("#dist-dir").textContent = s.delivered ? "Delivered. Thank you." : "Hand over the order, then mark it delivered.";
    return;
  }
  setButton($("#arrow"), "navigation");
  const toward = bearing(s.rider_pos, dest);
  const rel = (toward - (s.rider_pos.heading || 0) + 360) % 360;
  $("#arrow").style.setProperty("--rel", `${Math.round(rel)}deg`);
  const { value, unit } = formatDistance(metres);
  $("#dist-value").textContent = value;
  $("#dist-unit").textContent = unit;
  const side = rel < 30 || rel > 330 ? "ahead" : rel >= 150 && rel <= 210 ? "behind you" : rel < 180 ? "on your right" : "on your left";
  $("#dist-dir").textContent = `To the ${compass(toward)}, ${side}${pinIsRight ? ". The saved pin is right." : ""}`;
}

// ---------------------------------------------------------------- panel

function showError(text) {
  const node = $("#status");
  node.textContent = text;
  node.classList.remove("busy");
  node.classList.add("error");
  setTimeout(() => node.classList.remove("error"), 6000);
}

function render() {
  const s = session;
  const customer = s.order.customer_name;
  // The control room can rename the customer or change the order during a call.
  $("#title").textContent = customer;
  $("#subtitle").textContent = `${s.order.items}. ${s.order.address_text}`;
  $("#subtitle").title = $("#subtitle").textContent;
  $("#avatar").textContent = customer.slice(0, 1);
  // A rider who comes after a delivery hears the doorstep note first, and may not need to call at all.
  $("#start-lead").textContent = s.note ? "A rider has delivered here before." : "You're at the saved pin, and there's no building here.";
  $("#start-text").textContent = s.note
    ? `Start Pata and you'll hear the doorstep note in ${s.rider.lang_name} before calling ${customer}.`
    : `Start Pata to call ${customer}. You speak ${s.rider.lang_name}, ${customer} hears ${s.customer_lang_name}, and Pata translates both ways.`;
  talkLabels.idle = `Talk to ${customer}`;
  $("#talk").relabel?.();
  renderModes($("#modes"), s.modes);
  renderStatus($("#status"), s.status);
  renderLog($("#log"), s, "rider", { scroller: $("#scroller") });
  call.render(s);
  if (gpsWatch !== null) {
    const here = L.latLng(s.rider_pos.lat, s.rider_pos.lon);
    if (!map.getBounds().contains(here)) map.panTo(here);
  }

  const joined = s.joined.includes("rider");
  $("#start-card").classList.toggle("hidden", joined);
  $("#sheet").classList.toggle("waiting", !joined);
  $("#talk").disabled = !joined;
  $("#now").classList.toggle("hidden", !joined);
  if (!joined) return;

  renderGauge(s);
  const now = s.directions;
  $("#now-text").textContent = now ? now.text : "";
  $("#now-text").lang = now ? langAttr(s.rider.lang) : "en";
  $("#now-gloss").textContent = now && now.gloss_en && now.gloss_en !== now.text ? now.gloss_en : "";
  // After a doorstep note, the left button replays the note; otherwise it repeats the directions.
  const noteMode = s.directions?.kind === "briefing" || (Boolean(s.note) && !s.directions);
  $("#repeat").dataset.mode = noteMode ? "note" : "directions";
  setButton($("#repeat"), noteMode ? "notebook-text" : "volume-2", noteMode ? "Hear the doorstep note" : "Repeat directions");
  $("#repeat").disabled = noteMode ? !s.note : !s.destination;
  $("#delivered").disabled = s.delivered;
  $("#delivered").classList.toggle("done", s.delivered);
  // At the door, handing over is the next thing to do.
  $("#delivered").classList.toggle("primary", Boolean(s.arrived && !s.delivered));
  setButton($("#delivered"), s.delivered ? "circle-check" : "package", s.delivered ? "Delivered" : "Mark delivered");
}

async function postPosition(position) {
  try {
    await api(`/api/sessions/${sessionId}/position`, { method: "POST", json: position });
  } catch (error) {
    showError(error.message);
  }
}

function stopGps() {
  if (gpsWatch !== null) navigator.geolocation.clearWatch(gpsWatch);
  gpsWatch = null;
  lastFix = null;
  setButton($("#real-gps"), "locate", "Use GPS");
  $("#real-gps").classList.remove("on");
}

function toggleGps() {
  if (gpsWatch !== null) {
    stopGps();
    return;
  }
  if (!window.isSecureContext || !navigator.geolocation) {
    showError("The phone only shares its location on https. Open this page through the cloudflared address.");
    return;
  }
  setButton($("#real-gps"), "locate-fixed", "Following GPS");
  $("#real-gps").classList.add("on");
  gpsWatch = navigator.geolocation.watchPosition(async (position) => {
    const here = { lat: position.coords.latitude, lon: position.coords.longitude };
    if (lastFix && distanceM(lastFix, here) < 5) return; // ignore GPS jitter while standing still
    const from = session.rider_pos;
    const reported = position.coords.heading;
    const heading = typeof reported === "number" && Number.isFinite(reported)
      ? reported
      : distanceM(from, here) > 5 ? bearing(from, here) : from.heading;
    lastFix = here;
    await postPosition({ ...here, heading });
  }, (error) => {
    // Weak signal, tunnels and timeouts are temporary: keep watching. Only a refusal stops it.
    if (error.code === error.PERMISSION_DENIED) {
      showError("Location access is blocked. Allow it in the browser's site settings, then try again.");
      stopGps();
    }
  }, { enableHighAccuracy: true, maximumAge: 2000 });
}

function setExpanded(on) {
  const sheet = $("#sheet");
  const was = sheet.classList.contains("expanded");
  sheet.classList.toggle("expanded", on);
  // More map is showing again: frame the call for the space there is now.
  if (was && !on) {
    const done = (event) => {
      if (event.target !== sheet || event.propertyName !== "height") return; // ignore bubbling from buttons inside
      sheet.removeEventListener("transitionend", done);
      call.refit();
    };
    sheet.addEventListener("transitionend", done);
  }
  $("#grabber").setAttribute("aria-expanded", String(on));
  $("#grabber").setAttribute("aria-label", on ? "Show more of the map" : "Show more of the call");
}

async function main() {
  if (!sessionId) {
    lostPage();
    return;
  }
  hydrateIcons();
  themeCycle($("#theme-btn"));
  session = await api(`/api/sessions/${sessionId}`);
  initMap(session);
  render();

  setupTalk({
    button: $("#talk"),
    role: "rider",
    sessionId,
    queue,
    labels: talkLabels,
    onError: showError,
  });

  connect(sessionId, (event) => {
    if (event.type === "snapshot") {
      session = event.session;
      render();
    } else if (event.type === "audio" && event.for === "rider") {
      queue.push(event.url);
    } else if (event.type === "gone") {
      showError("This call session has ended. Start a new one from the control room.");
    }
  });

  $("#start").addEventListener("click", async () => {
    queue.unlock();
    try {
      await api(`/api/sessions/${sessionId}/join`, { method: "POST", json: { role: "rider" } });
    } catch (error) {
      showError(error.message);
    }
  });

  $("#grabber").addEventListener("click", () => setExpanded(!$("#sheet").classList.contains("expanded")));
  $("#type-toggle").addEventListener("click", () => {
    const drawer = $("#type-drawer");
    drawer.hidden = !drawer.hidden;
    $("#type-toggle").setAttribute("aria-expanded", String(!drawer.hidden));
    if (drawer.hidden && !desktop.matches) setExpanded(false);
    if (!drawer.hidden) {
      if (!desktop.matches) setExpanded(true);
      $("#type-input").focus({ preventScroll: true });
    }
  });

  $("#repeat").addEventListener("click", () => {
    const path = $("#repeat").dataset.mode === "note" ? "briefing" : "directions";
    api(`/api/sessions/${sessionId}/${path}`, { method: "POST" }).catch((e) => showError(e.message));
  });
  $("#delivered").addEventListener("click", async () => {
    const button = $("#delivered");
    button.disabled = true; // one tap is enough; the doorstep note is written in the background
    setButton(button, "circle-check", "Delivered");
    try {
      await api(`/api/sessions/${sessionId}/delivered`, { method: "POST" });
    } catch (error) {
      button.disabled = false;
      setButton(button, "package", "Mark delivered");
      showError(error.message);
    }
  });

  $("#real-gps").addEventListener("click", toggleGps);

  $("#walk").addEventListener("click", async () => {
    const from = session.rider_pos;
    const target = session.destination;
    const heading = target ? bearing(from, target) : from.heading;
    const step = target ? Math.min(100, distanceM(from, target)) : 100;
    const to = move(from, heading, step);
    await postPosition({ lat: to.lat, lon: to.lon, heading });
  });

  $("#type-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#type-input");
    const text = input.value.trim();
    if (!text) return;
    try {
      await sendText(sessionId, "rider", text);
      input.value = "";
    } catch (error) {
      showError(error.message);
    }
  });

  const { lines } = await api("/api/script");
  const mine = lines.filter((l) => l.role === "rider");
  $("#chips").replaceChildren(...(mine.length
    ? mine.map((line) => el("button", {
        type: "button", lang: langAttr(line.lang), title: line.gloss_en,
        onclick: () => sendText(sessionId, "rider", line.text).catch((e) => showError(e.message)),
      }, el("span", { class: "lang", lang: "en", text: languageName(line.lang) }), el("span", { text: line.text })))
    : [el("p", { class: "drawer-note", text: "No practice lines yet. Add some to data/demo_script.json, or type." })]));
}

main().catch((error) => showError(error.message));

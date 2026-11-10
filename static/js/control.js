import {
  $, el, api, connect, renderLog, renderModes, renderStatus, icon, hydrateIcons, setButton, BRAND_MARK, themeSwitch,
} from "./common.js";
import { createMap, markers, drawPlaces as drawPlaceDots, CallLayers, kindName } from "./map.js";

let config = null;
let orders = [];
let riders = [];
let setup = null;
let socket = null;
let lastNoteStamp = "";
let map = null;
let pin = null;
let placeDots = null;
let saveTimer = null;
let savedTimer = null;
let addingPlace = false;
let pinMoved = false; // only send the pin when you moved it here
let callLayers = null;
let currentNote = null; // the doorstep note for the demo address, if there is one
let pinWrong = false;

const placesSource = () => document.querySelector('input[name="places"]:checked')?.value || "sample";
const setPlacesSource = (value) => { document.querySelectorAll('input[name="places"]').forEach((r) => { r.checked = r.value === value; }); };

function setupStatus(text, isError = false) {
  const node = $("#setup-status");
  node.textContent = text;
  node.classList.toggle("error", isError);
}

function fillLanguages(select, value) {
  select.replaceChildren(...Object.values(config.languages).map((l) => el("option", { value: l.code, text: l.name })));
  select.value = value;
}

function renderRiders() {
  const box = $("#riders");
  box.querySelectorAll("label").forEach((node) => node.remove());
  for (const rider of riders) {
    box.append(el("label", { class: "rider-opt" },
      el("input", { type: "radio", name: "rider", value: rider.id, checked: rider.id === setup.rider_id }),
      el("span", { class: "avatar", "aria-hidden": "true", text: rider.name.slice(0, 1) }),
      el("span", { class: "who-text" }, el("strong", { text: rider.name }), el("small", { text: `Speaks ${rider.lang_name}, from ${rider.from}` })),
      el("span", { class: "tick", "aria-hidden": "true" })));
  }
}

function fillForm() {
  $("#f-name").value = setup.customer_name;
  $("#f-address").value = setup.address_text;
  $("#f-items").value = setup.items;
  fillLanguages($("#f-customer-lang"), setup.customer_lang);
  $("#f-customer-auto").checked = setup.customer_auto;
  fillLanguages($("#f-rider-lang"), setup.rider_lang);
  $("#f-rider-auto").checked = setup.rider_auto;
  setPlacesSource(setup.places_source);
  $("#f-hints").checked = setup.prisma_hints;
  renderRiders();
}

function readForm() {
  const at = pin.getLatLng();
  const name = $("#f-name").value.trim();
  return {
    ...(name ? { customer_name: name } : {}), // an empty box while you retype isn't saved
    address_text: $("#f-address").value.trim(),
    items: $("#f-items").value.trim(),
    ...(pinMoved ? { pin: { lat: at.lat, lon: at.lng } } : {}),
    customer_lang: $("#f-customer-lang").value,
    customer_auto: $("#f-customer-auto").checked,
    rider_id: $("#riders input:checked")?.value || setup.rider_id,
    rider_lang: $("#f-rider-lang").value,
    rider_auto: $("#f-rider-auto").checked,
    places_source: placesSource(),
    prisma_hints: $("#f-hints").checked,
  };
}

async function saveSetup() {
  clearTimeout(saveTimer);
  try {
    setup = await api("/api/setup", { method: "POST", json: readForm() });
    pinMoved = false;
    setupStatus($("#f-name").value.trim() ? "Saved." : "Type the customer's name; the rest is saved.");
    refreshNotes();
    clearTimeout(savedTimer);
    savedTimer = setTimeout(() => { if ($("#setup-status").textContent === "Saved.") setupStatus(""); }, 1500);
    return true;
  } catch (error) {
    // Show what went wrong, but never overwrite what's being typed.
    setupStatus(error.message, true);
    if (pinMoved) pin.setLatLng([setup.pin.lat, setup.pin.lon]);
    pinMoved = false;
    setPlacesSource(setup.places_source);
    return false;
  }
}

const saveSoon = () => { clearTimeout(saveTimer); saveTimer = setTimeout(saveSetup, 500); };

async function drawPlaces() {
  const { lat, lon } = setup.pin;
  const { places } = await api(`/api/places?lat=${lat}&lon=${lon}&radius=1500`);
  drawPlaceDots(placeDots, places);
  return places.length;
}

function describePlaces(count) {
  if (setup.places_source === "osm") return `${count} real places from OpenStreetMap within 1.5 km of the pin. Hover over a dot on the map to see its name.`;
  if (count === 0) return "No sample places near this pin. The sample data only covers the demo area in Chennai: load real places, or add the ones you need.";
  return `${count} sample places within 1.5 km of the pin. Hover over a dot on the map to see its name.`;
}

function initMap() {
  map = createMap("setup-map", [setup.pin.lat, setup.pin.lon], 16);
  placeDots = L.layerGroup().addTo(map);
  pin = L.marker([setup.pin.lat, setup.pin.lon], {
    draggable: true, zIndexOffset: 1000, title: "The customer's saved pin. Drag to move.",
    icon: markers.pin(false, "Saved pin"),
  }).addTo(map);
  const moved = async () => {
    // Moving the pin erases the address's doorstep note: never let a stray click do that silently.
    if (currentNote && !window.confirm("Moving the saved pin deletes this address's doorstep note, so the next rider won't hear it. Move the pin anyway?")) {
      pin.setLatLng([setup.pin.lat, setup.pin.lon]);
      return;
    }
    pinMoved = true;
    if (!(await saveSetup())) return;
    const count = await drawPlaces();
    await refreshNotes();
    $("#places-status").textContent = setup.places_source === "osm"
      ? "You moved the pin. Press \"Load real places around the pin\" again so the places match the new spot."
      : describePlaces(count);
  };
  pin.on("dragend", moved);
  map.on("click", (event) => {
    if (addingPlace) {
      openPlaceForm(event.latlng);
      return;
    }
    pin.setLatLng(event.latlng);
    moved();
  });
}

function useMyLocation() {
  const status = $("#places-status");
  if (!window.isSecureContext || !navigator.geolocation) {
    status.textContent = "Browsers only share your location on https or localhost. Open the control room through localhost (SSH tunnel) or the cloudflared https address.";
    return;
  }
  if (currentNote && !window.confirm("Moving the saved pin deletes this address's doorstep note, so the next rider won't hear it. Move the pin anyway?")) {
    return;
  }
  const button = $("#use-location");
  button.disabled = true;
  button.classList.add("working");
  status.textContent = "Finding your location…";
  navigator.geolocation.getCurrentPosition(async (position) => {
    const { latitude, longitude, accuracy } = position.coords;
    pin.setLatLng([latitude, longitude]);
    map.setView([latitude, longitude], 16);
    button.disabled = false;
    button.classList.remove("working");
    pinMoved = true;
    if (!(await saveSetup())) return;
    await drawPlaces();
    await refreshNotes();
    const rough = accuracy > 200
      ? " That's rough: laptops often guess from the network, so drag the pin to the exact spot."
      : "";
    status.textContent = `Pin moved to your location, accurate to about ${Math.round(accuracy)} m.${rough} Next, press "Load real places around the pin".`;
  }, (error) => {
    button.disabled = false;
    button.classList.remove("working");
    status.textContent = error.code === error.PERMISSION_DENIED
      ? "Location access is blocked. Allow it in the browser's site settings, then try again."
      : "Couldn't get your location. Drag the pin instead.";
  }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
}

function setAdding(on) {
  addingPlace = on;
  $("#setup-map").classList.toggle("adding", on);
  $("#add-place").classList.toggle("on", on);
  $("#add-place").setAttribute("aria-pressed", String(on));
  $("#adding-hint").classList.toggle("hidden", !on);
  if (!on) map?.closePopup();
}

function openPlaceForm(latlng) {
  const name = el("input", { type: "text", placeholder: "Name, e.g. Aryabhatta Hostel", "aria-label": "Place name" });
  const kind = el("select", { "aria-label": "Kind of place" },
    ...config.kinds.map((k) => el("option", { value: k, text: kindName(k) })));
  kind.value = "hostel";
  const status = el("p", { class: "err", role: "alert" });
  const form = el("form", { class: "place-form" },
    el("h3", { text: "Add a missing place" }),
    el("label", { class: "field" }, "Name people use", name),
    el("label", { class: "field" }, "Kind", kind),
    status,
    el("div", { class: "row" },
      el("button", { type: "button", class: "quiet", onclick: () => setAdding(false) }, "Cancel"),
      el("button", { type: "submit", class: "primary" }, "Save place")));
  const popup = L.popup({ minWidth: 260, closeButton: false }).setLatLng(latlng).setContent(form).openOn(map);
  setTimeout(() => name.focus(), 50);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!name.value.trim()) {
      status.textContent = "Give it a name, as people would say it.";
      return;
    }
    try {
      await api("/api/places/custom", { method: "POST", json: { name: name.value.trim(), kind: kind.value, lat: latlng.lat, lon: latlng.lng } });
      map.closePopup(popup);
      setAdding(false);
      await drawPlaces();
      await refreshCustomPlaces();
    } catch (error) {
      status.textContent = error.message;
    }
  });
}

async function refreshCustomPlaces() {
  const { places } = await api("/api/places/custom");
  $("#custom-places").replaceChildren(...places.map((place) => el("li", {},
    el("span", { class: "place-name" }, el("span", {}, place.name, " ", el("small", { text: kindName(place.kind) }))),
    el("button", {
      type: "button", class: "quiet", title: `Remove ${place.name}`, "aria-label": `Remove ${place.name}`,
      onclick: async () => {
        await api(`/api/places/custom/${place.id}`, { method: "DELETE" });
        await drawPlaces();
        await refreshCustomPlaces();
      },
    }, icon("trash-2", "i-sm")))));
}

async function loadRealPlaces() {
  const button = $("#load-osm");
  button.disabled = true;
  button.classList.add("working");
  $("#places-status").textContent = "Asking OpenStreetMap for places around the pin. This can take up to a minute…";
  try {
    if (!(await saveSetup())) return;
    const result = await api("/api/places/osm", { method: "POST", json: { radius: 1500 } });
    setup = await api("/api/setup");
    fillForm();
    await drawPlaces();
    $("#places-status").textContent = `Loaded ${result.count} real places within 1.5 km: ${result.summary}. Hover over a dot to see its name.`;
  } catch (error) {
    $("#places-status").textContent = error.message;
  } finally {
    button.disabled = false;
    button.classList.remove("working");
  }
}

function noteCard(id, note) {
  // Name the note by who and where, as set now; the internal address code means nothing to people.
  const current = id === orders[0]?.address_id;
  const title = current ? setup.customer_name : (note.customer_name || "Saved address");
  const address = current ? setup.address_text : (note.address_text || "");
  const when = note.updated_at
    ? new Date(note.updated_at).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })
    : "";
  const count = note.deliveries_learned_from || 1;
  const pinFact = note.pin_correction ? ["Wrong; riders are sent to the corrected spot", "bad"]
    : note.confirmed_by_customer ? ["Moved to the right building by the customer", ""] : ["Correct", ""];
  const facts = [
    ["Building", note.building_description],
    ["Entrance", note.entrance],
    ["Floor", note.floor],
    ["Landmarks", (note.landmarks || []).join(", ")],
    ["Cautions", (note.cautions || []).join(", ")],
    ["Saved pin", pinFact[0], pinFact[1]],
    ["Learned from", `${count} ${count === 1 ? "delivery" : "deliveries"}${when ? `, updated ${when}` : ""}`],
  ].filter(([, value]) => value);
  return el("article", { class: "note" },
    el("div", { class: "note-top" },
      el("span", { class: "note-badge", "aria-hidden": "true" }, icon("door-open")),
      el("div", {}, el("p", { class: "note-title", text: title }), address ? el("p", { class: "note-sub", text: address }) : null)),
    note.summary_en ? el("p", { class: "note-summary", text: note.summary_en }) : null,
    el("dl", { class: "note-facts" }, ...facts.flatMap(([label, value, cls]) => [el("dt", { text: label }), el("dd", { class: cls || null, text: value })])));
}

async function refreshNotes() {
  const notes = await api("/api/notes");
  const entries = Object.entries(notes);
  currentNote = notes[orders[0]?.address_id] || null;
  $("#notes-count").textContent = String(entries.length);
  $("#notes-count").classList.toggle("hidden", !entries.length);
  $("#clear-notes").disabled = !entries.length;
  $("#notes").replaceChildren(...(entries.length
    ? entries.map(([id, note]) => noteCard(id, note))
    : [el("div", { class: "empty-state" },
        icon("notebook-text"),
        el("h3", { text: "No doorstep notes yet" }),
        el("p", { text: "After a delivery, Pata writes one here so the next rider never has to call." }))]));
}

function showTab(name) {
  for (const tab of ["call", "notes"]) {
    const on = tab === name;
    $(`#tab-${tab}`).setAttribute("aria-selected", String(on));
    $(`#tab-${tab}`).tabIndex = on ? 0 : -1;
    $(`#panel-${tab}`).hidden = !on;
  }
}

function renderPeople(s) {
  const source = (l) => (!l.auto ? "set here" : l.source === "detected" ? "detected from speech" : "not heard yet");
  const row = (name, role, l) => el("div", { class: "person" },
    el("span", { class: "avatar", "aria-hidden": "true", text: name.slice(0, 1) }),
    el("strong", { text: name }),
    el("span", {}, `${role}, speaks `, el("b", { text: l.name }), `, ${source(l)}`));
  const rows = [row(s.rider.name, "Rider", s.languages.rider), row(s.order.customer_name, "Customer", s.languages.customer)];
  if (s.note) {
    rows.push(el("div", { class: "person note-row" },
      el("span", { class: "avatar", "aria-hidden": "true" }, icon("notebook-text", "i-sm")),
      el("strong", { text: "Doorstep note" }),
      el("span", { text: s.directions?.kind === "briefing" || s.delivered ? `saved for this address`
        : `${s.rider.name} hears it in ${s.languages.rider.name} on Start Pata` })));
  }
  $("#people").replaceChildren(...rows);
  $("#people").classList.remove("hidden");
}

function watch(sessionId) {
  socket?.close();
  socket = connect(sessionId, (event) => {
    if (event.type !== "snapshot") return;
    const s = event.session;
    renderPeople(s);
    renderStatus($("#status"), s.status);
    renderLog($("#log"), s, "monitor", { scroller: $("#log-scroll") });
    $("#call-empty").classList.toggle("hidden", s.log.length > 0);
    if (!s.log.length) {
      $("#call-empty h3").textContent = "Waiting for both phones";
      $("#call-empty p").textContent = `Open the rider's phone and press Start Pata, then answer on ${s.order.customer_name}'s phone.`;
    }
    // The live call on the hero map.
    callLayers.riderLabel = s.rider.name;
    callLayers.render(s);
    $(".stage").classList.add("live");
    if (pinWrong !== s.pin_is_wrong) {
      pinWrong = s.pin_is_wrong;
      pin.setIcon(markers.pin(pinWrong, pinWrong ? "Saved pin, wrong" : "Saved pin"));
    }
    const stamp = s.note ? `${s.note.updated_at}|${s.note.confirmed_by_customer}` : "";
    if (stamp && stamp !== lastNoteStamp) {
      lastNoteStamp = stamp;
      refreshNotes();
      // If the customer agreed to fix the pin, the saved pin has moved on the server: show it here too.
      api("/api/setup").then((fresh) => {
        setup = fresh;
        pin.setLatLng([fresh.pin.lat, fresh.pin.lon]);
        drawPlaces();
      });
    }
  });
}

async function startSession() {
  if (!(await saveSetup())) return;
  try {
    const session = await api("/api/sessions", { method: "POST", json: { order_id: orders[0].id, rider_id: setup.rider_id } });
    $("#rider-link").href = `/rider?s=${session.id}`;
    $("#customer-link").href = `/customer?s=${session.id}`;
    $("#phones").classList.remove("hidden");
    setButton($("#start"), "rotate-ccw", "Start a new call session");
    $("#start").classList.remove("primary");
    $(".setup-foot").classList.add("live");
    $("#live-dot").classList.remove("hidden");
    showTab("call");
    $("#log").dataset.key = "";
    watch(session.id);
  } catch (error) {
    setupStatus(error.message, true);
  }
}

async function main() {
  $("#brand").innerHTML = `${BRAND_MARK}<span class="brand-name">Pata</span>`;
  hydrateIcons();
  themeSwitch($("#theme"));
  config = await api("/api/config");
  renderModes($("#modes"), config.modes);
  ({ orders, riders } = await api("/api/orders"));
  setup = await api("/api/setup");
  fillForm();
  initMap();
  callLayers = new CallLayers(map, { showPin: false });
  callLayers.fitOptions = () => ({ paddingTopLeft: [60, 100], paddingBottomRight: [80, 80] });
  $("#places-status").textContent = describePlaces(await drawPlaces());
  await refreshNotes();

  // Editing the address also erases its doorstep note: ask once, on the first keystroke.
  let addressOk = false;
  $("#f-address").addEventListener("focus", () => { addressOk = false; });
  $("#f-address").addEventListener("input", (event) => {
    if (!currentNote || addressOk) return;
    if (window.confirm("Changing the address deletes its doorstep note, so the next rider won't hear it. Change it anyway?")) {
      addressOk = true;
    } else {
      event.stopImmediatePropagation();
      $("#f-address").value = setup.address_text;
      $("#f-address").blur();
    }
  });
  for (const id of ["#f-name", "#f-address", "#f-items"]) $(id).addEventListener("input", saveSoon);
  for (const id of ["#f-customer-lang", "#f-customer-auto", "#f-rider-lang", "#f-rider-auto", "#f-hints"]) {
    $(id).addEventListener("change", saveSetup);
  }
  $("#riders").addEventListener("change", (event) => {
    const rider = riders.find((r) => r.id === event.target.value);
    if (rider) $("#f-rider-lang").value = rider.lang;
    saveSetup();
  });
  document.querySelectorAll('input[name="places"]').forEach((radio) => radio.addEventListener("change", async () => {
    if (await saveSetup()) $("#places-status").textContent = describePlaces(await drawPlaces());
  }));
  $("#load-osm").addEventListener("click", loadRealPlaces);
  $("#add-place").addEventListener("click", () => setAdding(!addingPlace));
  $("#cancel-add").addEventListener("click", () => setAdding(false));
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && addingPlace) setAdding(false); });
  $("#tab-call").addEventListener("click", () => showTab("call"));
  $("#tab-notes").addEventListener("click", () => showTab("notes"));
  $(".tabs").addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const next = $("#tab-call").getAttribute("aria-selected") === "true" ? "notes" : "call";
    showTab(next);
    $(`#tab-${next}`).focus();
  });
  document.querySelectorAll("[data-copy]").forEach((button) => button.addEventListener("click", async () => {
    const link = new URL($(`#${button.dataset.copy}`).getAttribute("href"), location.href).href;
    try {
      await navigator.clipboard.writeText(link);
      button.classList.add("done");
      button.replaceChildren(icon("check", "i-sm"));
      setTimeout(() => { button.classList.remove("done"); button.replaceChildren(icon("copy", "i-sm")); }, 1600);
    } catch {
      window.prompt("Copy this link", link);
    }
  }));
  await refreshCustomPlaces();
  $("#use-location").addEventListener("click", useMyLocation);
  $("#start").addEventListener("click", startSession);
  $("#clear-notes").addEventListener("click", async () => {
    await api("/api/notes", { method: "DELETE" });
    await refreshNotes();
  });
  showTab("call");
}

main().catch((error) => setupStatus(error.message, true));

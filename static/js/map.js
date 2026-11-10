// The map, shared by the control room and the rider's phone.
// Tiles come from OpenStreetMap, which needs no API key. They are restyled in CSS to suit the theme:
// muted by day, inverted to a dark map at night. Geometry here is for drawing only: distances that
// matter to the call are computed by the server in app/geo.py.

const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

export const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const esc = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------------------------------------------------------------- display geometry

const toRad = (d) => (d * Math.PI) / 180;
const toDeg = (r) => (r * 180) / Math.PI;

export function distanceM(a, b) {
  const R = 6371000;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

export function bearing(a, b) {
  const y = Math.sin(toRad(b.lon - a.lon)) * Math.cos(toRad(b.lat));
  const x = Math.cos(toRad(a.lat)) * Math.sin(toRad(b.lat)) -
    Math.sin(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.cos(toRad(b.lon - a.lon));
  return (toDeg(Math.atan2(y, x)) + 360) % 360;
}

export function move(point, heading, metres) {
  const d = metres / 6371000;
  const b = toRad(heading);
  const lat1 = toRad(point.lat);
  const lon1 = toRad(point.lon);
  const lat2 = Math.asin(Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(b));
  const lon2 = lon1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(lat1), Math.cos(d) - Math.sin(lat1) * Math.sin(lat2));
  return { lat: toDeg(lat2), lon: toDeg(lon2) };
}

const COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"];
export const compass = (deg) => COMPASS[Math.round(deg / 45) % 8];

export function formatDistance(m) {
  if (m < 1000) return { value: String(Math.max(0, Math.round(m / 10) * 10)), unit: "m" };
  return { value: (m / 1000).toFixed(m < 10000 ? 1 : 0), unit: "km" };
}

// ---------------------------------------------------------------- basemap

export function createMap(elementId, center, zoom, options = {}) {
  const map = L.map(elementId, { zoomControl: false, attributionControl: true, ...options }).setView(center, zoom);
  L.control.zoom({ position: options.zoomPosition || "topright" }).addTo(map);
  map.attributionControl.setPrefix(false);

  L.tileLayer(OSM, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map);
  // The tiles restyle themselves through CSS when the theme changes; markers redraw in the new colours.
  window.pataTheme?.onChange(() => map.fire("themechange"));
  return map;
}

// ---------------------------------------------------------------- markers

const div = (html, anchor) => L.divIcon({ className: "mk", html, iconSize: null, iconAnchor: anchor });

const PIN_SVG = `<svg viewBox="0 0 22 28" aria-hidden="true"><path class="body" d="M11 0.8C5.4 0.8 1 5.2 1 10.7c0 6.9 8 14.6 9.3 15.9a1 1 0 0 0 1.4 0C13 25.3 21 17.6 21 10.7 21 5.2 16.6 0.8 11 0.8Z"/><circle class="hole" cx="11" cy="10.6" r="3.6"/></svg>`;
const DEST_SVG = `<svg viewBox="0 0 30 38" aria-hidden="true"><path class="body" d="M15 1C7.3 1 1.2 7.1 1.2 14.7c0 9.4 11 20 12.8 21.7a1.4 1.4 0 0 0 2 0c1.8-1.7 12.8-12.3 12.8-21.7C28.8 7.1 22.7 1 15 1Z"/><g class="door" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10.5 20.5h9"/><path d="M12 20.5V9.5h6v11"/><path d="M15.8 15.3h.01"/></g></svg>`;

export const markers = {
  pin: (wrong, label = wrong ? "Saved pin, wrong" : "Saved pin") =>
    div(`<div class="mk-pin ${wrong ? "wrong" : ""}">${PIN_SVG}${label ? `<span class="mk-label">${esc(label)}</span>` : ""}</div>`, [11, 27]),
  dest: (name) => div(`<div class="mk-dest">${DEST_SVG}<span class="mk-label">${esc(name)}'s building</span></div>`, [15, 37]),
  rider: (heading, label) =>
    div(`<div class="mk-rider" style="--heading:${Math.round(heading || 0)}deg">${label ? `<span class="mk-label">${esc(label)}</span>` : ""}</div>`, [13, 13]),
  site: (site, dim) => {
    const names = site.members.map((p) => esc(p.name)).join(" + ");
    const near = site.features.find((f) => f.kind !== "building");
    return div(`<div class="mk-site ${dim ? "dim" : ""}"><i></i><span class="mk-label"><b>${esc(site.id)}</b>${names}${near ? `<small>by ${esc(near.name)}</small>` : ""}</span></div>`, [9, 9]);
  },
  place: (kind = "") => div(`<div class="mk-place ${kind}"><i></i></div>`, [5, 5]),
};

const kindName = (kind) => ({ petrol_pump: "petrol bunk", atm: "ATM" }[kind] || String(kind).replace(/_/g, " "));
export { kindName };

/** Small dots for every known place, names on hover. Places added by hand are amber rings. */
export function drawPlaces(group, places) {
  group.clearLayers();
  for (const place of places) {
    const mine = place.source === "you";
    L.marker([place.lat, place.lon], { icon: markers.place(mine ? "mine" : ""), keyboard: false, zIndexOffset: mine ? 100 : 0 })
      .bindTooltip(`${place.name}, ${kindName(place.kind)}${mine ? ", added by you" : ""}`, { direction: "top", offset: [0, -4] })
      .addTo(group);
  }
}

// ---------------------------------------------------------------- the live call on a map

/**
 * Draws what Pata knows during a call: candidate spots, the found building, the dotted line from
 * the wrong pin to the real door, and the rider. Used by the rider's phone and the control room.
 */
export class CallLayers {
  constructor(map, { showPin = true, riderDraggable = false, riderLabel = null } = {}) {
    this.map = map;
    this.showPin = showPin;
    this.riderLabel = riderLabel;
    this.sites = L.layerGroup().addTo(map);
    this.route = L.layerGroup().addTo(map);
    this.pin = null;
    this.rider = L.marker([0, 0], { icon: markers.rider(0, riderLabel), draggable: riderDraggable, zIndexOffset: 1000, keyboard: false });
    this.fitKey = "";
    this.last = null;
    map.on("themechange", () => this.last && this.render(this.last));
  }

  render(s) {
    this.last = s;
    const pin = s.order.pin;
    const resolvedId = s.resolved_site?.id;
    this.sites.clearLayers();
    this.route.clearLayers();

    for (const site of s.sites) {
      if (site.id !== resolvedId) {
        L.marker([site.lat, site.lon], { icon: markers.site(site, Boolean(resolvedId)), keyboard: false, zIndexOffset: 300 }).addTo(this.sites);
      }
      for (const place of site.members) {
        L.marker([place.lat, place.lon], { icon: markers.place("member"), keyboard: false })
          .bindTooltip(place.name, { direction: "top", offset: [0, -4] }).addTo(this.sites);
      }
      for (const place of site.features) {
        if (place.kind === "building") continue;
        L.marker([place.lat, place.lon], { icon: markers.place(""), keyboard: false })
          .bindTooltip(place.name, { direction: "top", offset: [0, -4] }).addTo(this.sites);
      }
    }

    const dest = s.destination;
    if (this.showPin) {
      if (!this.pin) this.pin = L.marker([pin.lat, pin.lon], { keyboard: false, zIndexOffset: 500 }).addTo(this.map);
      this.pin.setLatLng([pin.lat, pin.lon]);
      // Once the red line says how far off the pin is, the pin itself needs no label.
      this.pin.setIcon(markers.pin(s.pin_is_wrong, s.pin_is_wrong && dest ? "" : undefined));
    }

    const joined = s.joined?.includes("rider");
    if (joined || this.rider.options.draggable) {
      if (!this.map.hasLayer(this.rider)) this.rider.addTo(this.map);
      this.rider.setLatLng([s.rider_pos.lat, s.rider_pos.lon]);
      this.rider.setIcon(markers.rider(s.rider_pos.heading, this.riderLabel));
    } else if (this.map.hasLayer(this.rider)) {
      this.rider.remove();
    }

    if (dest) {
      if (s.pin_is_wrong) {
        const off = Math.round(distanceM(pin, dest) / 10) * 10;
        L.polyline([[pin.lat, pin.lon], [dest.lat, dest.lon]], {
          color: css("--red"), weight: 4, dashArray: "0.1 9", lineCap: "round", interactive: false,
        }).bindTooltip(`Pin is ${off} m off`, { permanent: true, direction: "center", className: "off-label" }).addTo(this.route);
      }
      if (!s.arrived && distanceM(dest, s.rider_pos) > 25 && distanceM(pin, s.rider_pos) > 25) {
        L.polyline([[s.rider_pos.lat, s.rider_pos.lon], [dest.lat, dest.lon]], {
          color: css("--amber"), weight: 3, dashArray: "0.1 7", lineCap: "round", opacity: 0.9, interactive: false,
        }).addTo(this.route);
      }
      L.marker([dest.lat, dest.lon], { icon: markers.dest(s.order.customer_name), zIndexOffset: 800, title: dest.label, keyboard: false }).addTo(this.route);
    }

    const key = JSON.stringify([s.sites.map((x) => x.id), resolvedId, Boolean(dest), pin.lat, pin.lon]);
    if (key !== this.fitKey) {
      this.fitKey = key;
      this.refit();
    }
  }

  /** Frame what matters now: the candidate spots while asking, then just pin, building and rider. */
  refit() {
    const s = this.last;
    if (!s) return;
    const pin = s.order.pin;
    const dest = s.destination;
    const points = [[pin.lat, pin.lon]];
    if (dest) points.push([dest.lat, dest.lon]);
    else points.push(...s.sites.map((x) => [x.lat, x.lon]));
    if (s.joined?.includes("rider")) points.push([s.rider_pos.lat, s.rider_pos.lon]);
    if (points.length > 2 || dest) this.map.fitBounds(points, { maxZoom: 17, ...(this.fitOptions?.() || { padding: [56, 56] }) });
  }
}

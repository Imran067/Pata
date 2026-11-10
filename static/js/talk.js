// Tap to start talking, tap again to send. Shared by the rider and customer phones.
import { api, el, icon } from "./common.js";
import { WavRecorder } from "./recorder.js";

function micMessage(error) {
  if (error?.name === "NotAllowedError") {
    return "Microphone access is blocked. Allow it in the browser's site settings, then tap again.";
  }
  if (error?.name === "NotFoundError") return "No microphone was found on this device.";
  return error?.message || "The microphone could not start.";
}

export async function sendText(sessionId, role, text) {
  const form = new FormData();
  form.append("role", role);
  form.append("text", text);
  await api(`/api/sessions/${sessionId}/turn`, { method: "POST", form });
}

const ICONS = { idle: "mic", listening: "mic", sending: "loader-circle" };

export function setupTalk({ button, role, sessionId, queue, labels, onError }) {
  let state = "idle";
  const level = el("span", { class: "level", "aria-hidden": "true" }, el("i"), el("i"), el("i"), el("i"), el("i"));
  const recorder = new WavRecorder({
    onAutoStop: () => send(),
    onLevel: (value) => level.style.setProperty("--lvl", value.toFixed(2)),
  });

  const set = (next) => {
    state = next;
    button.classList.toggle("listening", next === "listening");
    button.classList.toggle("sending", next === "sending");
    button.replaceChildren(icon(ICONS[next], "i-lg"), level, el("span", { class: "label", text: labels[next] }));
    button.setAttribute("aria-pressed", String(next === "listening"));
  };
  // The page can rename the button (a new customer name, another language) without losing its state.
  button.relabel = () => { const node = button.querySelector(".label"); if (node) node.textContent = labels[state]; };

  async function send() {
    if (state !== "listening") return;
    set("sending");
    try {
      const blob = await recorder.stop();
      const form = new FormData();
      form.append("role", role);
      form.append("audio", blob, "turn.wav");
      await api(`/api/sessions/${sessionId}/turn`, { method: "POST", form });
    } catch (error) {
      onError(error.message);
    } finally {
      set("idle");
    }
  }

  button.addEventListener("click", async () => {
    if (state === "idle") {
      queue.stop(); // don't record Pata's own voice
      try {
        await recorder.start();
        set("listening");
      } catch (error) {
        onError(micMessage(error));
      }
    } else if (state === "listening") {
      await send();
    }
  });

  set("idle");
}

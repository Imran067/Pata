import {
  $, el, api, connect, AudioQueue, renderLog, renderStatus, sessionIdFromUrl, langAttr, languageName, hydrateIcons, themeCycle, lostPage,
} from "./common.js";
import { setupTalk, sendText } from "./talk.js";

// Screen labels in the customer's language. Have a native speaker check these.
const STRINGS = {
  "ta-IN": {
    partner: "டெலிவரி நபர்", calling: "உங்கள் ஆர்டர் பற்றி அழைக்கிறார்", pata: "Pata மொழிபெயர்க்கிறது",
    answer: "பதிலளி", idle: "பேச அழுத்தவும்", listening: "கேட்கிறேன்… அனுப்ப மீண்டும் அழுத்தவும்",
    sending: "அனுப்புகிறது…", yes: "ஆம்", no: "வேண்டாம்", you: "நீங்கள்",
    failed: "அனுப்ப முடியவில்லை. மீண்டும் சொல்லுங்கள்.",
  },
  "hi-IN": {
    partner: "डिलीवरी पार्टनर", calling: "आपके ऑर्डर के बारे में कॉल कर रहे हैं", pata: "Pata अनुवाद कर रहा है",
    answer: "जवाब दें", idle: "बोलने के लिए दबाएँ", listening: "सुन रहे हैं… भेजने के लिए फिर दबाएँ",
    sending: "भेज रहे हैं…", yes: "हाँ", no: "नहीं", you: "आप",
    failed: "संदेश नहीं गया। कृपया फिर से बोलिए।",
  },
  "bn-IN": {
    partner: "ডেলিভারি পার্টনার", calling: "আপনার অর্ডারের ব্যাপারে কল করছেন", pata: "Pata অনুবাদ করছে",
    answer: "উত্তর দিন", idle: "কথা বলতে চাপুন", listening: "শুনছি… পাঠাতে আবার চাপুন",
    sending: "পাঠানো হচ্ছে…", yes: "হ্যাঁ", no: "না", you: "আপনি",
    failed: "বার্তাটি যায়নি। আবার বলুন।",
  },
  "te-IN": {
    partner: "డెలివరీ పార్ట్‌నర్", calling: "మీ ఆర్డర్ గురించి కాల్ చేస్తున్నారు", pata: "Pata అనువదిస్తోంది",
    answer: "కాల్ ఎత్తండి", idle: "మాట్లాడటానికి నొక్కండి", listening: "వింటున్నాను… పంపడానికి మళ్ళీ నొక్కండి",
    sending: "పంపుతోంది…", yes: "అవును", no: "వద్దు", you: "మీరు",
    failed: "సందేశం వెళ్లలేదు. దయచేసి మళ్ళీ చెప్పండి.",
  },
  "kn-IN": {
    partner: "ಡೆಲಿವರಿ ಪಾರ್ಟ್ನರ್", calling: "ನಿಮ್ಮ ಆರ್ಡರ್ ಬಗ್ಗೆ ಕರೆ ಮಾಡುತ್ತಿದ್ದಾರೆ", pata: "Pata ಅನುವಾದಿಸುತ್ತಿದೆ",
    answer: "ಕರೆ ಸ್ವೀಕರಿಸಿ", idle: "ಮಾತನಾಡಲು ಒತ್ತಿ", listening: "ಆಲಿಸುತ್ತಿದೆ… ಕಳುಹಿಸಲು ಮತ್ತೆ ಒತ್ತಿ",
    sending: "ಕಳುಹಿಸಲಾಗುತ್ತಿದೆ…", yes: "ಹೌದು", no: "ಬೇಡ", you: "ನೀವು",
    failed: "ಸಂದೇಶ ಹೋಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಮತ್ತೆ ಹೇಳಿ.",
  },
  "ml-IN": {
    partner: "ഡെലിവറി പാർട്ണർ", calling: "നിങ്ങളുടെ ഓർഡറിനെക്കുറിച്ച് വിളിക്കുന്നു", pata: "Pata വിവർത്തനം ചെയ്യുന്നു",
    answer: "കോൾ എടുക്കുക", idle: "സംസാരിക്കാൻ അമർത്തുക", listening: "കേൾക്കുന്നു… അയയ്ക്കാൻ വീണ്ടും അമർത്തുക",
    sending: "അയയ്ക്കുന്നു…", yes: "അതെ", no: "വേണ്ട", you: "നിങ്ങൾ",
    failed: "സന്ദേശം പോയില്ല. ദയവായി വീണ്ടും പറയൂ.",
  },
  "mr-IN": {
    partner: "डिलिव्हरी पार्टनर", calling: "तुमच्या ऑर्डरबद्दल कॉल करत आहेत", pata: "Pata भाषांतर करत आहे",
    answer: "कॉल उचला", idle: "बोलण्यासाठी दाबा", listening: "ऐकत आहे… पाठवण्यासाठी पुन्हा दाबा",
    sending: "पाठवत आहे…", yes: "हो", no: "नको", you: "तुम्ही",
    failed: "संदेश गेला नाही. कृपया पुन्हा बोला.",
  },
  "gu-IN": {
    partner: "ડિલિવરી પાર્ટનર", calling: "તમારા ઓર્ડર વિશે કૉલ કરી રહ્યા છે", pata: "Pata અનુવાદ કરી રહ્યું છે",
    answer: "કૉલ ઉપાડો", idle: "બોલવા માટે દબાવો", listening: "સાંભળી રહ્યું છે… મોકલવા ફરી દબાવો",
    sending: "મોકલી રહ્યું છે…", yes: "હા", no: "ના", you: "તમે",
    failed: "સંદેશ ગયો નહીં. કૃપા કરીને ફરી બોલો.",
  },
  "pa-IN": {
    partner: "ਡਿਲੀਵਰੀ ਪਾਰਟਨਰ", calling: "ਤੁਹਾਡੇ ਆਰਡਰ ਬਾਰੇ ਕਾਲ ਕਰ ਰਹੇ ਹਨ", pata: "Pata ਅਨੁਵਾਦ ਕਰ ਰਿਹਾ ਹੈ",
    answer: "ਕਾਲ ਚੁੱਕੋ", idle: "ਬੋਲਣ ਲਈ ਦਬਾਓ", listening: "ਸੁਣ ਰਿਹਾ ਹੈ… ਭੇਜਣ ਲਈ ਮੁੜ ਦਬਾਓ",
    sending: "ਭੇਜ ਰਿਹਾ ਹੈ…", yes: "ਹਾਂ", no: "ਨਹੀਂ", you: "ਤੁਸੀਂ",
    failed: "ਸੁਨੇਹਾ ਨਹੀਂ ਗਿਆ। ਕਿਰਪਾ ਕਰਕੇ ਦੁਬਾਰਾ ਬੋਲੋ।",
  },
  "en-IN": {
    partner: "Delivery partner", calling: "is calling about your order", pata: "Pata translates this call",
    answer: "Answer", idle: "Tap to talk", listening: "Listening… tap to send",
    sending: "Sending…", yes: "Yes", no: "No", you: "You",
    failed: "That didn't go through. Please say it again.",
  },
};

const sessionId = sessionIdFromUrl();
const queue = new AudioQueue();
let session = null;
let t = STRINGS["en-IN"];
let currentLang = null;
let scriptLines = null;
const talkLabels = {};
let answeredAt = null;
let timer = null;

function showError(text) {
  const node = $("#status");
  node.textContent = text;
  node.classList.remove("busy");
  node.classList.add("error");
  setTimeout(() => node.classList.remove("error"), 6000);
}

function render() {
  const s = session;
  if (s.customer_lang !== currentLang) applyLanguage(s.customer_lang); // Prisma may detect another language
  const joined = s.joined.includes("customer");
  $("#incoming").classList.toggle("hidden", joined);
  $("#incall").classList.toggle("hidden", !joined);
  if (joined && !timer) startTimer();
  renderStatus($("#status"), s.status);
  renderLog($("#log"), s, "customer", { scroller: $("#scroller"), labels: { you: t.you, failed: t.failed } });
  const pending = s.pin_fix_pending && s.log.filter((e) => e.kind === "pin_fix").at(-1);
  $("#pinfix").classList.toggle("hidden", !pending);
  if (pending) {
    $("#pinfix-text").textContent = pending.text;
    $("#pinfix-text").lang = langAttr(s.customer_lang);
  }
}

function startTimer() {
  answeredAt = answeredAt || Date.now();
  const tick = () => {
    const secs = Math.floor((Date.now() - answeredAt) / 1000);
    $("#timer").textContent = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
  };
  tick();
  timer = setInterval(tick, 1000);
}

function renderChips() {
  if (!scriptLines) return;
  const mine = scriptLines.filter((l) => l.role === "customer");
  $("#chips").replaceChildren(...(mine.length
    ? mine.map((line) => el("button", {
        type: "button", lang: langAttr(line.lang), title: line.gloss_en,
        onclick: () => sendText(sessionId, "customer", line.text).catch((e) => showError(e.message)),
      }, el("span", { class: "lang", lang: "en", text: languageName(line.lang) }), el("span", { text: line.text })))
    : [el("p", { class: "drawer-note", text: "No practice lines yet. Add some to data/demo_script.json, or type." })]));
}

function applyLanguage(code) {
  currentLang = code;
  t = STRINGS[code] || STRINGS["en-IN"];
  document.documentElement.lang = langAttr(code);
  const rider = session.rider.name;
  $("#avatar").textContent = rider.slice(0, 1);
  $("#incall-avatar").textContent = rider.slice(0, 1);
  $("#partner").textContent = t.partner;
  $("#caller").textContent = rider;
  $("#calling").textContent = t.calling;
  $("#pata-line").textContent = t.pata;
  $("#answer-label").textContent = t.answer;
  $("#answer").setAttribute("aria-label", t.answer);
  $("#incall-name").textContent = rider;
  $("#incall-sub").textContent = t.pata;
  $("#type-input").placeholder = t.idle;
  $("#pinfix-yes").textContent = t.yes;
  $("#pinfix-no").textContent = t.no;
  Object.assign(talkLabels, { idle: t.idle, listening: t.listening, sending: t.sending });
  $("#talk").relabel?.();
  renderChips();
}

async function main() {
  if (!sessionId) {
    lostPage();
    return;
  }
  hydrateIcons();
  themeCycle($("#theme-btn"));
  session = await api(`/api/sessions/${sessionId}`);
  applyLanguage(session.customer_lang);
  render();

  setupTalk({
    button: $("#talk"),
    role: "customer",
    sessionId,
    queue,
    labels: talkLabels,
    onError: showError,
  });

  connect(sessionId, (event) => {
    if (event.type === "snapshot") {
      session = event.session;
      render();
    } else if (event.type === "audio" && event.for === "customer") {
      queue.push(event.url);
    } else if (event.type === "gone") {
      showError("This call has ended.");
    }
  });

  $("#answer").addEventListener("click", async () => {
    queue.unlock();
    try {
      await api(`/api/sessions/${sessionId}/join`, { method: "POST", json: { role: "customer" } });
    } catch (error) {
      showError(error.message);
    }
  });

  const answerPinFix = (accept) => api(`/api/sessions/${sessionId}/pin-fix`, { method: "POST", json: { accept } })
    .catch((e) => showError(e.message));
  $("#pinfix-yes").addEventListener("click", () => answerPinFix(true));
  $("#pinfix-no").addEventListener("click", () => answerPinFix(false));

  $("#type-toggle").addEventListener("click", () => {
    const drawer = $("#type-drawer");
    drawer.hidden = !drawer.hidden;
    $("#type-toggle").setAttribute("aria-expanded", String(!drawer.hidden));
    if (!drawer.hidden) $("#type-input").focus({ preventScroll: true });
  });

  $("#type-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#type-input");
    const text = input.value.trim();
    if (!text) return;
    try {
      await sendText(sessionId, "customer", text);
      input.value = "";
    } catch (error) {
      showError(error.message);
    }
  });

  scriptLines = (await api("/api/script")).lines;
  renderChips();
}

main().catch((error) => showError(error.message));

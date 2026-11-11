# Pata: the doorstep call copilot

When a delivery rider can't find the building, he calls the customer. Often they don't share a language, the saved pin is wrong, and whatever they work out is forgotten before the next delivery.

Pata sits inside that call. Each person speaks their own language. Pata translates both ways, turns the customer's landmarks into pins on the rider's map, notices when the saved pin is wrong, asks the customer a clarifying question itself when two places fit, and writes a doorstep note so the next rider never has to call.

Built for Gnani AI's Great Indian AI Internship Challenge, on all three Gnani models: Prisma, Evon and Timbre.

**One-page solution pitch:** [SOLUTION_PITCH.md](SOLUTION_PITCH.md)

---

## Our demo: a wrong pin at IIT (BHU), Varanasi

We filmed Pata on a real campus with real map data, live Gnani models, and three people who speak three different languages.

| Who | Role in Pata | Speaks |
|---|---|---|
| Rahul | Rider (played by Sourav in the video) | Hindi, with English words (Hinglish) |
| Rounak | Customer, in his room near SN Bose Hostel | Bengali, with English words (Benglish) |
| Karthik | The next day's rider | Tamil |

What happens:

1. **Wrong pin.** Rahul reaches the customer's saved pin, the back gate of Aryabhatta Hostel near the swimming pool. There is no building there. He says "let me use Pata" and taps **Start Pata**.
2. **The call.** Rounak's phone rings in Bengali. When he answers, each person hears, in their own language, that an AI is translating the call.
3. **Hinglish in, Bengali out.** Rahul taps **Talk** and says: *"Hello भैया, हाँ मैं swimming pool के पास आ गया भैया।"* Prisma transcribes it, keeping the English words in English letters. Evon rewrites it in Bengali, and Timbre speaks it on Rounak's phone.
4. **Benglish in, Hindi out.** Rounak answers: *"Hello দাদা, তুমি ভুল রাস্তায় চলে গেছ। তুমি SN Bose Hostel গেটের সামনে চলে এসো।"* (you've taken the wrong road; come to the SN Bose Hostel gate). Rahul hears it in Hindi.
5. **The map finds the building.** Pata looks up "SN Bose" among real places around the pin. Two spots fit, and Evon picks the one by SN Bose Hostel. The map shows the building with a red dotted line from the saved pin, labelled **Pin is 160 m off**.
6. **Directions.** Rahul's card shows the live distance and direction ("270 m, to the south, on your left"). Timbre reads the directions in Hindi, slowly, for traffic.
7. **Delivered.** Rahul taps **Mark delivered**. Evon writes a doorstep note for the address, and Pata asks Rounak in Bengali whether to move his saved location to the right building. He taps yes.
8. **Next day.** Karthik, who speaks Tamil, starts a delivery to the same address. Before calling anyone, he hears the doorstep note in Tamil, and the saved pin already points at the right building. He doesn't need to call.

Three Indian languages across two deliveries, two kinds of code-mixed speech, and a wrong pin fixed for every rider after the first.

---

## How the three models are used

| Model | What it does in Pata | Features used |
|---|---|---|
| **Prisma v3.0** (speech to text) | Transcribes every press-to-talk turn from the rider and the customer | `indic-auto` on the customer's first turn when detection is on, otherwise the set language plus English for code-mixed speech; `keyterms` filled with up to 60 names of real places around the pin; a `topic` sentence; `format=transcribe` so place names stay in English letters and numbers become digits |
| **Evon** (gnani-evon-v3.3-30B-A3B) | Five jobs: rewrites each turn for the listener and extracts landmarks; decides which map spot the customer means, or writes the question that tells two apart; phrases directions; merges each call into the doorstep note; briefs the next rider | Reasoning off for quick turn-by-turn work, on for matching and notes (`enable_thinking`); every reply is validated JSON; every spoken reply is checked for the right script and retried once if wrong; Evon never produces coordinates or distances |
| **Timbre v3.0** (text to speech) | Speaks to each person in their own language: the AI disclosure, translated turns, questions to the customer, directions and briefings to the rider | One voice per listener (every v3.0 voice speaks all ten languages); the `<slow>` tag for directions heard in traffic; an on-disk cache so repeated lines cost credits once |

The geometry (distances, left and right, nearby-place search) is plain Python in `app/geo.py`. The language model decides what people meant; it does no maths.

---

## How a call works, step by step

This is the path one spoken turn takes through the code (`app/pipeline.py`):

1. **Speech to text.** The phone records while Talk is pressed and uploads a WAV. Prisma transcribes it, with nearby place names as hints, only in English and the speaker's own script.
2. **Language.** With **Detect automatically** off, the language stays as set. With it on, Pata switches only when Prisma and Evon agree, the script matches, and (once confirmed) two turns in a row are in the new language (`app/language_tracking.py`).
3. **Relay and landmarks.** Evon rewrites the turn for the listener and, for the customer's turns, lists the places mentioned (`RelayOut` in `app/models.py`). The reply must be valid JSON. If Evon's server ignores JSON mode and a reply has a missing comma or similar slip, Pata repairs it locally; if a reply is beyond repair, it keeps the message or falls back to a plain translation (`app/services/evon.py`).
4. **Safety net for place names.** Pata also checks the customer's own words against the names of places near the pin (`spot_places` in `app/geo.py`). "SN Bose", "S. N. Bose" and small misspellings all match "S. N. Bose Hostel", even if Evon left it out.
5. **Candidate spots.** The map code finds clusters of real places that fit the landmarks (`candidate_sites`). One fit: Evon confirms it. Two or more: Evon either picks one with a reason, or writes a question for the customer in their language.
6. **Directions.** The map code computes distance, compass direction and left or right. Evon only phrases them, and Timbre reads them slowly. The saved pin counts as wrong when the building is more than `NEAR_PIN_M` (150 m) from it.
7. **Doorstep note.** On **Mark delivered**, Evon merges the call into the note for the address. Code then checks the note (`app/note_guard.py`): a room or flat number must come from the address or the call, and a floor or caution nobody mentioned is dropped. Pata then asks the customer whether to move the saved pin.
8. **Next rider.** A call session started after the delivery reads the note to the rider, in his language, when he taps **Start Pata**. **Hear the doorstep note** replays it.

---

## Quick start (mock mode, no keys needed)

Mock mode stands in for all three models, so you can try the screens before your Gnani key and Evon server are ready. Its generated sentences start with "(mock)".

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --port 8080
```

Open http://localhost:8080, press **Start a call session**, then open **Rider's phone** and **Customer's phone**. Press **Start Pata** on the rider's phone and **Answer** on the customer's phone, then use the practice lines behind the keyboard button beside **Talk**.

---

## Going live: the full setup we used

We ran Pata on an Ubuntu laptop, Evon on a separate GPU machine reached over SSH, and both phones through an https tunnel. You need four terminals, opened in this order.

### 1. Evon on the GPU machine (terminal 1)

**With a 24 GB GPU** (RTX 4090, RTX PRO 4000 Blackwell), use llama.cpp and the community 4-bit GGUF. One-time setup on the GPU machine:

```bash
nvidia-smi && nvcc --version        # Blackwell cards need CUDA 12.8 or newer
git clone https://github.com/ggml-org/llama.cpp ~/llama.cpp
cd ~/llama.cpp && cmake -B build -DGGML_CUDA=ON && cmake --build build --config Release -j
pip install -U huggingface_hub
hf download luminenio/gnani-evon-v3.3-30B-A3B-GGUF --include "*Q4_K_M*" --local-dir ~/models/evon
```

Every time:

```bash
ssh you@gpu-machine
tmux new -s evon
~/llama.cpp/build/bin/llama-server -m ~/models/evon/*Q4_K_M*.gguf --jinja -ngl 99 -c 16384 --host 127.0.0.1 --port 8000
```

Detach with **Ctrl+B**, then **D**; Evon keeps running if SSH drops, and `tmux attach -t evon` brings it back. This is the same command `scripts/serve_evon_llamacpp.sh` runs. Keep `--jinja`: without it the server may ignore Pata's requests to switch reasoning off and to answer in JSON.

**With an 80 GB GPU** (A100, H100, H200), use vLLM instead: `pip install "vllm>=0.12"`, then `bash scripts/serve_evon.sh`.

### 2. Connect the laptop to Evon (terminal 2, on the laptop)

```bash
ssh -N -L 8000:127.0.0.1:8000 you@gpu-machine
curl http://localhost:8000/v1/models     # in another terminal: should print JSON naming the model
```

The forward prints nothing while it works; leave it open. Skip this terminal if Evon runs on the laptop itself.

### 3. Settings in `.env`

These are the settings we used. Everything else stays as in `.env.example`.

```
GNANI_API_KEY=your-gnani-key
EVON_BASE_URL=http://localhost:8000/v1
EVON_JSON_MODE=1
EVON_REASONING=1
EVON_REASONING_TOKENS=3000
PRISMA_KEYTERMS_MAX=60
TIMBRE_VOICE_RIDER=Yashraj
TIMBRE_VOICE_CUSTOMER=Shivani
```

Optional thresholds (shown with their defaults; add a line only to change one):

| Setting | Default | What it does |
|---|---|---|
| `NEAR_PIN_M` | 150 | The saved pin counts as wrong when the building is farther than this. Our pin was 160 m off. If your gap is smaller, lower it (for example 60). |
| `ARRIVE_RADIUS_M` | 40 | The rider has arrived when he is this close to the building. |
| `SEARCH_RADIUS_M` | 1500 | How far around the pin Pata looks for places. |

If Pata takes too long to ask its question on a slower GPU, set `EVON_REASONING_TOKENS=2500`, or `EVON_REASONING=0`.

### 4. Pata on the laptop (terminal 3)

```bash
cd ~/pata
source .venv/bin/activate
python scripts/smoke_test_gnani.py      # optional, spends a few credits: Timbre speaks, Prisma hears, Evon translates
uvicorn app.main:app --port 8080
```

### 5. The phones (terminal 4)

Phone browsers only allow the microphone and GPS on `https`, so expose the laptop through a free tunnel. On Ubuntu, install cloudflared once:

```bash
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb       # arm64 machines: use cloudflared-linux-arm64.deb
```

Then, every time:

```bash
cloudflared tunnel --url http://localhost:8080
```

Open the printed `https://….trycloudflare.com` address **on the laptop**, so the phone links use the tunnel too. All three models at the top should say **live**. Start a call session, then send each phone its link with the copy buttons beside **Rider's phone** and **Customer's phone**. The address changes each time cloudflared restarts. Stop the tunnel after the demo: Pata has no login.

---

## Reproduce our demo: exact control room settings

1. **Clear doorstep notes** (Doorstep notes tab), so the first rider has nothing to read.
2. **Customer:** name *Rounak*, address *Room D-219, IIT (BHU) campus*, order *Medicines, 2 items*, **Speaks** Bengali, **Detect automatically** off. Put the real room number in the address: the doorstep note takes its room number only from the address or the call.
3. **Saved pin:** drag it (or click the map) to the back gate of Aryabhatta Hostel, near the swimming pool. This is the wrong place on purpose.
4. **Places:** press **Load real places around the pin** to fetch OpenStreetMap places within 1.5 km. Hover over the dots to check SN Bose Hostel is there. If it isn't, press **Add a missing place**, click where it is, and name it *SN Bose Hostel*, kind *hostel*.
5. **Give Prisma nearby place names as hints:** on.
6. **Rider:** pick Rahul. **Speaks** is set to Hindi automatically (picking a rider resets it to that rider's language). **Detect automatically** off.
7. **Start a call session**, and open the rider's and customer's links.
8. Play the scenario above: **Start Pata**, **Answer**, then each person taps **Talk** and speaks. Speak the lines rather than using the practice buttons, which skip Prisma.
9. On the rider's phone, tap **Use GPS** and ride to the building, or press **Ride 100 m** until he arrives, then **Mark delivered**. On the customer's phone, tap yes to move the saved location.
10. **Next day:** pick Karthik (Tamil) as the rider, press **Start a new call session**, open the new rider link, and tap **Start Pata**. The doorstep note plays in Tamil.

The rider list is in `data/orders_demo.json`: Rahul (Hindi), Sourav (Bengali) and Karthik (Tamil). Add riders there and restart Pata.

---

## Recording the demo video

What we did, on Ubuntu:

- **Screen recording:** OBS (`sudo apt install obs-studio`). Add **Screen Capture (PipeWire)**. Set Settings → Video to your screen's real resolution (not 1920×1080 if your screen differs), then press **Ctrl+F** to fit the capture.
- **Timbre's voice:** Settings → Audio → **Desktop Audio** = Default records what the laptop plays, digitally. For editing, record on separate tracks: Settings → Output → Advanced, tracks 1, 2 and 3; Edit → Advanced Audio Properties: Desktop Audio on tracks 1 and 2, Mic on tracks 1 and 3. Record as `.mkv`, then File → **Remux Recordings** to MP4.
- **No browser bars:** open each page as its own window with `google-chrome --app="https://…/rider?s=…"`, or crop the top in OBS (hold **Alt** and drag).
- **Headphones:** if both people talk on one laptop, both wear headphones, so the microphone doesn't hear Timbre and treat it as speech.
- **Before recording:** all three models say **live**, doorstep notes are cleared, Do Not Disturb is on.
- **Clean Timbre audio:** every line Timbre spoke is saved in `data/audio_cache` as WAV. Keep it until the video is edited.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `couldn't bind HTTP server socket ... port: 8000` | Something already uses port 8000. Run `ss -ltnp \| grep ':8000'`. If it's `llama-server`, Evon is already running: check it with `curl http://127.0.0.1:8000/v1/models`. If it's `ssh`, you opened the port forward on the Evon machine itself; close it. |
| `Evon did not return valid JSON` | Pata now repairs common slips itself and logs `pata.evon` warnings. If they're frequent, check `EVON_JSON_MODE=1` and that llama-server runs with `--jinja`. |
| The customer named a place but nothing happened | The control room explains why. If the place isn't on the map, add it with **Add a missing place**. |
| The next rider hears no doorstep note | The note is read only in a call session started after the delivery. Moving the saved pin or editing the address deletes the note; the control room asks first. |
| The map is blank or says "API key required" | Pata uses OpenStreetMap's own tiles, which need no key. Hard-refresh the page (Ctrl+Shift+R). |
| OBS doesn't capture the whole screen | Match Settings → Video to your screen's resolution, then Ctrl+F on the source. |

---

## Setting up your own demo

Everything is set in the control room, and remembered in `data/demo_setup.json`:

- **Customer:** name, address and order.
- **The customer's saved pin:** press **Use my location**, drag it, or click the map. Moving the pin, or editing the address, clears that address's doorstep note; the control room asks before doing either while a note exists.
- **Places:** the sample places only exist around the original demo pin in Chennai. Move the pin to any real neighbourhood and press **Load real places around the pin** to fetch temples, pharmacies, bus stops, hostels, shops and more within 1.5 km from OpenStreetMap.
- **Missing places:** OpenStreetMap misses many campus buildings. Press **Add a missing place**, click where it is, and give it the name people use. Places you add show as amber rings, are used for matching and as Prisma hints, and are kept in `data/places_custom.json`.
- **The rider's position:** on the rider's phone, **Use GPS** follows the phone; **Ride 100 m** and the draggable dot simulate riding. The phone must be within 20 km of the customer's pin.

## Languages: set or detected

- **Detect automatically off (the default, and what we used):** Prisma is told to expect the set language plus English, so code-mixed speech like Hinglish or Benglish works. The language stays the same for the whole call.
- **Detect automatically on:** Prisma detects the language of every turn, and Pata switches only under the rules in `app/language_tracking.py`.

Place-name hints go to Prisma only in English and in the speaker's own script; hints in another script can pull a transcript into that script.

## The interface

- **Light and dark:** every screen follows the device; the switch in the control room, or the button on each phone, overrides it.
- **Colour has jobs:** amber is Pata and the main action, red only means a wrong pin, green only means the building was found. In the call log, Prisma is blue, Evon amber, Timbre teal.
- **The dotted line** is the gap Pata closes: from the wrong pin to the real door on the map, and down the call log.
- **Works offline,** apart from map tiles: Instrument Sans, Noto Sans for eight Indian scripts, and Lucide icons are bundled in `static/vendor`.

## Saving credits

Each turn costs one Prisma call and one Timbre call; questions, directions and briefings add one Timbre call each. Timbre's audio is cached in `data/audio_cache`. Rehearse in mock mode, and switch one service at a time with `MOCK_PRISMA`, `MOCK_EVON` and `MOCK_TIMBRE`.

## Limits worth stating

- **Turns, not a live line.** People press to talk. In production, the platform's masked call would stream through Prisma's real-time WebSocket.
- **Direction, not turn-by-turn.** Pata says "270 m, to the south". Production would add a routing engine such as OSRM or Mappls.
- **Ten languages for speech:** Hindi, Bengali, Marathi, Gujarati, Punjabi, Tamil, Telugu, Kannada, Malayalam and English. Riders who speak Odia, Assamese, Nepali or Bhojpuri fall back to Hindi.
- **Map coverage.** Matching is only as good as the map; doorstep notes and added places fill the gaps.
- **Privacy.** Recordings go to Prisma and are not stored. Conversations live in memory until restart. Doorstep notes and the audio cache are saved in `data/`; clear them after demos.
- **No login.** Don't expose the server publicly for longer than a demo.

## Project layout

```
app/
  main.py            web server: pages, API, WebSocket
  pipeline.py        the call flow: who speaks, what Evon does, what Timbre says
  prompts.py         Evon's five prompts
  evon_tasks.py      each Evon job with its reasoning setting and token budget
  geo.py             map logic: nearby places, place-name spotting, candidate spots, directions
  note_guard.py      keeps room numbers, floors and cautions in doorstep notes true
  models.py          validated shapes of Evon's replies
  languages.py       the ten languages, and the script check for Evon's output
  phrases.py         the fixed AI-disclosure line in ten languages
  session.py, notes.py, config.py, language_tracking.py
  services/          Prisma, Timbre and Evon clients (with JSON repair), plus mock versions
static/              control room, rider phone, customer phone (plain HTML, CSS, JS)
  css/base.css       design tokens, light and dark themes, shared components
  js/map.js          OpenStreetMap basemap, markers, the live call on a map
  js/theme.js        the light or dark choice, applied before the page draws
  vendor/            Leaflet, fonts and icons, bundled so nothing loads from a CDN
data/                sample places, order, riders (Rahul, Sourav, Karthik) and practice lines
scripts/             serve_evon.sh (80 GB GPU), serve_evon_llamacpp.sh (24 GB GPU),
                     smoke_test_gnani.py, fetch_osm_places.py
tests/               81 tests, including a full live-mode run against fake servers
```

## Tests

```bash
python -m pytest -q
```

No network calls and no credits: the live-mode tests run whole calls against fake Gnani and Evon servers, including broken JSON, missed landmarks and invented room numbers.

Map data and tiles © OpenStreetMap contributors. Bundled: Leaflet (BSD-2-Clause), Instrument Sans and Noto Sans (SIL Open Font License 1.1), Lucide icons (ISC).

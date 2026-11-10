# Pata: the doorstep call copilot

When a delivery rider can't find the building, he calls the customer. Often they don't share a language, the saved pin is wrong, and whatever they work out is forgotten before the next delivery.

Pata sits inside that call. Each person speaks their own language. Pata translates both ways, turns the customer's landmarks into pins on the rider's map, notices when her saved pin is wrong, asks her a clarifying question itself when two places fit, and writes a doorstep note so the next rider never has to call.

Built for Gnani AI's Great Indian AI Internship Challenge, on all three Gnani models.

**One-page solution pitch:** [SOLUTION_PITCH.md](SOLUTION_PITCH.md)

## How the three models are used

| Model | What it does in Pata | Features used |
|---|---|---|
| **Prisma v3.0** (speech to text) | Transcribes every press-to-talk turn from the rider and the customer | `indic-auto` on the customer's first turn so nobody picks a language, then her detected language; `keyterms` filled with up to 200 names of shops, temples and bus stops around the pin; a `topic` sentence; `format=transcribe` so shop names stay in English letters and numbers become digits |
| **Evon** (gnani-evon-v3.3-30B-A3B) | Five jobs: rewrites each turn for the listener and extracts landmarks; decides which map location she is describing or writes the question that tells two apart; phrases directions; merges each call into the doorstep note; briefs the next rider | Reasoning off for quick turn-by-turn work, on for matching and notes (`enable_thinking`); every reply is validated JSON; every spoken reply is checked for the right script and retried once if wrong; Evon never produces coordinates or distances, the map code does |
| **Timbre v3.0** (text to speech) | Speaks to each person in their own language: the AI disclosure, translated turns, questions to the customer, directions and briefings to the rider | One voice per listener (every v3.0 voice speaks all ten languages); the `<slow>` tag for directions heard in traffic; an on-disk cache so repeated lines cost credits once |

The code that does geometry, distances, left and right, and nearby-place search is plain Python in `app/geo.py`. The language model decides what people meant; it does no maths. As a safety net, the same code also checks the customer's own words for the names of places near the pin, so a place she names ("come in front of SN Bose") is searched even if Evon leaves it out. "SN Bose", "S. N. Bose" and small misspellings all match. Doorstep notes are checked the same way (`app/note_guard.py`): a room or flat number must come from the address or the call, otherwise it is replaced with the address's number or removed. A floor or caution nobody mentioned is dropped, and the control room logs every correction.

## What happens in the demo

1. Rahul, a Hindi-speaking rider, reaches Meenakshi's saved pin. There is no building there.
2. He taps **Talk** and speaks Hindi. Meenakshi hears it in Tamil.
3. She answers in Tamil: opposite the Murugan temple, next to Apollo Pharmacy, green building, back gate, third floor. Rahul hears it in Hindi, and the places appear on his map.
4. The map has two spots with a Murugan temple next to an Apollo Pharmacy. Evon asks her, in Tamil, whether her building is near the bus stop or the petrol bunk.
5. She says the bus stop. The map shows her building 450 m north of her pin with a red dashed line, and Rahul hears directions in Hindi, slowly.
6. He rides there (or presses **Ride 100 m** on the map). On arrival he hears the entrance and floor.
7. He marks it delivered. Evon writes the doorstep note, and Pata asks her in Tamil whether to move her saved location.
8. Next day, Sourav, who speaks Bengali, starts a delivery to the same address. Before calling anyone he hears the doorstep note in Bengali and the map already shows the right building.

## Quick start (mock mode, no keys needed)

Mock mode stands in for all three models, so you can work on the screens before your Gnani key and Evon server are ready. Its generated sentences start with "(mock)".

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --port 8080
```

Open http://localhost:8080, press **Start a call session**, then open **Rider's phone** and **Customer's phone**. Press **Start Pata** on the rider's phone and **Answer** on the customer's phone, then tap the keyboard button beside **Talk** for a text box and the practice lines.

## Going live

1. **Gnani key.** Put it in `.env` as `GNANI_API_KEY`.
2. **Evon.** Evon is not hosted by Gnani's speech API, so serve it on a GPU machine:
   - With an 80 GB GPU (A100, H100, H200): `pip install "vllm>=0.12"`, then `bash scripts/serve_evon.sh`.
   - With a 24 GB GPU (RTX 4090, RTX PRO 4000 Blackwell): use llama.cpp and the community 4-bit GGUF of gnani-evon-v3.3. The setup steps are at the top of `scripts/serve_evon_llamacpp.sh`. If Pata takes too long to ask its question, set `EVON_REASONING_TOKENS=2500`, or `EVON_REASONING=0` to switch reasoning off.
   - Set `EVON_BASE_URL=http://<gpu-host>:8000/v1` in `.env`. If you reach the GPU machine over SSH, forward the port instead (`ssh -N -L 8000:127.0.0.1:8000 you@gpu-host`) and use `EVON_BASE_URL=http://localhost:8000/v1`.
3. **Check everything** (spends a few credits):
   ```bash
   python scripts/smoke_test_gnani.py
   ```
   It makes Timbre say a Tamil sentence, has Prisma transcribe it back, and asks Evon to translate it to Hindi.
4. Restart the server. The model status (Prisma, Evon, Timbre) at the top of each screen should all say **live**.

`EVON_JSON_MODE=1` (the default) asks the server to guarantee valid JSON for Evon's quick replies. Set it to 0 only if your server rejects it.

Some servers accept that setting but ignore it, and a 4-bit model then sometimes writes broken JSON, such as a missing comma. Pata repairs the common mistakes itself. If a reply is beyond repair, it keeps the message to relay, or falls back to a plain translation. Each repair prints a `pata.evon` warning in the server's terminal: "Evon's reply was not valid JSON … repaired it", followed by what Evon actually sent. If you see it often, update llama.cpp or vLLM to a version that supports `response_format`.

## Setting up your demo

Everything is set in the control room, and remembered in `data/demo_setup.json`:

- **Customer:** name, address and order.
- **The customer's saved pin:** press **Use my location** on the map, drag it on the map, or click the map, to set where the customer's app thinks they are. Laptops often guess their location from the network, so check the accuracy it reports and drag the pin to the exact spot if needed. For the wrong-pin moment, put it a few hundred metres from their real building. Moving the pin, or editing the address, clears that address's doorstep note; the control room asks before doing either while a note exists.
- **Places:** the sample places only exist around the original demo pin in Chennai. To use any real neighbourhood, move the pin there and press **Load real places around the pin**. Pata fetches temples, pharmacies, bus stops, shops and more within 1.5 km from OpenStreetMap. Hover over the dots to see their names, then have the customer describe real landmarks next to their real building.
- **The rider's position:** on the rider's phone, **Use GPS** follows the phone as you walk or ride; the buttons and the draggable dot still work for simulating. The phone must be within 20 km of the customer's pin.
- **Missing places:** OpenStreetMap misses many campus buildings. Press **Add a missing place**, click where it is, and give it the name people use, such as "Aryabhatta Hostel". Places you add show as amber rings, are used for matching and as Prisma hints, and are kept in `data/places_custom.json`. Names are matched with spelling tolerance, so "Vishveshvaraya" finds "Visvesvaraya Hostel".
- **Give Prisma nearby place names as hints:** on by default. Turn it off to compare Prisma's transcripts with and without hints.

## Languages: set or detected

Each person has a language and a **Detect automatically** switch, for the customer and for the rider.

- **Detect automatically off (the default, and the reliable choice for recording):** Prisma is told to expect that language, plus English so code-mixed speech like Hinglish or Tanglish still works. The language stays the same for the whole call.
- **Detect automatically on:** Prisma detects the language of every turn. Pata switches only when Evon agrees, the transcript is written in that language's script, the reply is at least three words, and, once a language is confirmed, two turns in a row are in the new language. The rules live in `app/language_tracking.py`.

Place-name hints go to Prisma only in English and in the speaker's own script. Hints in another script can pull a transcript into that script, for example Bengali speech coming out in Tamil letters. The topic sentence sent to Prisma names no city or region, for the same reason.

The riders and the demo order's defaults are in `data/orders_demo.json`. Practice lines are in `data/demo_script.json`; they are typed, so for those Pata relies on Evon's reading of the language. Mock mode understands only the Hindi and Tamil practice lines, and shows other text untranslated with "(mock)" in front until Evon is live.

## The interface

The three screens share one design system, in `static/css/base.css`:

- **Light and dark.** Every screen follows the device's setting. The switch at the top of the control room, or the sun and moon button on each phone, overrides it, and the choice is remembered in that browser. The map's basemap changes with it.
- **Colour has jobs.** Amber is Pata and the main action on each screen. Red only means a wrong pin. Green only means the building was found. Each model has its own colour in the call log: Prisma blue, Evon amber, Timbre teal.
- **The dotted line** is the gap Pata closes: from the wrong pin to the real door on the map, and down the call log from the first turn to the doorstep note.
- **Works offline.** Instrument Sans, Noto Sans for the eight Indian scripts, and Lucide icons are bundled in `static/vendor`. A script's font only downloads when that script appears. Only the map tiles need the internet. They come from OpenStreetMap, which needs no API key, and are shown in near-full colour by day and darkened in the browser at night.

The control room shows the live call on its map too, so a judge watching the laptop sees the candidate spots, the found building and the rider move.

## Using real phones

Browsers only allow the microphone on `https` or `localhost`. To use two phones, expose the server over https:

```bash
cloudflared tunnel --url http://localhost:8080     # or: ngrok http 8080
```

Open the control room through the tunnel URL. Use one device per person; on a single laptop, use two windows and headphones so one page doesn't record the other.

## Your own neighbourhood

The bundled places are hand-made sample data. To use a real area:

```bash
python scripts/fetch_osm_places.py --lat 13.0418 --lon 80.2341 --radius 1500 \
    --lang ta-IN --area "T. Nagar, Chennai" --out data/places_mine.json
```

Then set `PLACES_FILE=data/places_mine.json` in `.env` and move the order's `pin` in `data/orders_demo.json`. OpenStreetMap coverage varies, so add a few places by hand. If you want the clarifying question in your demo, make sure two spots share the landmarks the customer will name.

## Recording the demo video

- All three models say **live** at the top of each screen.
- Press **Clear doorstep notes** in the control room first.
- Speak the lines; don't press the practice buttons, which skip Prisma.
- Show the control room too: its tags say which model did what at each step.
- Finish with the next-day replay. Press **Start a new call session** after the delivery and pick the next rider (Sourav for Bengali, or Karthik for Tamil). The doorstep note is read automatically when he taps **Start Pata**, and **Hear the doorstep note** replays it. A session started before the delivery has no note to read.
- Have native speakers check the lines in `app/phrases.py`, `app/pipeline.py`, `static/js/customer.js` and `data/demo_script.json`.

## Saving credits

Each turn costs one Prisma call and one Timbre call; questions, directions and briefings add one Timbre call each. Timbre's audio is cached in `data/audio_cache`, so the disclosure line and repeated phrases are paid for once. Rehearse in mock mode, and switch one service at a time with `MOCK_PRISMA`, `MOCK_EVON` and `MOCK_TIMBRE`.

## Limits worth stating in your write-up

- **Turns, not a live line.** People press to talk, like a walkie-talkie. In production, the platform's masked call would be streamed through Prisma's real-time WebSocket.
- **Direction, not turn-by-turn.** Pata says "450 m ahead, to the north". Production would add a routing engine such as OSRM or Mappls.
- **Ten languages for speech.** Prisma and Timbre cover Hindi, Bengali, Marathi, Gujarati, Punjabi, Tamil, Telugu, Kannada, Malayalam and English. Riders who speak Odia, Assamese, Nepali or Bhojpuri fall back to Hindi.
- **Map coverage.** Matching is only as good as the map data; doorstep notes fill the gaps over time.
- **Privacy.** Recordings are sent to Prisma and not stored. Conversations live in memory until the server restarts. Doorstep notes and Timbre's audio cache are saved in `data/`; clear them after demos.
- **No login.** This is a demo server; don't expose it publicly for longer than a demo.

## Project layout

```
app/
  main.py            web server: pages, API, WebSocket
  pipeline.py        the call flow: who speaks, what Evon does, what Timbre says
  prompts.py         Evon's five prompts
  evon_tasks.py      each Evon job with its reasoning setting and token budget
  geo.py             map logic: nearby places, candidate locations, directions
  models.py          validated shapes of Evon's replies
  languages.py       the ten languages, and the script check for Evon's output
  phrases.py         the fixed AI-disclosure line in ten languages
  session.py, notes.py, config.py
  services/          Prisma, Timbre and Evon clients, plus their mock versions
static/              control room, rider phone, customer phone (plain HTML, CSS, JS)
  css/base.css       design tokens, light and dark themes, shared components
  js/map.js          basemap, markers and the live call on a map, shared by two screens
  js/theme.js        the light/dark choice, applied before the page draws
  vendor/            Leaflet, fonts and icons, bundled so nothing loads from a CDN
data/                sample places, order, riders and demo lines
scripts/             serve_evon.sh (80 GB GPU), serve_evon_llamacpp.sh (24 GB GPU),
                     smoke_test_gnani.py, fetch_osm_places.py
tests/               81 tests, including a full live-mode run against fake servers
```

## Tests

```bash
python -m pytest -q
```

No network calls and no credits: the live-mode test runs the whole demo against fake Gnani and Evon servers and checks every request Pata makes.

Map data and tiles © OpenStreetMap contributors. Bundled: Leaflet (BSD-2-Clause), Instrument Sans and Noto Sans (SIL Open Font License 1.1, with licenses in `static/vendor/fonts`), Lucide icons (ISC, `static/vendor/lucide`).

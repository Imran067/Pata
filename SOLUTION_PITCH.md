# Pata: the doorstep call copilot

**Solution pitch for Gnani AI's Great Indian AI Internship Challenge**

## The problem

A delivery rider reaches the saved pin and there is no building there. He calls the customer. He speaks Hindi, the customer speaks Bengali, and the pin is wrong. They lose minutes guessing at each other's words, and whatever they finally work out is forgotten, so tomorrow's rider makes the same call.

This happens every day in Indian cities, on campuses and in colonies where map pins drift and buildings have no clear address.

## Our demo: a real wrong pin at IIT (BHU), Varanasi

We filmed Pata end to end with live Gnani models and real OpenStreetMap data:

1. **Rahul**, a rider who speaks Hindi, reaches the saved pin: the back gate of Aryabhatta Hostel, by the swimming pool. No building. He starts Pata.
2. **Rounak**, the customer, speaks Bengali. His phone rings in Bengali, and both people hear that an AI is translating.
3. Rahul says, in Hinglish, that he has reached the swimming pool. Rounak hears it in Bengali.
4. Rounak answers in Benglish: you've taken the wrong road, come to the SN Bose Hostel gate. Rahul hears it in Hindi.
5. Pata finds SN Bose Hostel among the real places around the pin. Two spots fit, and Evon picks the right one. The map shows the saved pin was **160 m off**, and Rahul hears directions in Hindi, slowly.
6. After delivery, Evon writes a doorstep note, and Rounak moves his saved pin to the right building with one tap.
7. **Next day, Karthik**, who speaks Tamil, is sent to the same address. Before calling anyone, he hears the doorstep note in Tamil. No call needed.

Three Indian languages across two deliveries, Hinglish and Benglish understood, and a wrong pin fixed for every rider after the first.

## The solution

Pata sits inside the doorstep call. Each person speaks their own language, and Pata:

- **Translates both ways,** keeping English place names as people say them.
- **Turns the customer's landmarks into pins** on the rider's map, matched against real places around the saved pin.
- **Notices the saved pin is wrong** and shows the real building, with spoken directions.
- **Asks its own clarifying question,** in the customer's language, when two places fit.
- **Writes a doorstep note** after delivery, so the next rider hears it in his own language and never has to call.

## How it uses all three Gnani models

| Model | Job in Pata |
|---|---|
| **Prisma v3.0** (speech to text) | Transcribes every turn, code-mixed speech included. The names of real places around the pin are sent as key terms, so hostel, temple and shop names come out right. |
| **Evon v3.3** (language model) | Five jobs: rewrite each turn for the listener and extract landmarks; decide which map spot fits or write the clarifying question; phrase directions; write the doorstep note; brief the next rider. |
| **Timbre v3.0** (text to speech) | Speaks to each person in their own language, with slowed speech for directions heard in traffic. |

## How it is built

- **The model decides meaning; code does the maths.** Evon never produces a coordinate or a distance. Plain Python finds nearby places, groups them into candidate spots, and computes distance, direction and left or right.
- **Every Evon reply is checked.** Replies must match a JSON schema. If a 4-bit model on a server that ignores JSON mode drops a comma, Pata repairs it locally. If a reply is beyond repair, the call carries on with a plain translation instead of stopping.
- **A safety net for place names.** Pata also checks the customer's own words against the map, so "SN Bose", "S. N. Bose" or a misspelling still finds S. N. Bose Hostel even if Evon misses it.
- **Doorstep notes stay true.** A room or flat number must come from the address or the call, or it is corrected; a floor or caution nobody mentioned is dropped.
- **Built for real streets.** Ten languages for speech, the right script checked on every spoken line, and real neighbourhoods loaded from OpenStreetMap with one click. Campus buildings the map misses can be added by hand.

## What is built

- Three screens: the rider's phone (map, live distance and the talk button), the customer's phone (a call that rings, in very large text), and a control room that shows every step with the model that did it.
- Light and dark themes, bundled fonts for eight Indian scripts, and a mock mode that runs with no keys.
- **81 automated tests**, including full calls against fake Gnani and Evon servers, broken JSON, missed landmarks and invented room numbers.

## How we ran it

- **Pata** on an Ubuntu laptop (FastAPI, plain HTML and JavaScript), started with `uvicorn app.main:app --port 8080`.
- **Evon** on a 24 GB GPU with llama.cpp and the community 4-bit GGUF (`llama-server ... --jinja -ngl 99 -c 16384 --port 8000`), reached from the laptop through an SSH port forward.
- **Prisma and Timbre** through Gnani's API, with one key in `.env`.
- **Phones** connected through a free cloudflared https tunnel, since phone browsers only allow the microphone and GPS on https.

Step-by-step setup, every setting we used, and how to reproduce the demo exactly are in [README.md](README.md).

## Why it matters, and what comes next

Every call Pata handles makes the address better for every later delivery: the fix is saved once and reused in any rider's language. That turns the most frustrating minute of a delivery into a one-time cost.

In production, press-to-talk would become a live stream through Prisma's real-time API on the platform's masked call, with a routing engine for turn-by-turn directions, and doorstep notes shared across every rider on the platform.

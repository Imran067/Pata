# Pata: the doorstep call copilot

**Solution pitch for Gnani AI's Great Indian AI Internship Challenge**

## The problem

A delivery rider reaches the saved pin and there is no building there. He calls the customer. He speaks Hindi, she speaks Tamil, and the pin is 450 m off. They lose minutes guessing at each other's words, and whatever they finally work out is forgotten, so tomorrow's rider makes the same call.

## The solution

Pata sits inside that call. Each person speaks their own language and Pata does the rest:

- **Translates both ways**, so the rider hears Hindi and the customer hears Tamil.
- **Turns her landmarks into pins** on the rider's map ("opposite the Murugan temple, next to Apollo Pharmacy").
- **Notices the saved pin is wrong** and shows the real building, with spoken directions.
- **Asks its own clarifying question** in her language when two places fit her description.
- **Writes a doorstep note** after delivery, so the next rider hears it in his language and never has to call.

## How it uses all three Gnani models

| Model | Job in Pata |
|---|---|
| **Prisma v3.0** (speech to text) | Transcribes every turn. Auto-detects the customer's language and gets up to 200 nearby place names as key terms, so shop and temple names come out right. |
| **Evon v3.3** (language model) | Five jobs: translate and extract landmarks, match them to the map or write the clarifying question, phrase directions, write the doorstep note, brief the next rider. |
| **Timbre v3.0** (text to speech) | Speaks to each person in their own language, with slowed speech for directions heard in traffic. |

Evon decides what people meant; plain Python does all distances and directions, so the model never invents a coordinate. Every Evon reply is validated, and doorstep notes are checked so a flat number or floor nobody mentioned is never saved.

## What is built

A working demo with three screens (rider's phone, customer's phone, control room), ten languages, real neighbourhoods loaded from OpenStreetMap, and a mock mode that runs with no keys. 81 automated tests pass, including a full run of the call against fake Gnani and Evon servers.

## Why it matters, and what comes next

Every call Pata handles makes the address better for every later delivery: the fix is saved once and reused in any rider's language. In production, press-to-talk would become a live stream through Prisma's real-time API on the platform's masked call, with a routing engine for turn-by-turn directions.

**Run it:** see [README.md](README.md). Mock mode starts in under a minute.

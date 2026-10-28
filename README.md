# Saath

A daily voice check-in call for elderly parents who live alone, in Telugu and Hindi. Saath calls every evening on a normal phone, scores how the parent feels from both their **words** and their **voice**, remembers mood across days, adapts the next call, and alerts the family when mood keeps dropping.

Built for the Bolna Buildathon (Oct 2026).

## How it works

```
Parent's phone ⇄ Bolna agent (Sarvam saaras:v3 STT, LLM, Sarvam bulbul:v3 TTS)
                     │ webhook: transcript + recording
                     ▼
Saath backend ── webhook receiver → emotion pipeline → mood memory + alerts → SQLite
     ▲              (words: LLM · voice: emotion2vec+ · fusion)                │
     └── call placer ← context builder (tone, open threads, meds to check) ←──┘
                                                                              │
                                                       family app (API) ◄─────┘
```

- **Words:** one LLM call (Sarvam-105B by default) over the native transcript returns multi-label emotions, valence, arousal, evidence quotes, meals, medicines, worries and a summary. This is LLM scoring against a fixed schema, not a trained classifier.
- **Voice:** emotion2vec+ large on the parent's speech. It isn't trained specifically on Telugu or Hindi, so it is a tone signal beside the words, never alone.
- **Fusion:** `mood = 0.6 × text valence + 0.4 × voice valence`; a **mismatch** flag when the parent says they're fine but the voice valence is ≤ −0.3.
- **Alerts:** urgent (emergency words), she called Saath, sustained drop (last 3 calls ≥ 0.3 below the 14-day median), recurring loneliness/worry (3 of last 5), voice signals away from her usual, missed check-in. All thresholds are starting values, not measured results.
- **Messages from the child:** write a line in the app; Saath passes it on in tonight's call (in Telugu or Hindi) and brings back her reply. It only counts as delivered if the scoring confirms Saath actually said it.
- **Emergencies:** a mid-call tool raises the urgent alert the moment she mentions a fall or chest pain, and Bolna's Transfer Call tool can connect her to you live (`prompts/bolna_tools.md`).
- **Alerts that reach you:** Saath phones you through a second, English Bolna agent (`prompts/agent_alert_en.md`), and/or POSTs every alert, daily summary and Sunday digest to `ALERT_WEBHOOK_URL` for WhatsApp, email or Slack. Each alert shows in the app how it reached you.
- **Weekly digest:** the last 7 evenings against the 7 before: check-ins, medicines and reminder calls answered, meals, feelings, topics, calls she made, voice changes, best and hardest evening, your messages.
- **SOS line, she calls Saath:** a Bolna number linked to her agent for inbound calls. Caller identification (`/webhooks/bolna/caller`) answers within Bolna's 3 seconds with her context, so Saath greets her by name, knows her medicines and recent calls, and carries your latest message. You get an "Amma called Saath" alert (urgent if she mentions an emergency, with the same mid-call tool and transfer). If the line drops before she speaks, Saath rings her back, and tells you if she doesn't answer.
- **Medicine reminder calls:** give a medicine a reminder time and Saath places a short call then, asks if she took it, and records the answer. Reminder calls don't count toward mood, a missed reminder isn't an alert, and the week shows how many she answered.
- **Voice wellness signals:** from her own audio, Saath measures speaking pace (letters per second of speech, so Telugu and Hindi compare fairly), pause length, loudness and pitch movement (autocorrelation pitch, in semitones), and compares them only with her own usual. Two or more signals away from her usual over the last 3 calls raise a "voice" alert, worded as a reason to call, never a diagnosis. Needs parent-only audio (her recording channel, or the browser test call); on a one-channel recording only the pace from Bolna's speaking time is used. Response delay isn't measured: Bolna doesn't give per-turn timestamps.

## Run the backend

```bash
cd backend
pip install -r requirements.txt          # add requirements-voice.txt for emotion2vec+ (torch)
cp ../.env.example ../.env               # fill in keys when you have them
python -m app.seed --reset               # labelled demo history (13 evenings)
uvicorn app.main:app --reload --port 8000
```

**LLM for testing:** any OpenAI-compatible endpoint works. `.env.example` has ready blocks for OpenAI's open-weight gpt-oss on Groq (`openai/gpt-oss-120b`), the same model locally with Ollama (`gpt-oss:20b`, no key), OpenAI's API, and Sarvam-105B for the final build. Switching is config only.

With no keys it runs in mock mode: calls fail with a clear error, text scoring uses a keyword stand-in (`source: "mock"`), and voice scoring is skipped.

## Run the family app

```bash
cd web
npm install
npm run dev            # http://localhost:5173, proxies /api to the backend on :8000
```

If the backend isn't reachable, the app falls back to a bundled snapshot of the seeded demo (`src/demo/snapshot.json`) and says so at the top. Regenerate it after changing the seed with `python -m app.snapshot` (from `backend/`). `npm run build:single` produces one self-contained HTML file for sharing the demo.

Screens: Today (the one-line answer, the last two weeks, what needs you, a message for her, meals and medicines, tonight's call plan), Week, Calls, Call detail (words vs voice, how she spoke against her usual, her own words, your message and her reply, the conversation in Telugu/Hindi and English), Alerts (with how each reached you), Profile (reminder times per medicine, her Saath number, your phone and which alerts Saath calls you about), Setup, and the browser Test call.

## Test call in the browser (no Bolna needed)

With an OpenAI key in `.env` (`LLM_BASE_URL=https://api.openai.com/v1` plus `LLM_API_KEY`, or a separate `OPENAI_API_KEY`), open the app and choose **Try it in your browser** on Today. You answer as the parent through your mic; OpenAI does what Bolna does on a real call:

| Job | Model (override in `.env`) |
| --- | --- |
| Hear the parent | `OPENAI_STT_MODEL=gpt-4o-mini-transcribe` |
| Decide what to say | `LLM_MODEL`, using the same prompt as `prompts/agent_te.md` / `agent_hi.md` |
| Speak | `OPENAI_TTS_MODEL=gpt-4o-mini-tts-2025-12-15`, `OPENAI_TTS_VOICE=coral` |

Pick the kind of call first: the evening check-in, a medicine reminder, or **She calls Saath** (the SOS line from her side). Ending the call scores it through the same pipeline as a phone call and adds it to the parent's history. It carries your pending message like a real call, and an emergency phrase raises the urgent alert mid-call, but a test call never phones anyone. Only the parent's turns are recorded, so the voice signal gets clean parent-only audio (merging the turns needs `ffmpeg` on your PATH; without it the call is scored on words only).

## Connect Bolna (day 1)

1. Create two agents in the Bolna dashboard (Telugu, Hindi). Paste the welcome message and system prompt from `backend/prompts/agent_te.md` / `agent_hi.md`. Set Sarvam `saaras:v3` as transcriber and `bulbul:v3` as voice.
2. Put the agent IDs and your API key in `.env` (`BOLNA_AGENT_ID_TE`, `BOLNA_AGENT_ID_HI`, `BOLNA_API_KEY`).
3. Expose the backend: `ngrok http 8000`, then set the agent webhook to `https://<id>.ngrok.app/webhooks/bolna`.
   No tunnel? The backend also polls Bolna every 30 s for open calls, so calls still get processed.
4. `POST /api/parents/1/call-now` (or the app's Call now button) and your phone rings.

Per-call context reaches the agent through `user_data` on `POST /call`, which fills `{{variables}}` in the prompt and welcome message.

**Check on the first real call:** whether Bolna's recording is two-channel, and which channel is the parent. Set `PARENT_CHANNEL` accordingly. A one-channel recording is scored as `mixed` and down-weighted.

**Optional, for the full demo:**
- SOS line: link a Bolna number to her agent for inbound calls, point caller identification at `/webhooks/bolna/caller`, set `SOS_NUMBER` (`bolna_tools.md` section 3).
- Emergency tool + live transfer: follow `backend/prompts/bolna_tools.md`, then set `TOOL_TOKEN` and `TRANSFER_ON_EMERGENCY=true`. Use a second phone as "your" number: transferring to the phone you're testing on can't work.
- Alert calls to you: create the English agent from `backend/prompts/agent_alert_en.md`, set `BOLNA_AGENT_ID_ALERT`, and add your phone in Profile.

## Voice model

```bash
pip install -r requirements-voice.txt      # torch + FunASR; large download
python -m app.check_voice                  # scores the model's sample clip and your latest test call
```

It downloads emotion2vec+ large from Hugging Face on first run (`VOICE_HUB=ms` for ModelScope). Until it's installed, calls are scored on words only and the "said fine, sounded low" flag can't fire.

## Evaluation and tests

```bash
python -m app.evaluate                     # 32 scripted Telugu/Hindi calls with known answers
python -m pytest -q tests                  # rules, flows, SOS line, reminders, voice signals, migration
```

`app.evaluate` writes `results/eval-<model>-<time>.json` and prints accuracy for emergencies (split by LLM vs keyword safety net, and false alarms on calm calls), "said fine", mood direction, medicines and meals, per language. Every number comes from the run. The cases are scripted, so they measure how the scoring reads clear examples, not how it does on real parents.

## Hosting

One server runs everything: after `npm run build` in `web/`, the backend serves the app at `/` beside the API. `Dockerfile` builds both (`--build-arg VOICE=1` adds the voice model) and keeps the database on a `/data` volume. On Railway or Render, attach a volume at `/data`, set the `.env` values as environment variables, and point Bolna's webhook and tool URLs at the public address. Existing databases upgrade themselves on start.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Which keys and models are configured |
| GET/POST | `/api/parents` | List / set up a parent (optionally places the intro call) |
| PATCH | `/api/parents/{id}` | Edit profile, consent, medicines |
| GET | `/api/parents/{id}/overview` | Today card, latest call, stats, unseen alerts, next-call plan |
| GET | `/api/parents/{id}/trend?days=14` | Mood points with mismatch and alert markers |
| GET | `/api/parents/{id}/calls` | Call history |
| GET | `/api/calls/{id}` | Call detail: transcript, English rendering, words vs voice |
| GET | `/api/calls/{id}/audio` | Recording |
| GET | `/api/parents/{id}/alerts`, POST `/api/alerts/{id}/seen` | Alerts |
| GET/POST | `/api/parents/{id}/notes`, DELETE `/api/notes/{id}` | Messages from the child |
| GET | `/api/parents/{id}/week` | Weekly digest |
| POST | `/api/parents/{id}/call-now` | Place a call now |
| POST | `/api/test-call/start`, `/{id}/turn`, `/{id}/end` | Browser test call |
| POST | `/webhooks/bolna` | Bolna execution updates |
| GET/POST | `/webhooks/bolna/tools/urgent` | Mid-call emergency tool |
| GET/POST | `/webhooks/bolna/caller` | Caller identification for the SOS line (inbound calls) |
| POST | `/api/dev/simulate-call` | Run the pipeline on a pasted transcript, no phone call |

## Honest notes for judges

- Seeded history is marked `is_seeded` and labelled in the UI. Alerts on seeded data come from the same rules engine as live calls.
- The voice model has not been validated on Telugu or Hindi speech; it is shown beside the words signal.
- Voice wellness signals are checked on synthetic audio in the tests, not on real elderly speakers. The seeded "slower, quieter" trend is sample data. Real calls are measured, and only ever compared with the same person's usual.
- Saath gives no medical advice. On emergency words the family is alerted immediately and the parent is told to call a neighbour or 108.
- The intro call tells the parent Saath is an AI assistant and that it shares a short daily note with her child, and daily calls start only if she agrees.
- If a scheduled call can't be placed (Bolna down, wallet empty), Saath retries once, then raises a missed check-in alert with the reason. After a restart it catches up on a call it missed in the last 2 hours and re-schedules a pending retry.

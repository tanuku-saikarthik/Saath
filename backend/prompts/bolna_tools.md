# Bolna tools for emergencies

Two tools on the Telugu and Hindi agents (Agent, Tools tab). Together they make an emergency
immediate: the family is alerted mid-call, and Saath connects her to her child live.

Both need the backend reachable from the internet (`ngrok http 8000`, or the hosted version), with
`PUBLIC_BASE_URL` set to that address.

## 1. `alert_family_urgent` (custom function)

Raises the urgent alert the moment she mentions a fall, chest pain and so on, instead of after the
call ends. The backend's reply tells the agent what to say next.

Add a custom function with this JSON (replace the URL and token):

```json
{
  "name": "alert_family_urgent",
  "description": "Call this immediately if she mentions a fall, chest pain, trouble breathing, fainting, bleeding, or feeling confused. Pass a short English reason.",
  "pre_call_message": "",
  "parameters": {
    "type": "object",
    "properties": {
      "reason": { "type": "string", "description": "Short English description of what she said, e.g. 'Fell in the bathroom, hurt her knee'" },
      "execution_id": { "type": "string", "description": "This call's ID" },
      "to_number": { "type": "string", "description": "The number Saath called" }
    },
    "required": ["reason"]
  },
  "key": "custom_task",
  "value": {
    "method": "POST",
    "param": {
      "reason": "%(reason)s",
      "execution_id": "%(execution_id)s",
      "to_number": "%(to_number)s"
    },
    "url": "https://YOUR-PUBLIC-URL/webhooks/bolna/tools/urgent",
    "api_token": "Bearer YOUR_TOOL_TOKEN",
    "headers": {}
  }
}
```

- Set the same token in `.env` as `TOOL_TOKEN=YOUR_TOOL_TOKEN`.
- `execution_id` and `to_number` are Bolna system variables, filled in automatically. The backend
  finds the call by `execution_id` first, then by the parent's number.
- Bolna's docs don't say whether a POST tool sends JSON or form data, so the endpoint accepts both,
  and GET query strings too.

## 2. Transfer Call (built-in tool)

Connects her to her child while she's still on the line.

- Tools tab, add **Transfer Call**.
- Description: `After calling alert_family_urgent, if its reply says to connect her, transfer the call.`
- Transfer destination: the child's number in international format, e.g. `+9198XXXXXXXX`.
- Pre-tool message (Telugu agent): `ఒక్క నిమిషం అమ్మా, మిమ్మల్ని ఇప్పుడే కలుపుతున్నాను.`
- Then set `TRANSFER_ON_EMERGENCY=true` in `.env`. The urgent tool's reply then tells the agent to
  transfer, and Saath skips phoning the child separately (they're being connected directly).

Bolna's docs describe a fixed destination per agent; they don't say whether it can come from a call
variable. So for now the destination is typed into the agent. For the demo, use a second phone as
the child's number: transferring to the same phone you're testing on can't work.

When a transfer happens, Bolna's execution payload includes `transfer_call_data`, and the call shows
"Connected to you" in the app.

## 3. The SOS line: she calls Saath (inbound)

1. In Bolna, buy or connect a phone number and link it to her language's agent (Telugu or Hindi) for **inbound** calls.
2. In the agent's inbound settings, turn on **caller identification** and set:
   - URL: `{PUBLIC_BASE_URL}/webhooks/bolna/caller`
   - Header: `Authorization: Bearer <TOOL_TOKEN>`

   Bolna calls it with `contact_number`, `agent_id` and `execution_id` and must get an answer within 3 seconds. Saath replies with the same variables as an outgoing call (`call_kind` = `inbound`, her name, medicines, recent threads, any message from you), so the agent greets her by name.
3. Put the number in `.env` as `SOS_NUMBER`. The app's Profile page shows it so you can save it in her phone as "Saath".

After the call, the normal execution webhook scores it. You get an "Amma called Saath" alert (or an urgent one if she mentioned an emergency). If the call ended before she said anything, Saath rings her straight back (`CALLBACK_ON_DROPPED=true`), and if she doesn't answer that, you get an alert to call her.

The emergency tool and transfer above work on inbound calls too: add them to the same agent.

## 4. Medicine reminder calls

No Bolna setup beyond the outgoing agent. In the app's Profile, give a medicine a **Remind at** time. Saath places a short call at that time (`call_kind` = `reminder`, `reminder_medicine`, `reminder_timing`), asks if she has taken it, and records the answer. Reminder calls don't count toward her mood trend, a missed reminder is not an alert (the evening call asks about medicines anyway), and the week view shows how many reminders she answered.

Taking my time. Here it is.

---

## Artha.
### AI Business Assistant for Indian Merchants

*The AI munshi that lives in WhatsApp — listens to your day, knows your business, speaks your language.*

---

### Why This Wins

Simple. Complete. Demos in 90 seconds. Solves a real Paytm problem — 38 million merchants have transaction data but zero intelligence on top of it. Judges will feel it immediately because every one of them knows what a munshi is.

---

### The One-Line Pitch

*"Every big business has a CA and an analyst. Every kirana store has a munshi. We built the AI munshi for India's 63 million small merchants — lives in WhatsApp, knows your numbers, speaks Hindi, never forgets."*

---

### The Product — Three Things Only

**1. Voice-First Business Capture**
Merchant sends a WhatsApp voice note — in Hindi, Marathi, mixed, messy, natural. Whisper transcribes it. LLM extracts structured business events. Everything gets logged without the merchant typing a single word.

*"Aaj Suresh ko 300 ka udhaar diya, 800 ka atta aaya, aur ek naya customer tha — Vikram naam tha."*
→ Munshi logs: udhaar ₹300 to Suresh, expense ₹800 (atta/stock), new customer Vikram noted.
→ Replies: *"Note kar liya. Aaj abhi tak net: ₹2,400. Suresh ka total udhaar ab ₹800 ho gaya."*

**2. Payment Verification**
Merchant photographs customer's phone screen. Google Vision extracts UTR. One DB lookup. Honest answer.

- UTR found, amount matches → ✅ Genuine, maal do
- UTR found, amount differs → ⚠️ Amount mismatch, ruko
- UTR not found, <10 min ago → ⏳ Wait karo, network lag ho sakta hai — main dobara check karunga
- UTR not found, >20 min ago → ❌ Record mein nahi aaya, dobara payment maango
- Not a payment screen → "Yeh payment screen nahi hai, customer ki success screen photo lo"

No fraud detection algorithm. No layers. Just DB truth + honest LLM reasoning.

**3. Proactive Intelligence — Morning Brief + EOD Summary**

Morning: Merchant sends "good morning" or any first message of the day → Munshi volunteers:
*"Kal ₹3,200 aaya 14 transactions mein. Aaj Wednesday — historically thoda slow hota hai. Priya 18 din se nahi aayi, weekly aati thi pehle. Suresh ka ₹800 udhaar baki hai — 3 hafte ho gaye."*

EOD: Merchant sends a voice debrief, anything they want to say about the day → Munshi extracts, logs, summarizes the full day's P&L.

Nobody asked for either of these. Munshi volunteered. That's the magic moment in the demo.

---

### Technical Stack

```
WhatsApp Cloud API     → already working
FastAPI + PostgreSQL   → already working  
Railway deployment     → already working
Google Vision OCR      → already working
OpenAI GPT-4o          → function calling, agentic tool orchestration
Whisper API            → voice note transcription (build tonight)
```

---

### The LLM's Toolbox

```
search_transaction(utr)              → payment verification
get_sales_summary(period)            → today / week / month
get_top_customers(limit)             → best customers by spend
get_churned_customers(days)          → regulars who stopped coming
search_customer_transactions(name)   → "Rajesh ne kab diya tha?"
log_udhaar(customer, amount, type)   → credit given or received
log_expense(amount, category)        → stock, rent, misc
get_morning_brief()                  → aggregated daily start summary
```

LLM decides which tools to call. No routing. No if-else. ReAct loop until it has enough to respond. If it doesn't know something, it says so — never fabricates a number.

---

### The Demo Script — 90 Seconds, Three Acts

**Act 1 — Morning (30 sec)**
Judge watches: merchant sends "good morning" → Munshi replies unprompted with yesterday's summary, today's prediction, Rajesh churn alert.
*Judges feel: this thing is alive, it notices things*

**Act 2 — Payment Verification (30 sec)**
Merchant photographs customer's phone showing ₹450 PhonePe payment → Munshi extracts UTR → finds it in DB → "✅ ₹450 confirm hai, Ramesh se aaya. Maal de sakte ho."
Then show the modified screenshot (same UTR, amount changed to ₹4,500) → "⚠️ Amount mismatch — record mein ₹450 hai, screenshot mein ₹4,500 dikh raha hai. Ruko."
*Judges feel: this actually works, this is real*

**Act 3 — EOD Voice (30 sec)**
Merchant sends voice note in Hindi describing their day → Munshi transcribes, extracts events, replies with clean P&L summary.
*Judges feel: nobody has built this before*

---

### Demo Data Setup

Take two real payment screenshots from your phone tonight. Extract the exact UTR, amount, timestamp from each. Put both in seed data exactly. Modify one screenshot's amount in any image editor — that's your fraud demo. Everything else is already seeded.

---

### What To Build

**1. Voice note handler** — WhatsApp sends .ogg files, same download flow as images. Pass to Whisper API, get transcript, pass to agent. Two hours max.

**2. log_udhaar and log_expense tools** — Add two DB tables (udhaar, expenses), two tool functions, two LLM tool schemas. 

**3. Simplify fraud pipeline** — Remove all layers. Keep only: OCR → parse UTR → DB lookup → LLM reasoning on result. 

**4. Morning brief trigger** — If first message of day, prepend morning context to agent system prompt. 



### The Synthio Spike

| Munshi | Jarvis (Synthio) |
|---|---|
| Voice note in → structured business events out | Voice conversation → structured clinical insights out |
| Grounded in transaction DB, never hallucinates numbers | Grounded in FDA labels, never hallucinates dosages |
| Agentic tool calling — LLM decides what to query | Same agentic pattern for clinical data retrieval |
| Proactive morning brief without being asked | Proactive pre-call brief for pharma reps |
| Handles messy Hindi/Marathi mixed speech | Handles domain-specific medical conversation |
| Built and shipped in 3 days under real constraints | Production software for real healthcare workflows |



OpenAI now has a single API that does STT and TTS in the same ecosystem you're already using for the LLM. No extra service, no extra key.

What you use:
STT — whisper-1 model via openai.audio.transcriptions.create(). Pass the .ogg file directly from WhatsApp. Returns transcript. Done.
TTS — openai.audio.speech.create(). Pass text, get back an audio file. Send that audio file back via WhatsApp as a voice message. Merchant receives a voice reply, not text.
That second part — bot replying in voice — is what nobody in the demo room will have. Merchant sends voice, merchant gets voice back. That feels like magic.
Love it. **Artha: The AI Munshi for Kirana Shops.**

Let me write this properly. Four focused Copilot prompts, in order, each building on the last.

---

## PROMPT 1 — Fresh Seed Data (Grocery Store, 2 Weeks)

```
Replace all existing seed data in app/db/seed.py completely.

We are building Artha — AI Munshi for a kirana grocery store.

Create realistic mock data for ONE merchant:

MERCHANT:
Name: Sharma General Store
Owner: Rajiv Sharma
Phone: 919876543210
UPI ID: rajiv.sharma@paytm
Location: Pune, Maharashtra
Paytm Merchant ID: PTM_SHARMA_2024

CUSTOMERS — create 15 realistic customers:
4 regulars (visit 4-5 times per week, feel like family)
  - Priya Mehta (daily customer, small amounts ₹50-200)
  - Suresh Yadav (comes every 2 days, medium amounts ₹150-400)
  - Kamla Bai (weekly, large grocery runs ₹400-900)
  - Raju Delivery (daily small purchases ₹30-100, delivery boy)

4 semi-regulars (2-3 times per week):
  - Anita Desai
  - Mohammed Rafiq  
  - Sunita Patil
  - Deepak Joshi

4 occasional (once a week or less):
  - Vikram Singh
  - Meena Kumari
  - Arun Tiwari
  - Pooja Shah

3 who STOPPED coming (were regular, last visit 12-18 days ago):
  - Ramesh Gupta (was weekly, ₹300-500 avg, stopped 15 days ago)
  - Kavita Nair (was twice weekly, stopped 12 days ago)
  - Santosh Kumar (was daily small, stopped 18 days ago)

TRANSACTIONS — 14 days of history (Day 1 = 14 days ago, Day 14 = yesterday):

Time patterns (realistic kirana store):
- Morning rush 7:30-10:00 AM (25% of daily transactions)
- Lunch lull 10:00-12:00 (10%)
- Afternoon 12:00-4:00 PM (20%)
- Evening rush 4:00-8:00 PM (40%)
- Night 8:00-10:00 PM (5%)

Day patterns:
- Monday: slow (₹2,000-2,800 total)
- Tuesday-Thursday: medium (₹2,800-3,800)
- Friday: picking up (₹3,500-4,500)
- Saturday: busiest (₹5,000-7,000)
- Sunday: second busiest (₹4,000-5,500)

Transaction amounts:
- Small: ₹20-150 (bread, milk, eggs, small items)
- Medium: ₹150-500 (weekly essentials)
- Large: ₹500-1,200 (monthly grocery run)

UPI apps mix: 60% Paytm, 25% PhonePe, 15% GPay

Transaction ID formats:
- Paytm: numeric 16 digits e.g. "4721839204751836"
- PhonePe: T + YYMMDD + HHMMSS + 8 random chars 
  e.g. "T240315143022ABCD1234"
- GPay: alphanumeric 22 chars e.g. "CICAgKDf3pGRHxEe2vDvDA"

IMPORTANT — Add 3 specific demo transactions for Saturday demo:
1. txn_ref: "T260321153045DEMO0001", amount: 450.0, 
   customer: Suresh Yadav, timestamp: today at 3:30 PM
   (this is the GENUINE payment for demo)
2. txn_ref: "T260321160022DEMO0002", amount: 280.0,
   customer: Priya Mehta, timestamp: today at 4:00 PM
3. txn_ref: "4721839204751999", amount: 1200.0,
   customer: Kamla Bai, timestamp: yesterday at 6:15 PM

Also create an UDHAAR table (credit ledger):
Fields: id, merchant_id, customer_name, customer_phone,
        amount, type (GIVEN/RECEIVED), note, date, created_at

Seed 5 udhaar entries:
- Suresh Yadav owes ₹350 (given 5 days ago)
- Ramesh Gupta owes ₹600 (given 16 days ago — he stopped coming)
- Kavita Nair owes ₹200 (given 13 days ago)
- Rajiv received ₹150 from Deepak Joshi (3 days ago, partial payment)
- Mohammed Rafiq owes ₹450 (given 8 days ago)

Also create an EXPENSES table:
Fields: id, merchant_id, amount, category, note, date, created_at
Categories: STOCK, RENT, ELECTRICITY, TRANSPORT, MISC

Seed 10 expense entries spread across 2 weeks — realistic:
- Stock purchases (atta, dal, oil) ranging ₹2,000-8,000
- Electricity ₹1,200 (one time)
- Transport ₹300-500 (2-3 times)
- Misc small expenses

Seed function must be fully idempotent — 
check if merchant exists before inserting, skip if already there.
Print a summary at the end:
"Artha seed complete: X transactions, Y customers, 
 Z udhaar entries, W expenses"
```

---

## PROMPT 2 — The Orchestrator (ReAct Agentic Core)

```
Build the entire agentic orchestration layer for Artha.
Replace app/agent.py completely.

ARCHITECTURE:
Input (from merchant via WhatsApp) can be:
- Text message
- Transcribed voice note text  
- OCR text from an image
- Combined (e.g. voice note + image)

The orchestrator runs a ReAct loop:
Observe → Think → Act (call tool) → Observe result → 
Think again → Act again → ... → Final response

Use OpenAI GPT-4o with function calling.
Max 5 tool call iterations before forcing a final answer.

SYSTEM PROMPT:
"""
Tum ho Artha — Rajiv Sharma ke Sharma General Store ke 
liye ek AI munshi. Tum WhatsApp pe rehte ho.

Tumhara kaam:
1. Merchant ki baat sunna — voice notes, text, images — 
   sab kuch
2. Business ke saare sawaalon ke honest jawab dena
3. Payment verify karna (sirf DB mein dhundh ke)
4. Business insights dena jo UPI app kabhi nahi deta
5. Credit (udhaar), expenses, aur notes track karna

IMPORTANT RULES — kabhi mat todna:
- Agar DB mein nahi hai toh AGAR nahi — "nahi mila" bol do
- Kabhi bhi number mat banao — sirf real data use karo
- Agar intent clear nahi hai toh EK sawal poochho, 
  multiple nahi
- Agar input business se related nahi hai — 
  politely redirect karo
- NOTED sirf tab bol jab koi information share kare 
  bina sawaal ke

LANGUAGE:
- Merchant jo language use kare, wahi use karo
- Hindi default, but English/Hinglish natural hai
- Short rakho — yeh WhatsApp hai, email nahi
- Emojis natural use karo, overdo mat karo

INTENT TYPES tumhein pata hona chahiye:
- PAYMENT_VERIFY: customer ne payment ka screenshot bheja
- SALES_QUERY: aaj/is hafte/mahine kitna hua
- CUSTOMER_QUERY: specific customer ke baare mein
- UDHAAR_LOG: credit diya ya liya
- EXPENSE_LOG: kharcha hua
- CHURN_CHECK: kaun nahi aa raha
- MORNING_BRIEF: din ki shuruaat, brief chahiye
- EOD_BRIEF: din khatam, summary chahiye
- GENERAL_NOTE: koi information share ki, no action needed
- OUT_OF_SCOPE: business se related nahi

Agar GENERAL_NOTE hai: 
Log karo (future context ke liye) aur reply: "✓ Note kar liya"

Agar OUT_OF_SCOPE:
"Main sirf Sharma General Store ke business 
ke liye hoon. Koi business sawaal ho toh batao! 🏪"
"""

TOOLS — implement all of these:

1. search_payment(txn_ref: str, amount: float = None)
   - Search transactions table by txn_ref (exact match first)
   - If not found by txn_ref and amount provided:
     search transactions within ±5% amount AND last 30 min
   - Returns: {found, txn_ref, amount, customer_name, 
               timestamp, minutes_ago, status}
   - If not found: {found: false, searched_by: str}

2. get_sales_summary(period: str)
   period options: "today", "yesterday", "this_week", 
                   "last_week", "this_month"
   - Returns real aggregated data from transactions table
   - Include: total_amount, transaction_count, 
              avg_transaction, top_customer, 
              busiest_hour, comparison_to_previous_period

3. search_customer(name: str)
   - Fuzzy search by customer name (use ILIKE %name%)
   - Returns: last 10 transactions, total_spent,
              total_visits, avg_transaction, 
              last_visit_date, days_since_last_visit,
              udhaar_balance (from udhaar table)

4. get_churned_customers(days_threshold: int = 10)
   - Find customers with 3+ past transactions whose 
     last transaction was > days_threshold days ago
   - Returns list with: name, last_visit_days_ago, 
                        avg_spend, total_visits,
                        udhaar_balance

5. log_udhaar(customer_name: str, amount: float, 
              type: str, note: str = None)
   - type: "GIVEN" (merchant gave credit) or 
           "RECEIVED" (merchant received payment)
   - Insert into udhaar table
   - Returns: confirmation with running balance for customer

6. log_expense(amount: float, category: str, note: str)
   - category: STOCK, RENT, ELECTRICITY, TRANSPORT, MISC
   - Insert into expenses table
   - Returns: confirmation with today's total expenses

7. get_udhaar_summary(customer_name: str = None)
   - If customer_name: get their specific balance
   - If None: get all outstanding udhaar sorted by amount
   - Returns: list of {customer, amount_owed, days_pending,
                       last_transaction_date}

8. get_morning_brief()
   - Yesterday's total sales and transaction count
   - Comparison to same day last week
   - Today's day name and historical average for this day
   - Top 3 customers who haven't visited in 10+ days
   - Outstanding udhaar total and top 3 debtors
   - Any customer who owes and is historically likely 
     to come today (based on their usual visit pattern)
   - Returns structured dict

9. get_eod_summary(date: str = "today")
   - Full day P&L: 
     income (UPI transactions) + any manually logged cash
   - Expenses logged today
   - New udhaar given today
   - Udhaar received today
   - Net position
   - Notable events (new customers, large transactions)
   - Returns structured dict

10. log_general_note(note: str, category: str = "GENERAL")
    - Store free-text merchant notes with timestamp
    - Create a merchant_notes table if not exists
    - Returns: "✓ Note kar liya"

ORCHESTRATOR FUNCTION:

async def run_artha(
    merchant_phone: str,
    user_input: str,          # text or transcribed voice
    input_type: str,          # "text", "voice", "image", "mixed"
    ocr_text: str = None,     # if image was sent
    is_morning: bool = False,  # triggers morning brief context
    is_evening: bool = False,  # triggers EOD context
    conversation_history: list = [],  # last 6 messages
    db_session = None
) -> dict:
    # Returns: {
    #   response_text: str,
    #   response_type: "text" | "voice" | "both",
    #   tools_called: list,
    #   intent: str
    # }

MORNING BRIEF LOGIC:
If is_morning=True AND first message of day:
  Auto-call get_morning_brief() before processing user message
  Prepend brief to response

EVENING/EOD LOGIC:
If is_evening=True (after 7pm) AND input_type=="voice":
  After processing intent, also call get_eod_summary()
  Append summary offer: "Aaj ka pura hisaab chahiye? 
  'haan' bol do."

CONVERSATION HISTORY:
Store last 6 message pairs in WhatsappSessions.context_json
Pass to GPT as message history for context continuity
Merchant can refer to previous context naturally:
"usne kitna diya tha?" after discussing Suresh

ERROR HANDLING:
If any tool fails: continue without it, note in response
If GPT call fails: return "Thoda busy hoon abhi, 
                           ek minute mein try karo 🙏"
Never crash. Always return something useful.
```

---

## PROMPT 3 — Voice Pipeline (WhatsApp Voice ↔ OpenAI)

```
Build the complete voice pipeline for Artha.
Create app/voice.py

Artha's signature feature: merchant sends voice note, 
gets voice reply back. Feels like talking to a real munshi.

STEP 1 — TRANSCRIPTION:
async def transcribe_voice(audio_bytes: bytes, 
                           mime_type: str) -> str:
  
  Convert audio_bytes to a file-like object.
  WhatsApp sends voice notes as audio/ogg with Opus codec.
  
  Call OpenAI Whisper:
  client.audio.transcriptions.create(
    model="whisper-1",
    file=("audio.ogg", audio_bytes, "audio/ogg"),
    language=None,  # auto-detect Hindi/English/Marathi
    prompt="This is a message from an Indian grocery store 
            owner about their business. May contain Hindi, 
            Marathi, or English. Business terms: udhaar, 
            paisa, customer names, UPI amounts in rupees."
  )
  
  The prompt hint dramatically improves Hindi transcription.
  Return transcript text.
  
  If transcription fails or returns empty:
  Return None (caller will ask merchant to repeat)

STEP 2 — TEXT TO SPEECH:
async def synthesize_voice(text: str) -> bytes:
  
  Clean text before synthesis:
  - Remove emojis (TTS reads them as words)
  - Replace ₹ with "rupaye"
  - Replace % with "pratishat"  
  - Keep Hindi/English mixed naturally
  
  Call OpenAI TTS:
  client.audio.speech.create(
    model="tts-1",          # faster, good enough for WhatsApp
    voice="nova",           # warm, friendly voice
    input=cleaned_text,
    response_format="mp3"   # WhatsApp accepts mp3
  )
  
  Return audio bytes.

STEP 3 — SEND VOICE REPLY ON WHATSAPP:
async def send_voice_message(to: str, audio_bytes: bytes):
  
  WhatsApp requires uploading media first, then sending.
  
  Step A: Upload mp3 to WhatsApp Media API
  POST https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/media
  multipart/form-data:
    messaging_product: whatsapp
    type: audio/mp3
    file: audio_bytes
  Returns: {id: media_id}
  
  Step B: Send audio message using media_id
  POST .../messages
  {
    messaging_product: whatsapp,
    to: to,
    type: audio,
    audio: {id: media_id}
  }

DECISION LOGIC — when to reply in voice vs text:
async def should_reply_with_voice(
    input_type: str, 
    response_text: str,
    intent: str
) -> bool:
  
  Reply with VOICE when:
  - input_type == "voice" (merchant sent voice, gets voice back)
  - intent in ["MORNING_BRIEF", "EOD_BRIEF"] (these are briefings)
  
  Reply with TEXT when:
  - input_type == "text" or "image"
  - intent == "PAYMENT_VERIFY" (merchant needs to read the verdict)
  - response_text contains a list or table (hard to follow in audio)
  - len(response_text) < 50 chars (too short, just text it)
  
  Reply with BOTH (text + voice) when:
  - intent == "EOD_BRIEF" (merchant wants to hear AND have record)

MORNING BRIEF SPECIAL HANDLING:
Morning brief is always voice.
But also send a WhatsApp text with the key numbers:
"📊 *Kal ka hisaab:* ₹3,240 | 14 transactions
⚠️ *Udhaar:* Suresh ₹350, Ramesh ₹600 (16 din)
📅 *Aaj:* {day} — historically ₹2,800 avg"

Merchant gets the voice for feel, text for reference.
```

---

## PROMPT 4 — Wire Everything in main.py + Payment Verification

```
Rewire app/main.py completely for Artha.
Import and use: run_artha from agent.py, 
transcribe_voice and synthesize_voice from voice.py,
extract_text from google_vision.py

INCOMING MESSAGE HANDLER:

async def process_message(
    phone: str, 
    message_type: str,
    text_body: str = None,
    media_id: str = None,
    db = None
):

Step 1 — Determine time context:
  current_hour = datetime.now(IST).hour
  is_morning = 5 <= current_hour <= 10
  is_evening = current_hour >= 19

Step 2 — Check if first message of day:
  session = get_session(phone)
  last_message_date = session.get("last_message_date")
  is_first_message_today = last_message_date != today
  
  If is_first_message_today AND is_morning:
    is_morning_brief = True
  Else:
    is_morning_brief = False

Step 3 — Process input by type:

  If message_type == "text":
    input_text = text_body
    input_type = "text"
    ocr_text = None
  
  If message_type == "audio":
    Send immediate text: "🎙️ Sun raha hoon..."
    audio_bytes, mime = await download_media(media_id)
    transcript = await transcribe_voice(audio_bytes, mime)
    
    If transcript is None:
      Send: "Aawaz clearly nahi aayi. Dobara bhejo? 🙏"
      Return
    
    input_text = transcript
    input_type = "voice"
    ocr_text = None
  
  If message_type == "image":
    Send immediate text: "📸 Dekh raha hoon..."
    image_bytes, mime = await download_media(media_id)
    ocr_text = await extract_text(image_bytes)
    input_text = "image bheja hai"
    input_type = "image"

Step 4 — Get conversation history from session:
  history = session.get("conversation_history", [])

Step 5 — Run orchestrator:
  result = await run_artha(
    merchant_phone=phone,
    user_input=input_text,
    input_type=input_type,
    ocr_text=ocr_text,
    is_morning=is_morning_brief,
    is_evening=is_evening,
    conversation_history=history,
    db_session=db
  )

Step 6 — Update session:
  Update last_message_date = today
  Append to conversation_history:
    {role: user, content: input_text}
    {role: assistant, content: result.response_text}
  Keep only last 6 pairs
  Save session

Step 7 — Send response:
  voice_reply = should_reply_with_voice(
    input_type, result.response_text, result.intent
  )
  
  If voice_reply:
    audio = await synthesize_voice(result.response_text)
    await send_voice_message(phone, audio)
    
    If result.intent in ["EOD_BRIEF", "MORNING_BRIEF"]:
      Also send text summary (key numbers only)
  Else:
    await send_message(phone, result.response_text)

PAYMENT VERIFICATION — keep it simple:

In run_artha, when intent is PAYMENT_VERIFY:
  If ocr_text provided:
    Extract UTR using regex from ocr_text
    UTR patterns:
      PhonePe: r'T\d{12}[A-Z0-9]{8}'
      Paytm: r'\b\d{16}\b'  
      GPay: r'[A-Z0-9]{22}'
    
    Also extract amount: r'₹\s*[\d,]+\.?\d*'
    
    Call search_payment(txn_ref=utr, amount=extracted_amount)
    
    Result handling:
    FOUND + amount matches (within ±5%):
    "✅ *Payment Confirmed*
    
    ₹{amount} mila — {customer_name} se
    Transaction: {txn_ref}
    Time: {timestamp}
    
    Maal de sakte ho. 🙏"
    
    FOUND + amount differs:
    "⚠️ *Amount Mismatch*
    
    Yeh Transaction ID hamare record mein hai,
    lekin amount alag hai.
    Record mein: ₹{db_amount}
    Screenshot mein: ₹{image_amount}
    
    Customer se seedha UPI app khol ke confirm karao."
    
    NOT FOUND + <10 min ago:
    "⏳ *Abhi Tak Nahi Aaya*
    
    Transaction {txn_ref} record mein nahi hai.
    Payment {minutes_ago} minute pehle hua — 
    network delay ho sakta hai.
    
    Main 90 second mein dobara check karunga.
    Tab tak maal mat do."
    
    Then: schedule a re-check after 90 seconds
    (use asyncio.create_task with sleep(90))
    Re-check result → send follow-up automatically
    
    NOT FOUND + >20 min ago:
    "❌ *Transaction Nahi Mila*
    
    {txn_ref} — 20+ minute ho gaye, abhi tak 
    record nahi aaya.
    
    Customer se request karo ki woh apna 
    UPI app khol ke successful payment confirm kare.
    Ya dobara payment kare."
    
    NO UTR EXTRACTED:
    "Transaction ID clearly nahi dikh raha.
    Seedha customer ki screen pe zoom karke 
    ya better light mein photo lo."
  
  Reply type: always TEXT for payment verification
  Merchant needs to read this, not hear it.

HANDLE SPECIAL INPUTS:
  
  If merchant sends video:
  "Video abhi support nahi karti. 
   Voice note ya photo bhejo! 🎙️"
  
  If merchant sends location:
  "Location note kar li. 
   Business ke liye kuch chahiye? 🏪"
  
  If merchant sends a link:
  "Link dekh nahi sakta abhi. 
   Koi sawaal ho toh poochho!"

ROUTES:
GET /webhook → Meta verification (unchanged)
POST /webhook → routes to process_message
GET /health → {status, timestamp, db_connected, version: "Artha 1.0"}
GET /demo → HTML demo page (Artha branding, deep orange + gold colors)
```

---

Run these four prompts in order. After each one, test the specific feature before moving to the next.

The one thing to test manually before the train: voice note download from WhatsApp → Whisper transcript prints in terminal. If that single path works, everything else on the train is pure logic and you have no internet dependencies to worry about.

**Artha. The AI Munshi for Kirana Shops. Ship it.**
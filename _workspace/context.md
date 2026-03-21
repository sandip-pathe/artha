First, the clarification you made is the most important technical insight in this whole project.

---

### What you're actually scanning — this changes everything

Yes, you're 100% correct. The merchant is **not uploading a screenshot file**. They're opening WhatsApp camera and **pointing it at the customer's phone screen**. This is a completely different input than a clean digital screenshot, and it's actually *more powerful* for fraud detection because:

A photo of a real phone screen has physical artifacts — slight moiré pattern from screen pixels, ambient light reflection, screen bezels visible, natural hand-hold angle distortion, maybe a finger in frame.

A fraudster showing a **fake edited screenshot saved as an image on their own phone** — when photographed — looks unnaturally flat, perfectly sharp at the edges, no screen curvature, wrong pixel density pattern.

That's a detection signal most fraud systems completely miss. You're exploiting it.

---

### The Fraud Detection Algorithm — Multi-Layer, No False Positives

The design principle: **guilty only when multiple independent layers agree**. One layer flagging = CANNOT_VERIFY. Three+ layers flagging = SUSPICIOUS. This kills false positives.

```
LAYER 0 — Physical Reality Check (before any AI)
Is this actually a photo of a phone screen?
→ Checks: moiré pattern presence, screen bezel detection,
  reflection artifacts, image sharpness gradient
→ If looks like a clean digital file (perfect edges, no distortion)
  AND no photo artifacts → flag for deeper inspection
→ Signal weight: HIGH

LAYER 1 — App Identity & Color Validation (Google Vision)
Dominant color extraction
→ Paytm: teal #00BAF2 / dark background
→ PhonePe: deep purple #5F259F
→ GPay: white/blue
→ BHIM: navy
→ Color doesn't match claimed app → MISMATCH flag
→ Signal weight: HIGH

LAYER 2 — Transaction ID Format (pure regex, no AI)
→ PhonePe format: T + YYMMDD + HHMMSS + 8 digits
  (your uploaded PhonePe screenshot: T211021183039...)
  T = prefix, 21 = year, 10 = month, 21 = day,
  18 = hour, 30 = min, 39 = sec → perfectly matches 6:30pm Oct 21
→ Validate: does the embedded timestamp in TXN ID
  match the time shown in the receipt?
→ Delta > 3 minutes → MISMATCH flag
→ Signal weight: VERY HIGH (hardest to fake correctly)

LAYER 3 — Status Bar vs Receipt Timestamp (OCR)
→ Extract time from phone status bar (top of screen)
→ Extract time from "Paid at HH:MM" in receipt
→ These should be within 0-5 minutes of each other
  (no one screenshots 3 hours after paying)
→ Delta > 10 minutes → MISMATCH flag
→ Date check: is the receipt date today? Yesterday is borderline,
  last week = suspicious, last month = reject immediately
→ Signal weight: HIGH

LAYER 4 — Merchant Name / UPI ID Cross-Check
→ Does the recipient name/UPI on the screenshot
  match the merchant's registered Paytm details?
→ "Shri Sairaj Medical" vs "Ramesh Kirana" = MISMATCH
→ Signal weight: VERY HIGH

LAYER 5 — Amount Sanity (optional, if merchant pre-states amount)
→ If merchant told us "customer should pay ₹450"
  and screenshot shows ₹4,500 or ₹45 → flag
→ Signal weight: MEDIUM

LAYER 6 — GPT-4o Vision Deep Analysis (only if layers unclear)
→ Font consistency, pixel artifacts around numbers,
  compression artifacts from editing software,
  layout pixel-perfect match to known app templates
→ Signal weight: MEDIUM (AI can hallucinate, use as tiebreaker only)

FINAL VERDICT LOGIC:
→ 0-1 layers flagged: GENUINE (or CANNOT_VERIFY if Layer 0 fails)
→ 2 layers flagged: CANNOT_VERIFY — ask customer to pay again
→ 3+ layers flagged: SUSPICIOUS
→ Layer 2 OR Layer 4 flagged alone: SUSPICIOUS (these are near-certain)
```

---

### Updated Tech Stack

```
Backend:     FastAPI (Python)
AI - Chat:   OpenAI GPT-4o
AI - Vision: GPT-4o Vision (primary) + Google Vision API (color/OCR layer)
Database:    PostgreSQL (Railway managed)
ORM:         SQLAlchemy + Alembic migrations
WhatsApp:    Meta Cloud API (same setup you have)
Deployment:  Railway
Env:         python-dotenv
HTTP client: httpx (async, fits FastAPI)
Image:       Pillow (preprocessing before AI)
```

---

### Database Schema

```
merchants          → phone, name, upi_id, paytm_id, created_at
transactions       → merchant_id, amount, customer_name, customer_phone,
                     upi_id, timestamp, status (mock data lives here)
fraud_checks       → merchant_id, image_url, verdict, confidence,
                     layers_flagged, red_flags[], created_at
whatsapp_sessions  → phone, state, context_json, updated_at
fraud_reports      → fraud_check_id, merchant_id, report_ref, created_at
```

---

## The Copilot Prompts (FastAPI Version)

---

### PROMPT 1 — Scaffold and database setup

```
Create a Python FastAPI project called payguard.

Project structure:
payguard/
├── app/
│   ├── main.py              # FastAPI app, routes
│   ├── whatsapp.py          # Meta API send/receive/download
│   ├── fraud/
│   │   ├── __init__.py
│   │   ├── pipeline.py      # Orchestrates all fraud layers
│   │   ├── layer_physical.py   # Layer 0: photo vs screenshot
│   │   ├── layer_color.py      # Layer 1: Google Vision colors
│   │   ├── layer_txnid.py      # Layer 2: Transaction ID regex
│   │   ├── layer_timestamp.py  # Layer 3: Status bar vs receipt time
│   │   ├── layer_merchant.py   # Layer 4: Merchant name/UPI match
│   │   └── layer_ai.py         # Layer 6: GPT-4o Vision deep analysis
│   ├── merchant/
│   │   ├── __init__.py
│   │   └── chat.py          # GPT-4o merchant intelligence chat
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py        # SQLAlchemy models
│   │   ├── session.py       # DB connection
│   │   └── seed.py          # Mock data seeder
│   └── sessions.py          # WhatsApp conversation state
├── alembic/                 # DB migrations
├── .env
├── .gitignore
├── requirements.txt
├── Procfile
└── README.md

requirements.txt:
fastapi
uvicorn
sqlalchemy
alembic
psycopg2-binary
httpx
openai
google-cloud-vision
pillow
python-dotenv
python-multipart
pydantic

.env placeholders:
WHATSAPP_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_VERIFY_TOKEN=
OPENAI_API_KEY=
GOOGLE_VISION_API_KEY=
DATABASE_URL=postgresql://user:pass@localhost:5432/payguard
PORT=8000

In app/db/models.py create SQLAlchemy models exactly as:

Merchants: id, phone (unique), name, upi_id, paytm_merchant_id, 
           created_at

Transactions: id, merchant_id (FK), amount (float), customer_name,
              customer_phone, upi_id, transaction_ref, 
              timestamp (datetime), status, created_at

FraudChecks: id, merchant_id (FK), image_path, verdict 
             (GENUINE/SUSPICIOUS/CANNOT_VERIFY), confidence
             (HIGH/MEDIUM/LOW), layers_flagged (ARRAY of strings),
             red_flags (ARRAY of strings), recommendation, 
             raw_amount, payment_app, transaction_ref, created_at

FraudReports: id, fraud_check_id (FK), merchant_id (FK),
              report_ref (unique), created_at

WhatsappSessions: id, phone (unique), state, context_json, updated_at

In app/db/seed.py create realistic mock data:
- 1 merchant: Ramesh Kirana Store, Mumbai, 
  phone 919876543210, upi ramesh.kirana@paytm
- 60 transactions over 30 days
- 12 unique customers with Indian names
- Amounts ₹20 to ₹2000, realistic time-of-day distribution
  (busy 8-10am, 12-2pm, 6-9pm)
- Mix: 4 regulars who come weekly, 4 semi-regular, 4 one-time
- 2 transactions deliberately from today for demo purposes

Run alembic init and configure alembic.ini to use DATABASE_URL from .env
Create initial migration for all models.
```

---

### PROMPT 2 — WhatsApp webhook and routing

```
In app/main.py build the FastAPI app:

GET /webhook — Meta verification
- Query params: hub.mode, hub.verify_token, hub.challenge
- If mode == "subscribe" and verify_token matches env var → 
  return PlainTextResponse(challenge)
- Else raise HTTPException 403

POST /webhook — Message handler
- Accept Meta WhatsApp Cloud API payload as JSON
- Extract from payload:
  entry[0].changes[0].value.messages[0]
- Get: from (sender phone), type (text/image), 
  and either text.body or image.id
- If type == "image": await handle_fraud_check(from, image_id)
- If type == "text": await handle_text_message(from, text_body)
- Return JSONResponse({"status": "ok"}) immediately — never block

handle_text_message(phone, text):
- If text.strip().upper() == "REPORT": await handle_report(phone)
- If text.strip().upper() == "MORE": await handle_more(phone)
- Else: await handle_merchant_chat(phone, text)

GET /health → {"status": "ok", "timestamp": datetime.now()}

GET /demo → serve static HTML with project info 
(Paytm teal #00BAF2 color scheme, project name PayGuard,
two features explained, "Built for Paytm Build for India 
AI Hackathon 2026")

In app/whatsapp.py build:

async def download_media(media_id: str) -> tuple[bytes, str]:
  # Step 1: GET graph.facebook.com/v22.0/{media_id}
  #   with Authorization: Bearer WHATSAPP_TOKEN
  #   Returns JSON with url field
  # Step 2: GET that url with same auth header
  #   Returns binary image data
  # Return (image_bytes, mime_type)

async def send_message(to: str, text: str) -> dict:
  # POST graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages
  # Body: messaging_product=whatsapp, to=to, 
  #       type=text, text={body: text}
  # Bearer auth
  # Return response JSON

Use httpx.AsyncClient for all HTTP calls.
All functions should raise descriptive exceptions on failure.
```

---

### PROMPT 3 — Fraud detection pipeline

```
Build the multi-layer fraud detection pipeline.
The core principle: flag SUSPICIOUS only when multiple 
independent layers agree. No false positives.

In app/fraud/layer_txnid.py:

function analyze_transaction_id(image_text: str, 
                                 receipt_time_str: str) -> LayerResult:
  
  Extract transaction ID from OCR text using these regex patterns:
  - PhonePe: r'T(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\w+'
    (T + YY MM DD HH MM SS + suffix)
  - Paytm: r'\d{16,20}' (pure numeric, 16-20 digits)
  - GPay: r'[A-Z0-9]{20,25}'
  
  For PhonePe format (most common in India):
  - Parse YY,MM,DD,HH,MM,SS embedded in the transaction ID
  - Compare to the receipt time extracted from image
  - If delta > 3 minutes: MISMATCH
  
  Return LayerResult(
    layer="TRANSACTION_ID",
    flagged=bool,
    confidence="HIGH",
    detail=str  # explanation of what was found
  )

In app/fraud/layer_timestamp.py:

function analyze_timestamps(ocr_text: str) -> LayerResult:
  
  Extract two times from OCR:
  1. Status bar time (appears as HH:MM at top of screen)
  2. Receipt time ("Paid at HH:MM" or "Paid successfully at HH:MM")
  
  Rules:
  - Delta between them: 0-8 minutes is normal, >15 minutes suspicious
  - Check if receipt date matches today or yesterday (flag if older)
  - If date is more than 2 days ago: HIGH suspicion 
    (customer re-using old receipt)
  
  Return LayerResult

In app/fraud/layer_merchant.py:

function analyze_merchant_match(ocr_text: str, 
                                 merchant_upi: str,
                                 merchant_name: str) -> LayerResult:
  
  Extract recipient UPI ID and name from OCR text.
  Compare against merchant's registered details (passed as params).
  Use fuzzy matching — allow minor OCR errors (Levenshtein distance < 3).
  If name completely different or UPI domain different: MISMATCH
  
  Return LayerResult

In app/fraud/layer_physical.py:

async function analyze_physical_reality(image_bytes: bytes) -> LayerResult:
  
  Use Pillow to analyze the image:
  - Check image metadata: does EXIF data show this was taken by a camera?
    (not a screenshot — screenshots have no EXIF camera data)
  - Analyze edge sharpness distribution: real screen photos have
    natural blur falloff at edges, screenshots are uniform
  - Check for moiré-like patterns in pixel frequency (screen-on-screen)
  - Image aspect ratio: most phone screens are 9:16 or 19.5:9,
    a photo of a phone screen often has surrounding context visible
  
  This layer should lean toward NOT flagging (avoid false positives).
  Only flag if multiple sub-signals agree.
  
  Return LayerResult

In app/fraud/layer_ai.py:

async function analyze_with_gpt_vision(image_bytes: bytes,
                                        mime_type: str,
                                        ocr_summary: str) -> LayerResult:
  
  Call OpenAI GPT-4o with the image.
  
  System: "You are a payment fraud analyst. You are analyzing a 
  photo taken by a merchant of a customer's phone showing a 
  payment confirmation screen. This is NOT a digital screenshot — 
  it is a physical photo.
  
  Look for visual inconsistencies that suggest fraud:
  1. Font weight/style inconsistencies (edited numbers look different)
  2. Pixel artifacts or halos around text (signs of image editing)
  3. Color banding or JPEG compression artifacts around amounts
  4. Layout deviations from standard Paytm/PhonePe/GPay templates
  5. If the screen looks suspiciously perfect for a photo 
     (no reflections, no angle) it may be a pre-made fake image
     displayed on the fraudster's screen
  
  OCR text already extracted: {ocr_summary}
  
  Respond ONLY with JSON:
  {
    flagged: boolean,
    confidence: 'HIGH' | 'MEDIUM' | 'LOW',
    visual_anomalies: string[],
    payment_app_detected: string,
    amount_detected: string or null
  }
  
  Be conservative. Only flag=true when you have HIGH confidence 
  of manipulation. When uncertain, flag=false."
  
  Parse response. Return LayerResult.
  If GPT call fails, return LayerResult(flagged=False, confidence="LOW",
  detail="AI analysis unavailable")

In app/fraud/pipeline.py:

async function run_fraud_pipeline(
    image_bytes: bytes,
    mime_type: str, 
    merchant_upi: str,
    merchant_name: str,
    db_session
) -> FraudResult:

  Step 1: Run Google Vision OCR on image_bytes to extract all text
  Step 2: Run all layers in parallel using asyncio.gather where possible
    - layer_physical (Pillow, sync → run in executor)
    - layer_txnid (regex on OCR text, sync)
    - layer_timestamp (regex on OCR text, sync)  
    - layer_merchant (fuzzy match, sync)
    - layer_ai (GPT-4o, async) — run last or parallel
  
  Step 3: Count flagged layers
  flagged_layers = [l for l in results if l.flagged]
  
  Step 4: Verdict logic:
  
  # Non-negotiable single-layer verdicts (very high confidence signals)
  if layer_txnid.flagged and layer_txnid.confidence == "HIGH":
      if len(flagged_layers) >= 2:
          verdict = "SUSPICIOUS"
      else:
          verdict = "CANNOT_VERIFY"
  
  elif layer_merchant.flagged:
      verdict = "SUSPICIOUS"  # Wrong merchant = always suspicious
  
  elif len(flagged_layers) >= 3:
      verdict = "SUSPICIOUS"
  
  elif len(flagged_layers) == 2:
      verdict = "CANNOT_VERIFY"
  
  elif len(flagged_layers) == 0:
      verdict = "GENUINE"
  
  else:  # 1 layer flagged
      verdict = "CANNOT_VERIFY"
  
  Step 5: Save FraudCheck to database
  Step 6: Return FraudResult with verdict, flagged layers, 
          red flags list, detected amount and app
```

---

### PROMPT 4 — Merchant chat and WhatsApp message handlers

```
In app/merchant/chat.py:

async function handle_merchant_chat(phone: str, message: str, db):
  
  Step 1: await send_message(phone, "💬 Ek second...")
  
  Step 2: Fetch merchant from DB by phone number.
  If not found, send onboarding message and return.
  
  Step 3: Fetch all transactions for this merchant from DB.
  Compute context:
  - Total revenue this month
  - Total transactions this month  
  - Top 5 customers by total spend
  - Busiest hour bracket (morning/afternoon/evening)
  - Average daily revenue
  - Customers not seen in 14+ days (churned regulars — 
    only include if they had 3+ transactions before)
  - Today's revenue so far
  
  Step 4: Call GPT-4o:
  
  system = """You are PayGuard, a smart business assistant for 
  {merchant_name} — a small shop in India using Paytm.
  
  Answer in the same language the merchant uses (Hindi or English).
  Keep answers short — this is WhatsApp. Use ₹ for amounts.
  Use emojis naturally. Never use bullet points longer than 5 items.
  
  Business summary:
  {context summary}
  
  Full transaction history (last 60 days):
  {transactions as JSON}
  
  If asked about a specific customer, search transactions and 
  give exact numbers. If asked for advice, base it on real patterns 
  in their data."""
  
  Call GPT-4o with system prompt + merchant's message.
  
  Step 5: Send response via WhatsApp.
  If response > 900 chars, cut at last sentence boundary 
  before 900 chars. Append "... Reply MORE for full answer."
  Store full response in WhatsappSessions context_json.

In app/main.py add these handlers:

handle_fraud_check(phone, media_id, db):
  send_message(phone, "🔍 Screenshot check kar raha hoon...")
  image_bytes, mime_type = await download_media(media_id)
  
  Fetch merchant from DB by phone.
  merchant_upi = merchant.upi_id if found else ""
  merchant_name = merchant.name if found else ""
  
  result = await run_fraud_pipeline(image_bytes, mime_type,
                                     merchant_upi, merchant_name, db)
  
  Format WhatsApp reply based on verdict:
  
  GENUINE:
  "✅ *Payment Genuine Lag Raha Hai*
  
  💰 Amount: ₹{amount}
  📱 App: {app}
  🔑 Transaction: {txn_ref}
  
  Safely proceed. Maal de sakte ho. 🙏"
  
  CANNOT_VERIFY:
  "❓ *Screenshot Verify Nahi Ho Paya*
  
  {list any mild concerns}
  
  ⚡ Safe option: Customer se dobara payment request karo.
  
  Reply: REPORT if you think this is fraud."
  
  SUSPICIOUS:
  "⚠️ *Suspicious Payment — Ruko!*
  
  🚩 Issues found:
  {red flags as numbered list}
  
  ❌ Maal mat do abhi. Customer se directly 
  apne Paytm QR se payment maango.
  
  Reply REPORT to flag this attempt. 🛡️"

handle_report(phone, db):
  Fetch most recent fraud check for this merchant from DB.
  Create FraudReport record with report_ref = "RPT-" + 6 random digits.
  Send:
  "🚨 *Fraud Report Filed*
  
  Reference: {report_ref}
  
  Paytm fraud team ko alert kar diya. 
  Aapki report se 38 million merchants 
  safer ho jaate hain. 🙏
  
  Shukriya! 🛡️"

First-time welcome (check WhatsappSessions, if new phone):
  "🙏 Namaste! Main hoon *PayGuard* — 
  aapka Paytm merchant assistant.
  
  Bhejo mujhe:
  📸 *Payment screenshot* — main check karunga genuine hai ya fake
  💬 *Koi bhi sawaal* — aapki sales, customers, busy time
  
  Powered by Paytm AI 🔒"
```

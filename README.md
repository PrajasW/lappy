# 💻 Laptop Deal Bot

Every 30 minutes, the bot checks Amazon.in, Flipkart, Reliance Digital and Croma for laptops that meet your specs. You get a **WhatsApp** message when one hits a real deal within your budget. A **live dashboard** shows every tracked laptop, its price history, and which ones are in budget right now.

- **Dashboard:** https://prajasw.github.io/lappy/
- **Your specs** (`config.yaml`):
  - CPU: i7/i9 13th gen+ / Core Ultra 7+ / Ryzen 7 250/260-class or better
  - 16GB+ RAM
  - 512GB+ SSD
  - RTX 5050/4060/5060 or better
  - Budget: ≤ ₹1.5L
- It runs free on GitHub Actions, so your PC can be off.

## What triggers a WhatsApp alert
A laptop that meets your specs, is **in stock**, and is **at or under ₹1.5L** (or at/under a watchlist `target_price`) when any of these happen:
- 🎯 It reaches your watchlist target price.
- 📥 It **drops into your budget**. The bot tracks spec-matching laptops up to ₹2L, so it catches e.g. a ₹1.75L RTX 5060 laptop falling to ₹1.45L in a sale.
- 📉 Its lowest price so far, or 8%+ below its usual (30-day median) price.

Before alerting, the bot re-checks the price and specs on the product page. The same laptop won't alert again for 7 days unless it gets cheaper. If a store page fails 6 checks in a row, you get a warning so nothing breaks silently.

---

## One-time setup

### 1. Make the repo public and turn on Pages (2 min)
1. https://github.com/PrajasW/lappy/settings → bottom of the page → **Change visibility → Public**.
   - Public repos get unlimited free Actions minutes and free Pages.
   - Your secrets stay hidden. Only the code, `config.yaml` and the price history are visible.
2. https://github.com/PrajasW/lappy/settings/pages → **Source: GitHub Actions**.

### 2. WhatsApp: Meta WhatsApp Cloud API (~30–45 min, one time)
You'll use Meta's free **test number**. It can message up to 5 verified numbers at no cost.

1. **Create a Meta developer account** at https://developers.facebook.com (log in with Facebook) and verify it.
2. **My Apps → Create app** → use case **"Connect with customers through WhatsApp"** (type: Business) → follow the prompts. This creates a test WhatsApp Business Account (WABA) and a test phone number.
3. Open the app's **WhatsApp → API Setup** page:
   - Under **"To"**, click **Manage phone number list** → add **your** WhatsApp number → enter the code WhatsApp sends you.
   - Note the **Phone number ID** and the **WhatsApp Business Account ID** shown on that page.
4. **Get a permanent token.** The token on the API Setup page expires in 24 h.
   1. Go to https://business.facebook.com/settings → **Users → System users → Add**. Name it e.g. `deal-bot`, role **Admin**.
   2. **Assign assets**: your app (Full control) and your WhatsApp account (Full control).
   3. **Generate new token** → choose your app → **Expiration: Never** → permissions `whatsapp_business_messaging` and `whatsapp_business_management` → copy the token.
5. **Create the two message templates.** Meta requires templates for messages the bot sends first. In PowerShell, in this folder:
   ```powershell
   $env:WHATSAPP_TOKEN="<permanent token>"
   $env:WHATSAPP_WABA_ID="<WhatsApp Business Account ID>"
   $env:WHATSAPP_PHONE_NUMBER_ID="<Phone number ID>"
   $env:WHATSAPP_TO="91XXXXXXXXXX"   # your number: country code + number, digits only
   .venv\Scripts\python src\main.py --create-wa-templates
   ```
   Approval usually takes a few minutes to a few hours. Check under **WhatsApp Manager → Message templates**. Meta may re-label them "Marketing"; that's fine, messages from the test number are still free.
6. Once approved, run a test:
   ```powershell
   .venv\Scripts\python src\main.py --test-whatsapp
   ```
   *Tip:* send any message (e.g. "hi") from your phone to the test number once. For the next 24 h the bot can also send plain-text messages, which is the fallback if a template ever gets rejected.

### 3. Add the GitHub secrets (2 min)
https://github.com/PrajasW/lappy/settings/secrets/actions → **New repository secret**, three times:

| Name | Value |
|---|---|
| `WHATSAPP_TOKEN` | the permanent system-user token |
| `WHATSAPP_PHONE_NUMBER_ID` | Phone number ID from API Setup |
| `WHATSAPP_TO` | your number, e.g. `919812345678` |

### 4. Run it
https://github.com/PrajasW/lappy/actions → **Check laptop deals** → **Run workflow**. After it finishes (~2–3 min), open the dashboard link above. From then on it runs every ~30 min by itself.

---

## Everyday use
- **Add or remove a laptop to watch:** edit `config.yaml` on GitHub (pencil icon). Add the product page URL from any store under `watchlist:` with a `target_price`.
- **Change budget or specs:** see the `budget:` and `specs:` sections of `config.yaml`.
- **Scan more pages:** apply filters on a store's website, copy the URL, and add it under `criteria → search_urls`.
- **Check locally without sending anything:** `.venv\Scripts\python src\main.py --dry-run`

## Good to know
- Prices are **listed prices**. Bank card, exchange and coupon offers are not included, so the real price is often ₹5–10k lower.
- Search pages sometimes show different prices than product pages. The bot re-checks ~8 product pages per run and always alerts using product-page prices.
- Vijay Sales isn't scanned: its listings don't name the CPU model, so the spec filter can't check them. You can still put a Vijay Sales product URL in the watchlist.
- Amazon sometimes blocks automated checks; the bot retries with different browser fingerprints.
- If WhatsApp alerts stop: Meta tokens can be revoked if the app goes unused or its settings change. Regenerate the system-user token and update `WHATSAPP_TOKEN`.

## Files
| File | What it does |
|---|---|
| `config.yaml` | budget, specs, watchlist, store search pages, alert settings |
| `src/main.py` | the run: fetch → check specs → evaluate → alert |
| `src/specs.py` | reads CPU/GPU/RAM/SSD from product titles and URLs |
| `src/extract.py`, `src/fetch.py` | store page fetching and price extraction |
| `src/deals.py` | price history and deal rules |
| `src/whatsapp.py` | WhatsApp Cloud API |
| `src/dashboard.py` | builds the GitHub Pages dashboard |
| `data/history.json` | price history (committed by the bot every run) |

# 💻 Lappy: laptop deal bot

Runs on the home server **navi** (`~/Desktop/lappy`). Every 30 minutes it:

1. Scans **Amazon.in, Flipkart, Reliance Digital, Croma** and the official **Lenovo** and **HP** stores for laptops between ₹75k and ₹2L.
2. Reads each laptop's CPU / GPU / RAM / SSD and checks them against your specs. Every laptop found is tracked; your specs decide which ones can alert.
3. Pulls **real past prices** (up to ~1 year) from pricehistory.app for Amazon/Flipkart laptops.
4. Sends a **Telegram** message via @lappy_deal_alerts_bot when a laptop that meets your specs is in stock, at or under ₹1.5L, and:
   - drops into your budget, or
   - hits a watchlist target, or
   - hits a new low, or
   - falls 8%+ below its usual price.
5. Rebuilds the **dashboard**: http://10.1.75.56:8787/ (on your local network).

## Your specs (edit `config.yaml`)
- CPU: i7/i9 13th gen+, Core Ultra 7/9, Core 7 240H-class, or Ryzen 7/9 250/260, 8845HS, AI 7/9, 9000-series
- RAM 16GB+, SSD 512GB+
- GPU: RTX 5050 / 4060 / 5060 or better
- Budget ₹1.5L

## Telegram setup (one step left)
The bot @lappy_deal_alerts_bot is created and started, and your chat ID is already in `.env`. Add the bot token:
1. In Telegram, open **@BotFather** → `/mybots` → **Lappy Deal Alerts** → **API Token** → copy it.
2. On the server: `nano ~/Desktop/lappy/.env` → paste it after `TELEGRAM_BOT_TOKEN=` → save.
3. Test it: `cd ~/Desktop/lappy && .venv/bin/python src/main.py --test-telegram`

## Day-to-day
| Task | Command / file (on navi, in `~/Desktop/lappy`) |
|---|---|
| Change budget, specs, watchlist, stores | `config.yaml` (picked up on the next run) |
| Run now | `deploy/run.sh` |
| Dry run (no messages, nothing saved) | `.venv/bin/python src/main.py --dry-run` |
| See what happened | `tail -100 logs/run.log` |
| Dashboard server log | `logs/server.log` |
| Cron jobs | `crontab -l` (run every 30 min; keep the dashboard up every 5 min and on boot) |
| Reinstall (venv, deps, cron) | `bash deploy/install.sh` |

## How it decides
- **Tracked range:** ₹75k–₹2L. Tracking above budget lets the bot catch e.g. a ₹1.75L RTX 5060 laptop falling to ₹1.45L.
- **Search pages vs product pages:** prices on store search pages can be stale. The bot re-checks product pages (8 per run, round-robin) and always re-checks before alerting.
- **First sighting:** silent unless real price history exists for that laptop. Repeat alerts for the same laptop come after 7 days, or sooner if it gets cheaper.
- **Broken pages:** if a store page fails 6 runs in a row, you get a Telegram warning.
- **Brand stores:** Lenovo and HP prices come from their store APIs.
  - Acer's store blocks bots.
  - Dell India redirects to a reseller.
  - ASUS eShop India has no usable listing.
  - MSI and Gigabyte don't sell direct in India.
- **Prices are listed prices.** Bank card and exchange offers are not included.

## Files
| Path | What |
|---|---|
| `config.yaml` | budget, specs, watchlist, search pages, brand queries, settings |
| `.env` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (private, not in git) |
| `src/main.py` | one run: fetch → specs → evaluate → backfill → alert |
| `src/specs.py` | CPU/GPU/RAM/SSD parsing from titles and URLs |
| `src/extract.py`, `src/fetch.py` | store page fetching and price extraction |
| `src/brands.py` | Lenovo and HP official store APIs |
| `src/pricehistory.py` | real past prices from pricehistory.app |
| `src/deals.py` | price history and deal rules |
| `src/telegram.py` | Telegram messages |
| `src/dashboard.py` | builds `site/index.html` |
| `deploy/` | `install.sh`, `run.sh` (cron job), `serve.sh` (dashboard server on :8787) |
| `data/history.json` | price history (server only) |
| `claude-session/` | transcript of the Claude Code session that built this (not in git) |

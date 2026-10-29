STATUS: waiting for the next Sara

# BidReady handoff (29 Oct 2026, evening; finals on 30 Oct)

## State
- Product runs on **real GeM data** (commits 968df1c → b88c9b5 on `main`, pushed). Synthetic tenders are gone.
- Pipeline: GeM BidPlus search → direct PDF download → GeM template parser + Claude (`claude-opus-5-5`) → quote validator → deterministic rules `2026.10-r4` → report.
- Library: 23 open GeM IT bids in `backend/corpus/` (PDFs, `index.json`, `library.json`, cached Claude reads in `corpus/ai/`). Claude: 380/380 quotes verified verbatim. ~$0.11 per new bid read.
- Live: `/api/gem-search` (GeM's own open-bid search) and `/api/tenders/ingest` (download + read + store, ~19–25 s). Tested once end to end locally on GEM/2026/B/8191899.
- Supplier profiles are sample businesses (`backend/data.py`); say so when asked.
- Tests: `python -m pytest backend/tests -q` → 21 passed, all on real PDFs, no paid calls.
- Keys live only in `.env` (gitignored, vercelignored): ANTHROPIC_API_KEY, TINYFISH_API_KEY, BIDREADY_MODE=live.
- Docs: `README.md`, `docs/demo.md` (3-min script), `docs/demo-video-script.html` (Vinay's teleprompter page, gitignored on his request).

## Known limits (true, say them plainly)
- TinyFish Fetch returns `proxy_error` on GeM PDFs, so we download directly; TinyFish is used for web discovery (Search).
- Past-performance % is printed in a non-text font on many bids → listed as a condition, not decided.
- A different company already runs "BIDREADY" at bidready.vercel.app (React site, "Tender Enablement & Procurement Mastery"). Possible name question from judges.

## Left to do
1. **Vercel**: Vinay added ANTHROPIC_API_KEY and TINYFISH_API_KEY and redeployed, but his project URL is not known yet (CLI token on this machine is expired). Get the URL, then test `/api/health` (expect ai_extraction true, tenders 23), `/app.html`, one assessment, and Live GeM "Read & assess" (unverified: whether GeM serves PDFs to Vercel's non-Indian IPs; if not, library works and live reading is local-only).
2. **Time one live Read & assess** before the finals (Claude reads took 16–38 s, median ~23 s on first read).
3. **Before presenting**: restart the server (`python -m uvicorn backend.main:app --port 8000`) to clear test runs from the audit log.

## Vinay's pending decisions
- Whether to present from localhost (most reliable) or the Vercel URL.
- Whether the name clash with bidready.vercel.app matters for the pitch.

## Rules that still apply
No `git add -A`; no AI attribution in commits/docs; explain before changing behaviour; ask before deploys, production writes or spending money (Claude reads of new bids cost money).

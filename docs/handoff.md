STATUS: waiting for the next Sara

# BidReady handoff (30 Oct 2026, morning)

## State
- `main` is pushed and in sync with GitHub (last commit 861f931). Live: https://bid-ready-delta.vercel.app (Vercel, backend runs in Mumbai `bom1` per `vercel.json`).
- Real GeM data end to end: GeM BidPlus search → PDF download → GeM parser + Claude (`claude-opus-5-5`) → quote validator → rules `2026.10-r4` → report. Library: 23 open GeM bids in `backend/corpus/`. About $0.11 and ~23 s per new bid read.
- TinyFish: Search (web check, discovery, matching), Monitor (Bid watch), Fetch (CPPP, eTenders, Maharashtra, Tamil Nadu). Fetch returns proxy_error on GeM.
- New check (`frontend/pages/assess.js`): matching tenders per supplier (GeM + TinyFish, `backend/matching.py`), quick switch to other suppliers, Check all (cap 20, grouped by verdict). If GeM refuses the server, matching shows a labelled snapshot (`backend/corpus/matches_snapshot/`, refresh from India with `python -m backend.tools.snapshot_matches`).
- Live site verified 30 Oct: GeM answers from bom1 (search 1.1 s), Northstar matching = 49 live matches, no snapshot used.
- **BidReady AI** (voice + text assistant):
  - App (`app.html`, every page): `backend/assistant.py`, Claude Sonnet 5.5 tool loop; paid or saving actions (new checks, Check all, supplier edits, Bid watch) return a Confirm card and run only on Confirm. "Ask AI" / "Explain this" on reports. Knows every page (the "About BidReady" prompt section) and reads misheard voice names generously ("Bitwatch" = Bid watch).
  - Landing page (`index.html`): guest mode, enforced server-side: only search_gem_tenders and search_library, no actions, 403 on confirm, mode fixed per conversation, 500-char messages, 20 guest messages per IP per hour (`backend/ratelimit.py`, in memory, per instance).
  - Topic: BidReady plus general tender/bid/procurement questions; everything else politely declined.
  - Voice: Sarvam (`backend/voice.py`), STT saaras:v4, TTS bulbul:v4-flash, English + Hindi + Hinglish; 40 calls per IP per hour each. Browsers send `audio/webm;codecs=opus`; the server strips `;codecs=` because Sarvam rejects it (that was the "voice isn't taking" bug).
  - Frontend: `frontend/assets/assistant.js/.css` (guest mode via `data-mode="guest"`, no BR shell needed).
  - Vinay tested voice in the app and on the landing page locally (30 Oct).
- Tests: `python -m pytest -q backend/tests` → 129 passed.
- Keys only in `.env` (gitignored): ANTHROPIC_API_KEY, TINYFISH_API_KEY, SARVAM_API_KEY, BIDREADY_MODE=live.

## Vinay must do (Vercel → Settings → Environment Variables, then redeploy)
- Add `SARVAM_API_KEY`: live `/api/voice/status` says `available:false`, so voice is off on the live site (text chat works: live guest "What is an EMD?" answered).
- Set `BIDREADY_MODE=live`: live `/api/health` still says `"mode":"synthetic"`.

## Vinay's pending decisions
1. Overall daily cap on guest questions (proposed: 300 a day per server instance, no new infrastructure), on top of the per-IP limit. Not built.
2. Bid library sorted for the selected supplier: bids in the supplier's categories first with a "Fits <supplier>" reason, the rest below a divider, nothing hidden; reuse `matching.py` category logic. Not built; s3 was free to take it.
3. The TinyFish monitor `e730cef3-2cbc-4f4e-a488-b3b584d75c79` (GEM/2026/B/8096659) is billed daily until stopped: keep or stop after the finals.
4. Name clash: another company runs "BIDREADY" at bidready.vercel.app.
5. 20 cached Claude reads in `backend/corpus/ai/` (from a Check all) and a changed `backend/corpus/signals/GEM-2026-B-8096659.json` are uncommitted: commit (saves ~$0.11 per bid on re-check) or leave.

## Known limits (say them plainly)
- The app has no login: anyone with the app URL can use the full assistant and confirm paid checks. Fine for the demo, not for real customers.
- Rate limits are in memory: they reset on restart and each Vercel instance counts on its own.
- Past-performance % is often in a non-text font on GeM bids → listed as a condition, not decided.

## Rules that still apply
No `git add -A`; no AI attribution in commits/docs; explain before changing behaviour; ask before pushes, deploys, production writes or spending money. Parallel workers use one git worktree each, merged and deleted the same day (none open now).

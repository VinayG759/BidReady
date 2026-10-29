# BidReady demo script (about 3 minutes)

Before you start, the server must be running (`python -m uvicorn backend.main:app --port 8000`). Open http://localhost:8000/app.html.
Bids are real open GeM bids. The supplier, Northstar IT Supplies, is a sample business, because real company financials aren't public.

## 1. Overview (20 s)
"These are real, open GeM bids: 23 in the library, read and checked. The chart shows verdicts by category. The top gaps are too few years of similar supply, a missing OEM authorisation, and resellers assuming the MSE EMD exemption applies to them."

## 2. Supplier profile (20 s)
Open **Supplier profile**: Northstar IT Supplies, Bengaluru.
"One reusable profile: an average turnover of Rs 44.7 L, Lenovo and HP letters, Rs 1 L for EMD, and Udyam MSE registration. Every fact is marked declared, document or verified. Northstar is a **reseller**. Remember that."

## 3. A real bid, Not eligible (60 s)
**New assessment** → **Bid library** → **Core Switch, Distribution Switch… · GGSIP University · GEM/2026/B/8096659** → **Run eligibility check**.
While it runs: "Search on GeM BidPlus, then our code downloads the bid PDF. The GeM parser reads the labelled fields and Claude reads the full terms. Our code checks every quote is on its page and the numbers match, and fixed rules decide. The AI never makes the call."
Report: **Not eligible**, 4/4 evidence-checked:
- Turnover: Rs 44.7 L against the Rs 60 L required (p. 3).
- Experience: 0 of 3 years of networking supply (p. 4).
- OEM authorisation: required, and Northstar has none for networking (p. 4).
- EMD: Rs 3,64,542, and the bid's own clause says *"only manufacturers for goods and Service Providers for Services are eligible for exemption from EMD. Traders are excluded"* (p. 5).

"Northstar has Udyam, so most tools would call the EMD exempt. The bid itself says traders are excluded."
Open a criterion's **more clauses from this bid · read by Claude, quotes verified**. "Claude read this bid; all 16 quotes it returned were found word for word in the document."

## 4. A relaxation that really applies (30 s)
New assessment → **2 MP CCTV Cameras, 16 Channel NVR… · Indian Navy · GEM/2026/B/8166784** → Run.
Report: **Eligible with relaxation**.
- Turnover and OEM: Not required by this bid.
- EMD: not required.
- Experience: Northstar has no CCTV history, but the bid grants MSE relaxation of experience, and the Udyam certificate is on file.

"A relaxation counts only when the bid grants it, the supplier qualifies and the proof is there."

## 5. Live GeM (25 s)
New assessment → **Live GeM** → search **laptop**. "Hundreds of open laptop bids on GeM right now." Pick one marked **Read & assess** (not already in the library). "BidReady downloads it, reads it and runs the rules in about twenty seconds."

## 6. Consultant view (15 s)
**Consultant view** → the GGSIP University switch bid. "One bid, every client. Only one of four can bid, Meridian, and the screen lists what each of the others is missing."

## 7. Audit log and close (10 s)
**Audit log**. "Every check is recorded with its rule version, 2026.10-r4. Same bid, same profile, same rules: same verdict."

## Backup answers
- *Is this real data?* The bids are real open GeM bids, downloaded from bidplus.gem.gov.in. The supplier profiles are sample businesses, because real company financials aren't public.
- *Where's the AI?* Claude reads the bid's terms and returns exact quotes with page numbers; across the library, all 380 of those quotes were verified on their pages. The decision is made by fixed rules, so every verdict is explainable and reproducible.
- *What does it cost to run?* About $0.11 per bid for Claude's read, once. After that the read is cached and re-assessing is free.
- *What isn't checked?* Technical specs, delivery and warranty. Two conditions are listed for a person instead of decided: the past-performance percentage (some bids print it in a non-text font) and the OEM's turnover.

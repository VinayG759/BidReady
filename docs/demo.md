# BidReady demo script (about 3 minutes)

Start: `python -m uvicorn backend.main:app --port 8000`, open http://localhost:8000

## 1. Landing (20 s)
"Finding a tender is easy. Checking whether you're eligible is the hard part: the clauses are spread across the notice, the bid, annexures and relaxation conditions. BidReady checks the four criteria that knock small bidders out, and shows the evidence behind every answer."
Click **Open the app**.

## 2. Overview (15 s)
"Every check is logged. The top gaps that cause bids to fail: turnover, too few similar orders, and resellers wrongly assuming the MSE EMD exemption applies to them."

## 3. Supplier profile (25 s)
Open **Supplier profile** → Northstar IT Supplies.
"One reusable profile. Notice three evidence levels: verified, document attached, declared. We never merge them. If I edit a verified number, it drops back to *declared*." (Edit a turnover value to show it, then Discard.)
"Role matters: Northstar is a reseller. Remember that."

## 4. The money shot: run a check (60 s)
**New assessment** → pick **A4 Monochrome Laser Printers** (GeM/2026/B/6822096) → **Run eligibility check**.
While the pipeline animates: "Search, Fetch and Extract run on TinyFish. Then *our code* takes over: it validates every quote against the retrieved text and cross-checks the rupee amount, and a deterministic rules engine decides. The model never makes the eligibility decision."
Report: **Not eligible**. "Northstar has a Udyam MSE certificate, so most tools would say the EMD is exempt. But on GeM that exemption is for manufacturers and service providers, not traders. BidReady catches it and tells them exactly what's short."

## 5. Refusing to guess (30 s)
New assessment → **Desktop Computers for 200 School ICT Labs** (KPPP) → Run.
"The OEM annexure is an image-only scan. We could not validate the quote, so instead of guessing we say **Needs manual review, 3/4 evidence-checked**, and tell you which page to read."

## 6. Consultant view (20 s)
**Consultant view** → Laptops tender. "One tender, every client. A consultant sees in one screen who can bid and what each client is missing."

## 7. Live web (15 s, only if the TinyFish key is working)
New assessment → **Live web · TinyFish** → search. "These are real GeM tenders from the live web, right now. Discovery metadata only, never treated as evidence. Upload the bid PDF and it goes through the same pipeline." (Upload tab: `backend/samples/sample-gem-bid.pdf`.)

## Close (15 s)
"Who pays: tender consultants first (one tender × many clients), then IT resellers on GeM. What's different from TendersAgent, BidShakti and TenderKart: we handle relaxations correctly, validate evidence in code, and refuse to decide on weak evidence."

## Backup answers
- *Is this real data?* Tenders and profiles are synthetic, so the whole pipeline is shown end to end; live search uses the real TinyFish API.
- *Accuracy?* We don't claim a number yet. The next step is a labelled benchmark of 30–50 real GeM tenders, published with failures included.

# BidReady demo video script

Runtime: about 9 minutes. Eleven scenes. Each scene lists what is on screen, what you click, and what you say.
Tone: calm and specific. Let the screens carry the picture; the voice explains *why it matters*.

---

## Before you record

1. **Reset the demo data.** Stop the server, delete `backend/store.json` if it exists, start again:
   `python -m uvicorn backend.main:app --port 8000`
2. **Browser:** Chrome, 1920×1080, zoom 100%, bookmarks bar hidden, one tab. Open http://localhost:8000
3. **Check live search works:** in the app, New assessment → Live web · TinyFish → Search. If it shows results, keep Scene 9. If not, skip it.
4. **Have the sample PDF ready:** `backend/samples/sample-gem-bid.pdf` (Scene 8).
5. **Record in sections** (one file per scene). Re-recording one scene is easier than one long take.
6. On-screen text cards are marked **[CARD]**: add them in editing over the screen recording.

---

## Scene 1: Hook (0:00 – 0:30)

**Screen:** Landing page hero. Let the clause-highlight animation play.

**Say:**
> "Every year, thousands of small Indian suppliers spend days preparing government tender bids, and get rejected at the very first step: eligibility. Not because their product was wrong, but because their turnover was a little short, an OEM letter didn't cover the right model, or they assumed an exemption that didn't apply to them.
> BidReady tells a supplier, *before* they invest in the bid, whether they appear to qualify, and shows the exact clause behind every answer."

**[CARD]** BidReady: know if you qualify before you bid.

---

## Scene 2: The business (0:30 – 1:30)

Money first: who pays, how much, why now.

**Screen:** Scroll the landing page slowly through "The problem" section. Then **[CARD]** with the three points below.

**Say:**
> "Who pays? Our first customer is the **tender consultant**. One consultant screens the same tender for twenty or thirty clients, today by hand, reading forty-to-eighty-page bid documents again for each one. BidReady turns that into one screen.
> Our second customer is the **IT-hardware reseller on GeM**: laptops, printers, networking. They bid often and lose bids on eligibility, not price.
> Pricing we plan to test: a consultant plan priced per client profile, and a low monthly plan for single suppliers. Existing tender tools sell at about three to thirty thousand rupees a year, so we price inside the range buyers already accept, and win on accuracy.
> Why now? Government procurement keeps moving onto GeM, and every small seller there faces the same eligibility clauses."

**[CARD]**
- **Who pays:** tender consultants (per client profile), then GeM IT resellers (monthly)
- **Price anchor:** market tools ₹3k – ₹30k / year; we compete on accuracy, not discount
- **First paying customer path:** 5 consultants → 20 resellers in Karnataka IT hardware

*(Adjust the pricing line to whatever your PPT states.)*

---

## Scene 3: The app at a glance (1:30 – 2:10)

**Screen:** Click **Open the app →**. Overview dashboard loads.

**Do:** Hover over a bar in *Verdicts by day*. Point at *Top eligibility gaps*.

**Say:**
> "This is the supplier's workspace. Every check is logged here: how many were eligible, how many need review, how many failed.
> On the right, the reasons bids fail. Turnover below the requirement. Too few similar orders. And this one, *reseller excluded from MSE EMD exemption*. Remember that; we'll come back to it.
> At the bottom, tenders closing soon, each one a click away from an eligibility check."

---

## Scene 4: One reusable supplier profile (2:10 – 3:10)

**Screen:** Click **Supplier profile** (Northstar IT Supplies).

**Do:**
1. Point at the *Three evidence levels, never merged* strip.
2. Scroll to *Turnover*. Change one value (e.g. FY25) and show the row turn to **Declared (edited)**.
3. Click **Discard**.
4. Scroll up to *Role in this bid* and point at **Reseller** and the chip *"Role decides whether MSE EMD exemption applies"*.

**Say:**
> "The supplier fills this profile once and reuses it for every tender: turnover by year, similar orders, OEM letters, EMD funds, MSE and startup status.
> Every fact carries an evidence level: *declared* when it's typed in, *document* when a certificate is attached, *verified* when it's checked. We never merge them. Watch: if I edit a document-backed turnover figure, it drops back to *declared*. And that rule is enforced on the server too, not just in the browser.
> Notice the role: Northstar is a **reseller**. That single field changes the outcome of real tenders, as you're about to see."

---

## Scene 5: The core flow, an eligibility check (3:10 – 4:40)

**Screen:** Click **New assessment**.

**Do:**
1. Point at the stepper (Profile → Find tender → Pipeline → Report) and the profile summary card.
2. Under **Demo tenders**, click **A4 Monochrome Laser Printers, 60 Units** (GeM/2026/B/6822096).
3. Click **Run eligibility check**. Do not skip the animation.

**Say while the pipeline runs:**
> "Six stages. The first three run on **TinyFish**: Search finds the tender, Fetch retrieves the bid documents, and the Agent extracts the four criteria into a fixed schema: the clause heading, the exact quote and the page.
> Then *our* code takes over. Stage four validates the evidence: is that quote really in the document? Does the rupee amount in the quote match the number we extracted? Stage five is a deterministic rules engine that compares the four criteria with the profile.
> No AI model makes the eligibility decision. AI reads; code decides."

**When the report appears, say:**
> "**Not eligible.** Turnover met, experience met, OEM letter met. The EMD fails.
> Northstar has a Udyam MSE certificate, so most people, and most tools, would assume the EMD is exempt. But on GeM, that exemption applies to manufacturers and service providers, *not traders*. Northstar is a reseller. It has one lakh available against a one-and-a-half-lakh EMD. Short by fifty thousand rupees.
> That's a bid this supplier would have prepared for days and lost at the first gate."

**[CARD]** Reseller with a Udyam certificate ≠ EMD exempt.

---

## Scene 6: Every answer shows its evidence (4:40 – 5:40)

**Screen:** Same report. Scroll slowly.

**Do:**
1. Point at the rotated verdict stamp and the **4/4 evidence-checked** ring.
2. Open one criterion card: point at *Required*, *Supplier* (with its evidence badge), *Rule*.
3. Point at the paper clause block: heading, page number, highlighted quote, and the three checks **Quote found · Numbers match · Heading match**, and the **Source** link.
4. Scroll to **What would change this result**, **Missing documents**, and the **Scope** notice.
5. Click **Print / save PDF** and show the print preview for two seconds, then close it.

**Say:**
> "Every criterion shows what the tender requires, what the supplier has and how strong that evidence is, the rule result, and the exact clause it came from, with page number and a link to the source.
> These three checks are run by our code on every quote. If any of them fails, the criterion is not decided; it's marked unresolved.
> Below, the gap-closing guidance: what would change this result. And the scope notice: we check four criteria, not technical specs, delivery or warranty. We're a pre-screen, not a guarantee.
> The whole report exports to PDF for the supplier's records."

---

## Scene 7: The rules really reason (5:40 – 6:30)

**Screen:** Supplier profile.

**Do:**
1. Change **Role** from Reseller to **Manufacturer**. Click **Save profile**.
2. Go to **New assessment**, select the same **A4 Laser Printers** tender, **Run** (you can press **Skip** on the animation this time).
3. Show **Eligible with relaxation**, the EMD card now *Met via relaxation*.
4. Go back to **Supplier profile**, set Role back to **Reseller**, **Save**.

**Say:**
> "Same tender, same company, one change: suppose Northstar manufactured these printers.
> Now the result is **Eligible with relaxation**: the EMD is exempted, because the tender grants it, the supplier is an MSE, the role qualifies, and the Udyam proof is on file. All four conditions, checked separately.
> This is the part competitors gloss over. A relaxation only counts when the tender grants it, the status matches, the role qualifies, and the proof is present."

---

## Scene 8: Refusing to guess (6:30 – 7:10)

**Screen:** New assessment.

**Do:** Select **Desktop Computers for 200 School ICT Labs** (KPPP; note the amber *image-only* chip on the card). Run.

**Say:**
> "This tender's OEM annexure is a scanned image. There's no text to read.
> Most tools would still give you an answer. BidReady doesn't. The quote can't be validated, so OEM is **unresolved**, and the overall verdict is **Needs manual review, 3 of 4 criteria evidence-checked**. And it tells you exactly which page to read yourself.
> A pre-screen that guesses is worse than none. When the evidence isn't clean, we say so."

---

## Scene 9: Real tenders, live web (7:10 – 7:50)

**Screen:** New assessment → **Live web · TinyFish** tab.

**Do:** Search the default query *GeM laptop tender 2026*. Point at the result count and latency, and the banner.

**Say:**
> "This is live: real GeM tenders, found on the open web right now through the TinyFish Search API, in under two seconds.
> Note the label: discovery results are metadata only. A search snippet is never treated as eligibility evidence."

**Then:** Switch to **Upload bid PDF**, drop `backend/samples/sample-gem-bid.pdf`, Run.

**Say:**
> "To assess a real tender, the supplier uploads the bid PDF. BidReady reads the text, finds the turnover, experience, OEM and EMD clauses, and runs the same validation and rules."

*(If live search isn't working on the day, skip the first half and keep the upload.)*

---

## Scene 10: Built for consultants and for audits (7:50 – 8:40)

**Screen:** Click **Consultant view**. The laptops tender is selected.

**Say:**
> "Here's the consultant's screen. One tender, every client. Two of four clients can bid. For the others, it lists exactly what each is missing. This is the screen we charge consultants for."

**Screen:** Click **Audit log**.

**Say:**
> "And every check is recorded with its rule version. Same inputs, same source snapshot, same rule version: same verdict, every time. If a supplier or an auditor asks why we said *eligible* three weeks ago, the answer is here."

---

## Scene 11: How it's built, and the close (8:40 – 9:30)

**Screen:** Landing page, scroll to *How it works* / *Under the hood*. Then **[CARD]** with the architecture line.

**Say:**
> "Under the hood: TinyFish reads the live web: search, fetch, extract. A FastAPI backend validates every piece of evidence and runs versioned, tested rules. The model never makes the final decision.
> What's next: real GeM bid documents end to end, AI extraction for long and scanned PDFs, and a published accuracy benchmark across thirty to fifty real tenders, failures included. Nobody in this market publishes their accuracy. We will.
> BidReady. Know if you qualify, before you bid."

**[CARD]**
- TinyFish Search · Fetch · Agent → evidence validator → deterministic rules → report
- 25 automated tests on the rules and validator
- Next: real GeM documents, AI extraction, public accuracy benchmark

**[CARD, end]** BidReady · github.com/VinayG759/BidReady

---

## If a judge asks

- **"Is this real data?"** The demo tenders and suppliers are synthetic, so the whole pipeline can be shown end to end. Live search returns real tenders through TinyFish; PDF upload reads a real document.
- **"Where's the AI?"** AI's job is reading messy tender documents (TinyFish Agent; simulated in this demo). The decision is deliberately not AI: it's deterministic rules, so every verdict is explainable and reproducible.
- **"How is this different from TendersAgent / BidShakti / TenderKart?"** They also do AI eligibility checks. We differ in three ways: relaxations handled correctly (trader vs manufacturer, tenders that deny exemptions), evidence validated in code, and refusing to decide on weak evidence.
- **"How accurate is it?"** We don't claim a number yet. Next step is a labelled set of 30–50 real GeM tenders, published with the failures.

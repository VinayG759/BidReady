# BidReady

**Know if you qualify for a GeM bid before you spend time on it.**

BidReady is an eligibility pre-screen for real, open bids on GeM (Government e-Marketplace, India). It downloads the bid document, reads the four criteria that most often knock small suppliers out, checks every quote against the PDF, and compares the requirements with a supplier profile using fixed rules. Every answer points to the page it came from. TinyFish finds the bid across the wider web and flags corrigenda, extensions and changed deadlines that other tender sites report.

| Criterion | What is checked |
|---|---|
| Turnover | Minimum average annual turnover (lakh, last 3 financial years) vs the supplier's figures |
| Prior experience | Years of past experience: financial years with supplies of a similar category to Central/State Govt or PSU |
| OEM authorisation | Required when the bid lists it under "Document required from seller"; manufacturers authorise themselves |
| EMD / exemption | EMD amount, and whether the MSE or startup exemption really applies to this supplier |

A criterion the bid does not set is marked **Not required**, not guessed.

## What is real

- **Bids.** The library holds 23 open GeM bids downloaded from `bidplus.gem.gov.in/showbidDocument/<id>`: laptops, desktops, all-in-one PCs, MFPs, network switches and CCTV, closing between 19 Nov 2026 and 27 Feb 2027.
- **Live GeM.** The app searches GeM BidPlus for open bids right now. On 29 Oct 2026 that was 551 laptop bids and 783 desktop bids. **Read & assess** downloads any of them, reads it and runs the rules in about 20 seconds.
- **Evidence.** Claude read every library bid. All 380 clauses it returned were found word for word on their pages, and none was rejected. Reading costs about $0.11 per bid and is cached after the first read, so re-assessing is free.
- **Web signals.** For every assessed bid, TinyFish Search finds where else it is listed and flags corrigendum, extension, cancellation and date-mismatch signals, each with the snippet it came from. GEM/2026/B/8096659 is listed on 7 sites, and tenderlelo shows 2 corrigenda with the deadline moved from 26 Oct to 23 Nov.
- **Rules.** GeM's own fields are encoded: the turnover threshold, years of experience, MSE and startup relaxation flags (Yes/No, Complete/Partial), OEM authorisation and EMD. The bid's own clause is applied as written: *"Under MSE category, only manufacturers for goods and Service Providers for Services are eligible for exemption from EMD. Traders are excluded."*

**What is sample data:** the four supplier profiles (for example Northstar IT Supplies, a Bengaluru IT reseller with Udyam MSE registration). Real company financials are not public, so the profiles are realistic but invented businesses.

## Pipeline

| # | Stage | Done by |
|---|---|---|
| 1 | Search: open bids by keyword | GeM BidPlus search; TinyFish Search for web discovery |
| 2 | Web check: where else the bid is listed, and corrigendum / extension / cancellation / date-mismatch signals | TinyFish Search |
| 3 | Fetch: download the bid PDF, keep a fingerprinted copy | BidReady code (TinyFish Fetch returns `proxy_error` on GeM pages, so the PDF is downloaded directly) |
| 4 | Extract: requirements and exact quotes | GeM template parser for labelled fields; Claude (`claude-opus-5-5`) reads the full text for terms-and-conditions clauses |
| 5 | Validate: every quote is on its page, numbers match, labels are on the page | BidReady code |
| 6 | Evaluate: four criteria vs the supplier profile | BidReady rules engine, version `2026.10-r4`, no AI |
| 7 | Report: verdict, page-cited reasons, web signals, documents to gather, open conditions | BidReady UI |

Claude only extracts. A quote that fails validation leaves its criterion **Unresolved**; the rules engine never falls back to what the model claimed.

**Conditions, not decisions.** Some requirements are listed for a person to check instead of being decided automatically:
- the past-performance percentage, which some bids print in a non-text font;
- the OEM's own turnover.

## Where TinyFish is used

| Where | TinyFish product | What it does |
|---|---|---|
| Discovery (**New assessment → Web · TinyFish** tab) | Search | Finds tenders across the web, beyond GeM. Discovery metadata only, never eligibility evidence. |
| Web check (pipeline stage 2 of 7) | Search | For every assessed bid, finds where else it is listed and flags corrigendum, extension, cancellation and date-mismatch signals. Only results that name the exact bid number count. |
| Bid watch | Monitor | Watches saved bids daily for corrigenda, extensions and cancellations. |
| Other portals | Fetch | Reads CPPP (eprocure.gov.in) and Central eTenders live. CPPP was read in 3.0 s (7,083 characters). |

Real web-check results from the library:

| Bid | Result |
|---|---|
| GEM/2026/B/8096659 | Listed on 7 sites; tenderlelo shows 2 corrigenda and the deadline moved from 26 Oct to 23 Nov |
| GEM/2026/B/8000329 | tender247 shows a deadline of 15-09-2026, while GeM says 27 Feb 2027 (date mismatch) |
| GEM/2026/B/8167057 | Listed on 6 sites, no signals |

**Limits.** TinyFish Fetch returns `proxy_error` on GeM pages, so our code downloads GeM PDFs directly. Web signals are for a person to check against GeM, not verdicts: they never change an eligibility result.

## Verdicts

| Verdict | Meaning |
|---|---|
| Eligible | Every requirement the bid sets is met |
| Eligible with relaxation | The bid grants an MSE or startup relaxation, the supplier's status and role qualify, and the proof is on file |
| Not eligible | A requirement fails and no relaxation in the bid covers it |
| Needs manual review | A quote could not be verified, or a condition needs a person to read the PDF |

## Run it

Requires Python 3.11+.

```bash
pip install fastapi uvicorn pypdf python-multipart anthropic
cp .env.example .env        # add ANTHROPIC_API_KEY and TINYFISH_API_KEY (discovery, web check, Bid watch, Other portals)
python -m uvicorn backend.main:app --port 8000
```

Open http://localhost:8000 (landing page) or http://localhost:8000/app.html (app).

Without an Anthropic key the library still works from the cached reads. Reading a new bid then falls back to the GeM parser alone.

Without a TinyFish key, web discovery, the web check, Bid watch and live portal reads are unavailable; assessments still run and the web check shows as unavailable.

Tests (64; the rules tests run on real bid PDFs, TinyFish calls are replaced by fakes, no paid calls): `python -m pytest backend/tests -q`

Refresh the bid library (downloads open bids; Claude reads any bid not yet cached, which costs money):

```bash
python -m backend.tools.build_corpus
python -m backend.tools.build_corpus --rebuild-library
```

## Layout

```
backend/   FastAPI app, GeM search and download, PDF parser, Claude extraction, validator, rules engine,
           TinyFish web check (signals.py), Bid watch (monitor.py), Other portals (portals.py), tests
backend/corpus/  stored bid PDFs, library index, cached Claude reads, saved web checks (signals/), portal reads (portals/)
frontend/  index.html (landing), app.html (app shell), assets/ (shared), pages/ (one module per screen)
docs/      build plan, API contract, demo script
```

## Scope

BidReady is a pre-screen of four eligibility criteria. It does not check technical specifications, past-performance quantities, delivery or warranty, does not prepare or submit bids, and does not guarantee acceptance or award. The bid document on GeM remains the source of truth.

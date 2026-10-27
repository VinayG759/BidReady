# BidReady

**Know if you can bid before you invest in the bid.**

BidReady is an evidence-backed eligibility pre-screen for Indian government tenders. A supplier keeps one reusable profile (turnover, similar orders, OEM letters, EMD readiness, MSE / DPIIT status). For any tender, BidReady checks the four criteria that most often knock small bidders out:

| Criterion | What is checked |
|---|---|
| Turnover | Average annual turnover vs the tender threshold and period |
| Prior experience | Number and value of similar completed orders |
| OEM authorisation | Brand **and** product scope of the supplier's OEM letters |
| EMD / relaxation | EMD amount, and whether an MSE / startup exemption really applies |

Each result is backed by the clause heading, the exact quote and the source page. The verdict comes from deterministic rules, never from the language model.

## Why it is different

- **Relaxations handled correctly.** MSE EMD exemption on GeM applies to manufacturers and service providers, not traders. An IT reseller with a Udyam certificate does not automatically qualify, and BidReady says so. Tenders that explicitly withhold startup/MSE relaxations are respected.
- **Evidence is validated in code.** Every quote the extractor returns is checked against the retrieved text, and the rupee amount in the quote is cross-checked against the structured value. If a check fails, the criterion becomes *Unresolved*. The model's claim is never used as a fallback.
- **It refuses to guess.** Coverage is shown as *N/4 criteria evidence-checked*. Weak evidence leads to *Needs manual review*, not a confident verdict.
- **Declared vs verified facts stay separate.** Typed-in numbers, attached documents and verified documents are labelled differently in the profile and the report.
- **Consultant view.** One tender against every client profile, with each client's gaps listed.
- **Gap-closing guidance.** Each failed or unresolved criterion shows what would change the result.

## Pipeline

| # | Stage | Done by |
|---|---|---|
| 1 | Search: find tender candidates | TinyFish Search API |
| 2 | Fetch: retrieve the bid documents | TinyFish Fetch API |
| 3 | Extract: schema-bound fields (criterion, heading, quote, URL) | TinyFish Agent API |
| 4 | Validate evidence: quote, number, heading | BidReady code |
| 5 | Evaluate rules: four criteria vs profile | BidReady code |
| 6 | Report: verdict, reasons, documents, N/4 | BidReady UI |

Live web search runs on the real TinyFish Search API. The demo tenders, supplier profiles and history are **synthetic**, so the full pipeline can be shown end to end.

## Run it

Requires Python 3.11+ with `fastapi`, `uvicorn`, `pypdf`, `python-multipart` (and the TinyFish CLI for live search).

```bash
pip install fastapi uvicorn pypdf python-multipart pytest
python -m uvicorn backend.main:app --port 8000
```

Open http://localhost:8000 (landing page) or http://localhost:8000/app.html (app).

Tests: `python -m pytest backend/tests -q`

## Layout

```
backend/   FastAPI app, synthetic data, evidence validator, rules engine, tests
frontend/  index.html (landing), app.html (app shell), assets/ (shared), pages/ (one module per screen)
docs/      build plan and API contract
```

## Scope

BidReady is a pre-screen. It does not check technical specifications, delivery, warranty or other conditions, does not prepare or submit bids, and does not guarantee acceptance or award. The tender document remains the source of truth.

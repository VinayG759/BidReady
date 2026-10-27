# BidReady MVP — build plan (deadline 20:30 IST, 27 Oct 2026)

## Goal
A working demo with synthetic data. The flow: supplier profile → find tender → 6-stage pipeline → evidence-backed report.
The UI quality decides shortlisting, so polish beats extra features.

## Architecture (matches the deck, slide 8)
```
frontend/ (static, no build step)  ──fetch──▶  backend/ FastAPI (python)
  index.html   landing (uploaded)               main.py      routes + serves frontend/
  app.html     app shell (sidebar + router)     data.py      synthetic tenders, source text, profiles
  assets/      tokens, shell, api client        pipeline.py  fetch/extract (simulated TinyFish) + evidence validator
  pages/       one JS + CSS file per page       rules.py     deterministic rules engine (no LLM)
                                                tests/       pytest for rules + validator
```
Run: `python -m uvicorn backend.main:app --port 8000` from the repo root, then open http://localhost:8000

## Who owns which files (no two sessions edit the same file)
| Session | Job | Owns |
|---|---|---|
| Sara | contract, app shell, design tokens, landing link, integration, screenshots | `docs/`, `frontend/index.html`, `frontend/app.html`, `frontend/assets/*` |
| W1 backend | FastAPI, synthetic data, validator, rules engine, PDF upload, tests | `backend/**` |
| W2 overview | Dashboard, Supplier profile editor, Audit log pages | `frontend/pages/dashboard.*`, `frontend/pages/profile.*`, `frontend/pages/audit.*` |
| W3 assessment | Find tender + pipeline + report, Consultant matrix | `frontend/pages/assess.*`, `frontend/pages/matrix.*` |

## Frontend contract (the shell, written by Sara)
- `app.html` loads `assets/app.css`, Lucide icons, `assets/api.js`, `assets/shell.js`, then every `pages/*.js` and `pages/*.css`.
- Each page registers itself:
  ```js
  BR.register("dashboard", { title: "Overview", icon: "layout-dashboard", render(el, params) { ... } });
  ```
  Routes are hashes: `#/dashboard`, `#/profile`, `#/assess`, `#/assess?tender=t1`, `#/report?id=a-0001`, `#/matrix`, `#/audit`.
- Helpers on `window.BR`:
  - `BR.api.get(path)`, `BR.api.post(path, body)`, `BR.api.put(path, body)`, `BR.api.upload(path, file)` → parsed JSON, throws on error.
  - `BR.go(route, params)` navigate. `BR.icons()` re-render Lucide icons after you inject HTML (`<i data-lucide="check"></i>`).
  - `BR.toast(msg)`, `BR.esc(str)`, `BR.lakh(n)` → "₹50 L", `BR.status(s)` → `{label, cls, icon}` for criterion/verdict statuses.
  - `BR.state.profileId` — currently selected supplier profile (default `p-northstar`); `BR.on("profile", fn)` fires on change.
- Design tokens live in `assets/app.css` (`--bg`, `--surface`, `--line`, `--text`, `--muted`, `--accent`, `--pass`, `--relax`, `--unres`, `--fail`, fonts `--f-display/--f-body/--f-mono`). Shared classes: `.card`, `.card-h`, `.card-b`, `.btn`, `.btn-primary`, `.btn-ghost`, `.pill`, `.inp`, `.grid-2`, `.grid-3`, `.kpi`, `.tbl`, `.empty`, `.skeleton`. Use them; put page-only styles in your own `pages/<name>.css`, prefixed with `.pg-<name>`.
- Interface rules from Vinay: pictures before text, real icons only (Lucide, never emoji), calm colours where red means only "not met / fail", no wasted empty space, separate sections, responsive at every width.

## API contract (JSON, all under /api)
Status enums: criterion `met | relaxed | not_met | unresolved`; verdict `eligible | eligible_relaxation | not_eligible | manual_review`; evidence `declared | document | verified`.

- `GET /api/health` → `{ok:true, rule_version:"2026.10-r3", mode:"synthetic"}`
- `GET /api/stats` → `{assessments, eligible, manual_review, not_eligible, avg_seconds, tenders_tracked, verdicts_by_day:[{day,eligible,relaxed,review,not_eligible}], top_gaps:[{gap,count}]}`
- `GET /api/tenders?q=` → `[Tender]` where
  `Tender = {id, bid, title, buyer, portal, category, value_lakh, emd_lakh, closes, pages, url, docs:[{name, pages, text:"ok"|"image_only"}], snippet}`
- `GET /api/tenders/{id}` → `Tender` plus `clauses:{turnover|experience|oem|emd: {heading, quote, highlight, page, doc}}`
- `GET /api/profiles` → `[Profile]`; `GET /api/profiles/{id}`; `PUT /api/profiles/{id}` (full Profile body) → Profile
  ```
  Profile = {id, name, city, entity_type, role:"reseller"|"manufacturer"|"service_provider",
    gstin, udyam_mse:bool, dpiit:bool,
    turnover:[{fy:"FY23", value_lakh, evidence}],
    orders:[{buyer, item, value_lakh, date, evidence}],
    oem_letters:[{brand, scope, valid_until, evidence}],
    emd_funds_lakh, documents:[{name, status:"valid"|"expiring"|"missing", expires}]}
  ```
- `POST /api/assess {tender_id, profile_id}` → `Assessment`
  ```
  Assessment = {id:"a-0007", created_at, rule_version, seconds,
    tender:Tender, profile:{id,name,role},
    verdict, coverage:0..4,
    stages:[{key:"search"|"fetch"|"extract"|"validate"|"evaluate"|"report", name, owner:"TinyFish"|"Our code"|"UI",
             status:"ok"|"warn"|"fail", ms, logs:[string]}],
    criteria:[{key, name, status, requirement, supplier_fact, evidence, rule_result,
               clause:{heading, quote, highlight, page, doc, url},
               validation:{quote_found, number_match, heading_match},
               docs:[{name, ok}], next_steps:[string]}],
    missing_docs:[string], unresolved:[string],
    scope_notice:string}
  ```
- `GET /api/assessments` → `[{id, created_at, tender_bid, tender_title, profile_name, verdict, coverage, rule_version}]` newest first (seeded with ~8 history rows)
- `GET /api/assessments/{id}` → `Assessment`
- `GET /api/matrix?tender_id=t1` → `{tender, rows:[{profile_id, name, role, verdict, coverage, criteria:{turnover,experience,oem,emd: status}, gaps:[string]}]}`
- `POST /api/upload` (multipart `file` = PDF) → `Tender` (id starts `u-`), clauses extracted from the PDF text with regex; anything not found is `null` and becomes `unresolved`.

## Phases
0. (Sara, 19:25–19:35) git init, contract, shell, tokens. W1 starts immediately.
1. (all, 19:35–20:05) W1 backend with tests; W2/W3 pages against the contract.
2. (Sara, 20:05–20:20) integrate, run tests, screenshot at 1920 / 1366 / 768 / 390, fix.
3. (20:20–20:30) Vinay rehearses the demo script.

## Hard rules for every session
No production writes, no push, no deploy, no messages sent anywhere. Stage explicit paths only (never `git add -A` or `git add .`).
No AI attribution anywhere (no Co-Authored-By, no "Generated with"). Secrets only in `.env`. Edit only the files you own.

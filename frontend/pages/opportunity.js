/* Dynamic, URL-addressable details for a live GeM opportunity. */
(function () {
  "use strict";
  const BR = window.BR, E = BR.esc, I = name => `<i data-lucide="${name}"></i>`;
  let state;

  const quantity = value => {
    if (!value) return "Not listed";
    const n = Number(String(value).replace(/,/g, ""));
    return Number.isFinite(n) ? n.toLocaleString("en-IN") : value;
  };
  const displayValue = value => value && typeof value === "object" ? JSON.stringify(value) : value;
  const money = value => {
    const amount = Number(String(value).replace(/[^\d.]/g, ""));
    return Number.isFinite(amount) ? "₹" + amount.toLocaleString("en-IN") : value;
  };
  function date(value) {
    if (!value) return "Not listed";
    const m = /^(\d{2})-(\d{2})-(\d{4})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?$/.exec(String(value));
    if (m) {
      const d = new Date(Date.UTC(+m[3], +m[2] - 1, +m[1]));
      const day = new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).format(d);
      return `${day}${m[4] ? ` · ${m[4]}:${m[5]}${m[6] ? `:${m[6]}` : ""} UTC` : ""}`;
    }
    const d = new Date(value);
    return isNaN(d) ? value : new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" }).format(d);
  }
  const safeUrl = value => {
    try { const u = new URL(value); return ["http:", "https:"].includes(u.protocol) ? u.href : "#"; }
    catch (_) { return "#"; }
  };
  const isDemo = () => String((BR.state.account || {}).user_id || "").startsWith("demo:");
  const followsKey = () => "br.follows." + String((BR.state.account || {}).user_id || "demo");
  const normalizeFollows = value => ({
    bids: Array.isArray(value && value.bids) ? value.bids.map(String) : [],
    organizations: Array.isArray(value && value.organizations) ? value.organizations.map(String) : []
  });
  async function readFollows() {
    if (isDemo()) {
      try { return normalizeFollows(JSON.parse(localStorage.getItem(followsKey()) || "{}")); }
      catch (_) { return normalizeFollows({}); }
    }
    return normalizeFollows(await BR.api.get("/api/follows"));
  }
  async function writeFollows() {
    const value = { bids: state.follows.bids, organizations: state.follows.organizations };
    if (isDemo()) { localStorage.setItem(followsKey(), JSON.stringify(value)); return value; }
    return BR.api.put("/api/follows", value);
  }

  function draw() {
    const { root, info, bid } = state;
    const host = root.querySelector(".opp-detail-content");
    const tender = info.tender || {}, saved = state.follows.bids.includes(String(bid.id));
    const organization = bid.organization || bid.buyer;
    const isFollowing = state.follows.organizations.includes(organization);
    const supplier = BR.state.account && BR.state.account.account_type === "supplier";
    const categories = [...new Set((bid.categories || []).map(x => String(x).trim()).filter(Boolean))];
    if (!categories.length) categories.push("Other / unclassified");
    const items = [
      ["Bid number", bid.bid], ["Status", bid.status], ["Bid type", bid.bid_type], ["Quantity", quantity(bid.quantity)],
      ["Estimated bid amount", bid.estimated_value ? money(bid.estimated_value) : "Not published in GeM listing"],
      ["Published / start date", date(bid.start_date)], ["Bid opening date (PDF)", tender.pdf_opening_date || "See bid schedule"],
      ["Bid closing date (live GeM listing)", date(bid.end_date)], ["Offer validity", tender.offer_validity],
      ["Ministry", bid.ministry], ["Department", bid.department], ["Organisation", bid.organization], ["Office", bid.office],
      ["Evaluation method", tender.evaluation_description || bid.evaluation_type], ["GeM high-value flag", bid.high_value ? "Yes" : "No"],
      ["Custom item", bid.custom_item ? "Yes" : "No"],
      ["EMD", tender.emd_required === false ? "Not required" : tender.emd_lakh > 0 ? BR.lakh(tender.emd_lakh) : tender.emd_required === true ? "Required; amount in GeM document" : "See bid document"],
      ["ePBG", tender.epbg_required === false ? "Not required" : tender.epbg_required === true ? "Required; details in GeM document" : "See bid document"],
      ["Bid schedule", bid.bid_schedule]
    ].filter(([, value]) => value !== undefined && value !== null && value !== "");
    const clauses = info.clauses || {};
    const clauseNames = { turnover: "Turnover", experience: "Prior experience", oem: "OEM requirements", emd: "EMD / bid security" };
    const clauseBlock = Object.entries(clauseNames).map(([key, label]) => {
      const c = clauses[key], quote = String(c && c.quote || "");
      const shortened = quote.length > 900;
      return `<article class="opp-clause"><h4>${E(label)}</h4>${quote
        ? `<p>${E(shortened ? quote.slice(0, 900) + "…" : quote)}</p>${shortened ? `<details><summary>Show full extracted clause</summary><p>${E(quote)}</p></details>` : ""}${c.page ? `<small>GeM PDF · page ${E(c.page)}</small>` : ""}`
        : `<p class="opp-not-found">No readable clause was extracted. BidReady leaves this criterion unresolved; review the source PDF before relying on an eligibility check.</p>`}</article>`;
    }).join("");
    const raw = Object.entries(bid.raw_fields || {}).map(([key, value]) =>
      `<div><code>${E(key)}</code><span>${E(Array.isArray(value) ? value.join(", ") : typeof value === "object" ? JSON.stringify(value) : value)}</span></div>`).join("");
    const docText = info.document_text || "";

    host.innerHTML = `<div class="opp-detail">
      <nav class="opp-crumb"><a href="#/opportunities">${I("arrow-left")} All opportunities</a><span>Live GeM bid</span><button type="button" class="btn btn-ghost btn-sm" data-reload>${I("rotate-cw")}Refresh details</button></nav>
      <header class="opp-hero card"><div class="opp-hero-copy"><div class="eyebrow">LIVE GEM OPPORTUNITY · ${E(bid.status || "ONGOING")}</div><h2>${E(bid.title || "GeM bid")}</h2><p>${E(bid.buyer || "Buyer details not listed")}</p><div class="op-tags opp-tags">${categories.map(x => `<span class="op-tag">${E(x)}</span>`).join("")}<span class="op-tag">${E(bid.sector || "Other / unclassified")}</span><span class="op-tag">${E(bid.bid_type || "Bid")}</span></div></div>
        <div class="opp-hero-actions"><button class="btn btn-ghost" data-save>${I(saved ? "bookmark-check" : "bookmark")}${saved ? "Saved bid" : "Save bid"}</button><button class="btn btn-ghost" data-follow>${I(isFollowing ? "bell-ring" : "bell-plus")}${isFollowing ? "Following organisation" : "Follow organisation"}</button><a class="btn btn-ghost" href="${E(safeUrl(bid.document_url))}" target="_blank" rel="noopener noreferrer">${I("file-text")}Source PDF</a>${supplier ? `<button class="btn btn-primary" data-check>${I("scan-search")}Check eligibility</button>` : ""}</div></header>
      <section class="opp-section"><div class="eyebrow">AT A GLANCE</div><h3>Bid information</h3><div class="op-facts">${items.map(([label, value]) => `<div class="op-fact"><small>${E(label)}</small><b>${E(displayValue(value))}</b></div>`).join("")}</div></section>
      <section class="opp-section"><div class="eyebrow">DOCUMENT REVIEW</div><h3>Readiness clauses extracted from the bid PDF</h3><p class="opp-section-intro">These are text extraction results, not a legal interpretation. When a clause is unreadable or missing, check the official document.</p><div class="opp-clauses">${clauseBlock}</div></section>
      ${raw ? `<details class="opp-section op-raw"><summary>All GeM listing fields</summary><div class="op-raw-fields">${raw}</div></details>` : ""}
      <details class="opp-section op-document"><summary>Full GeM bid document text ${docText ? "" : "(not available from source)"}</summary>${docText ? `<pre>${E(docText)}</pre>` : `<p>The live listing is available, but the public bid document could not be fetched. Use the official GeM link to review its terms.</p>`}</details>
      <p class="op-source-note">The closing date comes from the current GeM listing. The PDF may contain an earlier date if GeM amended the bid. Listing changes refresh every five minutes while the opportunities page is open; GeM can take up to 15 minutes to publish an update.</p>
    </div>`;
    host.querySelector("[data-reload]").addEventListener("click", () => void load(state.id));
    host.querySelectorAll("[data-save]").forEach(button => button.addEventListener("click", () => void toggleSave()));
    host.querySelectorAll("[data-follow]").forEach(button => button.addEventListener("click", () => void toggleFollow()));
    host.querySelectorAll("[data-check]").forEach(button => button.addEventListener("click", () => BR.go("assess", { tender: "gem-" + bid.id })));
    BR.icons();
  }

  async function toggleSave() {
    const i = state.follows.bids.indexOf(String(state.bid.id));
    if (i >= 0) state.follows.bids.splice(i, 1); else state.follows.bids.push(String(state.bid.id));
    try { await writeFollows(); draw(); }
    catch (err) {
      if (i >= 0) state.follows.bids.splice(i, 0, String(state.bid.id));
      else state.follows.bids = state.follows.bids.filter(id => id !== String(state.bid.id));
      BR.toast("Could not save this bid: " + (err.message || ""), "triangle-alert");
    }
  }
  async function toggleFollow() {
    const organization = state.bid.organization || state.bid.buyer;
    const i = state.follows.organizations.indexOf(organization);
    if (i >= 0) state.follows.organizations.splice(i, 1); else state.follows.organizations.push(organization);
    try { await writeFollows(); draw(); }
    catch (err) {
      if (i >= 0) state.follows.organizations.splice(i, 0, organization);
      else state.follows.organizations = state.follows.organizations.filter(value => value !== organization);
      BR.toast("Could not follow this organisation: " + (err.message || ""), "triangle-alert");
    }
  }
  async function load(id) {
    if (!/^\d{5,20}$/.test(String(id || ""))) {
      state.root.querySelector(".opp-detail-content").innerHTML = `<div class="empty">That GeM bid link is not valid. <a href="#/opportunities">Return to opportunities</a></div>`;
      return;
    }
    state.id = String(id);
    const host = state.root.querySelector(".opp-detail-content");
    host.innerHTML = `<div class="empty">${I("loader-circle")}Loading live GeM bid details and document…</div>`;
    BR.icons();
    try {
      const [info, follows] = await Promise.all([
        BR.api.get(`/api/live-tenders/${encodeURIComponent(id)}`),
        readFollows().catch(() => normalizeFollows({}))
      ]);
      if (state.id !== String(id)) return;
      state.info = info; state.bid = info.bid; state.follows = follows;
      draw();
    } catch (err) {
      host.innerHTML = `<div class="empty">${I("cloud-off")}Could not load this live GeM bid. ${E(err.message || "")}<p><a href="#/opportunities">Return to opportunities</a></p></div>`;
      BR.icons();
    }
  }

  BR.register("opportunity", {
    title: "Bid details", icon: "file-search-2",
    render(root, params) {
      state = { root, id: null, bid: null, info: null, follows: { bids: [], organizations: [] } };
      root.innerHTML = `<div class="opp-detail-content"><div class="empty">${I("loader-circle")}Loading live GeM bid details…</div></div>`;
      void load(params.id);
    }
  });
})();

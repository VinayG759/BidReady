/* Sector-matched tenders plus an explicit live-search discovery path. */
(function () {
  "use strict";
  const BR = window.BR;
  const E = BR.esc;
  const I = name => `<i data-lucide="${name}"></i>`;
  const safeUrl = value => { try { const u = new URL(value, location.href); return ["http:", "https:"].includes(u.protocol) ? u.href : "#"; } catch (e) { return "#"; } };
  let state;

  function card(tender, supplier, index) {
    const close = tender.closes ? new Date(tender.closes + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "Closing date not extracted";
    return `<article class="op-card" style="animation-delay:${index * 35}ms">
      <div class="op-card-top"><span class="op-sector">${I("layers-3")}${E(tender.sector || "Other / unclassified")}</span><span class="op-portal">${E(tender.portal || "Portal")}</span></div>
      <h3>${E(tender.title)}</h3><p class="op-buyer">${E(tender.buyer || "Buyer not extracted")}</p>
      <div class="op-meta"><span>${I("hash")}<b>${E(tender.bid || tender.id)}</b></span><span>${I("calendar-clock")}Closes ${E(close)}</span></div>
      <div class="op-card-foot"><span>${E(tender.category || "Unclassified")}</span>${supplier ? `<button class="btn btn-primary btn-sm" data-assess="${E(tender.id)}">${I("scan-search")}Check eligibility</button>` : `<a class="btn btn-ghost btn-sm" href="${E(safeUrl(tender.url || "#"))}" target="_blank" rel="noopener noreferrer">${I("external-link")}View tender</a>`}</div>
    </article>`;
  }

  async function runLive(query) {
    const host = state.root.querySelector(".op-live-results");
    host.innerHTML = `<div class="empty">${I("loader-circle")}Searching the web…</div>`; BR.icons();
    try {
      const result = await BR.api.get("/api/live-search?q=" + encodeURIComponent(query));
      if (!result.ok) throw new Error(result.error || "Live search is unavailable");
      const rows = result.results || [];
      host.innerHTML = rows.length ? `<div class="op-live-note">${I("info")}Discovery results from ${E(result.source)}. Check the issuing portal for the complete tender, current dates, and amendments.</div>
        <div class="op-live-list">${rows.map(row => `<article class="op-live-row"><div class="eyebrow">${E(row.site_name || "WEB RESULT")}${row.date ? " · " + E(row.date) : ""}</div><a href="${E(safeUrl(row.url || "#"))}" target="_blank" rel="noopener noreferrer"><b>${E(row.title || "Untitled result")}</b>${I("external-link")}</a><p>${E(row.snippet || "")}</p></article>`).join("")}</div>`
        : `<div class="empty">No live results for that query. Try broader terms.</div>`;
    } catch (err) {
      host.innerHTML = `<div class="op-live-note warn">${I("cloud-off")}Live search needs TinyFish credentials or a logged-in TinyFish CLI. ${E(err.message || "No results returned.")}</div>`;
    }
    BR.icons();
  }

  async function render(root) {
    state = { root, rows: [] };
    const supplier = BR.state.account && BR.state.account.account_type === "supplier";
    root.innerHTML = `<header class="op-head"><div><div class="eyebrow">${supplier ? "SUPPLIER OPPORTUNITIES" : "TENDER DISCOVERY"}</div><h2>${supplier ? "Bids for your sectors" : "Find tenders in your sectors"}</h2>
      <p>${supplier ? "Your sector preferences filter this feed. Open any bid to run the eligibility pre-screen against your profile." : "Browse tracked opportunities and search for current tenders that match your selected industries."}</p></div><a class="btn btn-ghost" href="#/account">${I("settings-2")}Edit sectors</a></header>
      <section class="op-live card"><div class="card-h"><h3>${I("globe-2")}Search the live web</h3><span class="op-discovery-badge">Discovery, not a complete feed</span></div>
        <div class="card-b"><form class="op-search"><input class="inp" name="q" placeholder="Tender name, sector, buyer, or bid number" aria-label="Search live tenders"><button class="btn btn-primary" type="submit">${I("search")}Search</button></form>
        <p class="op-disclaimer">Search results are listings only. They may miss notices or updates; confirm each opportunity on its official procurement portal. Upload the tender PDF in a supplier account to assess it.</p><div class="op-live-results"></div></div></section>
      <section class="op-tracked"><div class="op-section-head"><div><div class="eyebrow">LOCAL CATALOG</div><h3>Tracked opportunities</h3></div><label class="op-all-toggle"><input type="checkbox" class="op-show-all"> Show all tracked sectors</label></div>
      <div class="op-catalog-note">${I("flask-conical")}The current project includes illustrative sample tenders. Live-market coverage depends on configured sources and is not exhaustive.</div>
      <div class="op-grid"><div class="empty">${I("loader-circle")}Loading tracked tenders…</div></div></section>`;
    const queryForm = root.querySelector(".op-search");
    queryForm.addEventListener("submit", event => {
      event.preventDefault();
      const typed = queryForm.elements.q.value.trim();
      const sectors = (BR.state.account && BR.state.account.sectors) || [];
      const sectorQuery = sectors.includes("All sectors") ? "" : sectors.join(" ");
      const query = typed || `${sectorQuery} government tenders procurement India`.trim() || "government tenders procurement India";
      void runLive(query);
    });
    root.querySelector(".op-show-all").addEventListener("change", () => draw());
    root.querySelector(".op-grid").addEventListener("click", event => {
      const button = event.target.closest("[data-assess]");
      if (button && BR.go) BR.go("assess", { tender: button.dataset.assess });
    });
    try {
      state.rows = await BR.api.get("/api/tenders");
      draw();
    } catch (err) {
      root.querySelector(".op-grid").innerHTML = `<div class="empty">${I("triangle-alert")}Could not load tenders: ${E(err.message || err)}</div>`;
      BR.icons();
    }
  }

  function draw() {
    const host = state.root.querySelector(".op-grid");
    const supplier = BR.state.account && BR.state.account.account_type === "supplier";
    const account = BR.state.account || {};
    const selected = new Set(account.sectors || []);
    const list = (state.rows || []).filter(row => state.root.querySelector(".op-show-all").checked ||
      selected.has("All sectors") || selected.has(row.sector) || row.sector === "Other / unclassified");
    host.innerHTML = list.length ? list.map((row, index) => card(row, supplier, index)).join("")
      : `<div class="empty">${I("search-x")}No tracked tenders match these sectors. Use live search above or broaden your sector preferences.</div>`;
    BR.icons();
  }

  BR.register("opportunities", { title: "Opportunities", icon: "briefcase-business", render });
})();

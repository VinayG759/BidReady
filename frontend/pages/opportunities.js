/* Live GeM bid discovery, detail, and saved/followed opportunities. */
(function () {
  "use strict";
  const BR = window.BR;
  const E = BR.esc;
  const I = name => `<i data-lucide="${name}"></i>`;
  let state;

  const sectorMatch = (bid, selected) => !selected.size || selected.has("All sectors") || selected.has(bid.sector) || bid.sector === "Other / unclassified";
  const numeric = value => value && /^\d+$/.test(String(value).replace(/,/g, "")) ? Number(String(value).replace(/,/g, "")) : null;
  const quantity = value => { const n = numeric(value); return n == null ? value || "Not listed" : n.toLocaleString("en-IN"); };
  const displayValue = value => value && typeof value === "object" ? JSON.stringify(value) : value;
  const money = value => { const amount = Number(String(value).replace(/[^\d.]/g, "")); return Number.isFinite(amount) ? "₹" + amount.toLocaleString("en-IN") : value; };
  function fmtDate(value) {
    if (!value) return "Not listed";
    const m = /^(\d{2})-(\d{2})-(\d{4})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?$/.exec(String(value));
    if (m) {
      const date = new Date(Date.UTC(+m[3], +m[2] - 1, +m[1]));
      const day = new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).format(date);
      return `${day}${m[4] ? ` · ${m[4]}:${m[5]}${m[6] ? `:${m[6]}` : ""} (GeM)` : ""}`;
    }
    const date = new Date(value);
    if (isNaN(date)) return value;
    return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" }).format(date);
  }
  const safeUrl = value => { try { const url = new URL(value); return ["http:", "https:"].includes(url.protocol) ? url.href : "#"; } catch (_) { return "#"; } };
  const isDemo = () => String((BR.state.account || {}).user_id || "").startsWith("demo:");
  const localFollowKey = () => "br.follows." + String((BR.state.account || {}).user_id || "demo");
  const normalizeFollows = value => ({
    bids: Array.isArray(value && value.bids) ? value.bids.map(String) : [],
    organizations: Array.isArray(value && value.organizations) ? value.organizations.map(String) : []
  });

  async function getFollows() {
    if (isDemo()) {
      try { return normalizeFollows(JSON.parse(localStorage.getItem(localFollowKey()) || "{}")); } catch (_) { return normalizeFollows({}); }
    }
    return normalizeFollows(await BR.api.get("/api/follows"));
  }
  async function putFollows() {
    const value = { bids: [...state.follows.bids], organizations: [...state.follows.organizations] };
    if (isDemo()) { localStorage.setItem(localFollowKey(), JSON.stringify(value)); return value; }
    return BR.api.put("/api/follows", value);
  }
  const followed = bid => state.follows.organizations.includes(bid.organization || bid.buyer);

  function card(bid, index) {
    const allTags = bid.categories && bid.categories.length ? bid.categories : [bid.category || "Other / unclassified"];
    const tags = `<span class="op-tag">${E(allTags[0])}</span>` +
      (allTags.length > 1 ? `<span class="op-tag">+${allTags.length - 1} more categories</span>` : "");
    const saved = state.follows.bids.includes(String(bid.id));
    return `<article class="op-card" data-open="${E(bid.id)}" style="animation-delay:${Math.min(index, 12) * 25}ms">
      <div class="op-card-top"><span class="op-sector">${I("layers-3")}${E(bid.sector || "Other / unclassified")}</span><span class="op-portal">GeM · ${E(bid.bid_type || "Bid")}</span></div>
      <h3>${E(bid.title || "GeM bid")}</h3><p class="op-buyer">${E(bid.buyer || "Buyer not listed")}</p>
      <div class="op-tags">${tags}</div>
      <div class="op-meta"><span>${I("hash")}<b>${E(bid.bid || bid.id)}</b></span><span>${I("boxes")}Qty ${E(quantity(bid.quantity))}</span><span>${I("calendar-clock")}Closes ${E(fmtDate(bid.end_date))}</span></div>
      <div class="op-card-foot"><span class="op-status">${I(bid.status === "Ongoing" ? "radio" : "circle-alert")}${E(bid.status || "Ongoing")}${bid.high_value ? " · High value" : ""}</span><span class="op-card-actions"><button type="button" class="btn btn-ghost btn-sm" data-save="${E(bid.id)}" aria-label="${saved ? "Unsave" : "Save"} bid">${I(saved ? "bookmark-check" : "bookmark")}${saved ? "Saved" : "Save"}</button><button type="button" class="btn btn-primary btn-sm" data-open="${E(bid.id)}">${I("arrow-up-right")}View</button></span></div>
    </article>`;
  }

  async function refresh(automatic = false) {
    const host = state.root.querySelector(".op-grid");
    if (!host) return;
    const seq = ++state.requestSeq;
    const query = state.root.querySelector("[name=q]").value.trim();
    const page = state.page;
    host.innerHTML = `<div class="empty">${I("loader-circle")}Loading live GeM bids…</div>`; BR.icons();
    try {
      const result = await BR.api.get(`/api/live-tenders?q=${encodeURIComponent(query)}&page=${page}`);
      if (state.requestSeq !== seq || state.page !== page) return;
      const nextRows = result.bids || [];
      const previousIds = new Set(state.rows.map(item => String(item.id)));
      const newFollowed = automatic ? nextRows.filter(item => !previousIds.has(String(item.id)) && followed(item)) : [];
      state.rows = nextRows; state.result = result;
      draw();
      if (newFollowed.length && BR.toast) BR.toast(`${newFollowed.length} new live bid${newFollowed.length === 1 ? "" : "s"} from a followed organisation`, "bell-ring");
      const info = state.root.querySelector(".op-feed-status");
      info.textContent = `${Number(result.total || 0).toLocaleString("en-IN")} ongoing GeM bids · refreshed ${new Date(result.updated_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`;
      const pages = Math.max(1, Math.ceil((result.total || 0) / 10));
      state.root.querySelector(".op-page-label").textContent = `Page ${page.toLocaleString("en-IN")} · ${pages.toLocaleString("en-IN")}`;
      state.root.querySelector("[data-page=prev]").disabled = page <= 1;
      state.root.querySelector("[data-page=next]").disabled = result.start + result.page_size >= result.total;
    } catch (err) {
      host.innerHTML = `<div class="empty">${I("cloud-off")}Could not load the GeM live feed. ${E(err.message || "")}</div>`;
      state.root.querySelector(".op-feed-status").textContent = "Live feed unavailable"; BR.icons();
    }
  }

  function draw() {
    const host = state.root.querySelector(".op-grid");
    if (!host) return;
    const sectorsOnly = state.root.querySelector(".op-sector-filter").checked;
    const followedOnly = state.root.querySelector(".op-follow-filter").checked;
    const selected = new Set((BR.state.account && BR.state.account.sectors) || []);
    const list = (state.rows || []).filter(bid => (!sectorsOnly || sectorMatch(bid, selected)) &&
      (!followedOnly || followed(bid)));
    host.innerHTML = list.length ? list.map(card).join("") : `<div class="empty">${I("search-x")}${followedOnly ? "No live bids from followed organisations on this page." : "No live bids match this search and filter."}</div>`;
    BR.icons();
  }

  async function toggleSave(id) {
    const key = String(id), i = state.follows.bids.indexOf(key);
    if (i >= 0) state.follows.bids.splice(i, 1); else state.follows.bids.push(key);
    try { await putFollows(); draw(); }
    catch (err) { BR.toast("Could not save this bid: " + (err.message || ""), "triangle-alert"); }
    BR.icons();
  }

  async function toggleFollow(id) {
    const bid = state.rows.find(item => String(item.id) === String(id)) || state.detailBid;
    if (!bid) return;
    const organization = bid.organization || bid.buyer;
    const i = state.follows.organizations.indexOf(organization);
    if (i >= 0) state.follows.organizations.splice(i, 1); else state.follows.organizations.push(organization);
    try { await putFollows(); }
    catch (err) { BR.toast("Could not follow this organisation: " + (err.message || ""), "triangle-alert"); }
    BR.icons();
  }

  async function render(root) {
    if (state && state.autoRefresh) clearInterval(state.autoRefresh);
    state = { root, rows: [], page: 1, requestSeq: 0, follows: { bids: [], organizations: [] }, detailBid: null };
    root.innerHTML = `<header class="op-head"><div><div class="eyebrow">LIVE GEМ BID FEED</div><h2>Government opportunities</h2><p>Browse ongoing bids from GeM. All listed sectors stay visible; choose your sectors as a quick filter.</p></div><a class="btn btn-ghost" href="#/account">${I("settings-2")}Edit sectors</a></header>
      <section class="op-live card"><div class="card-h"><h3>${I("globe-2")}Search live GeM bids</h3><span class="op-source">Official GeM listing</span></div><div class="card-b">
        <form class="op-search"><input class="inp" name="q" placeholder="Tender name, sector, buyer, or bid number" aria-label="Search live GeM bids"><button class="btn btn-primary" type="submit">${I("search")}Search</button><button class="btn btn-ghost" type="button" data-refresh>${I("rotate-cw")}Refresh</button></form>
        <div class="op-filter-row"><label><input type="checkbox" class="op-sector-filter"> Filter to my sectors</label><label><input type="checkbox" class="op-follow-filter"> Followed organisations only</label><span class="op-feed-status">Loading the current GeM feed…</span></div>
      </div></section>
      <section class="op-tracked"><div class="op-section-head"><div><div class="eyebrow">ONGOING BIDS</div><h3>Current opportunities</h3></div><div class="op-pager"><button type="button" class="btn btn-ghost btn-sm" data-page="prev">${I("chevron-left")}Previous</button><span class="op-page-label">Page 1</span><button type="button" class="btn btn-ghost btn-sm" data-page="next">Next${I("chevron-right")}</button></div></div>
        <div class="op-grid"><div class="empty">${I("loader-circle")}Loading live bids…</div></div></section>`;
    try { state.follows = normalizeFollows(await getFollows()); } catch (_) { state.follows = normalizeFollows({}); }
    const form = root.querySelector(".op-search");
    form.addEventListener("submit", event => { event.preventDefault(); state.page = 1; void refresh(); });
    root.querySelector("[data-refresh]").addEventListener("click", () => void refresh());
    root.querySelector(".op-sector-filter").addEventListener("change", draw);
    root.querySelector(".op-follow-filter").addEventListener("change", () => {
      if (root.querySelector(".op-follow-filter").checked) {
        const organization = state.follows.organizations[state.follows.organizations.length - 1];
        if (!organization) { root.querySelector(".op-follow-filter").checked = false; BR.toast("Follow an organisation from a bid detail first", "info"); return; }
        root.querySelector("[name=q]").value = organization;
        state.page = 1; void refresh();
      } else draw();
    });
    root.querySelectorAll("[data-page]").forEach(button => button.addEventListener("click", () => {
      state.page = Math.max(1, state.page + (button.dataset.page === "next" ? 1 : -1)); void refresh();
    }));
    root.querySelector(".op-grid").addEventListener("click", event => {
      const save = event.target.closest("[data-save]"); if (save) { event.stopPropagation(); void toggleSave(save.dataset.save); return; }
      const card = event.target.closest("[data-open]"); if (card) BR.go("opportunity", { id: card.dataset.open });
    });
    root.querySelector(".op-grid").addEventListener("keydown", event => {
      if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-open]")) { event.preventDefault(); BR.go("opportunity", { id: event.target.dataset.open }); }
    });
    await refresh();
    state.autoRefresh = setInterval(() => { if (document.body.contains(root)) void refresh(true); }, 5 * 60 * 1000);
  }

  BR.register("opportunities", { title: "Opportunities", icon: "briefcase-business", render });
})();

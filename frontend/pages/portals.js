/* Other portals: latest tenders on CPPP, Central eTenders and state NIC portals, read live by TinyFish Fetch. Discovery only. */
(function () {
  const esc = (s) => BR.esc(s);
  const I = (n) => `<i data-lucide="${n}"></i>`;
  const S = { key: null, itOnly: false, portals: [], data: {}, busy: false };

  const secs = (ms) => (ms == null ? "—" : (ms / 1000).toFixed(1) + " s");
  const num = (n) => (n == null ? "—" : Number(n).toLocaleString("en-IN"));
  const dayDiff = (iso) => {
    if (!iso) return null;
    const d = new Date(iso + "T23:59:59"), now = new Date();
    return Math.floor((d - now) / 86400000);
  };
  const fmtDate = (iso) => {
    const d = new Date(iso + "T00:00:00");
    return isNaN(d) ? esc(iso) : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  };
  const ago = (iso) => {
    const t = new Date(iso);
    if (isNaN(t)) return "";
    const m = Math.round((Date.now() - t) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return m + " min ago";
    const h = Math.round(m / 60);
    return h < 24 ? h + " h ago" : t.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  };

  function banner() {
    return `<div class="pp-banner">${I("info")}<p><b>Read live by TinyFish Fetch.</b> Discovery only: CPPP tender documents sit behind a captcha, so eligibility is checked on GeM bids.</p></div>`;
  }

  function chips() {
    return S.portals.map((p) => {
      const l = p.last;
      const sub = l ? `${num(l.tenders)} tenders · ${ago(l.fetched_at)}` : "not read yet";
      return `<button class="pp-chip ${p.key === S.key ? "on" : ""}" data-key="${esc(p.key)}" aria-pressed="${p.key === S.key}">
        <span class="pp-chip-ico">${I(p.key === "cppp" || p.key === "etenders" ? "landmark" : "map-pin")}</span>
        <span><b>${esc(p.name)}</b><small>${esc(sub)}</small></span></button>`;
    }).join("");
  }

  function stats(d) {
    const cards = [
      ["timer", "Fetch time", secs(d.ms), d.cached ? "at the last live read" : "this live read"],
      ["file-text", "Characters read", num(d.raw_chars), "markdown from TinyFish"],
      ["list", "Latest tenders", num(d.total), "on the portal home page"],
      ["cpu", "IT hardware", num(d.it_count), "keyword match on title or reference"],
    ];
    return `<div class="pp-stats">${cards.map(([ic, l, v, s]) => `<div class="pp-stat"><span class="pp-stat-ico">${I(ic)}</span><span><small>${l}</small><b>${v}</b><em>${s}</em></span></div>`).join("")}</div>`;
  }

  function closing(t) {
    if (!t.closing) return `<span class="pp-muted">${esc(t.closing_text || "—")}</span>`;
    const n = dayDiff(t.closing);
    const cls = n < 0 ? "past" : n <= 3 ? "soon" : "ok";
    const lbl = n < 0 ? "closed" : n === 0 ? "closes today" : n === 1 ? "1 day left" : `${n} days left`;
    return `<span class="pp-date">${fmtDate(t.closing)}</span><span class="pp-left ${cls}">${I(n < 0 ? "lock" : "hourglass")}${lbl}</span>`;
  }

  function table(d, portal) {
    const rows = d.tenders || [];
    if (!rows.length) {
      const msg = S.itOnly
        ? `None of the ${num(d.total)} latest tenders on ${esc(portal.name)} matches an IT-hardware keyword. Portal home pages list only the newest tenders, and most rows come without a title.`
        : `${esc(portal.name)} returned no tender rows this time.`;
      return `<div class="empty pp-empty">${I(S.itOnly ? "filter-x" : "inbox")}<b>${S.itOnly ? "No IT-hardware tenders right now" : "No tenders listed"}</b><span>${msg}</span>
        ${S.itOnly ? `<button class="btn btn-ghost btn-sm" data-act="all">${I("list")}Show all ${num(d.total)}</button>` : ""}</div>`;
    }
    const hasOrg = rows.some((t) => t.organisation);
    return `<div class="pp-tablewrap"><table class="tbl pp-tbl">
      <thead><tr><th>Tender</th><th>Reference</th>${hasOrg ? "<th>Organisation</th>" : ""}<th>Closing</th><th class="pp-r">Source</th></tr></thead>
      <tbody>${rows.map((t) => `<tr>
        <td data-label="Tender">${t.title ? `<b class="pp-title">${esc(t.title)}</b>` : `<span class="pp-notitle" title="The portal's home page lists this tender without a title">${I("eye-off")}No title on home page</span>`}</td>
        <td data-label="Reference"><code class="pp-ref">${esc(t.reference || "—")}</code></td>
        ${hasOrg ? `<td data-label="Organisation">${esc(t.organisation || "—")}</td>` : ""}
        <td data-label="Closing"><span class="pp-close">${closing(t)}</span></td>
        <td data-label="Source" class="pp-r"><a class="btn btn-ghost btn-sm" href="${esc(t.link || d.url)}" target="_blank" rel="noopener">${I("external-link")}${t.link ? "Open" : "Portal"}</a></td>
      </tr>`).join("")}</tbody></table></div>
      <p class="pp-foot">${I("search")}Find a tender on the portal with its reference number ("Search with ID/Title/Reference no"). The portal home page shows the newest tenders only.</p>`;
  }

  function panel(root) {
    const portal = S.portals.find((p) => p.key === S.key);
    const box = root.querySelector(".pp-panel");
    if (!portal) { box.innerHTML = ""; return; }
    const d = S.data[S.key];
    const head = `<div class="card-h pp-head">
        <div class="pp-ttl"><h3>${I("building")}${esc(portal.full_name)}</h3><a class="pp-url mono" href="${esc(portal.url)}" target="_blank" rel="noopener">${esc(portal.url.replace(/^https?:\/\//, ""))}${I("arrow-up-right")}</a></div>
        <div class="pp-actions">
          <label class="pp-toggle"><input type="checkbox" ${S.itOnly ? "checked" : ""} data-act="it"><span class="pp-sw"></span>IT hardware only</label>
          <button class="btn btn-primary btn-sm" data-act="read" ${S.busy ? "disabled" : ""}>${I(S.busy ? "loader" : "scan-text")}${S.busy ? "Reading…" : "Read with TinyFish Fetch"}</button>
        </div></div>`;
    let body;
    if (S.busy && !d) {
      body = `<div class="card-b"><div class="pp-reading">${I("loader")}<span>TinyFish Fetch is reading ${esc(portal.name)}. Usually 3–7 s.</span></div>
        ${'<div class="skeleton" style="height:42px;margin-top:10px"></div>'.repeat(5)}</div>`;
    } else if (!d) {
      body = `<div class="card-b"><div class="empty pp-empty">${I("scan-text")}<b>Not read yet</b><span>Read the latest tenders on ${esc(portal.name)} live with TinyFish Fetch.</span></div></div>`;
    } else if (d.error && !d.tenders) {
      body = `<div class="card-b"><div class="empty pp-empty">${I("plug-zap")}<b>Could not read ${esc(portal.name)}</b><span class="mono">${esc(d.error)}</span>
        <button class="btn btn-ghost btn-sm" data-act="read">${I("rotate-ccw")}Try again</button></div></div>`;
    } else {
      const stale = d.error ? `<div class="pp-stale">${I("history")}<span>A fresh read failed (<code>${esc(d.error)}</code>). Showing the last read from ${esc(ago(d.fetched_at))}.</span></div>` : "";
      const read = `<div class="pp-readat">${I(d.cached ? "database" : "radio")}${d.cached ? "Cached read" : "Live read"} · ${esc(ago(d.fetched_at))} · TinyFish Fetch</div>`;
      body = `<div class="card-b pp-body">${stale}${stats(d)}${read}${table(d, portal)}</div>`;
    }
    box.innerHTML = `<section class="card">${head}${body}</section>`;
    BR.icons();
  }

  async function load(root, refresh) {
    const key = S.key;
    S.busy = true;
    panel(root);
    try {
      const d = await BR.api.get(`/api/portals/${encodeURIComponent(key)}?it_only=${S.itOnly ? 1 : 0}${refresh ? "&refresh=1" : ""}`);
      S.data[key] = d;
      const p = S.portals.find((x) => x.key === key);
      if (p && d.tenders && !d.error) p.last = { fetched_at: d.fetched_at, ms: d.ms, raw_chars: d.raw_chars, tenders: d.total };
      if (refresh && !d.error && BR.toast) BR.toast(`Read ${p ? p.name : key} in ${secs(d.ms)} · ${num(d.raw_chars)} characters`, "scan-text");
    } catch (err) {
      S.data[key] = { error: err.message || String(err) };
    }
    S.busy = false;
    if (!root.isConnected) return;
    root.querySelector(".pp-chips").innerHTML = chips();
    if (S.key === key) panel(root);
    BR.icons();
  }

  async function render(el, params) {
    el.innerHTML = `<div class="pg-portals">${banner()}<div class="pp-chips">${'<div class="skeleton" style="height:52px;width:180px"></div>'.repeat(4)}</div><div class="pp-panel"></div></div>`;
    BR.icons();
    const root = el.firstElementChild;
    try { S.portals = (await BR.api.get("/api/portals")) || []; }
    catch (err) {
      root.querySelector(".pp-chips").outerHTML = `<div class="empty pp-empty">${I("plug-zap")}<b>Could not load the portal list</b><span class="mono">${esc(err.message || err)}</span><button class="btn btn-ghost btn-sm" data-retry>Try again</button></div>`;
      root.querySelector("[data-retry]").onclick = () => render(el, params);
      return BR.icons();
    }
    if (!root.isConnected) return;
    const wanted = params && params.portal;
    S.key = S.portals.some((p) => p.key === wanted) ? wanted : (S.key && S.portals.some((p) => p.key === S.key) ? S.key : (S.portals[0] || {}).key);
    root.querySelector(".pp-chips").innerHTML = chips();
    panel(root);

    root.addEventListener("click", (e) => {
      const chip = e.target.closest(".pp-chip");
      if (chip && !S.busy) {
        S.key = chip.dataset.key;
        root.querySelector(".pp-chips").innerHTML = chips();
        const p = S.portals.find((x) => x.key === S.key);
        if (!S.data[S.key] && p && p.last) load(root, false); else panel(root);
        BR.icons();
        return;
      }
      const act = e.target.closest("[data-act]");
      if (!act || S.busy) return;
      if (act.dataset.act === "read") load(root, true);
      if (act.dataset.act === "all") { S.itOnly = false; load(root, false); }
    });
    root.addEventListener("change", (e) => {
      if (e.target.matches('[data-act="it"]')) { S.itOnly = e.target.checked; if (S.data[S.key] && !S.data[S.key].error) load(root, false); else panel(root); }
    });

    const cur = S.portals.find((p) => p.key === S.key);
    if (cur && cur.last && !S.data[S.key]) load(root, false);  // show the last read straight away
  }

  BR.register("portals", { title: "Other portals", icon: "building", render });
})();

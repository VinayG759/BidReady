/* Audit log: every assessment, filterable by verdict, each one reproducible. */
(function () {
  const FILTERS = [
    { key: "all", label: "All", color: "var(--accent)" },
    { key: "eligible", label: "Eligible", color: "var(--pass)" },
    { key: "eligible_relaxation", label: "With relaxation", color: "var(--relax)" },
    { key: "manual_review", label: "Needs review", color: "var(--unres)" },
    { key: "not_eligible", label: "Not eligible", color: "var(--fail)" },
  ];
  const COLOR = Object.fromEntries(FILTERS.map((f) => [f.key, f.color]));

  const esc = (s) => BR.esc(s);
  const stamp = (iso) => {
    const t = new Date(iso);
    if (isNaN(t)) return { d: esc(iso || "—"), t: "" };
    return {
      d: t.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }),
      t: t.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false }) + " IST",
    };
  };
  const pill = (v) => (BR.pill ? BR.pill(v) : `<span class="pill">${esc(v)}</span>`);
  const meter = (cov, v) => {
    let s = "";
    for (let i = 0; i < 4; i++) s += `<span class="${i < cov ? "on" : ""}"></span>`;
    return `<span class="pa-meter" style="--mc:${COLOR[v] || "var(--accent)"}" title="${cov} of 4 criteria resolved from source"><span class="pa-segs">${s}</span><b>${cov}/4</b></span>`;
  };

  function formula() {
    const part = (icon, title, sub) => `<div class="pa-term"><span class="pa-tico"><i data-lucide="${icon}"></i></span><span><b>${title}</b><small>${sub}</small></span></div>`;
    const op = (icon) => `<span class="pa-op"><i data-lucide="${icon}"></i></span>`;
    return `<section class="card pa-formula" aria-label="Same inputs plus same source snapshot plus same rule version equals same verdict">
      ${part("building-2", "Same inputs", "supplier profile at check time")}${op("plus")}
      ${part("camera", "Same source snapshot", "tender text, hashed and stored")}${op("plus")}
      ${part("book-marked", "Same rule version", "deterministic rules, no LLM")}${op("equal")}
      <div class="pa-term pa-result"><span class="pa-tico"><i data-lucide="stamp"></i></span><span><b>Same verdict</b><small>every time, for any auditor</small></span></div>
    </section>`;
  }

  async function render(el, params) {
    el.innerHTML = `<div class="pa-root">${formula()}<div class="card"><div class="card-b" style="display:grid;gap:10px">${'<div class="skeleton" style="height:44px"></div>'.repeat(6)}</div></div></div>`;
    BR.icons();
    const root = el.firstElementChild;
    let rows;
    try { rows = (await BR.api.get("/api/assessments")) || []; }
    catch (err) {
      if (!root.isConnected) return;
      root.lastElementChild.outerHTML = `<div class="empty"><i data-lucide="plug-zap"></i><b>Could not load the audit log</b><span class="mono">${esc(err.message || err)}</span><button class="btn btn-ghost btn-sm" data-retry>Try again</button></div>`;
      root.querySelector("[data-retry]").onclick = () => render(el, params);
      return BR.icons();
    }
    if (!root.isConnected) return;

    let filter = FILTERS.some((f) => f.key === (params && params.verdict)) ? params.verdict : "all";
    let q = "";
    const counts = { all: rows.length };
    rows.forEach((r) => { counts[r.verdict] = (counts[r.verdict] || 0) + 1; });
    const versions = [...new Set(rows.map((r) => r.rule_version).filter(Boolean))];

    root.lastElementChild.outerHTML = `<section class="card pa-log">
      <div class="card-h pa-head">
        <div class="pa-chips" role="tablist" aria-label="Filter by verdict">${FILTERS.map((f) => `
          <button class="pa-chip" role="tab" data-f="${f.key}" style="--fc:${f.color}"><span class="pa-dot"></span>${f.label}<b>${counts[f.key] || 0}</b></button>`).join("")}</div>
        <label class="pa-search"><i data-lucide="search"></i><input class="inp" type="search" placeholder="Search tender, bid or supplier" aria-label="Search the audit log"></label>
      </div>
      <div class="pa-scroll">
        <table class="tbl pa-tbl">
          <thead><tr><th>Verdict</th><th>Tender</th><th>Supplier</th><th>Coverage</th><th>Rule version</th><th>Run at</th><th class="pa-go"><span class="pa-sr">Open</span></th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <div class="pa-foot"><span><i data-lucide="lock-keyhole"></i>Append-only. Entries are never edited, only re-run.</span><span class="mono">${versions.length ? "rules " + versions.map(esc).join(", ") : ""}</span></div>
    </section>`;

    const tbody = root.querySelector("tbody");
    function draw() {
      root.querySelectorAll(".pa-chip").forEach((c) => { const on = c.dataset.f === filter; c.classList.toggle("on", on); c.setAttribute("aria-selected", on); });
      const needle = q.trim().toLowerCase();
      const list = rows.filter((r) => (filter === "all" || r.verdict === filter) &&
        (!needle || [r.id, r.tender_bid, r.tender_title, r.profile_name].join(" ").toLowerCase().includes(needle)));
      tbody.innerHTML = list.length ? list.map((r) => {
        const s = stamp(r.created_at);
        return `<tr class="click" tabindex="0" data-id="${esc(r.id)}" style="--rc:${COLOR[r.verdict] || "var(--line-2)"}">
          <td class="pa-v">${pill(r.verdict)}</td>
          <td class="pa-t"><b>${esc(r.tender_title)}</b><small class="mono">${esc(r.tender_bid)} · ${esc(r.id)}</small></td>
          <td class="pa-p">${esc(r.profile_name)}</td>
          <td>${meter(Number(r.coverage) || 0, r.verdict)}</td>
          <td><span class="pa-rv mono"><i data-lucide="book-marked"></i>${esc(r.rule_version)}</span></td>
          <td class="pa-ts"><span>${s.d}</span><small class="mono">${s.t}</small></td>
          <td class="pa-go"><i data-lucide="chevron-right"></i></td>
        </tr>`;
      }).join("") : `<tr><td colspan="7"><div class="empty"><i data-lucide="filter-x"></i>No assessments match this filter.</div></td></tr>`;
      BR.icons();
    }

    root.addEventListener("click", (e) => {
      const c = e.target.closest(".pa-chip");
      if (c) { filter = c.dataset.f; return draw(); }
      const tr = e.target.closest("tr[data-id]");
      if (tr) BR.go("report", { id: tr.dataset.id });
    });
    root.addEventListener("keydown", (e) => {
      const tr = e.target.closest("tr[data-id]");
      if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); BR.go("report", { id: tr.dataset.id }); }
    });
    root.querySelector(".pa-search input").addEventListener("input", (e) => { q = e.target.value; draw(); });
    draw();
  }

  BR.register("audit", { title: "Audit log", icon: "scroll-text", render });
})();

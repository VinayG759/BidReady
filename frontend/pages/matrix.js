/* W3 · Consultant view: one tender checked against every client profile. */
(function () {
  "use strict";
  const E = (s) => BR.esc(s);
  const L = (n) => BR.lakh(n);
  const D = (s) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || ""); if (!m) return s || "—";
    return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }); };
  const I = (n, c) => `<i data-lucide="${n}"${c ? ` class="${c}"` : ""}></i>`;
  const TONE = { met: "pass", relaxed: "relax", not_met: "fail", unresolved: "unres",
    eligible: "pass", eligible_relaxation: "relax", not_eligible: "fail", manual_review: "unres" };
  const CRIT = [["turnover", "Turnover", "indian-rupee"], ["experience", "Experience", "briefcase"], ["oem", "OEM letter", "award"], ["emd", "EMD", "landmark"]];
  const ROLE = { reseller: "Reseller", manufacturer: "Manufacturer", service_provider: "Service provider" };
  const VORDER = ["eligible", "eligible_relaxation", "manual_review", "not_eligible"];
  let M = null;

  function cell(s) {
    const st = BR.status(s), tone = TONE[s] || "unres";
    return `<span class="mx-cell t-${tone}" title="${E(st.label)}">${I(st.icon)}<span>${E(st.label)}</span></span>`;
  }

  function tenderChip(t) {
    const on = M.tid === t.id;
    const closes = t.end_date || t.closes || "date unavailable";
    const amount = t.estimated_value ? "₹" + Number(t.estimated_value).toLocaleString("en-IN") : "amount not listed";
    return `<button class="mx-tchip${on ? " on" : ""}" data-id="${E(t.id)}" aria-pressed="${on}">
      <span class="mx-tci">${I(on ? "circle-dot" : "circle")}</span>
      <span class="mx-tct"><b>${E(t.title)}</b><small>${E(t.bid || t.id)} · ${E(amount)} · closes ${E(D(closes))}</small></span></button>`;
  }

  function renderPicker() {
    const host = M.page.querySelector(".mx-pick");
    host.innerHTML = M.tenders.length ? M.tenders.map(tenderChip).join("")
      : `<div class="empty">${I("inbox")}<span>No tenders available.</span></div>`;
    BR.icons();
  }

  function renderMatrix(d) {
    const host = M.page.querySelector(".mx-body");
    const rows = (d.rows || []).slice().sort((a, b) => VORDER.indexOf(a.verdict) - VORDER.indexOf(b.verdict) || (b.coverage - a.coverage));
    const can = rows.filter((r) => r.verdict === "eligible" || r.verdict === "eligible_relaxation").length;
    const cnt = (v) => rows.filter((r) => r.verdict === v).length;
    const t = d.tender || {};
    if (!rows.length) { host.innerHTML = `<div class="empty">${I("users")}<span>No client profiles yet. Add one on the Supplier profile page.</span></div>`; BR.icons(); return; }
    host.innerHTML = `
      <section class="mx-sum">
        <div class="mx-big">
          <div class="mx-bign"><b>${can}</b><span>of ${rows.length}</span></div>
          <div><h2>${can === 1 ? "client can bid" : "clients can bid"}</h2>
            <p>${E(t.title || "")}<br><span class="mono">${E(t.bid || "")} · ${E(t.buyer || "")}</span></p></div>
        </div>
        <div class="mx-bar" role="img" aria-label="Verdict split">${VORDER.map((v) => { const n = cnt(v); return n ? `<span class="t-${TONE[v]}" style="flex:${n}"></span>` : ""; }).join("")}</div>
        <div class="mx-counts">${VORDER.map((v) => { const st = BR.status(v);
          return `<div class="mx-cnt t-${TONE[v]}">${I(st.icon)}<b>${cnt(v)}</b><span>${E(st.label)}</span></div>`; }).join("")}</div>
      </section>

      <section class="card mx-grid">
        <div class="mx-row mx-headr"><span>Client</span>${CRIT.map(([, n, ic]) => `<span class="mx-ch">${I(ic)}${n}</span>`).join("")}<span>Verdict</span><span>Gaps to close</span></div>
        ${rows.map((r, i) => `<div class="mx-row t-${TONE[r.verdict] || "unres"}" style="animation-delay:${i * 70}ms">
          <div class="mx-client"><span class="mx-av">${E(String(r.name || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase())}</span>
            <div><b>${E(r.name)}</b><small>${E(ROLE[r.role] || r.role || "")} · ${E(r.coverage)}/4 evidence-checked</small></div></div>
          ${CRIT.map(([k, n]) => `<div class="mx-c" data-l="${n}">${cell(r.criteria && r.criteria[k])}</div>`).join("")}
          <div class="mx-v">${BR.pill(r.verdict)}</div>
          <div class="mx-gaps">${(r.gaps || []).length ? `<ul>${r.gaps.map((g) => `<li>${I("arrow-right")}${E(g)}</li>`).join("")}</ul>` : `<span class="mx-nogap">${I("circle-check")}Nothing to close</span>`}
            <button class="btn btn-ghost btn-sm" data-pid="${E(r.profile_id)}">${I("file-check-2")}Full report</button></div>
        </div>`).join("")}
      </section>`;
    BR.icons();
  }

  function load(tid) {
    M.tid = tid; renderPicker();
    const host = M.page.querySelector(".mx-body"), my = M;
    host.innerHTML = `<div class="skeleton" style="height:130px;border-radius:14px"></div><div class="skeleton" style="height:320px;border-radius:14px;margin-top:16px"></div>`;
    BR.api.get("/api/matrix?tender_id=" + encodeURIComponent("gem-" + tid)).then((d) => { if (M === my) renderMatrix(d); })
      .catch((err) => {
        if (M !== my) return;
        host.innerHTML = `<div class="empty">${I("plug-zap")}<b>Could not build the matrix</b><span class="mono">${E(err.message || err)}</span><button class="btn btn-ghost btn-sm" data-retry>${I("rotate-cw")}Try again</button></div>`;
        BR.icons(); host.querySelector("[data-retry]").addEventListener("click", () => load(tid));
      });
  }

  BR.register("matrix", {
    title: "Consultant view",
    icon: "grid-3x3",
    render(el, params) {
      el.innerHTML = `<div class="pg-mx">
        <header class="mx-head"><div><div class="eyebrow">Consultant view</div><h2>One tender, every client</h2>
          <p>Pick a tender. BidReady runs the same deterministic rules for every supplier profile you manage and shows who can bid and what each one is missing.</p></div></header>
        <section class="card"><div class="card-h"><h3>${I("file-search")}Tender</h3><a class="mx-link" href="#/assess">${I("scan-search")}Single assessment</a></div>
          <div class="card-b"><div class="mx-pick">${'<div class="skeleton" style="height:58px;border-radius:12px"></div>'.repeat(3)}</div></div></section>
        <div class="mx-body"></div>
      </div>`;
      BR.icons();
      const page = el.firstElementChild;
      M = { page, tid: null, tenders: [] };
      const my = M;
      page.querySelector(".mx-pick").addEventListener("click", (e) => {
        const b = e.target.closest(".mx-tchip"); if (b && b.dataset.id !== M.tid) load(b.dataset.id);
      });
      page.querySelector(".mx-body").addEventListener("click", async (e) => {
        const b = e.target.closest("[data-pid]"); if (!b) return;
        b.disabled = true; b.innerHTML = `${I("loader-circle", "mx-spin")}Running…`; BR.icons();
        try {
          const a = await BR.api.post("/api/assess", { tender_id: "gem-" + M.tid, profile_id: b.dataset.pid });
          BR.go("report", { id: a.id });
        } catch (err) {
          b.disabled = false; b.innerHTML = `${I("file-check-2")}Full report`; BR.icons();
          if (BR.toast) BR.toast("Could not run assessment: " + (err.message || err), "triangle-alert");
        }
      });
      BR.api.get("/api/live-tenders?page=1").then((response) => {
        if (M !== my) return;
        M.tenders = response.bids || [];
        const requested = String((params && params.tender) || "").replace(/^gem-/, "");
        const want = requested && M.tenders.some((t) => t.id === requested) ? requested : (M.tenders[0] && M.tenders[0].id);
        if (want) load(want); else renderPicker();
      }).catch((err) => {
        if (M !== my) return;
        page.querySelector(".mx-pick").innerHTML = `<div class="empty">${I("plug-zap")}<b>Tenders not loaded</b><span class="mono">${E(err.message || err)}</span></div>`;
        BR.icons();
      });
    },
  });
})();

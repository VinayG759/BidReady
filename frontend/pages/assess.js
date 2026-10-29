/* W3 · New assessment (find tender → live pipeline → report) and the standalone report page. */
(function () {
  "use strict";

  /* ---------- small helpers (fall back if a shell helper is missing) ---------- */
  const E = (s) => (window.BR && BR.esc ? BR.esc(s == null ? "" : String(s)) :
    String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])));
  const L = (n) => (n == null || n === "" ? "—" : (BR.lakh ? BR.lakh(n) : "₹" + Math.round(n * 10) / 10 + " L"));
  const icons = () => { try { BR.icons(); } catch (e) { if (window.lucide) lucide.createIcons(); } };
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const reduced = () => window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const D = (s) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || ""); if (!m) return s || "—";
    return new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }); };
  const I = (name, cls) => `<i data-lucide="${name}"${cls ? ` class="${cls}"` : ""}></i>`;

  const TONE = { met: "pass", relaxed: "relax", not_met: "fail", unresolved: "unres",
    eligible: "pass", eligible_relaxation: "relax", not_eligible: "fail", manual_review: "unres" };
  const LABEL = { met: "Met", relaxed: "Met via relaxation", not_met: "Not met", unresolved: "Unresolved",
    eligible: "Eligible", eligible_relaxation: "Eligible with relaxation", not_eligible: "Not eligible", manual_review: "Needs manual review" };
  const TICON = { pass: "circle-check", relax: "badge-check", fail: "circle-x", unres: "circle-help" };
  function meta(s) {
    const tone = TONE[s] || "unres";
    let label = LABEL[s] || String(s || "unknown");
    try { const r = BR.status && BR.status(s); if (r && r.label) label = r.label; } catch (e) { /* keep local label */ }
    return { tone, label, icon: TICON[tone] };
  }

  const CICON = { turnover: "indian-rupee", experience: "briefcase", oem: "award", emd: "landmark" };
  const SICON = { search: "search", fetch: "download", extract: "scan-text", validate: "shield-check", evaluate: "scale", report: "file-check-2" };
  const OWNER = { "TinyFish": "tf", "Our code": "oc", "UI": "ui" };
  const VERD = {
    eligible: { h: "All four criteria are met and evidenced.", d: "Proceed to detailed bid preparation. Technical compliance still needs a manual read." },
    eligible_relaxation: { h: "Eligible through a tender-specific relaxation.", d: "Keep the relaxation proof ready. Buyers check the certificate at bid opening." },
    not_eligible: { h: "A decisive requirement fails with no evidenced relaxation.", d: "Bidding now is unlikely to clear technical evaluation. What is short is listed below." },
    manual_review: { h: "Some evidence is missing, ambiguous or unverifiable.", d: "Nothing fails outright, but the open items below need a person to read the clause." },
  };
  const CHECKS = [["quote_found", "Quote found"], ["number_match", "Numbers match"], ["heading_match", "Heading match"]];

  function fmtDate(s) {
    if (!s) return "";
    const d = new Date(s);
    return isNaN(d) ? E(s) : d.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  function errBox(msg, retryLabel) {
    return `<div class="empty as-err">${I("triangle-alert")}<div><b>Something went wrong</b><span>${E(msg)}</span></div>${retryLabel ? `<button class="btn btn-ghost" data-act="retry">${I("rotate-cw")}${E(retryLabel)}</button>` : ""}</div>`;
  }

  /* ---------- quote with highlighted phrase ---------- */
  function quoteHTML(q, hl) {
    q = String(q || "");
    if (!hl) return E(q);
    const i = q.toLowerCase().indexOf(String(hl).toLowerCase());
    if (i < 0) return E(q);
    return E(q.slice(0, i)) + "<mark>" + E(q.slice(i, i + hl.length)) + "</mark>" + E(q.slice(i + hl.length));
  }

  /* =====================================================================
     REPORT (shared by #/assess inline and #/report)
     ===================================================================== */
  function critCard(c, i) {
    const m = meta(c.status);
    const cl = c.clause;
    const v = c.validation || {};
    const allOk = cl && CHECKS.every(([k]) => v[k] === true);
    const evid = cl ? `
      <div class="as-evid${allOk ? "" : " bad"}">
        <div class="as-eh"><span>${I("file-text")}${E(cl.heading || "Clause")}</span><span>${E(cl.doc || "")}${cl.page != null ? ` · p. ${E(cl.page)}` : ""}</span></div>
        <q>${quoteHTML(cl.quote, cl.highlight)}</q>
        <div class="as-ef">
          <div class="as-checks">${CHECKS.map(([k, n]) => {
            const val = v[k]; const cls = val === true ? "ok" : val === false ? "no" : "na";
            return `<span class="as-vchk ${cls}">${I(val === true ? "check" : val === false ? "x" : "minus")}${n}</span>`;
          }).join("")}</div>
          ${cl.url ? `<a class="as-src" href="${E(cl.url)}" target="_blank" rel="noopener">Source ${I("external-link")}</a>` : ""}
        </div>
      </div>` : `
      <div class="as-evid bad as-noclause">
        <div class="as-eh"><span>${I("file-x")}No clause extracted</span></div>
        <p>The source did not yield a clause the validator could confirm, so no rule result is issued for this criterion.</p>
      </div>`;
    const docs = (c.docs || []).length ? `<div class="as-docs">${c.docs.map((d) =>
      `<span class="as-dchip ${d.ok ? "ok" : ""}">${I(d.ok ? "file-check" : "file-clock")}${E(d.name)}</span>`).join("")}</div>` : "";
    const next = (c.next_steps || []).length && c.status !== "met" ? `
      <div class="as-next"><h4>${I("route")}What would change this result</h4><ul>${c.next_steps.map((s) => `<li>${E(s)}</li>`).join("")}</ul></div>` : "";
    return `<article class="as-crit t-${m.tone}" id="as-c-${E(c.key)}" style="animation-delay:${i * 90}ms">
      <header><span class="as-cicon">${I(CICON[c.key] || "list-checks")}</span><h3>${E(c.name)}</h3>${BR.pill(c.status)}</header>
      <dl class="as-kv">
        <dt>Required</dt><dd>${E(c.requirement || "—")}</dd>
        <dt>Supplier</dt><dd>${E(c.supplier_fact || "—")} ${BR.evBadge(c.evidence || "declared")}</dd>
        <dt>Rule</dt><dd class="as-rule">${E(c.rule_result || "—")}</dd>
      </dl>
      ${evid}${docs}${next}
    </article>`;
  }

  function reportHTML(a, opts) {
    opts = opts || {};
    const vm = meta(a.verdict);
    const V = VERD[a.verdict] || VERD.manual_review;
    const t = a.tender || {};
    const crits = a.criteria || [];
    const cov = Math.max(0, Math.min(4, +a.coverage || 0));
    const C = 2 * Math.PI * 40;
    const missing = a.missing_docs || [], unres = a.unresolved || [];
    return `<div class="as-report as-print t-${vm.tone}" data-cov="${cov}">
      <div class="as-rtools">
        <div class="as-rmeta">${I("hash")}<span>${E(a.id)}</span><span>${fmtDate(a.created_at)}</span><span>rules ${E(a.rule_version || "")}</span>${a.seconds != null ? `<span>${E(a.seconds)} s</span>` : ""}</div>
        <div class="as-rbtns">
          ${opts.inline ? `<button class="btn btn-ghost" data-act="open">${I("maximize-2")}Open as page</button>` : ""}
          <button class="btn btn-ghost" data-act="matrix">${I("grid-3x3")}All clients</button>
          <button class="btn btn-ghost" data-act="print">${I("printer")}Print / save PDF</button>
          <button class="btn btn-primary" data-act="rerun">${I("user-pen")}Re-run with edited profile</button>
        </div>
      </div>

      <section class="as-verdict">
        <div class="as-stamp">${E(vm.label)}<small>${E(t.bid || "")}</small></div>
        <div class="as-vtext">
          <div class="eyebrow">Eligibility verdict · ${E((a.profile && a.profile.name) || "")}</div>
          <h2>${E(V.h)}</h2><p>${E(V.d)}</p>
          <div class="as-vmeta"><span>${I("file-text")}${E(t.title || "")}</span><span>${I("building-2")}${E(t.buyer || "")}</span>${t.closes ? `<span>${I("calendar-clock")}Closes ${E(D(t.closes))}</span>` : ""}</div>
        </div>
        <div class="as-ring" role="img" aria-label="${cov} of 4 criteria evidence-checked">
          <svg viewBox="0 0 96 96"><circle cx="48" cy="48" r="40" class="trk"/><circle cx="48" cy="48" r="40" class="val" stroke-dasharray="${C}" stroke-dashoffset="${opts.animate ? C : C * (1 - cov / 4)}"/></svg>
          <div class="rl"><b>${cov}/4</b><small>EVIDENCE-<br>CHECKED</small></div>
        </div>
      </section>

      <div class="as-strip">${crits.map((c) => { const m = meta(c.status);
        return `<button class="as-sc t-${m.tone}" data-jump="${E(c.key)}">${I(CICON[c.key] || "list-checks")}<span><b>${E(c.name)}</b><small>${I(m.icon)}${E(m.label)}</small></span></button>`; }).join("")}</div>

      <div class="as-scope">${I("info")}<p><b>Scope.</b> ${E(a.scope_notice || "Pre-screen only. The tender document remains the source of truth.")}</p></div>

      <div class="as-crits">${crits.map(critCard).join("")}</div>

      <div class="as-bottom">
        <section class="card as-list ${missing.length ? "has" : "none"}"><div class="card-h"><h3>${I("folder-open")}Missing documents</h3><span class="as-count">${missing.length}</span></div>
          <div class="card-b">${missing.length ? `<ul>${missing.map((d) => `<li>${I("file-clock")}${E(d)}</li>`).join("")}</ul>` :
            `<p class="as-allgood">${I("circle-check")}Everything needed for these four criteria is on file.</p>`}</div></section>
        <section class="card as-list ${unres.length ? "has" : "none"}"><div class="card-h"><h3>${I("circle-help")}Unresolved conditions</h3><span class="as-count">${unres.length}</span></div>
          <div class="card-b">${unres.length ? `<ul>${unres.map((d) => `<li>${I("message-circle-question")}${E(d)}</li>`).join("")}</ul>` :
            `<p class="as-allgood">${I("circle-check")}No open conditions. Every criterion resolved from evidence.</p>`}</div></section>
        <section class="card as-list as-out"><div class="card-h"><h3>${I("eye-off")}Outside automated checks</h3></div>
          <div class="card-b"><ul><li>${I("cpu")}Technical specifications and model compliance</li><li>${I("truck")}Delivery schedule, warranty and service terms</li><li>${I("scroll-text")}Other certifications named in the bid document</li></ul></div></section>
      </div>
    </div>`;
  }

  /* mount a report into host, wire its buttons */
  function mountReport(host, a, opts) {
    host.innerHTML = reportHTML(a, opts);
    icons();
    const root = host.querySelector(".as-report");
    if (opts && opts.animate) {
      const val = root.querySelector(".as-ring .val");
      const C = 2 * Math.PI * 40, cov = +root.dataset.cov;
      requestAnimationFrame(() => requestAnimationFrame(() => { val.style.strokeDashoffset = C * (1 - cov / 4); }));
    }
    root.addEventListener("click", (e) => {
      const j = e.target.closest("[data-jump]");
      if (j) { const c = root.querySelector("#as-c-" + j.dataset.jump); if (c) { c.scrollIntoView({ behavior: "smooth", block: "start" }); c.classList.remove("as-flash"); void c.offsetWidth; c.classList.add("as-flash"); } return; }
      const b = e.target.closest("[data-act]"); if (!b) return;
      const act = b.dataset.act;
      if (act === "print") window.print();
      else if (act === "rerun") BR.go("profile");
      else if (act === "open") BR.go("report", { id: a.id });
      else if (act === "matrix") BR.go("matrix", { tender: (a.tender && a.tender.id) || "" });
    });
    return root;
  }

  function reportSkeleton() {
    return `<div class="as-report as-skel">
      <div class="skeleton" style="height:150px;border-radius:14px"></div>
      <div class="as-strip">${"<div class=\"skeleton\" style=\"height:58px;border-radius:12px\"></div>".repeat(4)}</div>
      <div class="as-crits">${"<div class=\"skeleton\" style=\"height:300px;border-radius:14px\"></div>".repeat(4)}</div>
    </div>`;
  }

  /* =====================================================================
     #/report?id=
     ===================================================================== */
  BR.register("report", {
    title: "Assessment report",
    icon: "file-check-2",
    render(el, params) {
      const id = params && params.id;
      el.innerHTML = `<div class="pg-assess pg-report"><div class="as-rhost">${reportSkeleton()}</div></div>`;
      icons();
      const page = el.firstElementChild, host = page.querySelector(".as-rhost");
      if (!id) { recentList(host); return; }
      const load = () => {
        host.innerHTML = reportSkeleton();
        BR.api.get("/api/assessments/" + encodeURIComponent(id))
          .then((a) => { if (page.isConnected) mountReport(host, a, { animate: true }); })
          .catch((err) => {
            host.innerHTML = errBox("Could not load assessment " + id + ". " + (err && err.message || ""), "Try again"); icons();
            host.querySelector('[data-act="retry"]').addEventListener("click", load);
          });
      };
      load();
    },
  });

  function recentList(host) {
    host.innerHTML = `<div class="skeleton" style="height:220px;border-radius:14px"></div>`;
    BR.api.get("/api/assessments").then((rows) => {
      if (!rows || !rows.length) {
        host.innerHTML = `<div class="empty">${I("file-search")}<p>No assessments yet. Run one to see a report here.</p></div>`; icons(); return;
      }
      host.innerHTML = `<section class="card"><div class="card-h"><h3>${I("history")}Recent assessments</h3><span class="as-count">${rows.length}</span></div>
        <div class="as-recent">${rows.map((r) => { const m = meta(r.verdict);
          return `<button class="as-rrow t-${m.tone}" data-id="${E(r.id)}">${BR.pill(r.verdict)}
            <span class="as-rt"><b>${E(r.tender_title)}</b><small>${E(r.tender_bid)} · ${E(r.profile_name)}</small></span>
            <span class="as-rc">${E(r.coverage)}/4</span><span class="as-rd">${fmtDate(r.created_at)}</span>${I("chevron-right")}</button>`; }).join("")}</div></section>`;
      icons();
      host.querySelectorAll(".as-rrow").forEach((b) => b.addEventListener("click", () => BR.go("report", { id: b.dataset.id })));
    }).catch((err) => { host.innerHTML = errBox("Could not load assessments. " + (err && err.message || "")); icons(); });
  }

  /* =====================================================================
     #/assess
     ===================================================================== */
  const STEPS = [["Profile", "user-round"], ["Find tender", "search"], ["Pipeline", "workflow"], ["Report", "file-check-2"]];
  let S = null; // per-render state

  function setStep(n) {
    if (!S) return;
    S.page.querySelectorAll(".as-step").forEach((s, i) => {
      s.classList.toggle("on", i + 1 === n); s.classList.toggle("done", i + 1 < n);
    });
  }

  function profileCard(p) {
    const tv = (p.turnover || []).map((t) => +t.value_lakh || 0);
    const avg = tv.length ? tv.reduce((x, y) => x + y, 0) / tv.length : 0;
    const docs = p.documents || [];
    const bad = docs.filter((d) => d.status !== "valid").length;
    const ini = String(p.name || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
    const role = { reseller: "Reseller", manufacturer: "Manufacturer", service_provider: "Service provider" }[p.role] || p.role || "";
    return `<div class="as-pname"><span class="as-avatar">${E(ini)}</span><div><b>${E(p.name)}</b><small>${[p.city, p.entity_type, role].filter(Boolean).map(E).join(" · ")}</small></div></div>
      <div class="as-pstats">
        <div>${I("indian-rupee")}<b>${L(Math.round(avg * 10) / 10)}</b><small>avg turnover</small></div>
        <div>${I("briefcase")}<b>${(p.orders || []).length}</b><small>similar orders</small></div>
        <div>${I("award")}<b>${(p.oem_letters || []).length}</b><small>OEM letters</small></div>
        <div>${I("landmark")}<b>${L(p.emd_funds_lakh)}</b><small>EMD funds</small></div>
      </div>
      <div class="as-ptags">
        <span class="as-tag ${p.udyam_mse ? "on" : ""}">${I(p.udyam_mse ? "check" : "minus")}Udyam MSE</span>
        <span class="as-tag ${p.dpiit ? "on" : ""}">${I(p.dpiit ? "check" : "minus")}DPIIT startup</span>
        ${bad ? `<span class="as-tag warn">${I("file-clock")}${bad} doc${bad > 1 ? "s" : ""} expiring or missing</span>` : `<span class="as-tag on">${I("file-check")}Documents valid</span>`}
      </div>`;
  }

  function loadProfile() {
    if (!S) return;
    const host = S.page.querySelector(".as-prof .card-b");
    host.innerHTML = `<div class="skeleton" style="height:44px;border-radius:10px"></div><div class="skeleton" style="height:96px;border-radius:10px;margin-top:12px"></div>`;
    const my = S;
    BR.api.get("/api/profiles/" + encodeURIComponent(BR.state.profileId)).then((p) => {
      if (S !== my) return;
      S.profile = p; host.innerHTML = profileCard(p); icons(); updateSel();
    }).catch((err) => { if (S !== my) return; host.innerHTML = errBox("Profile not loaded. " + (err && err.message || "")); icons(); });
  }

  function tenderCard(t, i) {
    const docs = t.docs || [];
    return `<button type="button" class="as-tcard${S.tender && S.tender.id === t.id ? " sel" : ""}" data-id="${E(t.id)}" style="animation-delay:${i * 60}ms" aria-pressed="${S.tender && S.tender.id === t.id}">
      <span class="as-ttop"><span class="as-portal">${I("landmark")}${E(t.portal || "Portal")}</span><span class="as-bid">${E(t.bid || t.id)}</span><span class="as-tick">${I("circle-check")}</span></span>
      <span class="as-tt">${E(t.title)}</span>
      <span class="as-buyer">${I("building-2")}${E(t.buyer || "")}</span>
      <span class="as-tmeta">
        <span><small>Value</small><b>${L(t.value_lakh)}</b></span>
        <span><small>EMD</small><b>${L(t.emd_lakh)}</b></span>
        <span><small>Closes</small><b>${E(D(t.closes))}</b></span>
        <span><small>Pages</small><b>${E(t.pages != null ? t.pages : "—")}</b></span>
      </span>
      ${docs.length ? `<span class="as-tdocs">${docs.map((d) => d.text === "image_only"
        ? `<span class="as-dc warn" title="No extractable text: clauses in this file cannot be validated">${I("scan-line")}${E(d.name)} · image-only</span>`
        : `<span class="as-dc">${I("file-text")}${E(d.name)}${d.pages ? ` · ${E(d.pages)} pp` : ""}</span>`).join("")}</span>` : ""}
    </button>`;
  }

  function renderResults() {
    const host = S.page.querySelector(".as-results");
    if (!S.results.length) {
      host.innerHTML = `<div class="empty as-emp">${I("search-x")}<p>No tenders match <b>${E(S.q)}</b>. Try an item, buyer or bid number, or upload the bid PDF.</p></div>`;
    } else host.innerHTML = S.results.map(tenderCard).join("");
    icons();
  }

  function search(q) {
    S.q = q;
    const host = S.page.querySelector(".as-results");
    host.innerHTML = `<div class="skeleton as-tsk"></div>`.repeat(3);
    const my = S, seq = ++S.seq;
    return BR.api.get("/api/tenders?relevant=true&q=" + encodeURIComponent(q || "")).then((rows) => {
      if (S !== my || seq !== S.seq) return;
      S.results = rows || [];
      if (S.uploaded && !S.results.some((t) => t.id === S.uploaded.id)) S.results.unshift(S.uploaded);
      renderResults();
    }).catch((err) => {
      if (S !== my) return;
      host.innerHTML = errBox("Tender search failed. " + (err && err.message || ""), "Retry"); icons();
      host.querySelector('[data-act="retry"]').addEventListener("click", () => search(q));
    });
  }

  function selectTender(t) {
    S.tender = t;
    S.page.querySelectorAll(".as-tcard").forEach((c) => { const on = c.dataset.id === t.id; c.classList.toggle("sel", on); c.setAttribute("aria-pressed", on); });
    updateSel(); setStep(2);
  }

  function updateSel() {
    if (!S) return;
    const bar = S.page.querySelector(".as-selbar"), btn = S.page.querySelector(".as-run");
    const t = S.tender;
    bar.querySelector(".as-seltxt").innerHTML = t
      ? `${I("crosshair")}<span><small>Selected tender</small><b>${E(t.bid || t.id)}</b> · ${E(t.title)}</span>`
      : `${I("mouse-pointer-click")}<span><small>No tender selected</small>Pick a card above or upload a bid PDF.</span>`;
    btn.disabled = !t || !S.profile || S.running;
    bar.classList.toggle("ready", !!t);
    icons();
  }

  function stageTile(s, i) {
    return `<div class="as-pst" data-i="${i}">
      <span class="as-pn">0${i + 1}<span class="as-pstat">${I("circle-dashed")}</span></span>
      <span class="as-pic">${I(SICON[s.key] || "circle")}</span>
      <b>${E(s.name)}</b>
      <span class="as-who ${OWNER[s.owner] || "oc"}">${E(s.owner)}</span>
      <span class="as-ms">${s.ms != null ? E(s.ms) + " ms" : ""}</span>
    </div>`;
  }

  /* colour a finished console line */
  function colorize(line) {
    let h = E(line);
    h = h.replace(/^(\s*)(GET|POST|PUT)\b/, '$1<span class="b">$2</span>')
      .replace(/\b(200|ok|OK|passed)\b/g, '<span class="g">$1</span>')
      .replace(/(✓[^·]*)/g, '<span class="g">$1</span>')
      .replace(/(✗[^·]*)/g, '<span class="r">$1</span>')
      .replace(/\b(warn|WARN|image-only|image_only|unresolved|UNRESOLVED)\b/g, '<span class="y">$1</span>')
      .replace(/\b(MET|ELIGIBLE)\b/g, '<span class="g">$1</span>')
      .replace(/\b(NOT[ _]MET|NOT[ _]ELIGIBLE|FAIL)\b/g, '<span class="r">$1</span>')
      .replace(/\b(RELAXED)\b/g, '<span class="b">$1</span>');
    return h;
  }

  async function typeLine(con, line, budget, ctl) {
    const row = document.createElement("div");
    const ts = new Date().toTimeString().slice(0, 8);
    row.innerHTML = `<span class="t">${ts}</span> <span class="x"></span>`;
    con.appendChild(row);
    const x = row.querySelector(".x");
    const text = String(line);
    if (!ctl.skip && !reduced()) {
      const typeMs = budget * 0.65, frames = Math.max(1, Math.floor(typeMs / 16));
      const step = Math.max(1, Math.ceil(text.length / frames));
      for (let n = 0; n < text.length && !ctl.skip; n += step) {
        x.textContent = text.slice(0, n + step); con.scrollTop = con.scrollHeight;
        await wait(16);
      }
    }
    x.innerHTML = colorize(text); con.scrollTop = con.scrollHeight;
    if (!ctl.skip && !reduced()) await wait(budget * 0.35);
  }

  async function animatePipeline(a, ctl) {
    const card = S.page.querySelector(".as-pipecard");
    const pipe = card.querySelector(".as-pipe"), con = card.querySelector(".as-console"), stat = card.querySelector(".as-pipestat");
    const stages = a.stages || [];
    pipe.innerHTML = stages.map(stageTile).join(""); icons();
    const tiles = [...pipe.children];
    const per = 4600 / Math.max(1, stages.length);
    for (let i = 0; i < stages.length; i++) {
      if (!card.isConnected) return false;
      const s = stages[i], tile = tiles[i];
      tile.classList.add("run");
      stat.innerHTML = `${I("loader-circle", "as-spin")}${E(s.name)}…`; icons();
      const logs = s.logs && s.logs.length ? s.logs : [s.name + " · " + s.status];
      for (const ln of logs) { if (!card.isConnected) return false; await typeLine(con, ln, per / logs.length, ctl); }
      const st = s.status === "ok" ? "ok" : s.status === "fail" ? "fail" : "warn";
      tile.classList.remove("run"); tile.classList.add(st);
      tile.querySelector(".as-pstat").innerHTML = I(st === "ok" ? "circle-check" : st === "fail" ? "circle-x" : "triangle-alert");
      icons();
    }
    const warns = stages.filter((s) => s.status !== "ok").length;
    stat.innerHTML = `${I(warns ? "triangle-alert" : "circle-check")}Complete${warns ? ` · ${warns} warning${warns > 1 ? "s" : ""}` : ""} · ${E(a.seconds != null ? a.seconds + " s" : "")}`;
    stat.classList.toggle("warn", !!warns); stat.classList.add("done");
    card.querySelector(".as-skip").hidden = true;
    icons();
    return true;
  }

  async function run() {
    if (!S || !S.tender || !S.profile || S.running) return;
    const my = S;
    S.running = true; updateSel(); setStep(3);
    const card = S.page.querySelector(".as-pipecard"), rep = S.page.querySelector(".as-reportwrap");
    card.hidden = false; rep.hidden = true; rep.innerHTML = "";
    const con = card.querySelector(".as-console"), stat = card.querySelector(".as-pipestat");
    con.innerHTML = ""; stat.className = "as-pipestat"; card.querySelector(".as-skip").hidden = false;
    card.querySelector(".as-pipe").innerHTML = ["search", "fetch", "extract", "validate", "evaluate", "report"].map((k, i) =>
      stageTile({ key: k, name: k[0].toUpperCase() + k.slice(1), owner: i < 3 ? "TinyFish" : i < 5 ? "Our code" : "UI" }, i)).join("");
    card.querySelector(".as-pst").classList.add("run");
    stat.innerHTML = `${I("loader-circle", "as-spin")}Starting…`; icons();
    card.scrollIntoView({ behavior: "smooth", block: "start" });
    const ctl = { skip: false }; S.ctl = ctl;
    await typeLine(con, `POST /api/assess  tender=${S.tender.id}  profile=${S.profile.id}`, 300, ctl);
    let a;
    try {
      const body = { tender_id: S.tender.id, profile_id: S.profile.id };
      if (String(S.tender.id).startsWith("u-")) body.tender = S.tender; // uploads live only client-side; send the upload response back unchanged
      a = await BR.api.post("/api/assess", body);
    } catch (err) {
      if (S !== my) return;
      S.running = false; updateSel(); setStep(2);
      stat.innerHTML = `${I("circle-x")}Failed`; stat.classList.add("fail");
      con.insertAdjacentHTML("beforeend", `<div><span class="t">${new Date().toTimeString().slice(0, 8)}</span> <span class="r">✗ ${E(err && err.message || "request failed")}</span></div>`);
      card.querySelector(".as-skip").hidden = true; icons();
      return;
    }
    if (S !== my) return;
    const done = await animatePipeline(a, ctl);
    if (!done || S !== my) return;
    S.running = false; S.last = a; updateSel(); setStep(4);
    rep.hidden = false;
    mountReport(rep, a, { inline: true, animate: true });
    setTimeout(() => { if (rep.isConnected) rep.scrollIntoView({ behavior: "smooth", block: "start" }); }, 180);
  }

  /* live web discovery (TinyFish Search): metadata only, never assessable */
  function liveSearch(q) {
    q = q || "GeM laptop tender 2026";
    S.liveDone = true;
    const host = S.page.querySelector(".as-lres"), my = S, seq = ++S.lseq;
    host.innerHTML = `<div class="as-lstat">${I("loader-circle", "as-spin")}Searching the live web for <b>${E(q)}</b>…</div>` + `<div class="skeleton as-lsk"></div>`.repeat(3);
    icons();
    const t0 = performance.now();
    const calm = (msg) => `<div class="empty as-emp">${I("cloud-off")}<p><b>Live search is unavailable right now.</b><br>Demo tenders and PDF upload still work.</p>${msg ? `<small class="as-why" title="${E(msg)}">${E(String(msg).slice(0, 140))}</small>` : ""}</div>`;
    BR.api.get("/api/live-search?q=" + encodeURIComponent(q)).then((r) => {
      if (S !== my || seq !== S.lseq) return;
      if (!r || r.ok === false) { host.innerHTML = calm(r && r.error); icons(); return; }
      const res = r.results || [];
      const secs = ((r.ms != null ? r.ms : performance.now() - t0) / 1000).toFixed(1);
      if (!res.length) { host.innerHTML = `<div class="empty as-emp">${I("search-x")}<p>No live results for <b>${E(q)}</b>.</p></div>`; icons(); return; }
      host.innerHTML = `<div class="as-lstat">${I("zap")}<b>${res.length} result${res.length > 1 ? "s" : ""} in ${secs} s</b><span>· ${E(r.source || "TinyFish Search")}</span></div>
        <div class="as-lgrid">${res.map((x, i) => `<article class="as-lcard" style="animation-delay:${i * 50}ms">
          <div class="as-ltop"><span class="as-lsite">${I("globe")}${E(x.site_name || (x.url || "").replace(/^https?:\/\/([^/]+).*/, "$1"))}</span>${x.date ? `<span class="as-ldate">${I("calendar")}${E(x.date)}</span>` : ""}</div>
          <h4>${E(x.title || "Untitled result")}</h4>
          <p>${E(x.snippet || "")}</p>
          <div class="as-lact">${x.url ? `<a href="${E(x.url)}" target="_blank" rel="noopener">${I("external-link")}Open source</a>` : "<span></span>"}
            <button class="btn btn-ghost" data-act="assess-live">${I("file-up")}Assess this tender</button></div>
        </article>`).join("")}</div>`;
      icons();
    }).catch((err) => {
      if (S !== my || seq !== S.lseq) return;
      host.innerHTML = calm(err && err.message); icons();
    });
  }

  async function upload(file) {
    const box = S.page.querySelector(".as-upres");
    if (!file) return;
    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") {
      box.innerHTML = errBox("That file is not a PDF. Choose the bid document in PDF format."); icons(); return;
    }
    const my = S;
    box.innerHTML = `<div class="as-uping">${I("loader-circle", "as-spin")}<span>Reading <b>${E(file.name)}</b> and extracting clauses…</span></div>`; icons();
    try {
      const t = await BR.api.upload("/api/upload", file);
      if (S !== my) return;
      S.uploaded = t;
      S.results = [t].concat(S.results.filter((x) => x.id !== t.id));
      box.innerHTML = `<div class="as-upok">${I("circle-check")}<span>Extracted <b>${E(t.title || file.name)}</b>. Selected below; clauses not found will show as unresolved.</span></div>`;
      S.tender = t;
      box.insertAdjacentHTML("beforeend", `<div class="as-results as-upcard">${tenderCard(t, 0)}</div>`);
      renderResults(); selectTender(t); icons();
    } catch (err) {
      if (S !== my) return;
      box.innerHTML = errBox("Upload failed. " + (err && err.message || "")); icons();
    }
  }

  BR.register("assess", {
    title: "New assessment",
    icon: "scan-search",
    render(el, params) {
      if (S && S.ctl) S.ctl.skip = true;
      el.innerHTML = `<div class="pg-assess">
        <ol class="as-steps">${STEPS.map(([n, ic], i) => `<li class="as-step${i === 0 ? " on" : ""}"><span class="as-sdot">${I(ic)}<span class="as-snum">${i + 1}</span></span><span>${n}</span></li>`).join("")}</ol>

        <div class="as-top">
          <section class="card as-prof"><div class="card-h"><h3>${I("user-round")}Supplier profile</h3><a class="as-link" href="#/profile">Edit ${I("arrow-up-right")}</a></div><div class="card-b"></div></section>

          <section class="card as-find">
            <div class="card-h"><h3>${I("search")}Find a tender</h3>
              <div class="as-tabs" role="tablist">
                <button role="tab" class="on" data-tab="search" aria-selected="true">${I("database")}<span>Demo tenders</span></button>
                <button role="tab" data-tab="live" aria-selected="false">${I("globe")}<span>Live web · TinyFish</span></button>
                <button role="tab" data-tab="upload" aria-selected="false">${I("file-up")}<span>Upload bid PDF</span></button>
              </div></div>
            <div class="card-b">
              <div data-pane="search">
                <form class="as-search" autocomplete="off">
                  <label class="as-sinp">${I("search")}<input class="inp" name="q" placeholder="Search by item, buyer or bid number" aria-label="Search tenders"></label>
                  <button class="btn btn-primary" type="submit">${I("search")}<span>Search</span></button>
                </form>
                <div class="as-results"></div>
              </div>
              <div data-pane="live" hidden>
                <form class="as-search as-lform" autocomplete="off">
                  <label class="as-sinp">${I("globe")}<input class="inp" name="q" value="GeM laptop tender 2026" aria-label="Search the live web"></label>
                  <button class="btn btn-primary" type="submit">${I("search")}<span>Search web</span></button>
                </form>
                <div class="as-lbanner">${I("info")}<p><b>Live results from TinyFish Search:</b> discovery metadata only, not eligibility evidence. To assess, upload the bid PDF or pick a demo tender.</p></div>
                <div class="as-lres"><div class="empty as-emp">${I("globe")}<p>Search the live web for tender listings.</p></div></div>
              </div>
              <div data-pane="upload" hidden>
                <div class="as-uphint" hidden>${I("download")}<p>Download the bid PDF from the source link, then drop it here.</p></div>
                <label class="as-drop"><input type="file" accept="application/pdf,.pdf" hidden>
                  <span class="as-dropic">${I("file-up")}</span><b>Drop a bid PDF here, or click to choose</b>
                  <small>Turnover, experience, OEM and EMD clauses are extracted from the PDF text. Anything not found stays unresolved, never guessed.</small></label>
                <div class="as-upres"></div>
              </div>
              <div class="as-selbar"><div class="as-seltxt"></div>
                <button class="btn btn-primary as-run" disabled>${I("play")}Run eligibility check</button></div>
            </div>
          </section>
        </div>

        <section class="card as-pipecard" hidden>
          <div class="card-h"><h3>${I("workflow")}Pipeline</h3><div class="as-pipehead"><span class="as-pipestat"></span><button class="btn btn-ghost as-skip">${I("fast-forward")}Skip</button></div></div>
          <div class="card-b"><div class="as-pipe"></div><div class="as-console" aria-live="polite"></div></div>
        </section>

        <div class="as-reportwrap" hidden></div>
      </div>`;

      const page = el.firstElementChild;
      S = { page, tender: null, profile: null, results: [], q: "", seq: 0, lseq: 0, liveDone: false, running: false, uploaded: null, ctl: null };
      icons(); updateSel(); loadProfile();

      const form = page.querySelector(".as-search"), inp = form.querySelector("input");
      let deb;
      form.addEventListener("submit", (e) => { e.preventDefault(); clearTimeout(deb); search(inp.value.trim()); });
      inp.addEventListener("input", () => { clearTimeout(deb); deb = setTimeout(() => search(inp.value.trim()), 280); });

      page.querySelector(".as-results").addEventListener("click", (e) => {
        const c = e.target.closest(".as-tcard"); if (!c || S.running) return;
        const t = S.results.find((x) => x.id === c.dataset.id); if (t) selectTender(t);
      });
      page.querySelector(".as-upres").addEventListener("click", (e) => {
        if (e.target.closest(".as-tcard") && S.uploaded) selectTender(S.uploaded);
      });

      const showTab = (tab) => {
        page.querySelectorAll(".as-tabs button").forEach((x) => { const on = x.dataset.tab === tab; x.classList.toggle("on", on); x.setAttribute("aria-selected", on); });
        page.querySelectorAll("[data-pane]").forEach((p) => { p.hidden = p.dataset.pane !== tab; });
        if (tab === "live" && !S.liveDone) liveSearch(page.querySelector(".as-lform input").value.trim());
      };
      page.querySelectorAll(".as-tabs button").forEach((b) => b.addEventListener("click", () => {
        page.querySelector(".as-uphint").hidden = true; showTab(b.dataset.tab);
      }));
      const lform = page.querySelector(".as-lform");
      lform.addEventListener("submit", (e) => { e.preventDefault(); liveSearch(lform.querySelector("input").value.trim()); });
      page.querySelector(".as-lres").addEventListener("click", (e) => {
        if (!e.target.closest("[data-act='assess-live']")) return;
        showTab("upload");
        const h = page.querySelector(".as-uphint"); h.hidden = false;
        h.classList.remove("as-flash"); void h.offsetWidth; h.classList.add("as-flash");
      });

      const drop = page.querySelector(".as-drop"), file = drop.querySelector("input");
      file.addEventListener("change", () => { upload(file.files[0]); file.value = ""; });
      ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
      ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
      drop.addEventListener("drop", (e) => upload(e.dataTransfer.files[0]));

      page.querySelector(".as-run").addEventListener("click", run);
      page.querySelector(".as-skip").addEventListener("click", () => { if (S.ctl) S.ctl.skip = true; });

      const want = params && params.tender;
      search("").then(() => {
        if (!want || !S || S.page !== page) return;
        const hit = S.results.find((t) => t.id === want);
        if (hit) { selectTender(hit); const c = page.querySelector(`.as-tcard[data-id="${CSS.escape(want)}"]`); if (c) c.scrollIntoView({ block: "nearest" }); }
        else BR.api.get("/api/tenders/" + encodeURIComponent(want)).then((t) => {
          if (S && S.page === page) { S.results.unshift(t); renderResults(); selectTender(t); }
        }).catch(() => BR.toast && BR.toast("Tender " + want + " not found"));
      });
    },
  });

  /* profile switched in the shell: refresh the summary card if this page is showing */
  if (BR.on) BR.on("profile", () => {
    if (S && S.page.isConnected && !S.running) { loadProfile(); }
  });
})();

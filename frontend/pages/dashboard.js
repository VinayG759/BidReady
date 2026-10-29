/* Overview page: KPIs, verdicts by category, top gaps, recent assessments, closing-soon tenders. */
(function () {
  const VERDICT = {
    eligible:            { label: "Eligible",              color: "var(--pass)",  icon: "circle-check" },
    eligible_relaxation: { label: "Eligible (relaxation)", color: "var(--relax)", icon: "badge-check" },
    manual_review:       { label: "Needs review",          color: "var(--unres)", icon: "circle-help" },
    not_eligible:        { label: "Not eligible",          color: "var(--fail)",  icon: "circle-x" },
  };
  const SERIES = [
    { key: "eligible",     label: "Eligible",     color: "var(--pass)" },
    { key: "relaxed",      label: "Relaxation",   color: "var(--relax)" },
    { key: "review",       label: "Needs review", color: "var(--unres)" },
    { key: "not_eligible", label: "Not eligible", color: "var(--fail)" },
  ];

  const esc = (s) => (window.BR && BR.esc ? BR.esc(s) : String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])));
  const lakh = (n) => (BR.lakh ? BR.lakh(n) : "₹" + Number(n || 0).toLocaleString("en-IN") + " L");
  const verdict = (v) => {
    const base = VERDICT[v] || { label: v, color: "var(--muted)", icon: "circle" };
    const s = BR.status ? BR.status(v) : null;
    return { ...base, label: (s && s.cls !== "neutral" && s.label) || base.label, icon: (s && s.cls !== "neutral" && s.icon) || base.icon };
  };
  const num = (n) => Number(n || 0).toLocaleString("en-IN");
  const parseDay = (d) => { const t = new Date(d); return isNaN(t) ? null : t; };
  const shortDay = (d) => { const t = parseDay(d); return t ? t.toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : String(d); };
  const ago = (iso) => {
    const t = parseDay(iso); if (!t) return esc(iso || "");
    const m = Math.round((Date.now() - t) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return m + " min ago";
    if (m < 1440) return Math.round(m / 60) + " h ago";
    return t.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  };

  function meter(cov) {
    let s = "";
    for (let i = 0; i < 4; i++) s += `<span class="${i < cov ? "on" : ""}"></span>`;
    return `<span class="pd-meter" title="${cov} of 4 criteria resolved">${s}</span>`;
  }

  function skeleton() {
    return `
      <div class="pd-kpis">${'<div class="card pd-kpi"><div class="skeleton" style="height:64px"></div></div>'.repeat(5)}</div>
      <div class="pd-grid">
        <div class="card pd-chart"><div class="card-b"><div class="skeleton" style="height:240px"></div></div></div>
        <div class="card pd-gaps"><div class="card-b"><div class="skeleton" style="height:240px"></div></div></div>
        <div class="card pd-recent"><div class="card-b"><div class="skeleton" style="height:260px"></div></div></div>
        <div class="card pd-soon"><div class="card-b"><div class="skeleton" style="height:260px"></div></div></div>
      </div>`;
  }

  function kpis(st) {
    const total = st.assessments || 0;
    const pct = (n) => (total ? Math.round((n / total) * 100) + "% of checks" : "no checks yet");
    const items = [
      { icon: "clipboard-check", label: "Assessments run", value: num(total), sub: num(st.open_tenders != null ? st.open_tenders : st.tenders_tracked) + " open GeM bids in library", color: "var(--accent)" },
      { icon: "circle-check", label: "Eligible", value: num(st.eligible), sub: st.eligible_relaxation ? "+" + num(st.eligible_relaxation) + " with relaxation" : pct(st.eligible), color: "var(--pass)" },
      { icon: "circle-help", label: "Needs review", value: num(st.manual_review), sub: pct(st.manual_review), color: "var(--unres)" },
      { icon: "circle-x", label: "Not eligible", value: num(st.not_eligible), sub: pct(st.not_eligible), color: "var(--fail)" },
      { icon: "timer", label: "First read of a bid", value: (Number(st.first_read_seconds) || Number(st.avg_seconds) || 0).toFixed(0) + "s",
        sub: "re-checks " + (Number(st.avg_seconds) || 0).toFixed(1) + "s · vs ~2 days by hand", color: "var(--relax)" },
    ];
    return `<div class="pd-kpis">${items.map((k) => `
      <div class="card kpi pd-kpi" style="--kc:${k.color}">
        <span class="pd-kicon"><i data-lucide="${k.icon}"></i></span>
        <div class="pd-ktext">
          <div class="pd-kval">${k.value}</div>
          <div class="pd-klabel">${k.label}</div>
          <div class="pd-ksub">${esc(k.sub)}</div>
        </div>
      </div>`).join("")}</div>`;
  }

  function drawChart(host, days) {
    const W = Math.max(280, Math.floor(host.clientWidth));
    const H = W < 480 ? 190 : 230;
    const pad = { l: 30, r: 8, t: 10, b: 26 };
    const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
    const totals = days.map((d) => SERIES.reduce((a, s) => a + (Number(d[s.key]) || 0), 0));
    const max = Math.max(1, ...totals);
    const step = max <= 4 ? 1 : Math.ceil(max / 4);
    const top = Math.ceil(max / step) * step;
    const slot = iw / Math.max(1, days.length);
    const bw = Math.min(42, slot * 0.62);
    const y = (v) => pad.t + ih - (v / top) * ih;
    let g = "";
    for (let v = 0; v <= top; v += step) {
      g += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(v)}" y2="${y(v)}" class="pd-gl"/>`;
      g += `<text x="${pad.l - 8}" y="${y(v) + 4}" text-anchor="end" class="pd-ax">${v}</text>`;
    }
    const labelEvery = Math.ceil(days.length / Math.max(1, Math.floor(iw / 52)));
    days.forEach((d, i) => {
      const x = pad.l + slot * i + (slot - bw) / 2;
      let acc = 0;
      const tip = [shortDay(d.day)].concat(SERIES.map((s) => `${s.label}: ${Number(d[s.key]) || 0}`)).join("\n");
      g += `<g class="pd-bar"><title>${esc(tip)}</title>`;
      g += `<rect x="${x - 2}" y="${pad.t}" width="${bw + 4}" height="${ih}" class="pd-hit"/>`;
      SERIES.forEach((s, si) => {
        const v = Number(d[s.key]) || 0;
        if (!v) return;
        const y1 = y(acc + v), h = y(acc) - y1;
        const last = SERIES.slice(si + 1).every((n) => !(Number(d[n.key]) || 0));
        g += `<rect x="${x}" y="${y1}" width="${bw}" height="${Math.max(0, h - 1.5)}" rx="${last ? 4 : 1.5}" fill="${s.color}"/>`;
        acc += v;
      });
      if (totals[i]) g += `<text x="${x + bw / 2}" y="${y(totals[i]) - 5}" text-anchor="middle" class="pd-tot">${totals[i]}</text>`;
      g += `</g>`;
      if (i % labelEvery === 0) g += `<text x="${x + bw / 2}" y="${H - 8}" text-anchor="middle" class="pd-ax">${esc(shortDay(d.day))}</text>`;
    });
    host.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Verdicts per category, stacked">${g}</svg>`;
  }

  /* Verdicts grouped by tender category (real bids are screened in one sweep, so days would be one bar). */
  const series = (st) => (st.verdicts_by_category || []).map((c) => Object.assign({ day: c.category }, c));

  function chartCard(st) {
    const days = series(st);
    const sums = SERIES.map((s) => days.reduce((a, d) => a + (Number(d[s.key]) || 0), 0));
    return `
      <section class="card pd-chart">
        <div class="card-h"><h3><i data-lucide="chart-column-stacked"></i> Verdicts by category</h3><span class="pd-hint">${num(st.assessments)} checks on real GeM bids</span></div>
        <div class="card-b">
          <div class="pd-legend">${SERIES.map((s, i) => `<span><i style="background:${s.color}"></i>${s.label} <b>${sums[i]}</b></span>`).join("")}</div>
          ${days.length ? '<div class="pd-svg"></div>' : '<div class="empty">No assessments yet. Run a check to see verdicts here.</div>'}
        </div>
      </section>`;
  }

  function gapsCard(st) {
    const gaps = (st.top_gaps || []).slice(0, 6);
    const max = Math.max(1, ...gaps.map((g) => g.count || 0));
    return `
      <section class="card pd-gaps">
        <div class="card-h"><h3><i data-lucide="target"></i> Top eligibility gaps</h3><span class="pd-hint">why bids fail</span></div>
        <div class="card-b">
          ${gaps.length ? `<ol class="pd-gaplist">${gaps.map((g, i) => `
            <li>
              <div class="pd-gaprow"><span class="pd-gapn">${i + 1}</span><span class="pd-gapname">${esc(g.gap)}</span><b>${g.count}</b></div>
              <div class="pd-gapbar"><span style="width:${Math.max(4, (g.count / max) * 100)}%"></span></div>
            </li>`).join("")}</ol>` : '<div class="empty">No gaps recorded yet.</div>'}
        </div>
      </section>`;
  }

  function recentCard(rows) {
    const list = (rows || []).slice(0, 5);
    return `
      <section class="card pd-recent">
        <div class="card-h"><h3><i data-lucide="history"></i> Recent assessments</h3>
          <button class="btn btn-ghost pd-sm" data-go="audit">Audit log <i data-lucide="arrow-right"></i></button></div>
        <div class="pd-rlist">
          ${list.length ? list.map((a) => {
            const v = verdict(a.verdict);
            return `<button class="pd-ritem" data-report="${esc(a.id)}" style="--vc:${v.color}">
              <span class="pd-rico"><i data-lucide="${v.icon}"></i></span>
              <span class="pd-rmain">
                <span class="pd-rtitle">${esc(a.tender_title)}</span>
                <span class="pd-rmeta"><span class="mono">${esc(a.tender_bid)}</span><span>${esc(a.profile_name)}</span><span>${ago(a.created_at)}</span></span>
              </span>
              <span class="pd-rside"><span class="pd-rverdict">${esc(v.label)}</span>${meter(a.coverage || 0)}</span>
              <i data-lucide="chevron-right" class="pd-chev"></i>
            </button>`;
          }).join("") : '<div class="card-b"><div class="empty">No assessments yet.</div></div>'}
        </div>
      </section>`;
  }

  function soonCard(tenders) {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const list = (tenders || [])
      .map((t) => ({ t, d: parseDay(t.closes) }))
      .sort((a, b) => (a.d ? a.d.getTime() : Infinity) - (b.d ? b.d.getTime() : Infinity))
      .filter((x) => !x.d || x.d >= today)
      .slice(0, 4);
    return `
      <section class="card pd-soon">
        <div class="card-h"><h3><i data-lucide="calendar-clock"></i> Closing soon</h3><span class="pd-hint">${(tenders || []).length} tracked</span></div>
        <div class="card-b">
          ${list.length ? `<div class="pd-tgrid">${list.map(({ t, d }) => {
            const left = d ? Math.round((d - today) / 86400000) : null;
            const urgent = left !== null && left <= 7;
            return `<article class="pd-tender">
              <div class="pd-ttop">
                <span class="pd-days ${urgent ? "urgent" : ""}"><b>${left === null ? "?" : left}</b><small>${left === 1 ? "day" : "days"}</small></span>
                <div class="pd-thead">
                  <span class="pd-tbid mono">${esc(t.bid)}</span>
                  <h4>${esc(t.title)}</h4>
                  <span class="pd-tbuyer"><i data-lucide="landmark"></i>${esc(t.buyer)}</span>
                </div>
              </div>
              <div class="pd-tfacts">
                <span><i data-lucide="indian-rupee"></i>${lakh(t.value_lakh)}</span>
                <span><i data-lucide="wallet"></i>EMD ${t.emd_lakh === 0 ? "none" : lakh(t.emd_lakh)}</span>
                <span><i data-lucide="file-text"></i>${t.pages || 0} pp</span>
              </div>
              <button class="btn btn-primary pd-sm" data-assess="${esc(t.id)}"><i data-lucide="scan-search"></i> Check eligibility</button>
            </article>`;
          }).join("")}</div>` : '<div class="empty">No open tenders closing soon.</div>'}
        </div>
      </section>`;
  }

  async function render(el) {
    el.innerHTML = `<div class="pd-root">${skeleton()}</div>`;
    const root = el.firstElementChild;
    const [st, rows, tenders] = await Promise.all([
      BR.api.get("/api/stats").catch((e) => ({ __err: e })),
      BR.api.get("/api/assessments").catch(() => []),
      BR.api.get("/api/tenders").catch(() => []),
    ]);
    if (!root.isConnected) return;
    if (st.__err) {
      root.innerHTML = `<div class="empty"><i data-lucide="plug-zap"></i><br>Could not load overview: ${esc(st.__err.message || st.__err)}<br><button class="btn btn-ghost pd-sm" data-retry>Try again</button></div>`;
      root.querySelector("[data-retry]").onclick = () => render(el);
      BR.icons();
      return;
    }
    root.innerHTML = kpis(st) + `<div class="pd-grid">${chartCard(st)}${gapsCard(st)}${recentCard(rows)}${soonCard(tenders)}</div>`;

    const svgHost = root.querySelector(".pd-svg");
    if (svgHost) {
      const days = series(st);
      drawChart(svgHost, days);
      if (window.ResizeObserver) {
        let w = svgHost.clientWidth;
        const ro = new ResizeObserver(() => {
          if (!svgHost.isConnected) return ro.disconnect();
          if (Math.abs(svgHost.clientWidth - w) > 4) { w = svgHost.clientWidth; drawChart(svgHost, days); }
        });
        ro.observe(svgHost);
      }
    }
    root.addEventListener("click", (e) => {
      const r = e.target.closest("[data-report]");
      if (r) return BR.go("report", { id: r.dataset.report });
      const a = e.target.closest("[data-assess]");
      if (a) return BR.go("assess", { tender: a.dataset.assess });
      const g = e.target.closest("[data-go]");
      if (g) return BR.go(g.dataset.go);
    });
    BR.icons();
  }

  BR.register("dashboard", { title: "Overview", icon: "layout-dashboard", render });
})();

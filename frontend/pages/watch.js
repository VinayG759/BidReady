/* Bid watch: TinyFish Monitor checks the web daily for corrigenda, extensions or cancellations of watched bids. */
(function () {
  "use strict";
  const esc = (s) => BR.esc(s);
  const I = (n, c) => `<i data-lucide="${n}"${c ? ` class="${c}"` : ""}></i>`;
  const when = (iso) => {
    const t = new Date(iso);
    if (!iso || isNaN(t)) return "—";
    return t.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }) + " IST";
  };
  /* BR.api has no DELETE; same base-URL rule as assets/api.js */
  async function del(path) {
    if (BR.api.del) return BR.api.del(path);
    const res = await fetch((location.port === "8000" ? "" : "http://localhost:8000") + path, { method: "DELETE" });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error((data && data.detail) || "HTTP " + res.status);
    return data;
  }
  const sched = (c) => (c === "0 3 * * *" ? "Daily" : "Scheduled") + ` <span class="mono">${esc(c || "")}</span>`;

  /* Called from the report ("Watch this bid"). Billed: one baseline run now, then one per day. */
  BR.watchBid = async (tenderId) => {
    try {
      const w = await BR.api.post("/api/watch", { tender_id: tenderId });
      BR.toast(w.already_watching ? `Already watching ${w.bid}` : `Watching ${w.bid}: TinyFish checks it daily`, "bell-ring");
      return w;
    } catch (err) {
      BR.toast("Could not start the watch: " + (err.message || err), "triangle-alert");
      return { error: String(err.message || err) };
    }
  };

  function how() {
    const step = (icon, b, s) => `<div class="wt-step"><span class="wt-sico">${I(icon)}</span><span><b>${b}</b><small>${s}</small></span></div>`;
    const arrow = `<span class="wt-arrow">${I("chevron-right")}</span>`;
    return `<section class="card wt-how" aria-label="How bid watch works">
      ${step("bell-ring", "Watch a bid", "one TinyFish Monitor per bid")}${arrow}
      ${step("search", "Daily web search", "bid number + corrigendum, extension, cancelled")}${arrow}
      ${step("triangle-alert", "Flag a change", "only results naming this exact bid")}
    </section>`;
  }

  function resultRow(r, last) {
    const hit = (last.change_positions || []).includes(r.position);
    const isNew = (last.new_result_positions || []).includes(r.position);
    return `<li class="wt-res${hit ? " hit" : ""}">
      <span class="wt-site">${I(hit ? "triangle-alert" : "globe")}${esc(r.site_name || "")}${r.date ? ` · ${esc(r.date)}` : ""}${isNew ? '<span class="wt-new">new</span>' : ""}</span>
      <a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title || r.url)}${I("external-link")}</a>
      ${r.snippet ? `<p>${esc(r.snippet)}</p>` : ""}
    </li>`;
  }

  function card(w) {
    const last = w.last_run || {};
    const results = last.results || [];
    const pill = w.change_detected
      ? `<span class="pill unresolved">${I("triangle-alert")}Change detected</span>`
      : `<span class="pill neutral">${I("check")}No change</span>`;
    const active = (w.status || "active") === "active";
    return `<article class="card wt-card${w.change_detected ? " changed" : ""}" data-id="${esc(w.monitor_id)}">
      <div class="wt-top">
        <span class="wt-bell">${I(w.change_detected ? "bell-dot" : "bell-ring")}</span>
        <div class="wt-tt"><span class="mono wt-bid">${esc(w.bid)}</span><b>${esc(w.title)}</b><small>${esc(w.buyer || "")}</small></div>
        ${pill}
      </div>
      <div class="wt-meta">
        <span>${I("calendar-clock")}${sched(w.schedule)}</span>
        <span>${I("clock")}Last run ${esc(when(last.at || w.last_run_at))}</span>
        <span>${I("list")}${results.length} result${results.length === 1 ? "" : "s"}</span>
        <span class="wt-st ${active ? "on" : ""}"><span class="dot"></span>${esc(w.status || "active")}</span>
        ${w.live_error ? `<span class="wt-warn" title="${esc(w.live_error)}">${I("cloud-off")}status not refreshed</span>` : ""}
      </div>
      <div class="wt-q">${I("search")}<span class="mono">${esc(w.query)}</span></div>
      ${results.length ? `<ul class="wt-results">${results.map((r) => resultRow(r, last)).join("")}</ul>`
        : `<div class="empty wt-none">${I("search-x")}<span>The last run found no web results for this bid yet.</span></div>`}
      <div class="wt-actions">
        <button class="btn btn-ghost btn-sm" data-ask="run">${I("refresh-cw")}Run now</button>
        <button class="btn btn-ghost btn-sm" data-ask="stop">${I("bell-off")}Stop watching</button>
      </div>
      <div class="wt-confirm" hidden></div>
    </article>`;
  }

  const ASK = {
    run: { icon: "wallet", text: "Run a check now? Each run is billed to the TinyFish wallet.", ok: "Run check", okIcon: "refresh-cw" },
    stop: { icon: "bell-off", text: "Stop watching? This deletes the TinyFish monitor; its history is not kept here.", ok: "Stop watching", okIcon: "trash-2" },
  };

  async function render(el) {
    el.innerHTML = `<div class="wt-root">${how()}<div class="wt-add"></div><div class="wt-list">${'<div class="skeleton" style="height:180px;border-radius:14px"></div>'.repeat(2)}</div></div>`;
    BR.icons();
    const root = el.firstElementChild, list = root.querySelector(".wt-list");
    let watches = [];

    const paint = () => {
      if (!root.isConnected) return;
      list.innerHTML = watches.length ? watches.map(card).join("")
        : `<div class="empty wt-empty">${I("bell-ring")}<b>No bids watched yet</b><span>TinyFish Monitor checks the web daily for corrigenda, extensions or cancellations of the bids you watch.</span></div>`;
      BR.icons();
    };

    try { watches = ((await BR.api.get("/api/watch")) || {}).watches || []; }
    catch (err) {
      if (!root.isConnected) return;
      list.innerHTML = `<div class="empty">${I("plug-zap")}<b>Could not load watched bids</b><span class="mono">${esc(err.message || err)}</span><button class="btn btn-ghost btn-sm" data-retry>${I("rotate-cw")}Try again</button></div>`;
      list.querySelector("[data-retry]").onclick = () => render(el);
      return BR.icons();
    }
    paint();
    addForm(root, watches, (w) => { if (!watches.some((x) => x.monitor_id === w.monitor_id)) watches.unshift(w); paint(); });

    // refresh live status quietly (GET is not billed)
    watches.forEach((w) => BR.api.get("/api/watch/" + encodeURIComponent(w.monitor_id)).then((fresh) => {
      const i = watches.findIndex((x) => x.monitor_id === fresh.monitor_id);
      if (i >= 0) { watches[i] = fresh; paint(); }
    }).catch(() => {}));

    list.addEventListener("click", async (e) => {
      const c = e.target.closest(".wt-card"); if (!c) return;
      const id = c.dataset.id, box = c.querySelector(".wt-confirm");
      const ask = e.target.closest("[data-ask]");
      if (ask) {
        const a = ASK[ask.dataset.ask];
        box.hidden = false;
        box.innerHTML = `${I(a.icon)}<span>${a.text}</span><div><button class="btn btn-ghost btn-sm" data-no>Cancel</button><button class="btn btn-primary btn-sm" data-yes="${ask.dataset.ask}">${I(a.okIcon)}${a.ok}</button></div>`;
        BR.icons(); return;
      }
      if (e.target.closest("[data-no]")) { box.hidden = true; return; }
      const yes = e.target.closest("[data-yes]"); if (!yes) return;
      box.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      yes.innerHTML = `${I("loader-circle", "wt-spin")}Working…`; BR.icons();
      try {
        if (yes.dataset.yes === "run") {
          const w = await BR.api.post("/api/watch/" + encodeURIComponent(id) + "/run");
          watches = watches.map((x) => (x.monitor_id === id ? w : x));
          BR.toast(w.change_detected ? "Change detected on " + w.bid : "Checked: no change", w.change_detected ? "triangle-alert" : "circle-check");
        } else {
          await del("/api/watch/" + encodeURIComponent(id));
          watches = watches.filter((x) => x.monitor_id !== id);
          BR.toast("Stopped watching", "bell-off");
        }
        paint();
      } catch (err) {
        box.innerHTML = `${I("circle-help")}<span>${esc(err.message || err)}</span><div><button class="btn btn-ghost btn-sm" data-no>Close</button></div>`;
        BR.icons();
      }
    });
  }

  /* Pick a library bid to watch (billed once now, then daily). */
  function addForm(root, watches, onAdded) {
    const host = root.querySelector(".wt-add");
    BR.api.get("/api/tenders?q=").then((ts) => {
      if (!root.isConnected) return;
      const open = (ts || []).filter((t) => t.status !== "closed");
      if (!open.length) return;
      host.innerHTML = `<section class="card"><div class="card-b wt-form">
        <label class="wt-sel"><span class="lbl">Watch a bid</span>
          <select class="inp">${open.map((t) => `<option value="${esc(t.id)}">${esc(t.bid)} · ${esc((t.title || "").slice(0, 70))}</option>`).join("")}</select></label>
        <button class="btn btn-primary" data-watch>${I("bell-plus")}Watch</button>
        <small class="wt-bill">${I("wallet")}Billed: one baseline search now, then one per day.</small>
      </div></section>`;
      BR.icons();
      const btn = host.querySelector("[data-watch]");
      btn.onclick = async () => {
        btn.disabled = true; btn.innerHTML = `${I("loader-circle", "wt-spin")}Starting…`; BR.icons();
        const w = await BR.watchBid(host.querySelector("select").value);
        btn.disabled = false; btn.innerHTML = `${I("bell-plus")}Watch`; BR.icons();
        if (w && !w.error) onAdded(w);
      };
    }).catch(() => {});
  }

  BR.register("watch", { title: "Bid watch", icon: "bell-ring", render });
})();

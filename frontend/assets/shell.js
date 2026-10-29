/* BidReady app shell: page registry, hash router, shared helpers. Pages call BR.register(name, {title, icon, render}). */
(function(){
  "use strict";
  const BR = window.BR = window.BR || {};
  const pages = {};
  const listeners = {};
  const $ = s => document.querySelector(s);

  BR.esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  BR.lakh = n => n == null || isNaN(n) ? "—" : "₹" + (Math.round(n * 10) / 10).toLocaleString("en-IN") + " L";
  BR.icons = () => { if (window.lucide) lucide.createIcons({ attrs: { "stroke-width": 2 } }); };

  const STATUS = {
    met:                 { label: "Met",                     cls: "met",                 icon: "circle-check" },
    relaxed:             { label: "Met via relaxation",      cls: "relaxed",             icon: "badge-check" },
    not_met:             { label: "Not met",                 cls: "not_met",             icon: "circle-x" },
    unresolved:          { label: "Unresolved",              cls: "unresolved",          icon: "circle-help" },
    eligible:            { label: "Eligible",                cls: "eligible",            icon: "shield-check" },
    eligible_relaxation: { label: "Eligible with relaxation",cls: "eligible_relaxation", icon: "badge-check" },
    not_eligible:        { label: "Not eligible",            cls: "not_eligible",        icon: "shield-x" },
    manual_review:       { label: "Needs manual review",     cls: "manual_review",       icon: "shield-question" },
    declared:            { label: "Declared",                cls: "declared",            icon: "pencil-line" },
    document:            { label: "Document attached",       cls: "document",            icon: "paperclip" },
    verified:            { label: "Verified",                cls: "verified",            icon: "shield-check" }
  };
  BR.status = s => STATUS[s] || { label: s || "—", cls: "neutral", icon: "circle" };
  BR.pill = s => { const t = BR.status(s); return `<span class="pill ${t.cls}"><i data-lucide="${t.icon}"></i>${BR.esc(t.label)}</span>`; };
  BR.evBadge = s => { const t = BR.status(s); return `<span class="ev ${t.cls}"><i data-lucide="${t.icon}"></i>${BR.esc(t.label)}</span>`; };

  BR.on = (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); };
  BR.emit = (ev, v) => (listeners[ev] || []).forEach(fn => { try { fn(v); } catch (e) { console.error(e); } });

  let saved = null;
  try { saved = localStorage.getItem("br.profile"); } catch (e) {}
  BR.state = { profileId: saved || "p-northstar" };
  BR.setProfile = id => {
    BR.state.profileId = id;
    try { localStorage.setItem("br.profile", id); } catch (e) {}
    refreshProfileChip();
    BR.emit("profile", id);
  };

  BR.toast = (msg, icon) => {
    const t = $("#toast");
    t.innerHTML = `<i data-lucide="${icon || "circle-check"}"></i><span>${BR.esc(msg)}</span>`;
    BR.icons(); t.classList.add("show");
    clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 2200);
  };

  BR.register = (name, def) => { pages[name] = def; if (BR._ready) renderNav(); };

  BR.go = (name, params) => {
    const q = params ? "?" + new URLSearchParams(params).toString() : "";
    location.hash = "#/" + name + q;
  };

  function NAV(){
    const supplier = BR.state.account && BR.state.account.account_type === "supplier";
    return supplier
      ? [["Workspace", ["dashboard", "opportunities", "assess"]], ["Records", ["profile", "audit", "account"]]]
      : [["Discover", ["opportunities"]], ["Account", ["account"]]];
  }
  function renderNav(){
    $("#nav").innerHTML = NAV().map(([label, names]) => {
      const links = names.filter(n => pages[n]).map(n =>
        `<a href="#/${n}" data-r="${n}"><i data-lucide="${pages[n].icon}"></i>${BR.esc(pages[n].title)}</a>`).join("");
      return links ? `<div class="nav-label">${label}</div>${links}` : "";
    }).join("");
    markNav(); BR.icons();
  }
  function markNav(){
    const cur = parse().name;
    const navName = cur === "report" ? "assess" : cur;
    document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("on", a.dataset.r === navName));
  }
  function parse(){
    const h = location.hash.replace(/^#\/?/, "");
    const [name, qs] = h.split("?");
    return { name: name || "dashboard", params: Object.fromEntries(new URLSearchParams(qs || "")) };
  }
  function route(){
    const { name, params } = parse();
    const seeker = BR.state.account && BR.state.account.account_type === "seeker";
    if (seeker && !["opportunities", "account"].includes(name)) { BR.go("opportunities"); return; }
    if (!seeker && BR.state.account && !["dashboard", "opportunities", "assess", "profile", "audit", "account", "report"].includes(name)) { BR.go("dashboard"); return; }
    const page = pages[name] || pages[seeker ? "opportunities" : "dashboard"];
    $("#shell").classList.remove("open");
    const view = $("#view");
    if (!page) { view.innerHTML = `<div class="empty"><i data-lucide="loader"></i>Loading…</div>`; BR.icons(); return; }
    $("#pageTitle").innerHTML = `<i data-lucide="${page.icon}"></i>${BR.esc(page.title)}`;
    document.title = page.title + " · BidReady";
    view.innerHTML = ""; view.className = "view pg-" + name;
    void view.offsetWidth; view.style.animation = "";
    markNav();
    try { const r = page.render(view, params); if (r && r.catch) r.catch(err => fail(view, err)); }
    catch (err) { fail(view, err); }
    BR.icons(); window.scrollTo(0, 0);
  }
  function fail(view, err){
    console.error(err);
    view.insertAdjacentHTML("beforeend", `<div class="empty"><i data-lucide="plug-zap"></i><b>Couldn't load this view</b><span class="mono">${BR.esc(err.message || err)}</span><span>Is the backend running on port 8000?</span></div>`);
    BR.icons();
  }

  async function refreshProfileChip(){
    try {
      const account = BR.state.account || (await BR.api.get("/api/account")).account;
      BR.state.account = account;
      const name = account.company_name || account.name || "My account";
      const type = account.account_type === "supplier" ? "Supplier" : "Tender seeker";
      $("#profChip").href = "#/account";
      $("#profChip").innerHTML = `<span class="av">${BR.esc(name[0] || "?")}</span><div><b>${BR.esc(name)}</b><small>${type} · ${BR.esc((account.sectors || []).length + " sectors")}</small></div>`;
    } catch (e) {
      $("#profChip").innerHTML = `<span class="av">?</span><div><b>Account</b><small>Choose sectors</small></div>`;
    }
  }
  async function health(){
    const h = $("#health");
    try { const r = await BR.api.get("/api/health"); h.className = "health ok"; h.innerHTML = `<span class="dot"></span>API online · rules ${BR.esc(r.rule_version)}`; }
    catch (e) { h.className = "health bad"; h.innerHTML = `<span class="dot"></span>API offline`; }
  }

  let started = false;
  function startApp(){
    if (started) { renderNav(); route(); void refreshProfileChip(); return; }
    if (!BR.auth || !BR.auth.signedIn || !BR.state.account) return;
    started = true;
    BR._ready = true;
    $("#menuBtn").addEventListener("click", () => $("#shell").classList.toggle("open"));
    $("#scrim").addEventListener("click", () => $("#shell").classList.remove("open"));
    window.addEventListener("hashchange", route);
    renderNav(); route(); refreshProfileChip(); health();
    setInterval(health, 15000);
  }
  BR.startApp = startApp;
  BR.refreshApp = () => { if (started) { renderNav(); route(); void refreshProfileChip(); } };
  document.addEventListener("DOMContentLoaded", () => {
    BR.authReady.then(() => { if (BR.auth && BR.auth.signedIn && BR.state.account) startApp(); });
  });
})();

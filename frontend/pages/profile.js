/* Supplier profile editor. Evidence levels are never edited directly: changing a
   document-backed or verified fact turns it back into a declaration. */
(function () {
  const EVIDENCE = {
    declared: { label: "Declared", icon: "pen-line", note: "Stated by the supplier. Not checked." },
    document: { label: "Document", icon: "file-text", note: "Backed by an uploaded document." },
    verified: { label: "Verified", icon: "shield-check", note: "Checked against the issuing source." },
  };
  const ROLES = [
    { key: "reseller", label: "Reseller", icon: "store" },
    { key: "manufacturer", label: "Manufacturer", icon: "factory" },
    { key: "service_provider", label: "Service provider", icon: "wrench" },
  ];
  const DOCSTATUS = {
    valid: { label: "Valid", icon: "file-check-2", color: "var(--pass)" },
    expiring: { label: "Expiring", icon: "clock", color: "var(--unres)" },
    missing: { label: "Missing", icon: "file-x-2", color: "var(--fail)" },
  };
  // Editable list sections: fields shown per row, and a blank declared row for "Add".
  const LISTS = {
    orders: {
      title: "Similar orders", icon: "receipt", add: "Add order",
      cols: [
        { k: "buyer", label: "Buyer", type: "text", w: "26%" },
        { k: "item", label: "Item / scope", type: "text", w: "30%" },
        { k: "value_lakh", label: "Value (₹ L)", type: "number", w: "14%" },
        { k: "date", label: "Order date", type: "date", w: "16%" },
      ],
      blank: () => ({ buyer: "", item: "", value_lakh: 0, date: "", evidence: "declared" }),
    },
    oem_letters: {
      title: "OEM authorisation letters", icon: "award", add: "Add letter",
      cols: [
        { k: "brand", label: "OEM brand", type: "text", w: "24%" },
        { k: "scope", label: "Scope", type: "text", w: "32%" },
        { k: "valid_until", label: "Valid until", type: "date", w: "18%" },
      ],
      blank: () => ({ brand: "", scope: "", valid_until: "", evidence: "declared" }),
    },
  };

  const esc = (s) => (window.BR && BR.esc ? BR.esc(s) : String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])));
  const lakh = (n) => (BR.lakh ? BR.lakh(n) : "₹" + Number(n || 0).toLocaleString("en-IN") + " L");
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const initials = (n) => String(n || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  const daysTo = (d) => { const t = new Date(d); if (isNaN(t)) return null; const n = new Date(); n.setHours(0, 0, 0, 0); return Math.round((t - n) / 86400000); };
  const fmtDate = (d) => { const t = new Date(d); return isNaN(t) ? (d || "—") : t.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }); };

  function evBadge(ev, changed) {
    const k = ev in EVIDENCE ? ev : "declared";
    const e = EVIDENCE[k], s = BR.status ? BR.status(k) : {};
    return `<span class="ev ${k} pp-ev${changed ? " pp-ev-changed" : ""}" title="${esc(changed ? "You edited this value, so it is now only declared." : e.note)}"><i data-lucide="${s.icon || e.icon}"></i>${changed ? "Declared (edited)" : e.label}</span>`;
  }

  // view state lives on the module so the profile change listener can reach it
  let S = null;

  function evCounts(p) {
    const c = { declared: 0, document: 0, verified: 0 };
    [p.turnover, p.orders, p.oem_letters].forEach((arr) => (arr || []).forEach((r) => { c[r.evidence in c ? r.evidence : "declared"]++; }));
    return c;
  }

  function switcher() {
    return `<div class="pp-switch" role="tablist" aria-label="Supplier profiles">${S.profiles.map((p) => {
      const role = ROLES.find((r) => r.key === p.role) || ROLES[0];
      return `<button class="pp-pchip${p.id === S.p.id ? " on" : ""}" role="tab" aria-selected="${p.id === S.p.id}" data-pid="${esc(p.id)}">
        <span class="pp-av">${esc(initials(p.name))}</span>
        <span class="pp-pmeta"><b>${esc(p.name)}</b><small><i data-lucide="${role.icon}"></i>${esc(role.label)}${p.city ? " · " + esc(p.city) : ""}</small></span>
      </button>`;
    }).join("")}</div>`;
  }

  function legend() {
    const c = evCounts(S.p), total = c.declared + c.document + c.verified || 1;
    return `<section class="card pp-legend">
      <div class="pp-lhead">
        <span class="pp-licon"><i data-lucide="layers"></i></span>
        <div><b>Three evidence levels, never merged</b><small>Editing a document-backed or verified fact turns it back into a declaration.</small></div>
      </div>
      <div class="pp-lbar" aria-hidden="true">${["verified", "document", "declared"].map((k) => c[k] ? `<span class="pp-lb-${k}" style="flex:${c[k]}"></span>` : "").join("")}</div>
      <div class="pp-lkeys">${["verified", "document", "declared"].map((k) => `<div class="pp-lkey">${evBadge(k)}<span><b>${c[k]}</b> facts ·${Math.round((c[k] / total) * 100)}%</span><small>${EVIDENCE[k].note}</small></div>`).join("")}</div>
    </section>`;
  }

  function identity() {
    const p = S.p;
    const proof = p.identity || {};
    const address = proof.registered_address || {};
    const integrityLabel = p.integrity_status === "sample_data" ? "Fictional demo supplier profile"
      : p.integrity_status === "pending_review" ? "Documents submitted · pending review"
      : p.integrity_status === "verified" ? "Business identity reviewed" : "Business identity incomplete";
    return `<section class="card pp-identity">
      <div class="card-h"><h3><i data-lucide="contact"></i> Identity</h3></div>
      <div class="card-b">
        <div class="pp-integrity ${p.integrity_status === "verified" ? "is-verified" : ""}"><b>${esc(integrityLabel)}</b><span>Uploaded documents are evidence for review; this status is not an automatic government verification.</span>
          ${proof.business_pan_masked ? `<small>PAN ${esc(proof.business_pan_masked)} · ${esc(address.street || "")}${address.city ? ", " + esc(address.city) : ""}${address.state ? ", " + esc(address.state) : ""}${address.pincode ? " " + esc(address.pincode) : ""}</small>` : ""}
        </div>
        <div class="pp-fields">
          <label class="pp-f pp-wide"><span>Legal name · locked to submitted evidence</span><input class="inp" data-f="name" value="${esc((proof.legal_name || p.name))}" readonly></label>
          <label class="pp-f"><span>GSTIN · submitted</span><input class="inp mono" data-f="gstin" value="${esc(proof.gstin || p.gstin)}" maxlength="15" spellcheck="false" readonly></label>
          <label class="pp-f"><span>Registered city</span><input class="inp" data-f="city" value="${esc(address.city || p.city)}" readonly></label>
          <label class="pp-f pp-wide"><span>Entity type · submitted</span><input class="inp" data-f="entity_type" value="${esc(proof.entity_type || p.entity_type)}" readonly></label>
        </div>
        <div class="pp-rolehead"><span>Role in this bid</span><span class="pp-why"><i data-lucide="info"></i>Role decides whether MSE EMD exemption applies</span></div>
        <div class="pp-roles" role="radiogroup" aria-label="Role">${ROLES.map((r) => `
          <button class="pp-role${p.role === r.key ? " on" : ""}" role="radio" aria-checked="${p.role === r.key}" data-role="${r.key}">
            <i data-lucide="${r.icon}"></i><span>${r.label}</span>
          </button>`).join("")}</div>
      </div>
    </section>`;
  }

  function recognitions() {
    const p = S.p;
    const row = (k, icon, title, sub) => `
      <label class="pp-tog">
        <span class="pp-togicon${p[k] ? " on" : ""}"><i data-lucide="${icon}"></i></span>
        <span class="pp-togtext"><b>${title}</b><small>${sub}</small></span>
        <input type="checkbox" data-t="${k}"${p[k] ? " checked" : ""}>
      </label>`;
    return `<section class="card pp-recog">
      <div class="card-h"><h3><i data-lucide="badge-check"></i> Recognitions</h3></div>
      <div class="card-b pp-togs">
        ${row("udyam_mse", "building", "Udyam MSE", "EMD exemption and turnover relaxations, if role qualifies")}
        ${row("dpiit", "rocket", "DPIIT startup", "Prior turnover and experience relaxations")}
        ${unlocks()}
      </div>
    </section>`;
  }

  // What the current role + recognitions unlock, so the role rule is visible before a check runs.
  function unlocks() {
    const p = S.p;
    const items = [
      p.udyam_mse && p.role !== "reseller" ? ["ok", "EMD exemption applies", "MSE that makes or services the goods"]
        : p.udyam_mse ? ["no", "No EMD exemption", "Resellers are excluded even with Udyam"] : ["off", "No EMD exemption", "Needs Udyam MSE registration"],
      p.udyam_mse || p.dpiit ? ["ok", "Turnover / experience relaxation", p.dpiit ? "DPIIT startup" : "Udyam MSE, where the tender allows"]
        : ["off", "No relaxations", "Full criteria apply"],
    ];
    const ic = { ok: "circle-check", no: "circle-x", off: "circle-minus" };
    return `<div class="pp-unlock"><span class="pp-unlock-h">What this unlocks</span>${items.map(([s, t, d]) =>
      `<div class="pp-ul pp-ul-${s}"><i data-lucide="${ic[s]}"></i><span><b>${t}</b><small>${d}</small></span></div>`).join("")}</div>`;
  }

  function emd() {
    const f = Number(S.p.emd_funds_lakh) || 0;
    const ts = (S.tenders || []).filter((t) => t.emd_lakh != null);
    const covered = ts.filter((t) => Number(t.emd_lakh) <= f).length;
    const maxEmd = Math.max(f, ...ts.map((t) => Number(t.emd_lakh) || 0), 1);
    return `<section class="card pp-emd">
      <div class="card-h"><h3><i data-lucide="wallet"></i> EMD funds</h3></div>
      <div class="card-b">
        <div class="pp-emdbig">${lakh(f)}<small>available for bid security</small></div>
        <div class="pp-emdbars" aria-hidden="true">${ts.slice(0, 12).map((t) => {
          const e = Number(t.emd_lakh) || 0;
          return `<span class="${e <= f ? "ok" : ""}" style="height:${Math.max(8, (e / maxEmd) * 100)}%" title="${esc(t.bid)}: EMD ${esc(lakh(e))}"></span>`;
        }).join("")}<i style="bottom:${(f / maxEmd) * 100}%"></i></div>
        <div class="pp-emdcap">${ts.length ? `Your EMD funds cover <b>${covered} of ${ts.length}</b> live bids with published EMD amounts` : "EMD amounts are checked from each live GeM bid document."}</div>
        <label class="pp-f"><span>Funds (₹ lakh)</span><input class="inp" type="number" min="0" step="0.5" data-f="emd_funds_lakh" value="${f}"></label>
      </div>
    </section>`;
  }

  function turnover() {
    const rows = S.p.turnover || [];
    const max = Math.max(1, ...rows.map((r) => Number(r.value_lakh) || 0));
    return `<section class="card pp-turn">
      <div class="card-h"><h3><i data-lucide="trending-up"></i> Annual turnover</h3><span class="pp-hint">per financial year</span></div>
      <div class="card-b">
        <div class="pp-spark" aria-hidden="true">${rows.map((r) => `
          <div class="pp-sp"><span class="pp-sp-v">${lakh(r.value_lakh)}</span><span class="pp-sp-bar pp-lb-${r.evidence in EVIDENCE ? r.evidence : "declared"}" style="height:${Math.max(6, ((Number(r.value_lakh) || 0) / max) * 100)}%"></span><span class="pp-sp-fy">${esc(r.fy)}</span></div>`).join("")}</div>
        <div class="pp-trows">${rows.map((r, i) => `
          <div class="pp-trow">
            <span class="pp-fy mono">${esc(r.fy)}</span>
            <label class="pp-money"><span>₹</span><input class="inp" type="number" min="0" step="1" data-list="turnover" data-i="${i}" data-k="value_lakh" value="${Number(r.value_lakh) || 0}" aria-label="${esc(r.fy)} turnover in lakh"><span>L</span></label>
            ${evBadge(r.evidence, S.changed.has("turnover:" + i))}
          </div>`).join("") || '<div class="empty">No turnover declared.</div>'}</div>
      </div>
    </section>`;
  }

  function listCard(key) {
    const L = LISTS[key];
    const rows = S.p[key] || [];
    const isOem = key === "oem_letters";
    return `<section class="card pp-list pp-${key}">
      <div class="card-h"><h3><i data-lucide="${L.icon}"></i> ${L.title}</h3>
        <button class="btn btn-ghost pp-sm" data-add="${key}"><i data-lucide="plus"></i> ${L.add}</button></div>
      <div class="pp-scroll">
        <table class="tbl pp-tbl">
          <thead><tr>${L.cols.map((c) => `<th style="width:${c.w}">${c.label}</th>`).join("")}${isOem ? "<th>Validity</th>" : ""}<th>Evidence</th><th class="pp-x"><span class="sr">Remove</span></th></tr></thead>
          <tbody>${rows.length ? rows.map((r, i) => {
            let validity = "";
            if (isOem) {
              const d = daysTo(r.valid_until);
              const st = d === null ? ["none", "No date"] : d < 0 ? ["exp", "Expired"] : d <= 60 ? ["soon", d + " days left"] : ["ok", "Valid"];
              validity = `<td><span class="pp-valid pp-valid-${st[0]}">${st[1]}</span></td>`;
            }
            return `<tr>${L.cols.map((c) => `<td><input class="inp pp-cell${c.type === "number" ? " num" : ""}" type="${c.type}" data-list="${key}" data-i="${i}" data-k="${c.k}" value="${esc(r[c.k] ?? "")}" aria-label="${c.label}"></td>`).join("")}${validity}
              <td>${evBadge(r.evidence, S.changed.has(key + ":" + i))}</td>
              <td class="pp-x"><button class="pp-del" data-del="${key}" data-i="${i}" title="Remove row" aria-label="Remove row"><i data-lucide="trash-2"></i></button></td></tr>`;
          }).join("") : `<tr><td colspan="${L.cols.length + (isOem ? 4 : 3)}"><div class="empty">Nothing yet. Add one to strengthen eligibility.</div></td></tr>`}</tbody>
        </table>
      </div>
    </section>`;
  }

  function vault() {
    const docs = S.p.documents || [];
    const c = { valid: 0, expiring: 0, missing: 0 };
    docs.forEach((d) => { c[d.status in c ? d.status : "missing"]++; });
    return `<section class="card pp-vault">
      <div class="card-h"><h3><i data-lucide="folder-lock"></i> Document vault</h3><span class="pp-hint">${docs.length} documents</span></div>
      <div class="card-b">
        <div class="pp-vsum">${Object.keys(DOCSTATUS).map((k) => `<div class="pp-vs" style="--dc:${DOCSTATUS[k].color}"><i data-lucide="${DOCSTATUS[k].icon}"></i><b>${c[k]}</b><span>${DOCSTATUS[k].label}</span></div>`).join("")}</div>
        <div class="pp-vbar" aria-hidden="true">${Object.keys(DOCSTATUS).map((k) => c[k] ? `<span style="flex:${c[k]};background:${DOCSTATUS[k].color}"></span>` : "").join("")}</div>
        <ul class="pp-docs">${docs.map((d) => {
          const s = DOCSTATUS[d.status] || DOCSTATUS.missing;
          const n = daysTo(d.expires);
          const when = d.status === "missing" ? "Not uploaded" : d.expires ? (n !== null && n < 0 ? "Expired " : "Expires ") + fmtDate(d.expires) : "No expiry";
          return `<li class="pp-doc pp-doc-${esc(d.status)}" style="--dc:${s.color}">
            <span class="pp-dico"><i data-lucide="${s.icon}"></i></span>
            <span class="pp-dname"><b>${esc(d.name)}</b><small>${esc(when)}</small></span>
            <span class="pp-dst">${s.label}</span>
          </li>`;
        }).join("") || '<li><div class="empty">No documents in the vault.</div></li>'}</ul>
      </div>
    </section>`;
  }

  function draw() {
    const root = S.root;
    const dirty = JSON.stringify(S.p) !== JSON.stringify(S.saved);
    root.innerHTML = `
      <div class="pp-top">
        ${switcher()}
        <div class="pp-actions">
          <span class="pp-dirty${dirty ? " on" : ""}"><i data-lucide="${dirty ? "circle-dot" : "check"}"></i>${dirty ? "Unsaved changes" : "All changes saved"}</span>
          <button class="btn btn-ghost pp-sm" data-reset${dirty ? "" : " disabled"}><i data-lucide="undo-2"></i> Discard</button>
          <button class="btn btn-primary" data-save${dirty ? "" : " disabled"}><i data-lucide="save"></i> Save profile</button>
        </div>
      </div>
      ${BR.auth && BR.auth.demo ? `<div class="pp-demo-note">Sample values are fictional and the demo profile is read-only.</div>` : ""}
      ${legend()}
      <div class="pp-grid">
        ${identity()}${recognitions()}${emd()}${turnover()}${vault()}${listCard("orders")}${listCard("oem_letters")}
      </div>`;
    BR.icons();
      if (BR.auth && BR.auth.demo) {
        root.querySelectorAll("input, [data-role], [data-add], [data-del], [data-save], [data-reset]").forEach(control => { control.disabled = true; });
      }
  }

  function setDirtyUi() {
    const dirty = JSON.stringify(S.p) !== JSON.stringify(S.saved);
    const d = S.root.querySelector(".pp-dirty");
    if (!d) return;
    d.classList.toggle("on", dirty);
    d.innerHTML = `<i data-lucide="${dirty ? "circle-dot" : "check"}"></i>${dirty ? "Unsaved changes" : "All changes saved"}`;
    S.root.querySelector("[data-save]").disabled = !dirty;
    S.root.querySelector("[data-reset]").disabled = !dirty;
    BR.icons();
  }

  // A row whose value moves away from what was saved loses its document/verified status.
  function touchRow(list, i) {
    const row = S.p[list][i], was = (S.saved[list] || [])[i];
    const same = was && JSON.stringify({ ...row, evidence: 0 }) === JSON.stringify({ ...was, evidence: 0 });
    const id = list + ":" + i;
    if (same) { row.evidence = was.evidence; S.changed.delete(id); }
    else if (row.evidence !== "declared") { row.evidence = "declared"; S.changed.add(id); }
    else if (was && was.evidence !== "declared") S.changed.add(id);
  }

  function refreshUnlock() {
    const u = S.root.querySelector(".pp-unlock");
    if (u) { u.outerHTML = unlocks(); BR.icons(); }
  }

  function wire() {
    const root = S.root;
    root.addEventListener("input", (e) => {
      const t = e.target;
      if (t.dataset.f) {
        S.p[t.dataset.f] = t.type === "number" ? Number(t.value) || 0 : t.value;
        return setDirtyUi();
      }
      if (t.dataset.list) {
        const { list, i, k } = t.dataset;
        S.p[list][i][k] = t.type === "number" ? Number(t.value) || 0 : t.value;
        const before = S.changed.has(list + ":" + i);
        touchRow(list, +i);
        if (before !== S.changed.has(list + ":" + i)) {
          const row = t.closest("tr, .pp-trow");
          const badge = row && row.querySelector(".pp-ev");
          if (badge) badge.outerHTML = evBadge(S.p[list][i].evidence, S.changed.has(list + ":" + i));
        }
        return setDirtyUi();
      }
    });
    root.addEventListener("change", (e) => {
      const t = e.target;
      if (t.dataset.f === "emd_funds_lakh") {
        const card = t.closest(".card");
        if (card) card.outerHTML = emd();
        BR.icons(); setDirtyUi();
      }
      if (t.dataset.t) { S.p[t.dataset.t] = t.checked; t.closest(".pp-tog").querySelector(".pp-togicon").classList.toggle("on", t.checked); refreshUnlock(); setDirtyUi(); }
      if (t.dataset.list && (t.dataset.list === "turnover" || t.dataset.k === "valid_until")) {
        const card = t.closest(".card");
        if (card) card.outerHTML = t.dataset.list === "turnover" ? turnover() : listCard(t.dataset.list);
        const legendCard = root.querySelector(".pp-legend");
        if (legendCard) legendCard.outerHTML = legend();
        BR.icons(); setDirtyUi();
      }
    });
    root.addEventListener("click", async (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.pid && b.dataset.pid !== S.p.id) return selectProfile(b.dataset.pid, true);
      if (b.dataset.role) {
        S.p.role = b.dataset.role;
        root.querySelectorAll(".pp-role").forEach((r) => { const on = r.dataset.role === S.p.role; r.classList.toggle("on", on); r.setAttribute("aria-checked", on); });
        refreshUnlock();
        return setDirtyUi();
      }
      if (b.dataset.add) { (S.p[b.dataset.add] = S.p[b.dataset.add] || []).push(LISTS[b.dataset.add].blank()); draw(); const ins = root.querySelectorAll(`[data-list="${b.dataset.add}"]`); if (ins.length) ins[ins.length - LISTS[b.dataset.add].cols.length].focus(); return; }
      if (b.dataset.del) {
        S.p[b.dataset.del].splice(+b.dataset.i, 1);
        S.changed = new Set([...S.changed].filter((k) => !k.startsWith(b.dataset.del + ":")));
        return draw();
      }
      if ("reset" in b.dataset) { S.p = clone(S.saved); S.changed.clear(); return draw(); }
      if ("save" in b.dataset) return doSave(b);
      if (b.dataset.guard) {
        const next = S.pending; S.pending = null;
        if (b.dataset.guard === "stay" || !next) return hideGuard();
        if (b.dataset.guard === "save" && !(await doSave(b))) { S.pending = next; return; }
        return selectProfile(next.id, next.announce, true);
      }
    });
  }

  // Saves the current profile; resolves true on success so the switch guard can continue.
  async function doSave(b) {
    const html = b.innerHTML;
    b.disabled = true; b.innerHTML = '<i data-lucide="loader-circle" class="pp-spin"></i> Saving';
    BR.icons();
    try {
      // rows added but never filled in are dropped rather than sent as empty facts
      const body = clone(S.p);
      Object.keys(LISTS).forEach((k) => {
        body[k] = (body[k] || []).filter((r) => LISTS[k].cols.some((c) => c.type !== "number" && String(r[c.k] || "").trim()));
      });
      const saved = await BR.api.put("/api/profiles/" + encodeURIComponent(S.p.id), body);
      S.saved = clone(saved || S.p); S.p = clone(S.saved); S.changed.clear();
      const ix = S.profiles.findIndex((p) => p.id === S.p.id); if (ix >= 0) S.profiles[ix] = clone(S.p);
      BR.toast && BR.toast("Profile saved: " + S.p.name);
      draw();
      return true;
    } catch (err) {
      BR.toast && BR.toast("Save failed: " + (err.message || err), "circle-alert");
      b.disabled = false; b.innerHTML = html; BR.icons();
      setDirtyUi();
      return false;
    }
  }

  function hideGuard() {
    const g = S.root.querySelector(".pp-guard");
    if (g) g.remove();
  }

  // Inline banner shown instead of switching when the current profile has unsaved edits.
  function showGuard(target) {
    hideGuard();
    S.root.querySelector(".pp-top").insertAdjacentHTML("afterend", `
      <section class="card pp-guard" role="alertdialog" aria-labelledby="pp-guard-t">
        <span class="pp-guard-ico"><i data-lucide="triangle-alert"></i></span>
        <div class="pp-guard-txt"><b id="pp-guard-t">You have unsaved changes to ${esc(S.p.name)}</b>
          <small>Save them before switching to ${esc(target.name)}, or switch and lose them.</small></div>
        <div class="pp-guard-act">
          <button class="btn btn-ghost pp-sm" data-guard="stay"><i data-lucide="pencil"></i> Keep editing</button>
          <button class="btn btn-ghost pp-sm" data-guard="switch"><i data-lucide="trash-2"></i> Switch anyway</button>
          <button class="btn btn-primary pp-sm" data-guard="save"><i data-lucide="save"></i> Save and switch</button>
        </div>
      </section>`);
    BR.icons();
    S.root.querySelector('[data-guard="save"]').focus();
  }

  async function selectProfile(id, announce, force) {
    const local = S.profiles.find((p) => p.id === id) || S.profiles[0];
    if (!local) return;
    if (!force && JSON.stringify(S.p) !== JSON.stringify(S.saved)) { S.pending = { id, announce }; return showGuard(local); }
    S.p = clone(local); S.saved = clone(local); S.changed = new Set();
    draw();
    if (announce) {
      S.selfSwitch = true;
      if (BR.setProfile) BR.setProfile(id); else BR.state.profileId = id;
      S.selfSwitch = false;
    }
  }

  async function render(el) {
    el.innerHTML = `<div class="pp-root">
      <div class="pp-top"><div class="skeleton" style="height:58px;flex:1"></div></div>
      <div class="pp-grid"><div class="card pp-identity"><div class="skeleton" style="height:280px"></div></div><div class="card pp-recog"><div class="skeleton" style="height:280px"></div></div><div class="card pp-emd"><div class="skeleton" style="height:280px"></div></div></div>
    </div>`;
    const root = el.firstElementChild;
    let profiles, tenders;
    try {
      [profiles, tenders] = await Promise.all([BR.api.get("/api/profiles"), BR.api.get("/api/live-tenders?page=1").then((result) => result.bids || []).catch(() => [])]);
    } catch (err) {
      if (!root.isConnected) return;
      root.innerHTML = `<div class="empty"><i data-lucide="plug-zap"></i><br>Could not load profiles: ${esc(err.message || err)}<br><button class="btn btn-ghost pp-sm" data-retry>Try again</button></div>`;
      root.querySelector("[data-retry]").onclick = () => render(el);
      return BR.icons();
    }
    if (!root.isConnected) return;
    if (!profiles || !profiles.length) { root.innerHTML = '<div class="empty">No supplier profiles yet.</div>'; return; }
    S = { root, profiles, tenders: tenders || [], p: null, saved: null, changed: new Set(), selfSwitch: false, pending: null };
    const want = (BR.state && BR.state.profileId) || profiles[0].id;
    const start = profiles.find((p) => p.id === want) || profiles[0];
    S.p = clone(start); S.saved = clone(start);
    wire();
    draw();
  }

  if (BR.on) BR.on("profile", (id) => {
    if (!S || S.selfSwitch || !S.root.isConnected) return;
    const pid = id || (BR.state && BR.state.profileId);
    if (pid && pid !== S.p.id) selectProfile(pid, false);
  });

  BR.register("profile", { title: "Supplier profile", icon: "building-2", render });
})();

/* Account details and sector preferences shared by suppliers and tender seekers. */
(function () {
  "use strict";
  const BR = window.BR;
  const E = BR.esc;
  const I = name => `<i data-lucide="${name}"></i>`;

  async function render(root) {
    root.innerHTML = `<div class="ac-wrap"><div class="empty">${I("loader-circle")}Loading account settings…</div></div>`;
    const result = await BR.api.get("/api/account");
    const account = result.account;
    if (!account) { root.innerHTML = `<div class="empty">Complete account setup to continue.</div>`; return; }
    const options = [result.all_sectors, ...result.sectors];
    root.innerHTML = `
      <header class="ac-head"><div><div class="eyebrow">YOUR WORKSPACE</div><h2>Account and sectors</h2>
      <p>Update the industries that shape your tender feed. You can choose several or keep every sector in view.</p></div></header>
      <section class="card ac-card"><form id="account-settings">
        <div class="ac-meta"><span>${I("user-round")} ${account.account_type === "supplier" ? "Supplier account" : "Tender seeker account"}</span><span>${I("shield-check")} Signed in with Clerk</span></div>
        <div class="ac-fields"><label>Your name<input class="inp" name="name" maxlength="100" value="${E(account.name || "")}"></label>
        ${account.account_type === "supplier" ? `<label>Company / supplier name<input class="inp" name="company_name" maxlength="120" value="${E(account.company_name || "")}" required></label>` : ""}</div>
        <div class="eyebrow">INDUSTRIES TO MONITOR</div>
        <p class="ac-hint">BidReady keeps “Other / unclassified” opportunities visible so unfamiliar categories are not silently dropped.</p>
        <div class="sector-picks">${options.map(s => `<label class="sector-pick"><input type="checkbox" name="sectors" value="${E(s)}" ${(account.sectors || []).includes(s) ? "checked" : ""}><span>${E(s)}</span></label>`).join("")}</div>
        <div class="ac-actions"><span class="ac-status" role="status"></span><button class="btn btn-primary" type="submit">${I("save")}Save account</button></div>
      </form></section>`;
    const form = root.querySelector("#account-settings");
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const sectors = Array.from(form.querySelectorAll('input[name="sectors"]:checked'), input => input.value);
      const payload = Object.fromEntries(new FormData(form));
      payload.account_type = account.account_type;
      payload.sectors = sectors;
      const status = form.querySelector(".ac-status");
      const button = form.querySelector("button[type=submit]"); button.disabled = true; status.textContent = "Saving…";
      try {
        const saved = await BR.api.put("/api/account", payload);
        BR.state.account = saved.account;
        status.textContent = "Saved";
        BR.toast("Account and sector preferences saved", "circle-check");
        if (BR.refreshApp) BR.refreshApp();
      } catch (err) { status.textContent = err.message || "Could not save"; }
      finally { button.disabled = false; }
    });
    BR.icons();
  }

  BR.register("account", { title: "Account & sectors", icon: "settings-2", render });
})();

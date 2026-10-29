/* Clerk authentication and first-run supplier/seeker onboarding. */
(function () {
  "use strict";
  const BR = window.BR = window.BR || {};
  const gate = document.getElementById("auth-gate");
  const shell = document.getElementById("shell");
  let resolveReady;
  BR.authReady = new Promise(resolve => { resolveReady = resolve; });
  BR.auth = { signedIn: false, getToken: async () => null };
  let readyResolved = false;
  let userButtonMounted = false;
  let authWidgetsMounted = false;
  let onboardingBusy = false;

  const esc = value => String(value == null ? "" : value).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const showGate = () => { gate.hidden = false; shell.hidden = true; };
  const resolve = () => { if (!readyResolved) { readyResolved = true; resolveReady(); } };
  const error = message => { document.getElementById("auth-error").textContent = message || ""; };

  function loadScript(src, attributes) {
    return new Promise((ok, fail) => {
      const script = document.createElement("script");
      script.src = src;
      script.crossOrigin = "anonymous";
      script.onload = ok;
      script.onerror = () => fail(new Error("Could not load Clerk's browser SDK. Check your network and Clerk domain settings."));
      Object.entries(attributes || {}).forEach(([key, value]) => script.setAttribute(key, value));
      document.head.appendChild(script);
    });
  }

  function frontendApiFromKey(key) {
    const encoded = String(key).replace(/^pk_(test|live)_/, "").replace(/-/g, "+").replace(/_/g, "/");
    const decoded = atob(encoded.replace(/=+$/, ""));
    return decoded.replace(/\$$/, "");
  }

  async function loadClerk(key) {
    const frontendApi = frontendApiFromKey(key);
    const root = "https://" + frontendApi + "/npm";
    await loadScript(root + "/@clerk/ui@1/dist/ui.browser.js");
    await loadScript(root + "/@clerk/clerk-js@6/dist/clerk.browser.js", { "data-clerk-publishable-key": key });
    if (!window.Clerk) throw new Error("Clerk loaded without its browser client.");
    await window.Clerk.load({ ui: { ClerkUI: window.__internal_ClerkUICtor } });
  }

  function renderAuthWidgets() {
    const tabs = document.getElementById("auth-tabs");
    const signIn = document.getElementById("auth-signin");
    const signUp = document.getElementById("auth-signup");
    const activate = mode => {
      error("");
      tabs.querySelectorAll("button").forEach(button => button.classList.toggle("on", button.dataset.authMode === mode));
      document.getElementById("auth-title").textContent = mode === "signup" ? "Create your BidReady account" : "Sign in to BidReady";
      signIn.hidden = mode !== "signin";
      signUp.hidden = mode !== "signup";
      if (!authWidgetsMounted) {
        window.Clerk.mountSignIn(signIn);
        window.Clerk.mountSignUp(signUp);
        authWidgetsMounted = true;
      }
    };
    tabs.hidden = false;
    document.getElementById("onboarding").innerHTML = "";
    tabs.querySelectorAll("button").forEach(button => button.onclick = () => activate(button.dataset.authMode));
    activate("signin");
  }

  async function renderOnboarding() {
    if (onboardingBusy) return;
    onboardingBusy = true;
    const card = document.getElementById("auth-card");
    card.querySelector(".auth-intro").textContent = "Tell us what you do so BidReady can show the right opportunities.";
    document.getElementById("auth-title").textContent = "Set up your workspace";
    document.getElementById("auth-tabs").hidden = true;
    document.getElementById("auth-signin").hidden = true;
    document.getElementById("auth-signup").hidden = true;
    const host = document.getElementById("onboarding");
    try {
      const data = await BR.api.get("/api/sectors");
      const options = [data.all_sectors, ...data.sectors];
      host.innerHTML = `
        <form id="onboarding-form">
          <div class="onboard-grid">
            <label>Account type<select name="account_type"><option value="supplier">Supplier</option><option value="seeker">Tender seeker</option></select></label>
            <label>Your name<input name="name" maxlength="100" placeholder="Your name" autocomplete="name"></label>
            <label class="supplier-only">Company / supplier name<input name="company_name" maxlength="120" placeholder="Registered business name" autocomplete="organization" required></label>
            <label class="supplier-only">Supplier type<select name="supplier_type"><option value="reseller">Reseller</option><option value="manufacturer">Manufacturer</option><option value="service_provider">Service provider</option></select></label>
          </div>
          <div class="eyebrow">SECTORS AND INDUSTRIES</div>
          <p class="muted">Choose every sector you serve or want to monitor. “All sectors” keeps the full feed visible.</p>
          <div class="sector-picks">${options.map(s => `<label class="sector-pick"><input type="checkbox" name="sectors" value="${esc(s)}"><span>${esc(s)}</span></label>`).join("")}</div>
          <button class="btn btn-primary onboard-submit" type="submit">Save workspace and continue</button>
        </form>`;
      const form = host.querySelector("form");
      const accountType = form.elements.account_type;
      const companyName = form.elements.company_name;
      accountType.addEventListener("change", () => {
        const supplier = accountType.value === "supplier";
        host.querySelectorAll(".supplier-only").forEach(el => { el.hidden = !supplier; });
        if (companyName) { companyName.required = supplier; companyName.disabled = !supplier; }
      });
      form.addEventListener("submit", async event => {
        event.preventDefault(); error("");
        const sectorsPicked = Array.from(form.querySelectorAll('input[name="sectors"]:checked'), input => input.value);
        const payload = Object.fromEntries(new FormData(form));
        payload.sectors = sectorsPicked;
        const button = form.querySelector("button[type=submit]"); button.disabled = true; button.textContent = "Saving…";
        try {
          const result = await BR.api.put("/api/account", payload);
          BR.state.account = result.account;
          BR.state.profileId = result.account.user_id;
          gate.hidden = true; shell.hidden = false;
          if (BR.startApp) BR.startApp();
        } catch (err) {
          error(err.message || "Could not save your workspace."); button.disabled = false; button.textContent = "Save workspace and continue";
        }
      });
    } catch (err) {
      error(err.message || "Could not load the sector list.");
      host.innerHTML = `<p class="setup-note">We couldn't load onboarding data. <button type="button" id="retry-onboarding">Try again</button></p>`;
      host.querySelector("#retry-onboarding").onclick = () => { onboardingBusy = false; renderOnboarding(); };
    }
    onboardingBusy = false;
  }

  async function syncAuth() {
    const signedIn = !!(window.Clerk && window.Clerk.isSignedIn);
    BR.auth = { signedIn, getToken: async () => signedIn && window.Clerk.session ? window.Clerk.session.getToken() : null };
    if (!signedIn) {
      BR.state.account = null;
      showGate();
      document.getElementById("auth-title").textContent = "Sign in to BidReady";
      document.querySelector("#auth-card .auth-intro").textContent = "Create a supplier or tender seeker account to continue.";
      renderAuthWidgets();
      resolve();
      return;
    }
    error("");
    try {
      const result = await BR.api.get("/api/account");
      BR.state.account = result.account;
      if (!result.account) {
        showGate();
        await renderOnboarding();
        resolve();
        return;
      }
      BR.state.profileId = result.account.user_id;
      gate.hidden = true; shell.hidden = false;
      if (!userButtonMounted) {
        const target = document.getElementById("clerk-user-button");
        if (target) { window.Clerk.mountUserButton(target); userButtonMounted = true; }
      }
      if (BR.startApp) BR.startApp();
      if (BR.refreshApp) BR.refreshApp();
    } catch (err) {
      showGate();
      document.getElementById("auth-title").textContent = "Can't reach BidReady";
      document.querySelector("#auth-card .auth-intro").textContent = "Start the local backend, then reload this page.";
      document.getElementById("auth-tabs").hidden = true;
      error(err.message || "Backend unavailable.");
    }
    resolve();
  }

  async function init() {
    try {
      const config = await BR.api.get("/api/public-config");
      if (!config.clerk_configured || !config.publishable_key) {
        showGate();
        document.getElementById("auth-title").textContent = "Clerk setup needed";
        document.querySelector("#auth-card .auth-intro").textContent = "Add development keys for the selected Clerk application to enable sign-in.";
        document.getElementById("auth-tabs").hidden = true;
        document.getElementById("auth-signin").innerHTML = `<div class="setup-note">The selected Clerk application is ready to connect. Copy its publishable key, secret key, and JWT public key into your local <code>.env</code> file using <code>.env.example</code> as the guide, then restart the server.</div>`;
        resolve();
        return;
      }
      await loadClerk(config.publishable_key);
      window.Clerk.addListener(() => { void syncAuth(); });
      await syncAuth();
    } catch (err) {
      showGate();
      document.getElementById("auth-title").textContent = "Clerk could not load";
      document.querySelector("#auth-card .auth-intro").textContent = "Check your Clerk development keys and network, then reload.";
      error(err.message || "Clerk initialization failed.");
      resolve();
    }
  }

  void init();
})();

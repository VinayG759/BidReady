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
    await window.Clerk.load({
      ui: { ClerkUI: window.__internal_ClerkUICtor },
      appearance: {
        variables: {
          colorPrimary: "#f59e2b", colorBackground: "#131a2b", colorForeground: "#ece7da",
          colorInput: "#0d1220", colorInputForeground: "#ece7da", colorBorder: "#344061",
          colorMuted: "#1a2236", colorMutedForeground: "#b9b4a6", colorNeutral: "#b9b4a6",
          colorRing: "#f59e2b", fontFamily: '"Hanken Grotesk", system-ui, sans-serif',
          fontFamilyButtons: '"Hanken Grotesk", system-ui, sans-serif',
          fontFamilyMono: '"JetBrains Mono", ui-monospace, monospace', borderRadius: "10px"
        }
      }
    });
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
            <label>Your full name<input name="name" maxlength="100" placeholder="Your full name" autocomplete="name" required></label>
            <label class="supplier-only">Company / supplier name<input name="company_name" maxlength="120" placeholder="Registered business name" autocomplete="organization" required></label>
            <label class="supplier-only">Supplier type<select name="supplier_type"><option value="reseller">Reseller</option><option value="manufacturer">Manufacturer</option><option value="service_provider">Service provider</option></select></label>
          </div>
          <div class="eyebrow">SECTORS AND INDUSTRIES</div>
          <p class="muted">Choose every sector you serve or want to monitor. “All sectors” keeps the full feed visible.</p>
          <div class="sector-picks">${options.map(s => `<label class="sector-pick"><input type="checkbox" name="sectors" value="${esc(s)}"><span>${esc(s)}</span></label>`).join("")}</div>
          <button class="btn btn-primary onboard-submit" type="submit">Save and continue</button>
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
          if (result.account.account_type === "supplier" && !result.account.profile_complete) {
            await renderSupplierVerification();
          } else openWorkspace();
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

  function openWorkspace() {
    gate.hidden = true; shell.hidden = false;
    const target = document.getElementById("clerk-user-button");
    if (target && !userButtonMounted && window.Clerk && window.Clerk.isSignedIn) {
      window.Clerk.mountUserButton(target); userButtonMounted = true;
    }
    if (BR.startApp) BR.startApp();
  }

  async function renderSupplierVerification() {
    const card = document.getElementById("auth-card");
    card.classList.add("auth-card-wide");
    card.querySelector(".auth-intro").textContent = "Suppliers must complete this business identity step before accessing BidReady. Uploaded evidence stays private and is marked pending review.";
    document.getElementById("auth-title").textContent = "Verify your business profile";
    document.getElementById("auth-tabs").hidden = true;
    document.getElementById("auth-signin").hidden = true;
    document.getElementById("auth-signup").hidden = true;
    const host = document.getElementById("onboarding");
    host.innerHTML = `
      <form id="verification-form" enctype="multipart/form-data">
        <div class="verify-section"><div class="eyebrow">BUSINESS IDENTITY</div>
          <div class="onboard-grid">
            <label>Full legal business name<input name="legal_name" maxlength="160" autocomplete="organization" required></label>
            <label>Business structure<select name="entity_type" required><option value="">Select structure</option><option value="proprietorship">Sole proprietorship</option><option value="partnership">Partnership</option><option value="llp">Limited liability partnership</option><option value="private_limited">Private limited company</option><option value="public_limited">Public limited company</option><option value="cooperative">Cooperative</option><option value="trust_society">Trust / society</option><option value="other">Other registered structure</option></select></label>
            <label>Business PAN<input name="business_pan" class="mono" maxlength="10" pattern="[A-Za-z]{5}[0-9]{4}[A-Za-z]" placeholder="ABCDE1234F" autocomplete="off" required></label>
            <label>PAN proof (PDF, PNG, JPEG)<input name="pan_document" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" required></label>
            <label>Business registration proof<input name="registration_document" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" required></label>
            <span class="verify-hint">PAN is stored masked. Never enter Aadhaar or personal identity numbers here.</span>
          </div>
        </div>
        <div class="verify-section"><div class="eyebrow">GST REGISTRATION</div>
          <div class="onboard-grid">
            <label>GST status<select name="gst_status" id="gst-status" required><option value="">Select status</option><option value="registered">Registered</option><option value="not_registered">Not registered</option></select></label>
            <label class="gst-registered" hidden>GSTIN<input name="gstin" maxlength="15" class="mono" autocomplete="off"></label>
            <label class="gst-registered" hidden>GST certificate<input name="gst_document" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"></label>
            <label class="gst-unregistered" hidden>Why not registered?<select name="gst_reason"><option value="">Select a reason</option><option value="not_applicable">Not applicable to this business</option><option value="registration_in_progress">Registration in progress</option><option value="other">Other</option></select></label>
          </div>
        </div>
        <div class="verify-section"><div class="eyebrow">REGISTERED BUSINESS ADDRESS</div>
          <div class="onboard-grid">
            <label class="verify-wide">Street address<input name="street" autocomplete="street-address" required></label>
            <label>City<input name="city" autocomplete="address-level2" required></label>
            <label>State / UT<input name="state" autocomplete="address-level1" required></label>
            <label>PIN code<input name="pincode" inputmode="numeric" maxlength="6" pattern="[1-9][0-9]{5}" autocomplete="postal-code" required></label>
          </div>
        </div>
        <p class="verify-hint">Files are private to your account and limited to 10 MB each. Submitting them does not automatically verify them; BidReady marks them pending review.</p>
        <button class="btn btn-primary onboard-submit" type="submit">Submit identity and continue</button>
      </form>`;
    const form = host.querySelector("#verification-form");
    const gstStatus = form.elements.gst_status;
    const gstin = form.elements.gstin, gstDoc = form.elements.gst_document, gstReason = form.elements.gst_reason;
    const updateGst = () => {
      const registered = gstStatus.value === "registered", unregistered = gstStatus.value === "not_registered";
      host.querySelectorAll(".gst-registered").forEach(el => { el.hidden = !registered; });
      host.querySelectorAll(".gst-unregistered").forEach(el => { el.hidden = !unregistered; });
      gstin.required = registered; gstDoc.required = registered; gstReason.required = unregistered;
      gstin.disabled = !registered; gstDoc.disabled = !registered; gstReason.disabled = !unregistered;
    };
    gstStatus.addEventListener("change", updateGst);
    form.addEventListener("submit", async event => {
      event.preventDefault(); error("");
      const button = form.querySelector("button[type=submit]"); button.disabled = true; button.textContent = "Submitting…";
      try {
        const result = await BR.api.form("PUT", "/api/profile/verification", new FormData(form));
        BR.state.account = result.account; BR.state.profileId = result.account.user_id;
        openWorkspace();
      } catch (err) {
        error(err.message || "Could not submit business identity details.");
        button.disabled = false; button.textContent = "Submit identity and continue";
      }
    });
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
      if (result.account.account_type === "supplier" && !result.account.profile_complete) {
        showGate(); await renderSupplierVerification(); resolve(); return;
      }
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

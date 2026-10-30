/* BidReady AI: chat + voice assistant panel on every page. Talks to /api/assistant/* and /api/voice/*.
   Actions it returns run at once (navigate, switch supplier, refresh); paid or data-changing ones wait for a Confirm card.
   Guest mode (<script src="assets/assistant.js" data-mode="guest">, the landing page): needs no BR shell, sends mode:"guest",
   only answers (never runs actions or shows confirm cards) and keeps its conversation apart from the app's. */
(function () {
  "use strict";
  const GUEST = !!(document.currentScript && document.currentScript.dataset.mode === "guest");
  const BR = window.BR = window.BR || {};
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const E = (s) => (BR.esc || esc)(s);
  const I = (n, c) => `<i data-lucide="${n}"${c ? ` class="${c}"` : ""}></i>`;
  const icons = () => BR.icons ? BR.icons() : window.lucide && lucide.createIcons({ attrs: { "stroke-width": 2 } });
  /* guests use their own fetch, so a 429/422 comes back with its status and the server's detail text */
  async function req(method, path, body, isForm) {
    const opt = { method, headers: {} };
    if (body !== undefined) { if (isForm) opt.body = body; else { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); } }
    const res = await fetch((location.protocol === "file:" ? "http://localhost:8000" : "") + path, opt);
    const text = await res.text(); let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
    if (!res.ok) { const err = new Error((data && data.detail) || "HTTP " + res.status); err.status = res.status; err.detail = data && data.detail; throw err; }
    return data;
  }
  const api = GUEST || !BR.api ? { get: (p) => req("GET", p), post: (p, b) => req("POST", p, b || {}),
    upload: (p, file) => { const f = new FormData(); f.append("file", file); return req("POST", p, f, true); } } : BR.api;
  const MAX_REC = 28, KEEP = 20, MAX_LEN = 500;
  const KEY = GUEST
    ? { log: "br.ai.guest.log", open: "br.ai.guest.open", speak: "br.ai.guest.speak", lang: "br.ai.guest.lang", conv: "br.ai.guest.conv" }
    : { log: "br.ai.log", open: "br.ai.open", speak: "br.ai.speak", lang: "br.ai.lang", conv: "br.ai.conv" };
  const SUGGEST = GUEST ? [
    { icon: "sparkles", text: "What does BidReady do?" },
    { icon: "wallet", text: "What is an EMD?" },
    { icon: "bell-ring", text: "How does Bid watch work?" },
    { icon: "search", text: "Find laptop tenders on GeM" },
    { icon: "languages", text: "टेंडर क्या होता है?" },
  ] : [
    { icon: "search", text: "Find laptop tenders for this supplier" },
    { icon: "circle-help", text: "Why is this bid not eligible?" },
    { icon: "list-checks", text: "Check all matches" },
  ];
  /* a calm line in the chat (the landing page has no toast); server limits (429/422) use the same look */
  const notify = (msg, icon) => {
    if (!GUEST && BR.toast) return notify(msg, icon);
    S.log.push({ role: "assistant", notice: true, icon: icon || "info", content: msg }); save(); paint();
  };
  const limited = (err) => !!err && (err.status === 429 || err.status === 422);
  const EXPLAIN = "Explain clearly in simple words what did not meet the requirements in this check, and how we can meet them.";
  const ss = {
    get(k, d) { try { const v = sessionStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
  };

  /* log items: {role:"user"|"assistant", content, tools?:[{summary}], pending?:[{id,label,detail,cost_note,state}], error?, voice?} */
  const S = {
    log: ss.get(KEY.log, []), open: false, busy: false, lang: ss.get(KEY.lang, null),
    speak: ss.get(KEY.speak, null), voiceOk: false, rec: null, audio: null, lastReq: null, profileName: "", conv: ss.get(KEY.conv, null),
  };

  function route() {
    const h = location.hash.replace(/^#\/?/, ""), [name, qs] = h.split("?");
    return { page: name || "dashboard", params: Object.fromEntries(new URLSearchParams(qs || "")) };
  }
  function context(extra) {
    const r = route(), c = { page: r.page, params: r.params, profile_id: BR.state && BR.state.profileId };
    if (r.page === "report" && r.params.id) c.assessment_id = r.params.id;
    if (r.params.tender) c.tender_id = r.params.tender;
    return Object.assign(c, extra || {});
  }
  const apiMessages = () => S.log.filter((m) => !m.error && m.content).map((m) => ({ role: m.role, content: m.content }));
  const setConv = (id) => { S.conv = id || null; ss.set(KEY.conv, S.conv); };
  const save = () => ss.set(KEY.log, S.log.slice(-KEEP));

  /* ---------- tiny markdown: paragraphs, **bold**, `code`, lists, [links](url) ---------- */
  function inline(t) {
    return E(t)
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\(((?:https?:\/\/|#\/)[^)\s]+)\)/g, (m, txt, url) =>
        `<a href="${GUEST && url[0] === "#" ? "app.html" + url : url}"${url[0] === "#" ? "" : ' target="_blank" rel="noopener"'}>${txt}</a>`);
  }
  function md(src) {
    const out = []; let list = null;
    const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
    String(src || "").split(/\r?\n/).forEach((line) => {
      const ul = /^\s*[-*•]\s+(.*)/.exec(line), ol = /^\s*\d+[.)]\s+(.*)/.exec(line);
      if (ul || ol) {
        const want = ul ? "ul" : "ol";
        if (list !== want) { close(); out.push(`<${want}>`); list = want; }
        out.push(`<li>${inline((ul || ol)[1])}</li>`);
      } else if (!line.trim()) close();
      else { close(); out.push(`<p>${inline(line.replace(/^#+\s*/, ""))}</p>`); }
    });
    close();
    return out.join("");
  }

  /* ---------- DOM ---------- */
  let el = {};
  function mount() {
    if (document.getElementById("aiPanel")) return;
    document.body.insertAdjacentHTML("beforeend", `
      <button class="ai-fab${GUEST ? " ai-guest" : ""}" id="aiFab" type="button" aria-label="Open BidReady AI" title="Ask BidReady AI">${I("sparkles")}</button>
      <section class="ai-panel${GUEST ? " ai-guest" : ""}" id="aiPanel" role="dialog" aria-label="BidReady AI" aria-hidden="true">
        <header class="ai-head">
          <span class="ai-logo">${I("sparkles")}</span>
          <div class="ai-ht"><b>BidReady AI</b><small class="ai-sup">${GUEST ? I("landmark") + "<span>Ask about BidReady or tenders</span>" : I("store") + "<span>Loading supplier…</span>"}</small></div>
          <button class="ai-ib" type="button" data-ai="speak" title="Voice replies" aria-pressed="false" hidden>${I("volume-x")}</button>
          <button class="ai-ib" type="button" data-ai="new" title="New conversation">${I("message-square-plus")}</button>
          <button class="ai-ib" type="button" data-ai="close" title="Close" aria-label="Close">${I("x")}</button>
        </header>
        <div class="ai-log" aria-live="polite"></div>
        <div class="ai-speaking" hidden><span class="ai-eq"><i></i><i></i><i></i><i></i></span><span>Speaking</span>
          <button type="button" class="ai-chipbtn" data-ai="stop-audio">${I("square")}Stop</button></div>
        <form class="ai-input">
          <div class="ai-row">
            <textarea rows="1" placeholder="Ask anything, or tap the mic" aria-label="Message"${GUEST ? ` maxlength="${MAX_LEN}"` : ""}></textarea>
            <button class="ai-ib ai-mic" type="button" data-ai="mic" title="Speak (English or Hindi)" aria-label="Speak" hidden>${I("mic")}</button>
            <button class="ai-send" type="submit" aria-label="Send">${I("arrow-up")}</button>
          </div>
          <div class="ai-recbar" hidden>
            <span class="ai-dot"></span><span class="ai-time mono">0:00</span>
            <span class="ai-level">${"<i></i>".repeat(18)}</span>
            <button type="button" class="ai-chipbtn" data-ai="rec-cancel">${I("x")}Cancel</button>
            <button type="button" class="ai-recstop" data-ai="rec-stop" aria-label="Stop and send">${I("send-horizontal")}</button>
          </div>
          ${GUEST ? `<div class="ai-foot ai-gfoot"><span>Free answers. Real checks run in the app.</span>
            <a class="ai-applink" href="app.html#/assess">${I("scan-search")}Open the app</a></div>`
            : `<small class="ai-foot">Paid or data-changing steps always ask you first.</small>`}
        </form>
      </section>`);
    const p = document.getElementById("aiPanel");
    el = { fab: document.getElementById("aiFab"), panel: p, log: p.querySelector(".ai-log"), form: p.querySelector(".ai-input"),
      ta: p.querySelector("textarea"), send: p.querySelector(".ai-send"), mic: p.querySelector("[data-ai=mic]"), spk: p.querySelector("[data-ai=speak]"),
      sup: p.querySelector(".ai-sup span"), row: p.querySelector(".ai-row"), recbar: p.querySelector(".ai-recbar"),
      time: p.querySelector(".ai-time"), bars: [...p.querySelectorAll(".ai-level i")], speaking: p.querySelector(".ai-speaking") };

    el.fab.addEventListener("click", open);
    el.form.addEventListener("submit", (e) => { e.preventDefault(); const t = el.ta.value.trim(); if (t) { el.ta.value = ""; grow(); ask(t); } });
    el.ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); el.form.requestSubmit(); } });
    el.ta.addEventListener("input", grow);
    p.addEventListener("click", onClick);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.open && !S.rec) close(); });
    if (!GUEST && BR.on) BR.on("profile", supplier);

    paint(); if (!GUEST) supplier(); voiceStatus(); speakBtn(); grow();
    if (ss.get(KEY.open, false)) open(true);
  }
  function grow() { el.ta.style.height = "auto"; el.ta.style.height = Math.min(el.ta.scrollHeight, 140) + "px"; }

  async function supplier() {
    try {
      const p = await BR.api.get("/api/profiles/" + encodeURIComponent(BR.state.profileId));
      S.profileName = p.name || BR.state.profileId;
    } catch (e) { S.profileName = BR.state.profileId || "No supplier"; }
    if (el.sup) el.sup.textContent = S.profileName;
  }
  async function voiceStatus() {
    const can = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
    try { const v = await api.get("/api/voice/status"); S.voiceOk = !!(v && v.available !== false); }
    catch (e) { S.voiceOk = false; }
    el.mic.hidden = !(S.voiceOk && can);
    el.spk.hidden = !S.voiceOk;
  }
  function speakBtn() {
    const on = !!S.speak;
    el.spk.setAttribute("aria-pressed", on); el.spk.classList.toggle("on", on);
    el.spk.title = on ? "Voice replies on" : "Voice replies off";
    el.spk.innerHTML = I(on ? "volume-2" : "volume-x"); icons();
  }

  function open(silent) {
    S.open = true; ss.set(KEY.open, true);
    el.panel.classList.add("open"); el.panel.setAttribute("aria-hidden", "false");
    document.body.classList.add("ai-open");
    el.fab.hidden = true;
    scroll();
    if (silent !== true && !matchMedia("(pointer:coarse)").matches) setTimeout(() => el.ta.focus(), 120);
  }
  function close() {
    S.open = false; ss.set(KEY.open, false);
    el.panel.classList.remove("open"); el.panel.setAttribute("aria-hidden", "true");
    document.body.classList.remove("ai-open");
    el.fab.hidden = false;
    if (S.rec) stopRec(false);
  }

  /* ---------- rendering ---------- */
  function bubble(m, i) {
    if (m.role === "user") return `<div class="ai-msg me">${m.voice ? `<span class="ai-vtag">${I("mic")}</span>` : ""}<div class="ai-b">${E(m.content).replace(/\n/g, "<br>")}</div></div>`;
    if (m.notice) return `<div class="ai-msg bot"><div class="ai-b ai-note">${I(m.icon || "info")}<span>${E(m.content)}</span></div></div>`;
    if (m.error) return `<div class="ai-msg bot"><div class="ai-b ai-err">${I("cloud-off")}<span>${E(m.content)}</span>
      ${i === S.log.length - 1 && S.lastReq ? `<button type="button" class="ai-chipbtn" data-ai="retry">${I("rotate-cw")}Try again</button>` : ""}</div></div>`;
    const tools = (m.tools || []).map((t) => `<li>${I("circle-check")}<span>Done: ${E(t.summary || t.name)}</span></li>`).join("");
    const pend = GUEST ? "" : (m.pending || []).map((p) => pendingCard(p, i)).join("");
    return `<div class="ai-msg bot">
      ${m.content ? `<div class="ai-b ai-md">${md(m.content)}</div>` : ""}
      ${tools ? `<ul class="ai-tools">${tools}</ul>` : ""}${pend}</div>`;
  }
  function pendingCard(p, i) {
    const st = p.state;
    return `<div class="ai-pend${st ? " " + st : ""}" data-pid="${E(p.id)}" data-i="${i}">
      <div class="ai-pt">${I(st === "approved" ? "circle-check" : st === "cancelled" ? "circle-slash" : "shield-alert")}<b>${E(p.label)}</b></div>
      ${p.detail ? `<p>${E(p.detail)}</p>` : ""}
      ${p.cost_note ? `<p class="ai-cost">${I("wallet")}${E(p.cost_note)}</p>` : ""}
      ${st ? `<small class="ai-pst">${st === "approved" ? "Confirmed" : "Cancelled"}</small>`
        : `<div class="ai-pacts"><button type="button" class="ai-chipbtn" data-ai="deny">${I("x")}Cancel</button><button type="button" class="ai-ok" data-ai="approve">${I("check")}Confirm</button></div>`}
    </div>`;
  }
  function paint() {
    if (!S.log.length) {
      el.log.innerHTML = `<div class="ai-hello">
        <span class="ai-big">${I("sparkles")}</span>
        <b>Ask BidReady AI</b>
        <p>${GUEST ? "Type or speak, in English or Hindi. Ask what BidReady does, how tenders and bids work, or find open GeM tenders."
          : "Type or speak, in English or Hindi. I can find tenders, explain a check, switch the supplier and run eligibility for you."}</p>
        <div class="ai-sugs">${SUGGEST.map((s) => `<button type="button" class="ai-sug" data-ai="sug">${I(s.icon)}<span>${E(s.text)}</span></button>`).join("")}</div>
      </div>`;
    } else {
      el.log.innerHTML = S.log.map(bubble).join("") + (S.busy ? `<div class="ai-msg bot"><div class="ai-b ai-typing" aria-label="BidReady AI is typing"><i></i><i></i><i></i></div></div>` : "");
    }
    el.send.disabled = S.busy;
    icons(); scroll();
  }
  const scroll = () => requestAnimationFrame(() => { el.log.scrollTop = el.log.scrollHeight; });

  /* ---------- chat ---------- */
  async function ask(text, extra, voice) {
    if (!el.panel) mount();
    if (!S.open) open(true);
    stopAudio();
    S.log.push({ role: "user", content: text, voice: !!voice });
    save();
    if (GUEST) return request("/api/assistant/chat", () => ({ conv_id: S.conv, message: text.slice(0, MAX_LEN), context: {}, lang: S.lang, mode: "guest" }));
    return request("/api/assistant/chat", () => ({ conv_id: S.conv, message: text, messages: apiMessages(), context: context(extra), lang: S.lang }));
  }
  async function request(path, body) {
    S.lastReq = { path, body }; S.busy = true;
    if (S.log.length && S.log[S.log.length - 1].error) S.log.pop();
    paint();
    let r;
    try { r = await api.post(path, body()); }
    catch (err) {
      S.busy = false;
      const msg = (err && err.message) || "";
      if (limited(err)) { // too many messages, or too long: the server's own words as a calm notice, no retry
        S.lastReq = null; S.log.push({ role: "assistant", notice: true, icon: err.status === 429 ? "timer" : "info", content: err.detail || msg }); save();
      } else if (/confirm/.test(path) && /expired|not found|HTTP 404/i.test(msg)) { // the server forgot this conversation: start a fresh one
        setConv(null); S.lastReq = null;
        S.log.push({ role: "assistant", error: true, content: "That request expired, please ask again." });
      } else S.log.push({ role: "assistant", error: true, content: "The assistant is unavailable right now." + (msg && !/^HTTP 5/.test(msg) ? " (" + msg + ")" : "") });
      paint(); return null;
    }
    S.busy = false; S.lastReq = null;
    handle(r || {});
    return r;
  }
  function handle(r) {
    if (r.conv_id) setConv(r.conv_id);
    if (r.lang) { S.lang = r.lang; ss.set(KEY.lang, S.lang); }
    const tools = (r.tools || []).slice();
    if (!GUEST) (r.actions || []).forEach((a) => { const s = act(a); if (s) tools.push({ summary: s }); });
    S.log.push({ role: "assistant", content: r.reply || "", tools, pending: GUEST ? [] : (r.pending || []).map((p) => Object.assign({}, p)) });
    save(); paint();
    if (S.speak && S.voiceOk && (r.speak || r.reply)) say(r.speak || r.reply);
  }
  function act(a) {
    try {
      if (a.type === "navigate" && a.route) { BR.go(a.route, a.params && Object.keys(a.params).length ? a.params : undefined); return a.summary || "opened " + a.route; }
      if (a.type === "set_profile" && a.profile_id) { BR.setProfile(a.profile_id); return a.summary || "switched supplier"; }
      if (a.type === "refresh") { window.dispatchEvent(new HashChangeEvent("hashchange")); return a.summary || "refreshed this page"; }
    } catch (e) { console.error(e); }
    return null;
  }
  function decide(card, approve) {
    const m = S.log[+card.dataset.i], p = m && (m.pending || []).find((x) => String(x.id) === card.dataset.pid);
    if (GUEST || !p || p.state || S.busy) return;
    p.state = approve ? "approved" : "cancelled"; save();
    request("/api/assistant/confirm", () => ({ conv_id: S.conv, pending_id: p.id, approve, context: context(), lang: S.lang }));
  }

  function onClick(e) {
    const b = e.target.closest("[data-ai]"); if (!b) return;
    switch (b.dataset.ai) {
      case "close": return close();
      case "new": stopAudio(); S.log = []; S.lastReq = null; setConv(null); save(); return paint();
      case "sug": return ask(b.textContent.trim());
      case "retry": return S.lastReq && request(S.lastReq.path, S.lastReq.body);
      case "approve": return decide(b.closest(".ai-pend"), true);
      case "deny": return decide(b.closest(".ai-pend"), false);
      case "speak": S.speak = !S.speak; ss.set(KEY.speak, S.speak); if (!S.speak) stopAudio(); return speakBtn();
      case "stop-audio": return stopAudio();
      case "mic": return startRec();
      case "rec-stop": return stopRec(true);
      case "rec-cancel": return stopRec(false);
    }
  }

  /* ---------- voice in: tap to start, tap to stop (max 28 s) ---------- */
  async function startRec() {
    if (S.rec || S.busy) return;
    stopAudio();
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch (err) {
      const denied = err && (err.name === "NotAllowedError" || err.name === "SecurityError");
      notify(denied ? "Microphone is blocked. Allow it in the browser's site settings, or type instead." : "No microphone found. You can type instead.", "mic-off");
      return;
    }
    const type = MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
    const mr = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const R = S.rec = { mr, stream, chunks: [], t0: Date.now(), send: true };
    mr.ondataavailable = (ev) => { if (ev.data && ev.data.size) R.chunks.push(ev.data); };
    mr.onstop = () => finishRec(R);
    mr.start(250);
    try { // level meter
      const ac = R.ac = new (window.AudioContext || window.webkitAudioContext)(), an = ac.createAnalyser();
      an.fftSize = 64; ac.createMediaStreamSource(stream).connect(an);
      const buf = new Uint8Array(an.frequencyBinCount);
      const tick = () => { if (S.rec !== R) return; an.getByteFrequencyData(buf);
        el.bars.forEach((b, i) => { b.style.transform = `scaleY(${0.15 + (buf[(i + 2) % buf.length] / 255) * 0.85})`; }); R.raf = requestAnimationFrame(tick); };
      tick();
    } catch (e) {}
    R.timer = setInterval(() => {
      const s = Math.floor((Date.now() - R.t0) / 1000);
      el.time.textContent = `0:${String(s).padStart(2, "0")} / 0:${MAX_REC}`;
      if (s >= MAX_REC) stopRec(true);
    }, 200);
    el.time.textContent = `0:00 / 0:${MAX_REC}`;
    el.row.hidden = true; el.recbar.hidden = false; el.panel.classList.add("rec");
    icons();
  }
  function stopRec(send) {
    const R = S.rec; if (!R) return;
    R.send = send;
    clearInterval(R.timer); cancelAnimationFrame(R.raf);
    try { R.ac && R.ac.close(); } catch (e) {}
    R.stream.getTracks().forEach((t) => t.stop());
    if (R.mr.state !== "inactive") R.mr.stop(); else finishRec(R);
    S.rec = null;
    el.row.hidden = false; el.recbar.hidden = true; el.panel.classList.remove("rec");
  }
  async function finishRec(R) {
    if (R.done) return; R.done = true;
    if (!R.send || !R.chunks.length) return;
    if (S.speak == null) { S.speak = true; ss.set(KEY.speak, true); speakBtn(); } // voice replies default on after first mic use
    const blob = new Blob(R.chunks, { type: R.mr.mimeType || "audio/webm" });
    el.ta.value = ""; el.ta.placeholder = "Transcribing…"; el.mic.disabled = true;
    let t;
    try { t = await api.upload("/api/voice/stt", new File([blob], "voice.webm", { type: blob.type })); }
    catch (err) { notify(limited(err) ? err.detail || err.message : "Could not understand the recording. Try again or type.", limited(err) ? "timer" : "mic-off"); }
    el.ta.placeholder = "Ask anything, or tap the mic"; el.mic.disabled = false;
    const text = t && (t.transcript || "").trim();
    if (!t) return;
    if (!text) { notify("I didn't catch that. Try again a little closer to the mic.", "mic-off"); return; }
    if (t.language_code) { S.lang = t.language_code; ss.set(KEY.lang, S.lang); }
    ask(text, null, true);
  }

  /* ---------- voice out ---------- */
  async function say(text) {
    stopAudio();
    const clean = String(text).replace(/\*\*|`|#+\s/g, "").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").slice(0, 1500);
    const my = S.say = {};
    let r;
    try { r = await api.post("/api/voice/tts", { text: clean, language_code: S.lang || undefined }); }
    catch (e) { if (limited(e) && S.say === my) notify(e.detail || e.message, "timer"); return; }
    if (S.say !== my || !r || !r.audio_base64) return;
    const a = S.audio = new Audio(`data:audio/${r.format || "mp3"};base64,${r.audio_base64}`);
    const done = () => { if (S.audio === a) { S.audio = null; el.speaking.hidden = true; } };
    a.onended = done; a.onerror = done;
    el.speaking.hidden = false; icons();
    a.play().catch(done);
  }
  function stopAudio() {
    S.say = null;
    if (S.audio) { try { S.audio.pause(); } catch (e) {} S.audio = null; }
    if (el.speaking) el.speaking.hidden = true;
  }

  BR.assistant = { open: () => { if (!el.panel) mount(); open(); }, close: () => el.panel && close(), ask: (text, ctx) => ask(text, ctx) };
  if (!GUEST) BR.askAI = (ctx) => {
    const c = Object.assign({ page: "report", profile_id: BR.state && BR.state.profileId }, ctx || {});
    return ask(EXPLAIN, { assessment_id: c.assessment_id, tender_id: c.tender_id, profile_id: c.profile_id, page: c.page });
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount); else mount();
})();

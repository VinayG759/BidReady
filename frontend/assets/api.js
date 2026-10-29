/* BidReady API client. Same origin when served by FastAPI; falls back to :8000 when the page is opened another way. */
(function(){
  "use strict";
  const BASE = location.port === "8000" ? "" : "http://localhost:8000";
  async function req(method, path, body, isForm){
    const opt = { method, headers: {} };
    if (BR.auth && BR.auth.getToken) {
      const token = await BR.auth.getToken();
      if (token) opt.headers.Authorization = "Bearer " + token;
    }
    if (body !== undefined) {
      if (isForm) opt.body = body;
      else { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    }
    const res = await fetch(BASE + path, opt);
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
    if (!res.ok) throw new Error((data && data.detail) || ("HTTP " + res.status));
    return data;
  }
  window.BR = window.BR || {};
  BR.api = {
    get: p => req("GET", p),
    post: (p, b) => req("POST", p, b || {}),
    put: (p, b) => req("PUT", p, b || {}),
    upload: (p, file) => { const f = new FormData(); f.append("file", file); return req("POST", p, f, true); }
  };
})();

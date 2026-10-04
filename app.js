/* InEra All-in-One Plugins — web client (no build step, no external requests). */
"use strict";
(() => {
  const S = { config: null, user: null, plugins: null, attach: [], jobId: null, poll: null, draft: "" };
  const ACTIVE = ["queued", "planning", "running"];

  /* ================================================================ helpers */
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
        else if (v === true) el.setAttribute(k, "");
        else el.setAttribute(k, String(v));
      }
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  const $ = (sel, root = document) => root.querySelector(sel);

  const ICONS = {
    solve: "M12 3v4|M12 17v4|M3 12h4|M17 12h4|M6.3 6.3l2.8 2.8|M14.9 14.9l2.8 2.8|M6.3 17.7l2.8-2.8|M14.9 9.1l2.8-2.8",
    runs: "M4 6h16|M4 12h16|M4 18h10",
    clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z|M12 7v5l3 2",
    folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
    grid: "M4 4h7v7H4z|M13 4h7v7h-7z|M4 13h7v7H4z|M13 13h7v7h-7z",
    link: "M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1|M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1",
    user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z|M4 21a8 8 0 0 1 16 0",
    clip: "M21 11.5l-8.5 8.5a5 5 0 0 1-7-7l8.5-8.5a3.5 3.5 0 0 1 5 5L10.5 18a2 2 0 0 1-3-3l7.5-7.5",
    play: "M7 5l12 7-12 7z",
    download: "M12 4v12|M7 11l5 5 5-5|M5 20h14",
    eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z|M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
    trash: "M4 7h16|M9 7V4h6v3|M6 7l1 13h10l1-13",
    x: "M6 6l12 12|M18 6L6 18",
    menu: "M4 7h16|M4 12h16|M4 17h16",
    doc: "M7 3h7l5 5v13H7z|M14 3v5h5",
    image: "M4 5h16v14H4z|M4 16l5-5 4 4 3-3 4 4|M15 9.5h.01",
    video: "M4 6h12v12H4z|M16 10l5-3v10l-5-3",
    mic: "M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z|M5 11a7 7 0 0 0 14 0|M12 18v3",
    zip: "M7 3h10v18H7z|M12 5v2|M12 9v2|M12 13v2",
    quiz: "M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14|M12 17.5v.5|M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
    cards: "M4 8h12v12H4z|M8 4h12v12",
    globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z|M3 12h18|M12 3c3 3.5 3 14.5 0 18|M12 3c-3 3.5-3 14.5 0 18",
    mail: "M3 6h18v12H3z|M3 7l9 6 9-6",
    instagram: "M7 3h10a4 4 0 0 1 4 4v10a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V7a4 4 0 0 1 4-4z|M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z|M17.5 6.5h.01",
    chart: "M4 20V10|M10 20V4|M16 20v-7|M22 20H2",
    table: "M3 5h18v14H3z|M3 10h18|M3 15h18|M9 5v14",
    pen: "M4 20l4-1 11-11-3-3L5 16z|M14 6l3 3",
    book: "M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z|M4 19V5",
    code: "M8 8l-4 4 4 4|M16 8l4 4-4 4|M14 5l-4 14",
    qr: "M4 4h6v6H4z|M14 4h6v6h-6z|M4 14h6v6H4z|M14 14h2v2h-2z|M18 18h2v2h-2z|M18 14h2v2|M14 18v2h2",
    lock: "M6 11h12v10H6z|M8 11V8a4 4 0 0 1 8 0v3",
    unlock: "M6 11h12v10H6z|M8 11V8a4 4 0 0 1 7.5-2",
    send: "M4 12l16-8-6 16-2-6z",
    chat: "M4 5h16v11H9l-5 4z",
    list: "M8 6h12|M8 12h12|M8 18h12|M4 6h.01|M4 12h.01|M4 18h.01",
    wand: "M4 20L16 8|M14 4l1 2 2 1-2 1-1 2-1-2-2-1 2-1z|M19 11l.7 1.3L21 13l-1.3.7L19 15l-.7-1.3L17 13l1.3-.7z",
    language: "M4 5h9|M8.5 3v2|M6 5c0 4 3 7 6 8|M11 5c0 4-3 8-7 9|M13 21l4-9 4 9|M14.5 18h5",
    calendar: "M4 6h16v15H4z|M4 10h16|M8 3v4|M16 3v4",
    mindmap: "M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z|M5 6a2 2 0 1 0 0-.01|M19 6a2 2 0 1 0 0-.01|M5 18a2 2 0 1 0 0-.01|M19 18a2 2 0 1 0 0-.01|M10.5 10.5L6.5 7|M13.5 10.5l4-3.5|M10.5 13.5l-4 3.5|M13.5 13.5l4 3.5",
    merge: "M6 4v5a6 6 0 0 0 6 6h6|M15 12l3 3-3 3|M6 20v-5",
    split: "M12 4v6|M12 10l-6 6v4|M12 10l6 6v4",
    rotate: "M20 12a8 8 0 1 1-2.3-5.7|M20 4v4h-4",
    compress: "M4 9h5V4|M20 9h-5V4|M4 15h5v5|M20 15h-5v5",
    stamp: "M9 4h6l-1 7h4l1 4H5l1-4h4z|M5 20h14",
    hash: "M9 4L7 20|M17 4l-2 16|M4 9h16|M3 15h16",
    scan: "M4 8V4h4|M16 4h4v4|M20 16v4h-4|M8 20H4v-4|M7 12h10",
    text: "M5 6h14|M12 6v13|M9 19h6",
    receipt: "M6 3h12v18l-3-2-3 2-3-2-3 2z|M9 8h6|M9 12h6",
    slides: "M3 5h18v11H3z|M12 16v4|M8 20h8",
    "file-pdf": "M7 3h7l5 5v13H7z|M14 3v5h5|M9 14h6|M9 17h4",
    "file-word": "M7 3h7l5 5v13H7z|M14 3v5h5|M9 12l1 5 2-3 2 3 1-5",
    spark: "M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z",
    check: "M5 12l5 5 9-10",
    plus: "M12 5v14|M5 12h14",
    refresh: "M20 12a8 8 0 1 1-2.3-5.7|M20 4v4h-4",
    pause: "M8 5v14|M16 5v14",
    out: "M14 4h6v6|M20 4l-9 9|M18 14v6H4V6h6",
  };
  function icon(name, cls) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.7");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    if (cls) svg.setAttribute("class", cls);
    for (const d of (ICONS[name] || ICONS.spark).split("|")) {
      const p = document.createElementNS(ns, "path");
      p.setAttribute("d", d);
      svg.append(p);
    }
    return svg;
  }

  function csrf() {
    const m = document.cookie.match(/(?:^|; )inera_csrf=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }
  async function api(path, opts = {}) {
    const init = { method: opts.method || "GET", headers: {}, credentials: "same-origin" };
    if (init.method !== "GET") init.headers["X-CSRF-Token"] = csrf();
    if (opts.form) init.body = opts.form;
    else if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    let r;
    try { r = await fetch(path, init); } catch (e) { throw new Error("Can't reach the server. Check your connection."); }
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    if (!r.ok) {
      if (r.status === 401 && S.user && !opts.quiet) { S.user = null; renderAuth("login"); }
      let msg = data && data.detail;
      if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
      throw new Error(msg || `Request failed (${r.status}).`);
    }
    return data;
  }

  function toast(msg, isErr) {
    const t = h("div", { class: "toast" + (isErr ? " err" : ""), text: msg });
    $("#toast").append(t);
    setTimeout(() => t.remove(), isErr ? 7000 : 4200);
  }
  function modal(title, body, actions) {
    const back = h("div", { class: "modal-back", role: "dialog", "aria-modal": "true", "aria-label": title });
    const close = () => { back.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    back.addEventListener("click", (e) => { if (e.target === back) close(); });
    const box = h("div", { class: "modal" }, h("h2", { text: title }), body,
      h("div", { class: "row" }, h("span", { class: "spacer" }), ...(actions ? actions(close) : [h("button", { class: "btn", onclick: close }, "Close")])));
    back.append(box);
    document.body.append(back);
    const f = box.querySelector("input, button, textarea, select");
    if (f) f.focus();
    return close;
  }

  const tz = () => (S.user && S.user.profile && S.user.profile.timezone) || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  function fmtTime(ts, withDate = true) {
    if (!ts) return "—";
    const opts = withDate ? { dateStyle: "medium", timeStyle: "short" } : { timeStyle: "medium" };
    try { return new Intl.DateTimeFormat(undefined, { ...opts, timeZone: tz() }).format(new Date(ts * 1000)); }
    catch (e) { return new Date(ts * 1000).toLocaleString(); }
  }
  function ago(ts) {
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    return fmtTime(ts);
  }
  function size(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1048576) return `${(n / 1024).toFixed(0)} KB`;
    return `${(n / 1048576).toFixed(1)} MB`;
  }
  const STATUS = {
    queued: ["Queued", ""], planning: ["Planning", "gilt"], running: ["Working", "gilt"], completed: ["Done", "ok"],
    completed_with_errors: ["Done with issues", "warn"], failed: ["Failed", "err"], cancelled: ["Cancelled", ""],
    awaiting_approval: ["Needs your approval", "warn"],
  };
  const statusBadge = (s) => h("span", { class: "badge " + ((STATUS[s] || [s, ""])[1]) }, (STATUS[s] || [s])[0]);

  /* safe mini-markdown: everything is escaped first, then a fixed set of tags is added */
  function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function inline(s) {
    return esc(s.replace(/!\[[^\]]*\]\([^)]*\)/g, ""))
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*\w])\*(?!\s)(.+?)\*(?!\w)/g, "$1<em>$2</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  }
  function markdown(src) {
    const lines = String(src).replace(/\r/g, "").split("\n");
    const out = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const t = line.trim();
      if (!t) { i++; continue; }
      let m;
      if ((m = t.match(/^(#{1,3})\s+(.*)$/))) { out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`); i++; continue; }
      if (/^\|.*\|$/.test(t)) {
        const rows = [];
        while (i < lines.length && /^\|.*\|$/.test(lines[i].trim())) { rows.push(lines[i].trim()); i++; }
        const cells = rows.filter((r) => !/^\|\s*:?-{2,}/.test(r)).map((r) => r.slice(1, -1).split("|").map((c) => c.trim()));
        if (cells.length) {
          out.push("<table><thead><tr>" + cells[0].map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>" +
            cells.slice(1).map((r) => "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") + "</tbody></table>");
        }
        continue;
      }
      if (/^\s*[-*•]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
        const ordered = /^\s*\d+[.)]\s+/.test(line);
        const items = [];
        while (i < lines.length && (ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*•]\s+/).test(lines[i])) {
          items.push(lines[i].replace(/^\s*(?:[-*•]|\d+[.)])\s+/, "")); i++;
        }
        out.push((ordered ? "<ol>" : "<ul>") + items.map((x) => `<li>${inline(x)}</li>`).join("") + (ordered ? "</ol>" : "</ul>"));
        continue;
      }
      if (t.startsWith(">")) { out.push(`<blockquote>${inline(t.replace(/^>\s?/, ""))}</blockquote>`); i++; continue; }
      const para = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,3}\s|\||>|\s*[-*•]\s|\s*\d+[.)]\s)/.test(lines[i])) { para.push(lines[i].trim()); i++; }
      if (para.length) out.push(`<p>${inline(para.join(" "))}</p>`);
      else i++;
    }
    return out.join("\n");
  }

  /* ================================================================ boot */
  async function boot() {
    try {
      S.config = await api("/api/config");
    } catch (e) {
      $("#app").replaceChildren(h("div", { class: "boot" }, h("p", { text: e.message })));
      return;
    }
    S.user = S.config.user;
    if (S.user) startApp();
    else renderAuth(location.hash === "#/register" ? "register" : "login");
  }

  /* ================================================================ auth */
  const INDUSTRIES = ["Automobile", "Food & Restaurant", "Fashion", "Real Estate", "Education & Coaching", "Fitness",
    "Healthcare", "Beauty & Wellness", "Technology", "Retail", "Finance & Accounting", "Travel", "Other"];
  const VOICES = ["Friendly expert", "Professional and calm", "Bold and energetic", "Luxury and refined", "Warm and local", "Playful"];

  function privacyNotice() {
    modal("Privacy & terms", h("div", { class: "stack" },
      h("p", { text: "This InEra server stores your account, business details, uploaded files, generated outputs and run history so it can work for you. Passwords are hashed and connection secrets are encrypted at rest." }),
      h("p", { text: "Nothing is sent to other services unless you ask for it: posting to Instagram, sending e-mail or messages uses only the connections you add, and web research fetches public pages. If the server owner configured an AI engine, your problem text and source material are sent to that engine to generate content." }),
      h("p", { text: `Generated files are kept for ${S.config && S.config.limits ? "a limited period set by the server owner" : "a limited period"} and you can export or delete all your data at any time from Profile.` }),
      h("p", { text: "Use InEra lawfully: only post or send content you have the rights to, only e-mail people who expect to hear from you, and follow the terms of the platforms you connect." })));
  }

  function renderAuth(mode) {
    stopPoll();
    const app = $("#app");
    const ns = "http://www.w3.org/2000/svg";
    const orbit = document.createElementNS(ns, "svg");
    orbit.setAttribute("class", "orbit");
    orbit.setAttribute("viewBox", "0 0 400 300");
    orbit.setAttribute("aria-hidden", "true");
    for (const [rx, ry, rot] of [[190, 70, -18], [175, 58, -24]]) {
      const e = document.createElementNS(ns, "ellipse");
      e.setAttribute("cx", "200"); e.setAttribute("cy", "135");
      e.setAttribute("rx", rx); e.setAttribute("ry", ry);
      e.setAttribute("transform", `rotate(${rot} 200 135)`);
      orbit.append(e);
    }
    const brandSide = h("section", { class: "auth-brand" },
      h("div", { class: "auth-emblem" }, orbit, h("img", { src: "/logo.svg", alt: "InEra", width: 300, height: 315 })),
      h("h1", { text: "One problem in, finished work out." }),
      h("p", { class: "lede", text: "Describe what you need in plain words. InEra chooses the right built-in plugins, runs them for you and keeps repeating the job on schedule." }),
      h("ul", {},
        h("li", { text: "Study notebooks, quizzes, flashcards, podcasts and explainer videos" }),
        h("li", { text: "PDF, Word, PowerPoint and Excel — created, converted, merged and signed off" }),
        h("li", { text: "Daily Instagram posts, e-mails and reports that run while you sleep" })));
    const panel = h("section", { class: "auth-panel" });
    app.replaceChildren(h("main", { class: "auth" }, brandSide, panel));
    if (mode === "register") registerForm(panel, 1, {});
    else loginForm(panel);
  }

  function loginForm(panel) {
    history.replaceState(null, "", "#/login");
    const err = h("p", { class: "form-error", role: "alert" });
    const form = h("form", { class: "stack", novalidate: true },
      h("label", { class: "field" }, h("span", { text: "E-mail" }), h("input", { type: "email", name: "email", autocomplete: "email", required: true })),
      h("label", { class: "field" }, h("span", { text: "Password" }), h("input", { type: "password", name: "password", autocomplete: "current-password", required: true })),
      err, h("button", { class: "btn primary", type: "submit" }, "Sign in"));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      err.textContent = "";
      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      try {
        const r = await api("/api/auth/login", { method: "POST", body: { email: form.email.value, password: form.password.value } });
        S.user = r.user;
        startApp();
      } catch (ex) { err.textContent = ex.message; btn.disabled = false; }
    });
    const card = h("div", { class: "auth-card" },
      h("h2", { text: "Welcome back" }),
      h("p", { class: "muted", text: "Sign in to continue where you left off." }), form);
    if (S.config.registration) {
      card.append(h("p", { class: "auth-switch" }, "New here? ",
        h("button", { type: "button", onclick: () => { panel.replaceChildren(); registerForm(panel, 1, {}); } }, "Create an account")));
    }
    panel.replaceChildren(card);
    form.email.focus();
  }

  function registerForm(panel, step, data) {
    history.replaceState(null, "", "#/register");
    const err = h("p", { class: "form-error", role: "alert" });
    const ind = h("div", { class: "steps-indicator", "aria-hidden": "true" }, h("i", { class: "on" }), h("i", { class: step === 2 ? "on" : "" }));
    let form;
    if (step === 1) {
      form = h("form", { class: "stack", novalidate: true },
        h("label", { class: "field" }, h("span", { text: "Your name" }), h("input", { type: "text", name: "name", autocomplete: "name", value: data.name || "", required: true })),
        h("label", { class: "field" }, h("span", { text: "E-mail" }), h("input", { type: "email", name: "email", autocomplete: "email", value: data.email || "", required: true })),
        h("label", { class: "field" }, h("span", { text: "Password" }), h("input", { type: "password", name: "password", autocomplete: "new-password", required: true }),
          h("span", { class: "hint", text: "At least 10 characters, mixing letters with numbers or symbols." })),
        err, h("button", { class: "btn primary", type: "submit" }, "Continue"));
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        const name = form.name.value.trim(), email = form.email.value.trim(), password = form.password.value;
        if (name.length < 2) return (err.textContent = "Enter your name.");
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return (err.textContent = "Enter a valid e-mail address.");
        if (password.length < 10) return (err.textContent = "Password must be at least 10 characters.");
        panel.replaceChildren();
        registerForm(panel, 2, { ...data, name, email, password });
      });
    } else {
      const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      const country = zone === "Asia/Calcutta" || zone === "Asia/Kolkata" ? "India" : "";
      form = h("form", { class: "stack", novalidate: true },
        h("label", { class: "field" }, h("span", { text: "Business or brand name" }), h("input", { type: "text", name: "business_name", required: true, placeholder: "Use your own name if you work solo" })),
        h("div", { class: "grid-2" },
          h("label", { class: "field" }, h("span", { text: "Industry" }), h("select", { name: "industry" }, INDUSTRIES.map((x) => h("option", { value: x }, x)))),
          h("label", { class: "field" }, h("span", { text: "Brand voice" }), h("select", { name: "brand_voice" }, VOICES.map((x) => h("option", { value: x }, x))))),
        h("label", { class: "field" }, h("span", { text: "What do you do?" }), h("textarea", { name: "description", rows: 2, placeholder: "e.g. Car servicing and detailing studio in Belagavi" })),
        h("div", { class: "grid-2" },
          h("label", { class: "field" }, h("span", { text: "City" }), h("input", { type: "text", name: "city" })),
          h("label", { class: "field" }, h("span", { text: "Country" }), h("input", { type: "text", name: "country", value: country }))),
        h("div", { class: "grid-2" },
          h("label", { class: "field" }, h("span", { text: "Instagram handle" }), h("input", { type: "text", name: "instagram", placeholder: "@yourbrand" })),
          h("label", { class: "field" }, h("span", { text: "Business phone" }), h("input", { type: "text", name: "phone", autocomplete: "tel" }))),
        h("p", { class: "hint", text: `Time zone: ${zone}. Schedules run in this time zone; you can change it later in Profile.` }),
        h("label", { class: "check" }, h("input", { type: "checkbox", name: "accept" }),
          h("span", {}, "I'll use InEra lawfully and I accept the ", h("a", { href: "#", onclick: (e) => { e.preventDefault(); privacyNotice(); } }, "privacy notice and terms"), ".")),
        err,
        h("div", { class: "row" },
          h("button", { class: "btn", type: "button", onclick: () => { panel.replaceChildren(); registerForm(panel, 1, data); } }, "Back"),
          h("span", { class: "spacer" }),
          h("button", { class: "btn primary", type: "submit" }, "Create my workspace")));
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        err.textContent = "";
        if (!form.business_name.value.trim()) return (err.textContent = "Tell us your business or brand name.");
        if (!form.accept.checked) return (err.textContent = "Please accept the privacy notice and terms.");
        const btn = form.querySelector("button[type=submit]");
        btn.disabled = true;
        const profile = { timezone: zone };
        for (const k of ["business_name", "industry", "brand_voice", "description", "city", "country", "instagram", "phone"]) profile[k] = form[k].value.trim();
        profile.instagram = profile.instagram.replace(/^@/, "");
        try {
          const r = await api("/api/auth/register", { method: "POST", body: { name: data.name, email: data.email, password: data.password, accept_terms: true, profile } });
          S.user = r.user;
          location.hash = "#/solve";
          startApp();
          toast("Your workspace is ready. Describe your first problem.");
        } catch (ex) {
          err.textContent = ex.message;
          btn.disabled = false;
          if (/password|e-mail|name/i.test(ex.message)) { panel.replaceChildren(); registerForm(panel, 1, data); setTimeout(() => toast(ex.message, true), 50); }
        }
      });
    }
    panel.replaceChildren(h("div", { class: "auth-card" },
      h("h2", { text: step === 1 ? "Create your account" : "Tell InEra about your work" }),
      h("p", { class: "muted", text: step === 1 ? "Step 1 of 2: your sign-in details." : "Step 2 of 2: these details shape every post, document and invoice InEra makes for you." }),
      ind, form,
      step === 1 ? h("p", { class: "auth-switch" }, "Already have an account? ",
        h("button", { type: "button", onclick: () => loginForm(panel) }, "Sign in")) : null));
    const first = form.querySelector("input, select");
    if (first) first.focus();
  }

  /* ================================================================ shell */
  const NAV = [
    ["solve", "Solve", "solve"], ["runs", "Runs", "runs"], ["automations", "Automations", "clock"],
    ["library", "Library", "folder"], ["plugins", "Plugins", "grid"], ["connections", "Connections", "link"],
    ["profile", "Profile", "user"],
  ];

  function startApp() {
    const sidebar = h("aside", { class: "sidebar", id: "sidebar" },
      h("a", { class: "brand", href: "#/solve" }, h("img", { src: "/logo_mark.svg", alt: "", width: 46, height: 34 }),
        h("span", {}, h("b", { text: "InEra" }), h("small", { text: "All-in-One Plugins" }))),
      h("nav", { class: "nav", "aria-label": "Main" }, NAV.map(([id, label, ic]) =>
        h("a", { href: `#/${id}`, "data-route": id }, icon(ic), h("span", { text: label })))),
      h("div", { class: "sidebar-foot" }, engineCard(), whoCard()));
    const top = h("header", { class: "topbar" },
      h("button", { class: "btn quiet", "aria-label": "Open menu", onclick: () => sidebar.classList.toggle("open") }, icon("menu")),
      h("img", { src: "/logo_mark.svg", alt: "" }), h("b", { text: "InEra" }));
    const main = h("main", { class: "main", id: "main", tabindex: "-1" });
    $("#app").replaceChildren(h("div", { class: "shell" }, sidebar, h("div", {}, top, main)));
    sidebar.addEventListener("click", (e) => { if (e.target.closest("a")) sidebar.classList.remove("open"); });
    if (!location.hash || location.hash === "#/login" || location.hash === "#/register") location.hash = "#/solve";
    route();
    refreshApprovals();
  }

  function engineCard() {
    const e = S.config.engine || {};
    return h("div", { class: "engine", title: e.online ? "Plugins use this AI engine for writing and planning." : "No AI engine is configured on this server. Plugins use the built-in offline engine; the server owner can add Ollama or an API key." },
      h("span", { class: "small" }, "AI engine"),
      h("strong", {}, h("i", { class: "dot" + (e.online ? " on" : "") }), e.online ? e.label : "Built-in offline engine"));
  }
  function whoCard() {
    const u = S.user;
    return h("div", { class: "who" }, h("span", { class: "avatar", text: (u.name || "?").trim().charAt(0).toUpperCase() }),
      h("div", {}, h("b", { text: u.name }), h("span", { text: (u.profile && u.profile.business_name) || u.email })));
  }
  async function refreshApprovals() {
    try {
      const r = await api("/api/automations", { quiet: true });
      const waiting = r.automations.filter((a) => !a.approved).length;
      const link = $('.nav a[data-route="automations"]');
      if (!link) return;
      const old = link.querySelector(".count");
      if (old) old.remove();
      if (waiting) link.append(h("span", { class: "count", title: "Waiting for your approval", text: String(waiting) }));
    } catch (e) { /* ignore */ }
  }

  window.addEventListener("hashchange", () => { if (S.user) route(); });

  function route() {
    stopPoll();
    const parts = (location.hash.replace(/^#\/?/, "") || "solve").split("/");
    const name = parts[0];
    document.querySelectorAll(".nav a").forEach((a) => {
      a.classList.toggle("active", a.dataset.route === name);
      if (a.dataset.route === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    const main = $("#main");
    if (!main) return;
    const pages = { solve: pageSolve, runs: parts[1] ? () => pageRunDetail(parts[1]) : pageRuns, automations: pageAutomations,
      library: pageLibrary, plugins: pagePlugins, connections: pageConnections, profile: pageProfile };
    const fn = pages[name] || pageSolve;
    main.replaceChildren();
    window.scrollTo(0, 0);
    Promise.resolve(fn(main)).catch((e) => main.append(h("p", { class: "form-error", text: e.message })));
  }

  function head(title, sub, ...actions) {
    return h("header", { class: "page-head" }, h("div", {}, h("h1", { text: title }), sub ? h("p", { text: sub }) : null),
      h("span", { class: "spacer" }), ...actions);
  }

  /* ================================================================ solve */
  function examples() {
    const p = S.user.profile || {};
    const ind = (p.industry && p.industry !== "Other") ? p.industry.toLowerCase() : "my business";
    return [
      `Every day at 8 am, design and post ${/^[aeiou]/.test(ind) ? "an" : "a"} ${ind} tip with an image and caption on my Instagram`,
      "Make a study notebook on photosynthesis with a quiz, flashcards, a mind map and a video",
      "Convert the attached PDF to an editable Word document",
      "Analyze the attached sales CSV and show me the trends",
      "Plan 30 days of Instagram content for my business",
      `Invoice for Ravi Motors: brake pads 2 x 1500, wheel alignment 800, 18% GST`,
      "Build a one-page website for my business",
      "Merge the attached PDFs, add page numbers and a DRAFT watermark",
    ];
  }

  function pageSolve(main) {
    const first = (S.user.name || "").split(" ")[0];
    const hr = new Date().getHours();
    const greet = hr < 12 ? "Good morning" : hr < 17 ? "Good afternoon" : "Good evening";
    const ta = h("textarea", { id: "problem", rows: 4, "aria-label": "Describe your problem",
      placeholder: "Describe the problem you want solved. Example: every Monday at 9 am e-mail me a PDF summary of the attached report." });
    ta.value = S.draft || "";
    const chips = h("div", { class: "attachments" });
    const fileInput = h("input", { type: "file", multiple: true, class: "sr-only", id: "file-input", tabindex: "-1" });
    const runBtn = h("button", { class: "btn primary", type: "button" }, icon("play"), "Run");
    const planBtn = h("button", { class: "btn quiet", type: "button" }, "Preview plan");
    const planBox = h("div");
    const composer = h("section", { class: "composer", "aria-label": "Problem statement" }, ta, chips,
      h("div", { class: "composer-bar" },
        h("button", { class: "btn small", type: "button", onclick: () => fileInput.click() }, icon("clip"), "Attach files"),
        h("button", { class: "btn small quiet", type: "button", onclick: pickFromLibrary }, "From library"),
        fileInput, h("span", { class: "spacer" }),
        h("span", { class: "kbd", text: "Enter runs it, Shift + Enter adds a line" }), planBtn, runBtn));
    const runArea = h("div", { id: "run-area" });

    function drawChips() {
      chips.replaceChildren(...S.attach.map((f, i) => h("span", { class: "chip" + (f.uploading ? " uploading" : ""), title: f.name },
        h("span", { text: f.uploading ? `Uploading ${f.name}…` : f.name }),
        f.uploading ? null : h("button", { type: "button", "aria-label": `Remove ${f.name}`, onclick: () => { S.attach.splice(i, 1); drawChips(); } }, icon("x")))));
    }
    async function upload(files) {
      if (!files || !files.length) return;
      const list = Array.from(files);
      const max = (S.config.limits && S.config.limits.max_upload_mb) || 50;
      for (const f of list) if (f.size > max * 1048576) { toast(`${f.name} is larger than ${max} MB.`, true); return; }
      const temp = list.map((f) => ({ name: f.name, uploading: true }));
      S.attach.push(...temp);
      drawChips();
      const form = new FormData();
      list.forEach((f) => form.append("files", f, f.name));
      try {
        const r = await api("/api/files", { method: "POST", form });
        S.attach = S.attach.filter((x) => !temp.includes(x)).concat(r.files);
      } catch (e) {
        S.attach = S.attach.filter((x) => !temp.includes(x));
        toast(e.message, true);
      }
      drawChips();
    }
    async function pickFromLibrary() {
      let files;
      try { files = (await api("/api/files?origin=upload")).files; } catch (e) { return toast(e.message, true); }
      if (!files.length) return toast("Your library has no uploads yet. Attach files first.");
      const chosen = new Set(S.attach.map((f) => f.id));
      const pick = h("div", { class: "pick" }, files.map((f) => h("label", {},
        h("input", { type: "checkbox", value: f.id, checked: chosen.has(f.id) }), h("span", { text: `${f.name} (${size(f.size)})` }))));
      modal("Add files from your library", pick, (close) => [
        h("button", { class: "btn", onclick: close }, "Cancel"),
        h("button", { class: "btn primary", onclick: () => {
          const ids = Array.from(pick.querySelectorAll("input:checked")).map((x) => x.value);
          S.attach = S.attach.filter((f) => ids.includes(f.id) || f.uploading);
          for (const f of files) if (ids.includes(f.id) && !S.attach.some((a) => a.id === f.id)) S.attach.push(f);
          drawChips(); close();
        } }, "Add selected")]);
    }
    async function submit() {
      const problem = ta.value.trim();
      if (!problem) { ta.focus(); return toast("Describe the problem first.", true); }
      if (S.attach.some((f) => f.uploading)) return toast("Wait for the upload to finish.");
      runBtn.disabled = true;
      try {
        const r = await api("/api/run", { method: "POST", body: { problem, file_ids: S.attach.map((f) => f.id) } });
        S.jobId = r.job_id;
        S.draft = ""; ta.value = ""; S.attach = []; drawChips(); planBox.replaceChildren();
        showRun(runArea, r.job_id, true);
      } catch (e) { toast(e.message, true); }
      runBtn.disabled = false;
    }
    async function previewPlan() {
      const problem = ta.value.trim();
      if (!problem) return toast("Describe the problem first.", true);
      planBtn.disabled = true;
      try {
        const p = await api("/api/plan", { method: "POST", body: { problem, file_ids: S.attach.filter((f) => f.id).map((f) => f.id) } });
        planBox.replaceChildren(h("div", { class: "plan-preview" },
          h("strong", { text: p.summary }),
          h("div", { class: "tags" }, p.steps.map((s) => h("span", { class: "badge gilt" }, s.name))),
          p.notes.length ? h("ul", { class: "notes" }, p.notes.map((n) => h("li", { text: n }))) : null));
      } catch (e) { toast(e.message, true); }
      planBtn.disabled = false;
    }
    ta.addEventListener("input", () => { S.draft = ta.value; });
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); } });
    runBtn.addEventListener("click", submit);
    planBtn.addEventListener("click", previewPlan);
    fileInput.addEventListener("change", () => { upload(fileInput.files); fileInput.value = ""; });
    composer.addEventListener("dragover", (e) => { e.preventDefault(); composer.classList.add("drag"); });
    composer.addEventListener("dragleave", () => composer.classList.remove("drag"));
    composer.addEventListener("drop", (e) => { e.preventDefault(); composer.classList.remove("drag"); upload(e.dataTransfer.files); });

    main.append(h("div", { class: "page" },
      h("p", { class: "greeting", text: `${greet}, ${first}.` }),
      h("h1", { text: "What should InEra take care of?" }),
      composer, planBox,
      h("section", { class: "examples" }, h("h2", { text: "Start from an example" }),
        h("div", { class: "example-list" }, examples().map((x) => h("button", { class: "example", type: "button",
          onclick: () => { ta.value = x; S.draft = x; ta.focus(); } }, x)))),
      runArea));
    drawChips();
    if (S.jobId) showRun(runArea, S.jobId, false);
    ta.focus();
  }

  /* ================================================================ run view */
  function stopPoll() { if (S.poll) { clearTimeout(S.poll); S.poll = null; } }

  async function showRun(container, jobId, scroll) {
    stopPoll();
    const view = { root: h("section", { class: "run", "aria-label": "Current run" }), rendered: new Set(), lastLog: -1 };
    container.replaceChildren(view.root);
    let first = true;
    const tick = async () => {
      let job;
      try { job = await api(`/api/jobs/${jobId}`); } catch (e) { view.root.replaceChildren(h("p", { class: "form-error", text: e.message })); return; }
      if (!view.root.isConnected) return;
      renderRun(view, job);
      if (first && scroll) view.root.scrollIntoView({ behavior: "smooth", block: "start" });
      first = false;
      if (ACTIVE.includes(job.status)) S.poll = setTimeout(tick, 1100);
      else if (job.automation_created) refreshApprovals();
    };
    tick();
  }

  const STEP_STATE = { pending: "Waiting", running: "Working", done: "Done", failed: "Failed", skipped: "Skipped",
    cancelled: "Cancelled", scheduled: "On schedule", awaiting_approval: "Needs approval" };

  function renderRun(view, job) {
    const r = view.root;
    if (!view.built) {
      view.head = h("div", { class: "run-head" });
      view.notes = h("ul", { class: "notes" });
      view.colonnade = h("div", { class: "colonnade", role: "list", "aria-label": "Plugins in this run" });
      view.progress = h("div", { class: "progress-line" }, h("i"));
      view.extra = h("div");
      view.errors = h("div", { class: "step-errors" });
      view.outTitle = h("h3", { text: "Results" });
      view.outList = h("div", { class: "out-list" });
      view.outputs = h("div", { class: "outputs" }, view.outTitle, view.outList);
      view.logList = h("ol");
      view.log = h("details", { class: "log" }, h("summary", { text: "Activity log" }), view.logList);
      r.append(view.head, view.notes, view.colonnade, view.progress, view.extra, view.errors, view.outputs, view.log);
      view.built = true;
    }
    const plan = job.plan || { steps: [] };
    const active = ACTIVE.includes(job.status);
    view.head.replaceChildren(...[
      h("div", {}, h("h2", { text: job.title || plan.title || "Your run" }),
        h("p", { class: "summary", text: plan.summary || (active ? "Choosing the right plugins…" : job.problem) })),
      h("span", { class: "spacer" }), statusBadge(job.status),
      active ? h("button", { class: "btn small danger", onclick: async () => {
        try { await api(`/api/jobs/${job.id}/cancel`, { method: "POST" }); toast("Cancelling…"); } catch (e) { toast(e.message, true); }
      } }, "Cancel") : null].filter(Boolean));
    view.notes.replaceChildren(...(plan.notes || []).map((n) => h("li", { text: n })));
    view.colonnade.replaceChildren(...plan.steps.map((s) => h("div", { class: `pillar ${s.status}`, role: "listitem",
      title: s.error || s.name },
      h("div", { class: "col", "aria-hidden": "true" }, h("div", { class: "cap" }), h("div", { class: "shaft" }, h("div", { class: "fill" })), h("div", { class: "base" })),
      h("span", { class: "name", text: s.name }),
      h("span", { class: "state", text: (STEP_STATE[s.status] || s.status) + (s.seconds && s.status === "done" ? ` in ${s.seconds}s` : "") }))));
    view.progress.firstChild.style.width = `${Math.round((job.progress || 0) * 100)}%`;
    view.progress.hidden = !active;

    const extra = [];
    if (job.status === "awaiting_approval") {
      const waiting = plan.steps.find((s) => s.status === "awaiting_approval");
      extra.push(h("div", { class: "approval" },
        h("h3", { text: `Ready for ${waiting ? waiting.name : "the next step"}` }),
        h("p", { class: "muted", text: "This step acts on your behalf outside InEra. Check the results below, then approve. You can switch on automatic approval in Profile." }),
        h("div", { class: "row" },
          h("button", { class: "btn primary", onclick: async (e) => {
            e.target.disabled = true;
            try { await api(`/api/jobs/${job.id}/approve`, { method: "POST" }); showRun(view.root.parentElement, job.id, false); }
            catch (ex) { toast(ex.message, true); e.target.disabled = false; }
          } }, icon("check"), "Approve and continue"),
          h("button", { class: "btn", onclick: async () => {
            try { await api(`/api/jobs/${job.id}/cancel`, { method: "POST" }); showRun(view.root.parentElement, job.id, false); }
            catch (ex) { toast(ex.message, true); }
          } }, "Don't send"))));
    }
    if (job.automation_created) {
      extra.push(h("div", { class: "approval" },
        h("h3", { text: "Automation saved" }),
        h("p", { class: "muted", text: `${plan.schedule_text || "It will repeat on schedule"}. What you see below is a preview of one run. Manage it in Automations.` }),
        h("a", { class: "btn small", href: "#/automations" }, "Open Automations")));
    }
    if (job.instagram && job.instagram.permalink) {
      extra.push(h("p", {}, "Published on Instagram: ", h("a", { href: job.instagram.permalink, target: "_blank", rel: "noopener noreferrer", text: job.instagram.permalink })));
    }
    view.extra.replaceChildren(...extra);
    view.errors.replaceChildren(...plan.steps.filter((s) => s.error && s.status !== "skipped").map((s) =>
      h("div", { class: "step-error" }, h("b", { text: s.name + ": " }), s.error)));

    const outs = job.outputs || [];
    view.outputs.hidden = !outs.length;
    for (const o of outs) {
      const key = o.file_id || o.name;
      if (view.rendered.has(key)) continue;
      view.rendered.add(key);
      view.outList.append(outputCard(o));
    }
    const log = job.log || [];
    if (log.length !== view.lastLog) {
      view.lastLog = log.length;
      const start = log.length ? log[0].t : 0;
      view.logList.replaceChildren(...log.map((l) => h("li", { class: l.level },
        h("time", { text: `+${Math.max(0, l.t - start).toFixed(1)}s` }), h("span", { text: l.msg }))));
      view.logList.scrollTop = view.logList.scrollHeight;
    }
  }

  const KIND_ICON = { image: "image", video: "video", audio: "mic", pdf: "file-pdf", word: "file-word", slides: "slides",
    sheet: "table", zip: "zip", markdown: "book", text: "text", html: "globe", quiz: "quiz", flashcards: "cards", data: "doc" };

  function outputCard(o) {
    const src = `/api/files/${o.file_id}`;
    const body = h("div", { class: "out-body" });
    body.hidden = true;
    const toggle = async (builder, btn) => {
      if (!body.hidden) { body.hidden = true; body.replaceChildren(); btn.setAttribute("aria-expanded", "false"); return; }
      body.hidden = false;
      btn.setAttribute("aria-expanded", "true");
      body.replaceChildren(h("p", { class: "muted small", text: "Loading…" }));
      try { body.replaceChildren(await builder()); } catch (e) { body.replaceChildren(h("p", { class: "form-error", text: e.message })); }
    };
    const fetchText = async () => {
      const r = await fetch(src + "?inline=1", { credentials: "same-origin" });
      if (!r.ok) throw new Error("Couldn't open the file.");
      return r.text();
    };
    const acts = [];
    const mkBtn = (label, ic, builder) => {
      const b = h("button", { class: "btn small", type: "button", "aria-expanded": "false" }, icon(ic), label);
      b.addEventListener("click", () => toggle(builder, b));
      acts.push(b);
    };
    const thumb = o.kind === "image" && /\.(png|jpe?g|webp|gif)$/i.test(o.name)
      ? h("img", { src: src + "?inline=1", alt: "", loading: "lazy" }) : icon(KIND_ICON[o.kind] || "doc");
    if (o.kind === "image") mkBtn("View", "eye", async () => h("img", { class: "preview", src: src + "?inline=1", alt: o.label }));
    if (o.kind === "video") { body.hidden = false; body.append(h("video", { src: src + "?inline=1", controls: true, preload: "metadata" })); }
    if (o.kind === "audio") { body.hidden = false; body.append(h("audio", { src: src + "?inline=1", controls: true, preload: "metadata" })); }
    if (o.kind === "pdf") acts.push(h("a", { class: "btn small", href: src + "?inline=1", target: "_blank", rel: "noopener" }, icon("out"), "Open"));
    if (o.kind === "markdown") mkBtn("Read", "book", async () => { const d = h("div", { class: "reader" }); d.innerHTML = markdown(await fetchText()); return d; });
    if (o.kind === "text") mkBtn("Read", "text", async () => h("pre", { class: "plain", text: await fetchText() }));
    if (o.kind === "html") mkBtn("Preview", "eye", async () => h("iframe", { src: src + "?inline=1", sandbox: "", title: o.label, loading: "lazy" }));
    if (o.kind === "quiz") mkBtn("Take quiz", "quiz", async () => quizWidget(JSON.parse(await fetchText())));
    if (o.kind === "flashcards") mkBtn("Study", "cards", async () => cardsWidget(JSON.parse(await fetchText())));
    acts.push(h("a", { class: "btn small quiet", href: src, download: o.name, "aria-label": `Download ${o.name}` }, icon("download"), "Download"));
    return h("article", { class: "out" },
      h("div", { class: "ico" }, thumb),
      h("div", { class: "meta" }, h("b", { text: o.label || o.name }), h("span", { text: `${o.name}, ${size(o.size)}` })),
      h("div", { class: "acts" }, acts), body);
  }

  function quizWidget(quiz) {
    let answered = 0, right = 0;
    const score = h("span", { class: "badge gilt", text: "0 answered" });
    const wrap = h("div", { class: "quiz" }, h("div", { class: "quiz-top" }, h("h3", { text: quiz.title || "Quiz" }), h("span", { class: "spacer" }), score));
    (quiz.questions || []).forEach((q, qi) => {
      const why = h("p", { class: "why" });
      const opts = h("div", { class: "opts" });
      q.options.forEach((opt, oi) => {
        const b = h("button", { class: "opt", type: "button", text: `${"ABCDEF"[oi]}. ${opt}` });
        b.addEventListener("click", () => {
          opts.querySelectorAll("button").forEach((x, xi) => { x.disabled = true; if (xi === q.answer) x.classList.add("right"); });
          if (oi !== q.answer) b.classList.add("wrong"); else right++;
          answered++;
          score.textContent = `${right} of ${answered} correct`;
          why.textContent = q.explanation ? `Why: ${q.explanation}` : "";
        });
        opts.append(b);
      });
      wrap.append(h("div", { class: "q" }, h("p", { text: `${qi + 1}. ${q.question}` }), opts, why));
    });
    return wrap;
  }

  function cardsWidget(deck) {
    return h("div", { class: "stack" }, h("p", { class: "muted", text: `${deck.title || "Flashcards"}: select a card to flip it.` }),
      h("div", { class: "cards" }, (deck.cards || []).map((c) => {
        const b = h("button", { class: "card", type: "button", "aria-pressed": "false" },
          h("div", { class: "in" }, h("div", { class: "face front", text: c.front }), h("div", { class: "face back", text: c.back })));
        b.addEventListener("click", () => { b.classList.toggle("flipped"); b.setAttribute("aria-pressed", String(b.classList.contains("flipped"))); });
        return b;
      })));
  }

  /* ================================================================ runs */
  async function pageRuns(main) {
    const page = h("div", { class: "page" }, head("Runs", "Every problem you've given InEra, newest first."));
    main.append(page);
    const { jobs } = await api("/api/jobs");
    if (!jobs.length) {
      page.append(h("div", { class: "empty" }, h("h2", { text: "No runs yet" }),
        h("p", { text: "Describe a problem on the Solve page and it will show up here." }),
        h("a", { class: "btn primary", href: "#/solve" }, "Go to Solve")));
      return;
    }
    page.append(h("div", { class: "list" }, jobs.map((j) => h("article", { class: "item" },
      h("div", {}, h("h3", {}, h("a", { class: "title", href: `#/runs/${j.id}`, text: j.title || j.problem })),
        h("div", { class: "sub" }, statusBadge(j.status), h("span", { text: ago(j.created_at) }),
          j.source === "schedule" ? h("span", { class: "badge" }, icon("clock"), "Scheduled run") : null,
          h("span", { text: `${j.plugins.length} plugin${j.plugins.length === 1 ? "" : "s"}, ${j.output_count} result${j.output_count === 1 ? "" : "s"}` }))),
      h("div", { class: "acts" }, h("a", { class: "btn small", href: `#/runs/${j.id}` }, "Open"))))));
  }

  async function pageRunDetail(main, id) {
    if (typeof main === "string") { id = main; main = $("#main"); }
    const page = h("div", { class: "page" });
    main.append(page);
    const job = await api(`/api/jobs/${id}`);
    page.append(head("Run details", job.problem,
      h("a", { class: "btn small", href: "#/runs" }, "All runs"),
      h("button", { class: "btn small", onclick: () => { S.draft = job.problem; location.hash = "#/solve"; } }, icon("refresh"), "Run again"),
      h("button", { class: "btn small danger", onclick: () => modal("Delete this run?", h("p", { text: "Its results will be deleted too. This can't be undone." }), (close) => [
        h("button", { class: "btn", onclick: close }, "Keep it"),
        h("button", { class: "btn danger", onclick: async () => {
          try { await api(`/api/jobs/${id}`, { method: "DELETE" }); close(); toast("Run deleted."); location.hash = "#/runs"; } catch (e) { toast(e.message, true); }
        } }, "Delete run")]) }, icon("trash"), "Delete")));
    const area = h("div");
    page.append(area);
    showRun(area, id, false);
  }

  /* ================================================================ automations */
  async function pageAutomations(main) {
    const page = h("div", { class: "page" }, head("Automations", "Jobs that repeat on their own. Ones that post or send on your behalf wait for your one-time approval."));
    main.append(page);
    const draw = async () => {
      const { automations } = await api("/api/automations");
      page.querySelectorAll(".list, .empty").forEach((x) => x.remove());
      if (!automations.length) {
        page.append(h("div", { class: "empty" }, h("h2", { text: "No automations yet" }),
          h("p", { text: "Add a time to any problem, for example “every day at 8 am”, and InEra turns it into an automation." }),
          h("a", { class: "btn primary", href: "#/solve" }, "Create one")));
        return;
      }
      page.append(h("div", { class: "list" }, automations.map((a) => {
        const act = async (action, payload) => {
          try {
            const r = await api(`/api/automations/${a.id}/${action}`, { method: "POST", body: payload || {} });
            if (r.job_id) { toast("Started. Opening the run…"); location.hash = `#/runs/${r.job_id}`; return; }
            toast({ approve: "Approved. It will run on schedule.", pause: "Paused.", resume: "Resumed.", schedule: "Schedule updated." }[action] || "Done.");
            draw(); refreshApprovals();
          } catch (e) { toast(e.message, true); }
        };
        const editor = h("form", { class: "sched-edit" }, h("input", { type: "text", name: "text", value: a.schedule_text, "aria-label": "New schedule" }),
          h("button", { class: "btn small", type: "submit" }, "Save"));
        editor.hidden = true;
        editor.addEventListener("submit", (e) => { e.preventDefault(); act("schedule", { text: editor.text.value }); });
        return h("article", { class: "item" },
          h("div", {},
            h("h3", { text: a.name }),
            h("div", { class: "sub" },
              a.approved ? (a.enabled ? h("span", { class: "badge ok" }, "Active") : h("span", { class: "badge" }, "Paused")) : h("span", { class: "badge warn" }, "Needs approval"),
              h("span", { text: `${a.schedule_text} (${a.timezone})` }),
              h("span", { text: a.enabled && a.next_run_at ? `Next: ${fmtTime(a.next_run_at)}` : "No upcoming run" }),
              a.last_status ? h("span", {}, "Last: ", a.last_job_id ? h("a", { href: `#/runs/${a.last_job_id}`, text: (STATUS[a.last_status] || [a.last_status])[0] }) : a.last_status) : null,
              h("span", { text: `${a.plugins.length} plugins` }),
              a.input_count ? h("span", { text: `${a.input_count} library file${a.input_count === 1 ? "" : "s"} in rotation` }) : null),
            editor),
          h("div", { class: "acts" },
            !a.approved ? h("button", { class: "btn small primary", onclick: () => act("approve") }, icon("check"), "Approve") : null,
            a.enabled ? h("button", { class: "btn small", onclick: () => act("pause") }, icon("pause"), "Pause") : h("button", { class: "btn small", onclick: () => act("resume") }, icon("play"), "Resume"),
            a.approved ? h("button", { class: "btn small", onclick: () => act("run") }, "Run now") : null,
            h("button", { class: "btn small quiet", onclick: () => { editor.hidden = !editor.hidden; if (!editor.hidden) editor.text.focus(); } }, "Change time"),
            h("button", { class: "btn small quiet", "aria-label": "Delete automation", onclick: () => modal("Delete this automation?", h("p", { text: `“${a.name}” will stop running. Past runs stay in Runs.` }), (close) => [
              h("button", { class: "btn", onclick: close }, "Keep it"),
              h("button", { class: "btn danger", onclick: async () => {
                try { await api(`/api/automations/${a.id}`, { method: "DELETE" }); close(); toast("Automation deleted."); draw(); refreshApprovals(); } catch (e) { toast(e.message, true); }
              } }, "Delete")]) }, icon("trash"))));
      })));
    };
    await draw();
  }

  /* ================================================================ library */
  async function pageLibrary(main) {
    const input = h("input", { type: "file", multiple: true, class: "sr-only" });
    const page = h("div", { class: "page" }, head("Library", "Files you uploaded and everything InEra produced. Uploads attached to an automation stay available for every run.",
      h("button", { class: "btn primary", onclick: () => input.click() }, icon("plus"), "Upload files"), input));
    main.append(page);
    const lists = h("div");
    page.append(lists);
    const draw = async () => {
      const { files } = await api("/api/files");
      const ups = files.filter((f) => f.origin === "upload"), outs = files.filter((f) => f.origin === "output");
      const row = (f) => h("article", { class: "item" },
        h("div", {}, h("h3", { text: f.label && f.origin === "output" ? f.label : f.name }),
          h("div", { class: "sub" }, h("span", { text: f.name }), h("span", { text: size(f.size) }), h("span", { text: ago(f.created_at) }),
            f.job_id ? h("a", { href: `#/runs/${f.job_id}`, text: "From a run" }) : null)),
        h("div", { class: "acts" },
          f.origin === "upload" ? h("button", { class: "btn small", onclick: () => { if (!S.attach.some((a) => a.id === f.id)) S.attach.push(f); location.hash = "#/solve"; } }, "Use in a run") : null,
          h("a", { class: "btn small quiet", href: `/api/files/${f.id}`, download: f.name }, icon("download"), "Download"),
          h("button", { class: "btn small quiet", "aria-label": `Delete ${f.name}`, onclick: async () => {
            try { await api(`/api/files/${f.id}`, { method: "DELETE" }); toast("File deleted."); draw(); } catch (e) { toast(e.message, true); }
          } }, icon("trash"))));
      lists.replaceChildren(
        h("h2", { class: "cat", text: `Uploads (${ups.length})` }),
        ups.length ? h("div", { class: "list" }, ups.map(row)) : h("p", { class: "muted", text: "Nothing uploaded yet." }),
        h("h2", { class: "cat", text: `Generated (${outs.length})` }),
        outs.length ? h("div", { class: "list" }, outs.slice(0, 200).map(row)) : h("p", { class: "muted", text: "Results from your runs will appear here." }));
    };
    input.addEventListener("change", async () => {
      const form = new FormData();
      Array.from(input.files).forEach((f) => form.append("files", f, f.name));
      input.value = "";
      try { const r = await api("/api/files", { method: "POST", form }); toast(`${r.files.length} file(s) uploaded.`); draw(); } catch (e) { toast(e.message, true); }
    });
    await draw();
  }

  /* ================================================================ plugins */
  async function pagePlugins(main) {
    if (!S.plugins) S.plugins = await api("/api/plugins");
    const { plugins, categories } = S.plugins;
    const search = h("input", { type: "search", class: "search", placeholder: "Find a plugin, e.g. merge, quiz, Instagram", "aria-label": "Search plugins" });
    const body = h("div");
    const page = h("div", { class: "page" }, head(`${plugins.length} built-in plugins`, "You don't need to pick them — just describe the problem on Solve and InEra chains the right ones. Browse to see what's possible.", search), body);
    main.append(page);
    const draw = () => {
      const q = search.value.trim().toLowerCase();
      body.replaceChildren(...categories.map((c) => {
        const list = plugins.filter((p) => p.category === c.id && (!q || (p.name + " " + p.description).toLowerCase().includes(q)));
        if (!list.length) return null;
        return h("section", { class: "cat" }, h("h2", { text: c.label }),
          h("div", { class: "plugin-grid" }, list.map((p) => h("article", { class: "plugin" },
            h("header", {}, icon(p.icon), h("h3", { text: p.name })),
            h("p", { text: p.description }),
            h("footer", {},
              p.side_effect ? h("span", { class: "badge warn", title: "Posts or sends on your behalf after your approval" }, "Acts for you") : null,
              p.needs.some((n) => n.startsWith("vault:")) ? h("span", { class: "badge" }, "Needs a connection") : null,
              p.needs.includes("ai") ? h("span", { class: "badge warn", title: "Needs Ollama or an API key configured on the server" }, "Needs an AI engine")
                : p.ai_enhanced ? h("span", { class: "badge gilt", title: "Works offline; writes better with an AI engine" }, "Sharper with AI") : h("span", { class: "badge ok" }, "Fully offline"),
              p.example ? h("button", { class: "btn small", onclick: () => { S.draft = p.example; location.hash = "#/solve"; } }, "Try it") : null)))));
      }).filter(Boolean));
      if (!body.children.length) body.append(h("p", { class: "muted", text: "No plugin matches that search." }));
    };
    search.addEventListener("input", draw);
    draw();
  }

  /* ================================================================ connections */
  const CONN = {
    instagram: {
      title: "Instagram", icon: "instagram",
      intro: "Lets InEra publish posts to your Instagram Business or Creator account through Instagram's official publishing API. Your Instagram password is never needed.",
      steps: ["Switch your Instagram to a Professional account (Business or Creator).",
        "At developers.facebook.com create an app, add “Instagram API with Instagram Login” and generate an access token with the instagram_business_basic and instagram_business_content_publish permissions.",
        "Paste your Instagram account ID and the token below, then press Test. Long-lived tokens expire after about 60 days; refresh them in the developer dashboard.",
        "Instagram downloads each image from this server, so the server must run on a public HTTPS address (PUBLIC_BASE_URL)."],
      fields: [["ig_user_id", "Instagram account ID", "text", "Numbers only, e.g. 17841400000000000"], ["access_token", "Access token", "password", ""]],
    },
    smtp: {
      title: "E-mail", icon: "mail",
      intro: "Sends e-mails from your own mailbox using SMTP, so replies come back to you. Works with Gmail, Outlook, Zoho or your hosting provider.",
      steps: ["For Gmail: turn on 2-Step Verification, then create an App Password (Google Account → Security → App passwords) and use it below.",
        "Use port 587 with STARTTLS, or 465 with SSL.",
        "Only e-mail people who expect to hear from you."],
      presets: { Gmail: { host: "smtp.gmail.com", port: "587", security: "starttls" }, "Outlook / Microsoft 365": { host: "smtp.office365.com", port: "587", security: "starttls" }, "Zoho (India)": { host: "smtp.zoho.in", port: "465", security: "ssl" } },
      fields: [["host", "SMTP server", "text", "smtp.gmail.com"], ["port", "Port", "number", "587"], ["security", "Security", "select", ["starttls", "ssl", "none"]],
        ["username", "Username", "text", "you@yourdomain.com"], ["password", "Password or app password", "password", ""],
        ["from_email", "From address", "email", "Leave blank to use the username"], ["from_name", "From name", "text", "Your business name"]],
    },
    messenger: {
      title: "Messengers and webhooks", icon: "send",
      intro: "Delivers results to your phone or team chat. Fill in only the ones you use.",
      steps: ["Telegram: message @BotFather to create a bot and copy its token. Send any message to your bot, then open api.telegram.org/bot<token>/getUpdates to find your chat ID.",
        "Discord: Channel settings → Integrations → Webhooks → New webhook → Copy URL.",
        "Slack: create an Incoming Webhook for your channel and copy its URL.",
        "Webhook: any HTTPS address that accepts a JSON POST (for your own systems)."],
      fields: [["telegram_bot_token", "Telegram bot token", "password", ""], ["telegram_chat_id", "Telegram chat ID", "text", ""],
        ["discord_webhook", "Discord webhook URL", "password", ""], ["slack_webhook", "Slack webhook URL", "password", ""], ["webhook_url", "Custom webhook URL", "password", ""]],
    },
  };

  async function pageConnections(main) {
    const page = h("div", { class: "page" }, head("Connections", "InEra does the work itself. Connections are only for delivering results to places you own. Secrets are encrypted on this server and never shown again."));
    main.append(page);
    const { vault } = await api("/api/vault");
    for (const [kind, c] of Object.entries(CONN)) {
      const v = vault[kind];
      const form = h("form", { novalidate: true });
      const inputs = {};
      for (const [key, label, type, ph] of c.fields) {
        let input;
        const saved = v.fields[key];
        if (type === "select") input = h("select", { name: key }, ph.map((o) => h("option", { value: o, selected: saved === o }, o.toUpperCase() === "NONE" ? "None" : o === "starttls" ? "STARTTLS" : "SSL")));
        else input = h("input", { type, name: key, autocomplete: "off", spellcheck: "false",
          placeholder: type === "password" && saved ? "Saved. Type a new value to replace it." : ph, value: type === "password" ? "" : (saved || "") });
        inputs[key] = input;
        form.append(h("label", { class: "field" }, h("span", { text: label }), input));
      }
      const status = v.configured ? h("span", { class: "badge ok" }, "Connected") : h("span", { class: "badge" }, "Not connected");
      form.append(h("div", { class: "row" },
        h("button", { class: "btn primary", type: "submit" }, "Save"),
        h("button", { class: "btn", type: "button", onclick: async () => {
          try { const r = await api(`/api/vault/${kind}/test`, { method: "POST" }); toast(r.message, !r.ok); } catch (e) { toast(e.message, true); }
        } }, "Test"),
        h("span", { class: "spacer" }),
        v.configured ? h("button", { class: "btn quiet", type: "button", onclick: async () => {
          try { await api(`/api/vault/${kind}`, { method: "DELETE" }); toast(`${c.title} disconnected.`); route(); } catch (e) { toast(e.message, true); }
        } }, "Disconnect") : null));
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const payload = {};
        for (const [k, el] of Object.entries(inputs)) payload[k] = el.value.trim();
        try { await api(`/api/vault/${kind}`, { method: "PUT", body: payload }); toast(`${c.title} saved. Press Test to check it.`); route(); } catch (ex) { toast(ex.message, true); }
      });
      page.append(h("section", { class: "panel", "aria-label": c.title },
        h("div", { class: "row" }, icon(c.icon), h("h2", { text: c.title }), h("span", { class: "spacer" }), status),
        h("p", { class: "muted", text: c.intro }),
        h("ol", { class: "howto" }, c.steps.map((s) => h("li", { text: s }))),
        c.presets ? h("div", { class: "presets" }, h("span", { class: "muted small", text: "Quick fill:" }), Object.entries(c.presets).map(([name, vals]) =>
          h("button", { class: "btn small", type: "button", onclick: () => { for (const [k, val] of Object.entries(vals)) inputs[k].value = val; } }, name))) : null,
        form));
    }
  }

  /* ================================================================ profile */
  async function pageProfile(main) {
    const u = S.user, p = u.profile || {};
    const page = h("div", { class: "page" }, head("Profile", "Your details shape every post, document, website and invoice InEra creates.",
      h("button", { class: "btn", onclick: async () => {
        try { await api("/api/auth/logout", { method: "POST" }); } catch (e) { /* ignore */ }
        S.user = null; S.jobId = null; renderAuth("login");
      } }, "Sign out")));
    main.append(page);
    const field = (name, label, opts = {}) => h("label", { class: "field" }, h("span", { text: label }),
      opts.textarea ? h("textarea", { name, rows: 2, text: p[name] || "" }) :
        opts.select ? h("select", { name }, opts.select.map((o) => h("option", { value: o, selected: (p[name] || "") === o }, o))) :
          h("input", { type: opts.type || "text", name, value: name === "name" ? u.name : (p[name] || ""), placeholder: opts.ph || "" }),
      opts.hint ? h("span", { class: "hint", text: opts.hint }) : null);
    let zones = [];
    try { zones = Intl.supportedValuesOf("timeZone"); } catch (e) { zones = [p.timezone || "UTC"]; }
    if (p.timezone && !zones.includes(p.timezone)) zones.unshift(p.timezone);
    const details = h("form", {},
      h("div", { class: "grid-2" }, field("name", "Your name"), field("business_name", "Business or brand name")),
      h("div", { class: "grid-2" }, field("industry", "Industry", { select: INDUSTRIES.includes(p.industry) || !p.industry ? INDUSTRIES : [p.industry, ...INDUSTRIES] }), field("brand_voice", "Brand voice", { select: VOICES.includes(p.brand_voice) || !p.brand_voice ? VOICES : [p.brand_voice, ...VOICES] })),
      field("description", "What you do", { textarea: true }),
      field("tagline", "Tagline", { ph: "Used on your website and posts" }),
      h("div", { class: "grid-2" }, field("audience", "Who you serve"), field("brand_color", "Brand colour", { ph: "#C9A55C" })),
      h("div", { class: "grid-2" }, field("phone", "Business phone"), field("public_email", "Public e-mail", { type: "email" })),
      h("div", { class: "grid-2" }, field("website", "Website"), field("instagram", "Instagram handle")),
      field("address", "Address", { textarea: true }),
      h("div", { class: "grid-2" }, field("city", "City"), field("country", "Country")),
      h("label", { class: "field" }, h("span", { text: "Time zone" }), h("select", { name: "timezone" }, zones.map((z) => h("option", { value: z, selected: z === (p.timezone || "UTC") }, z)))),
      h("h3", { text: "Invoice details" }),
      h("div", { class: "grid-2" }, field("gstin", "GSTIN", { hint: "Shown on invoices" }), field("upi_id", "UPI ID", { hint: "Shown as a payment option" })),
      field("bank_details", "Bank details", { textarea: true }),
      h("div", { class: "row" }, h("button", { class: "btn primary", type: "submit" }, "Save details")));
    details.addEventListener("submit", async (e) => {
      e.preventDefault();
      const profile = {};
      for (const el of details.elements) if (el.name && el.name !== "name") profile[el.name] = el.value;
      profile.instagram = (profile.instagram || "").replace(/^@/, "");
      try { const r = await api("/api/me", { method: "PUT", body: { name: details.elements.name.value, profile } }); S.user = r.user; toast("Details saved."); }
      catch (ex) { toast(ex.message, true); }
    });
    const pref = (key, title, text) => {
      const box = h("input", { type: "checkbox", checked: key === "signature" ? p[key] !== false : !!p[key], "aria-label": title });
      box.addEventListener("change", async () => {
        try { const r = await api("/api/me", { method: "PUT", body: { profile: { [key]: box.checked } } }); S.user = r.user; toast("Preference saved."); }
        catch (e) { toast(e.message, true); box.checked = !box.checked; }
      });
      return h("div", { class: "toggle-row" }, h("div", {}, h("strong", { text: title }), h("p", { text })), h("label", { class: "switch" }, box, h("i")));
    };
    const pw = h("form", {},
      h("div", { class: "grid-2" },
        h("label", { class: "field" }, h("span", { text: "Current password" }), h("input", { type: "password", name: "current", autocomplete: "current-password" })),
        h("label", { class: "field" }, h("span", { text: "New password" }), h("input", { type: "password", name: "new", autocomplete: "new-password" }))),
      h("div", { class: "row" }, h("button", { class: "btn", type: "submit" }, "Change password")));
    pw.addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await api("/api/me/password", { method: "POST", body: { current: pw.current.value, new: pw.new.value } }); pw.reset(); toast("Password changed. Other devices were signed out."); }
      catch (ex) { toast(ex.message, true); }
    });
    page.append(
      h("section", { class: "panel" }, h("h2", { text: "Business details" }), h("p", { class: "muted", text: `Signed in as ${u.email}.` }), details),
      h("section", { class: "panel" }, h("h2", { text: "Preferences" }),
        pref("auto_approve", "Approve posting and sending automatically", "When on, steps that post to Instagram, send e-mail or message someone run without asking you first — including scheduled automations you create from now on. Leave it off until you trust the results."),
        pref("signature", "Show the InEra mark on documents", "Adds a small InEra emblem to PDFs, slides and videos. Social posts, websites and invoices always carry only your own brand.")),
      h("section", { class: "panel" }, h("h2", { text: "Security" }), pw),
      h("section", { class: "panel" }, h("h2", { text: "Your data" }),
        h("p", { class: "muted", text: "Download everything InEra stores about you, or delete your account with all files, runs, automations and connections." }),
        h("div", { class: "row" },
          h("a", { class: "btn", href: "/api/me/export", download: "inera-my-data.json" }, icon("download"), "Export my data"),
          h("button", { class: "btn danger", onclick: () => {
            const pwd = h("input", { type: "password", autocomplete: "current-password", "aria-label": "Password" });
            modal("Delete your account?", h("div", { class: "stack" }, h("p", { text: "This permanently deletes your account and everything in it. Enter your password to confirm." }), pwd), (close) => [
              h("button", { class: "btn", onclick: close }, "Keep my account"),
              h("button", { class: "btn danger", onclick: async () => {
                try { await api("/api/me", { method: "DELETE", body: { password: pwd.value } }); close(); S.user = null; renderAuth("login"); toast("Your account was deleted."); }
                catch (e) { toast(e.message, true); }
              } }, "Delete everything")]);
          } }, icon("trash"), "Delete account"))));
  }

  boot();
})();

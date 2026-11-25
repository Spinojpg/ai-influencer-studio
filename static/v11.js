/* AI Influencer Studio 1.1.0 – Pregled, red čekanja, LoRA stack, Kalendar, Inbox i CRM, Postavke.
   Ovisi o window.StudioCore (izlaže ga index.html). Bez vanjskih biblioteka. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const C = () => window.StudioCore || null;
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const toast = (m, bad) => { const c = C(); if (c) c.toast(m, bad); };
  const num = (v, d) => { const n = Number(v); return Number.isFinite(n) ? n : d; };
  const fmtTime = (ts) => { if (!ts) return "—"; const d = new Date(ts * 1000); return d.toLocaleString("hr-HR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); };
  const money = (v) => (Number(v) || 0).toLocaleString("hr-HR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €";

  async function api(method, url, body) {
    const opt = { method: method, cache: "no-store", headers: {} };
    if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    const r = await fetch(url, opt);
    let d = {};
    try { d = await r.json(); } catch (e) { d = {}; }
    if (!r.ok || d.ok === false) throw new Error(d.error || ("HTTP " + r.status));
    return d;
  }
  const get = (u) => api("GET", u);
  const post = (u, b) => api("POST", u, b || {});

  const V = {
    opts: null, hw: null, templates: [], stack: [], stackPersona: null, stackTouched: false,
    queue: null, queueTimer: null, galOffset: 0, galItems: [], lastShot: null,
    calMonth: null, posts: [], editPost: null, crmTab: "contacts", contactSel: null, sendState: null,
    llm: null, env: null, gallery: [], ovTimer: null, pStack: []
  };

  /* ---------- zajedničko: LoRA stack ---------- */
  function loraOptionsHtml(selected) {
    const c = C();
    const opts = c ? c.loraOptions() : [];
    let found = false;
    let html = '<option value="">— odaberi LoRA-u —</option>';
    opts.forEach((o) => {
      const sel = o.value === selected ? " selected" : "";
      if (sel) found = true;
      html += '<option value="' + esc(o.value) + '"' + sel + ">" + esc(o.label) + "</option>";
    });
    if (selected && !found) html += '<option value="' + esc(selected) + '" selected>' + esc(selected) + "</option>";
    return html;
  }
  function stackEditorHtml(prefix, stack) {
    const rows = (stack || []).map((it, i) => {
      const s = num(it.strength_model, 0.8);
      return '<div class="v11-lora-row" data-i="' + i + '">'
        + '<select class="' + prefix + '-name" aria-label="LoRA">' + loraOptionsHtml(it.name) + "</select>"
        + '<input type="range" class="' + prefix + '-str" min="-2" max="2" step="0.05" value="' + s + '" aria-label="Jačina" />'
        + '<input type="number" class="' + prefix + '-str-num" min="-2" max="2" step="0.05" value="' + s.toFixed(2) + '" aria-label="Jačina (broj)" />'
        + '<button type="button" class="btn ' + prefix + '-del" title="Ukloni">×</button></div>';
    }).join("");
    return rows + '<button type="button" class="btn ' + prefix + '-add"' + ((stack || []).length >= 5 ? " disabled" : "") + ">+ Dodaj LoRA</button>";
  }
  function readRows(root, prefix, keepEmpty) {
    const out = [];
    root.querySelectorAll(".v11-lora-row").forEach((row) => {
      const nameEl = row.querySelector("." + prefix + "-name");
      const strEl = row.querySelector("." + prefix + "-str") || row.querySelector("." + prefix + "-str-num");
      const name = nameEl ? nameEl.value : "";
      const s = Math.max(-2, Math.min(2, num(strEl ? strEl.value : 0.8, 0.8)));
      if (name || keepEmpty) out.push({ name: name, strength_model: s, strength_clip: s });
    });
    return out;
  }
  function stackMounts() {
    return [...document.querySelectorAll(".js-lora-stack")];
  }
  function syncStrInputs(row, prefix, value) {
    const s = Math.max(-2, Math.min(2, num(value, 0)));
    const range = row.querySelector("." + prefix + "-str");
    const numEl = row.querySelector("." + prefix + "-str-num");
    if (range) range.value = String(s);
    if (numEl) numEl.value = s.toFixed(2);
    return s;
  }
  function bindStack(root, prefix, setStack) {
    if (!root || root.dataset.loraBound === "1") return;
    root.dataset.loraBound = "1";
    root.addEventListener("input", (e) => {
      if (e.target.classList.contains(prefix + "-str") || e.target.classList.contains(prefix + "-str-num")) {
        const row = e.target.closest(".v11-lora-row");
        if (row) syncStrInputs(row, prefix, e.target.value);
        setStack(readRows(root, prefix, true), false);
      }
    });
    root.addEventListener("change", (e) => {
      if (e.target.classList.contains(prefix + "-name") || e.target.classList.contains(prefix + "-str") || e.target.classList.contains(prefix + "-str-num")) {
        setStack(readRows(root, prefix, true), false);
      }
    });
    root.addEventListener("click", (e) => {
      if (e.target.classList.contains(prefix + "-add")) {
        const all = readRows(root, prefix, true);
        if (all.length >= 5) return;
        all.push({ name: "", strength_model: 0.6, strength_clip: 0.6 });
        setStack(all, true);
      } else if (e.target.classList.contains(prefix + "-del")) {
        const row = e.target.closest(".v11-lora-row");
        if (!row) return;
        const i = Number(row.dataset.i);
        const all = readRows(root, prefix, true);
        all.splice(i, 1);
        setStack(all, true);
      }
    });
  }
  function badge(ok, yes, no) {
    if (ok === null || ok === undefined) return '<span class="v11-badge">nepoznato</span>';
    return '<span class="v11-badge ' + (ok ? "ok" : "bad") + '">' + esc(ok ? yes : no) + "</span>";
  }
  function kpi(k, v, s, cls) { return '<div class="v11-kpi ' + (cls || "") + '"><div class="k">' + esc(k) + '</div><div class="v">' + v + '</div><div class="s">' + (s || "") + "</div></div>"; }
  function statusBadge(st, label) {
    const cls = { draft: "", scheduled: "gold", published: "ok", error: "bad", publishing: "run" }[st] || "";
    return '<span class="v11-badge ' + cls + '">' + esc(label || st) + "</span>";
  }

  /* ---------- GENERIRANJE ---------- */
  async function loadGenOptions(force) {
    if (V.opts && !force) return V.opts;
    try {
      V.opts = await get("/api/gen/options");
      V.templates = V.opts.templates || [];
    } catch (e) {
      V.opts = { samplers: ["dpmpp_2m_sde"], schedulers: ["karras"], defaults: {}, nodes: {}, templates: [] };
    }
    return V.opts;
  }
  function tplOptions(selected) {
    const groups = { public_teaser: "Javni teaser", premium: "Premium sadržaj" };
    let html = '<option value="">Bez predloška</option>';
    Object.keys(groups).forEach((tier) => {
      const list = V.templates.filter((t) => t.tier === tier);
      if (!list.length) return;
      html += '<optgroup label="' + groups[tier] + '">' + list.map((t) => '<option value="' + t.id + '"' + (String(selected) === String(t.id) ? " selected" : "") + ">" + esc(t.name) + "</option>").join("") + "</optgroup>";
    });
    return html;
  }
  function rangeLabel(label, id, valId, min, max, step, val, dp, tipText) {
    return '<label class="rl"><span class="rl-head"><span class="rl-name">' + label + "</span>" + (tipText ? tip(tipText, label) : "") + '<span class="range-val" id="' + valId + '">' + num(val, 0).toFixed(dp) + '</span></span><input type="range" id="' + id + '" min="' + min + '" max="' + max + '" step="' + step + '" value="' + val + '" /></label>';
  }
  /* 1.3.0: kratko objašnjenje uz svaku naprednu opciju (popover radi ui_v130.js: hover, fokus i klik) */
  function tip(text, label) {
    return '<button type="button" class="tip" data-tip="' + esc(text) + '" aria-label="Objašnjenje: ' + esc(label || "opcija") + '">?</button>';
  }
  const TIPS = {
    tpl: "Gotov recept za scenu: dopisuje prompt prije i poslije tvoje scene te postavlja format i postavke. Javni teaser je za feed, Premium za ekskluzivni (SFW) sadržaj.",
    sampler: "Algoritam koji iz šuma crta sliku. dpmpp_2m_sde + karras daje prirodne detalje; dpmpp_2m je malo brži; euler + sgm_uniform je za Turbo (8 koraka). dpmpp_sde je 2× sporiji po koraku.",
    scheduler: "Raspored jačine šuma po koracima. karras je najbolji za realizam u 20–30 koraka, sgm_uniform za Turbo/Hyper LoRA-e.",
    cfg: "Koliko strogo model prati prompt. Previsok CFG (6+) daje „prepečenu”, plastičnu kožu i prezasićene boje. Realizam: SDXL 4,0–4,5, SD 1.5 ~5; Turbo 1,5–2,5. Bez kvačice vrijedi profil kvalitete.",
    freeu: "Besplatno pojačanje detalja unutar modela (bez dodatnog VRAM-a i vremena). Ako slike izgledaju pretjerano oštro ili „AI”, isključi.",
    hiresScale: "Koliko se baza poveća u drugom prolazu. 1,25–1,35× je brzo i stane u 8 GB; 8 GB zaštita sama smanji skalu ako bi slika bila prevelika.",
    hiresDenoise: "Koliko drugi prolaz smije mijenjati sliku. 0,32–0,38 dodaje oštrinu i teksturu kože bez mijenjanja kompozicije; iznad 0,45 se pojave novi detalji i artefakti.",
    hiresSteps: "Koraci drugog prolaza. 6–10 je dovoljno uz nizak denoise; više samo produžuje generiranje.",
    refMode: "Kako se drži isto lice: IP-Adapter (do 8 slika s profila, lakši) ili InstantID (jedna referenca, jači identitet, SDXL). Automatski bira ono što je instalirano.",
    iid: "Jačina InstantID identiteta. 0,6–0,85 je prirodno; iznad 1,0 lice postaje ukočeno i „zalijepljeno”. Uz InstantID 8 GB zaštita smanjuje hires.",
    fdDenoise: "Koliko Face Detailer smije preslikati lice. 0,20–0,25 je prirodnije (zadano 0,25); 0,3–0,45 jače doradi; više mijenja crte lica. 8 GB zaštita ograničava na 0,5.",
    fdGuide: "Veličina na kojoj se lice ponovno crta. 384–512 je oštro i sigurno za 8 GB.",
    fdMax: "Najveća veličina izreza lica. 768 je gornja sigurna granica za RX 6600.",
    fdBbox: "Koliko siguran mora biti detektor da je to lice. Niže hvata i manja/profilna lica, ali i lažne pogotke.",
    guard: "Automatski sprječava „out of memory” na RX 6600: smanji hires skalu, uz InstantID + Face Detailer isključi hires, uz SDXL + hires generira 1 sliku, prebaci VAE na tiled. Ništa ne briše iz tvojih postavki.",
    detail: "Kurirane SFW LoRA-e za realizam (preuzimaju se u kartici Modeli). Uključi prekidač i podesi jačinu (0–1,5). Uz Realističnu kožu Studio sam doda okidač u prompt, bez duplikata. Uz Turbo najviše dvije.",
    stack: "Do 5 LoRA-a odjednom, svaka s vlastitom jačinom od −2 do 2. Ista lista je i na glavnom ekranu Generiranja. Popunjava se iz profila osobe; LoRA osobe i dalje ide zasebno. Više LoRA-a = sporije i veći rizik od „AI” izgleda i od popunjenog VRAM-a (8 GB).",
    series: "Dodaje više poslova u red čekanja. Red radi jedan po jedan posao (sigurno za 8 GB) i preživi restart Studija.",
    seedMode: "Nasumični: svaka slika nova. Uzastopni: seed, seed+1… — dobro za varijacije iste scene.",
    multiTpl: "Isti opis scene kroz više predložaka odjednom (npr. kafić, ulica, studio) — po jedan posao za svaki.",
    vae: "Odvojeni VAE dekoder umjesto onog iz checkpointa. Za SDXL: sdxl_vae ili sdxl-vae-fp16-fix (manje crnih slika u fp16). vae-ft-mse-840000 je samo za SD 1.5. \u201eIz checkpointa\u201d ostavlja postojeće ponašanje.",
    iidEnd: "Do kojeg dijela koraka InstantID još drži lice. 0,8 je prirodnije (zadano); 1,0 drži identitet do kraja i može učiniti lice ukočenim.",
    ipaEnd: "Do kojeg dijela koraka IP-Adapter još drži referentno lice. Zadano 1,0 (cijeli prolaz); malo niže (0,8) ostavlja više slobode za izraz."
  };
  function slot(id) { return $(id) || $("v11Gen"); }
  async function renderGen() {
    const box = $("v11Gen");
    if (!box) return;
    const o = await loadGenOptions(false);
    const d = o.defaults || {};
    const n = o.nodes || {};
    const fd = d.face_detailer || {};
    const sel = (id, list, cur) => '<select id="' + id + '">' + (list || []).map((s) => "<option" + (s === cur ? " selected" : "") + ">" + s + "</option>").join("") + "</select>";
    const modelHtml = '<div class="v11-grid2">'
      + '<div class="field"><label class="lbl" for="v11Sampler">Sampler ' + tip(TIPS.sampler, "Sampler") + "</label>" + sel("v11Sampler", o.samplers, d.sampler || "dpmpp_2m_sde") + "</div>"
      + '<div class="field"><label class="lbl" for="v11Scheduler">Scheduler ' + tip(TIPS.scheduler, "Scheduler") + "</label>" + sel("v11Scheduler", o.schedulers, d.scheduler || "karras") + "</div>"
      + "</div>"
      + '<div class="field"><label class="lbl" for="v11Cfg">CFG ' + tip(TIPS.cfg, "CFG") + ' <span class="range-val" id="v11CfgVal">auto</span></label>'
      + '<div class="v11-inline"><label><input type="checkbox" id="v11CfgOn" /> Ručno</label><input type="range" id="v11Cfg" min="1.5" max="8" step="0.1" value="4.3" disabled /></div>'
      + '<div class="hint">Auto = profil kvalitete (Realizam 4,3 · Brzo 4,0 · Turbo 2,2). Niži CFG = manje plastičan izgled.</div></div>'
      + '<div class="field"><label class="lbl"><input type="checkbox" id="v11Freeu" /> FreeU_V2 ' + tip(TIPS.freeu, "FreeU") + " " + badge(n.freeu_v2, "čvor postoji", "nema čvora – preskače se") + "</label></div>"
      + '<div class="field"><label class="lbl" for="v11VaeFile">VAE ' + tip(TIPS.vae, "VAE") + '</label><select id="v11VaeFile"></select>'
      + '<div class="hint">Preuzimanje: kartica Modeli → „VAE (dekoder slike)”. Ako datoteka nije preuzeta, pokretanje javi jasnu grešku.</div></div>';
    const hiresHtml = '<div class="field"><label class="lbl">Hires postavke (kad je uključen)</label><div class="v11-grid3">'
      + rangeLabel("Skala", "v11HiresScale", "v11HsVal", 1.2, 1.6, 0.01, num(d.hires_scale, 1.33), 2, TIPS.hiresScale)
      + rangeLabel("Denoise", "v11HiresDenoise", "v11HdVal", 0.25, 0.5, 0.01, num(d.hires_denoise, 0.35), 2, TIPS.hiresDenoise)
      + rangeLabel("Koraci", "v11HiresSteps", "v11HstVal", 4, 16, 1, num(d.hires_steps, 8), 0, TIPS.hiresSteps)
      + '</div><div class="hint">Drugi prolaz ide kroz VAEDecodeTiled kad je VAE način „tiled”.</div></div>';
    const faceHtml = '<div class="field"><label class="lbl" for="v11RefMode">Konzistentnost lica ' + tip(TIPS.refMode, "Konzistentnost lica") + "</label>"
      + '<div class="v11-inline"><select id="v11RefMode"><option value="">Kao na profilu osobe</option><option value="auto">Automatski</option><option value="ipadapter">IP-Adapter</option><option value="instantid">InstantID</option></select>'
      + "IP-Adapter " + badge(n.ipadapter, "spreman", "nedostaje") + " InstantID " + badge(n.instantid, "spreman", "nedostaje") + "</div>"
      + rangeLabel("Jačina InstantID", "v11IidWeight", "v11IidVal", 0.3, 1.2, 0.05, 0.8, 2, TIPS.iid)
      + rangeLabel("Kraj utjecaja", "v11IidEnd", "v11IidEndVal", 0.5, 1.0, 0.05, num(d.instantid_end_at, 0.8), 2, TIPS.iidEnd)
      + '<div class="hint">Automatski: IP-Adapter ako je instaliran, inače InstantID (SDXL, treba ComfyUI_InstantID + antelopev2). Na AMD-u InsightFace radi na CPU-u. Kraj utjecaja 0,8 je prirodniji od 1,0.</div></div>'
      + '<div class="field"><label class="lbl">Face Detailer postavke (kad je uključen)</label><div class="v11-grid2">'
      + rangeLabel("Denoise", "v11FdDenoise", "v11FdDVal", 0.1, 0.8, 0.02, num(fd.denoise, 0.25), 2, TIPS.fdDenoise)
      + rangeLabel("Guide size", "v11FdGuide", "v11FdGVal", 256, 768, 32, num(fd.guide_size, 384), 0, TIPS.fdGuide)
      + rangeLabel("Max size", "v11FdMax", "v11FdMVal", 512, 1024, 64, num(fd.max_size, 768), 0, TIPS.fdMax)
      + rangeLabel("Prag detekcije", "v11FdBbox", "v11FdBVal", 0.2, 0.9, 0.05, num(fd.bbox_threshold, 0.5), 2, TIPS.fdBbox)
      + "</div></div>"
      + '<div class="field guard-field"><label class="lbl"><input type="checkbox" id="v11VramGuard" checked /> 8 GB zaštita (RX 6600) ' + tip(TIPS.guard, "8 GB zaštita") + "</label>"
      + '<div class="hint">Face Detailer + InstantID + Hires zajedno? Zaštita sama složi kombinaciju koja stane u 8 GB i javi što je promijenila.</div></div>';
    const dl = o.detail_loras || [];
    const loraHtml = '<div class="field"><label class="lbl">Detail LoRA-e (SFW, 1 klik) ' + tip(TIPS.detail, "Detail LoRA-e") + "</label>"
      + '<div class="detail-toggles" id="v11DetailLoras">' + (dl.length ? dl.map((x) => '<label class="dtoggle' + (x.available ? "" : " missing") + '" title="' + esc(x.hint || "") + '">'
        + '<input type="checkbox" class="dt-on" value="' + esc(x.key) + '" />'
        + '<span class="dt-name">' + esc(x.label) + "</span>"
        + (x.available
          ? '<span class="dt-str"><input type="range" class="dt-w" min="0" max="1.5" step="0.05" value="' + num(x.weight, 0.5) + '" aria-label="Jačina: ' + esc(x.label) + '" /><span class="dt-wval">' + num(x.weight, 0.5).toFixed(2) + "</span></span>"
          : '<span class="dt-meta">nije preuzeta</span>')
        + "</label>").join("") : '<span class="hint">Nema kuriranih detail LoRA-a.</span>') + "</div>"
      + '<div class="hint">Preuzimanje: Modeli → „Preporučene SDXL LoRA-e”. Jačina 0–1,5 (korak 0,05) ide u workflow. Ako datoteka nedostaje, preskače se uz poruku.</div></div>'
      + '<div class="field"><label class="lbl">LoRA stack (do ' + (o.max_loras || 5) + ") " + tip(TIPS.stack, "LoRA stack") + '</label><div id="v11Stack" class="js-lora-stack"></div>'
      + '<div class="hint">Ista lista kao odjeljak LoRA na glavnom ekranu. Popunjava se iz profila osobe. LoRA osobe i dalje ide zasebno.</div></div>';
    const miscHtml = '<div class="field"><label class="lbl" for="v11Tpl">Predložak sadržaja ' + tip(TIPS.tpl, "Predložak") + "</label>"
      + '<div class="v11-inline"><select id="v11Tpl">' + tplOptions("") + '</select><button type="button" class="btn" id="v11TplManage">Uredi predloške</button></div>'
      + '<div class="hint" id="v11TplHint">Javni teaser (lifestyle, moda, BTS) i Premium sadržaj (studio glamour, editorial, putovanja, personalizirani portreti). Predložak dopunjuje prompt, format i postavke.</div>'
      + '<div id="v11TplEditor" hidden></div></div>'
      + '<div class="field"><label class="lbl">Serija u redu čekanja ' + tip(TIPS.series, "Serija u redu čekanja") + '</label><div class="v11-grid2">'
      + '<label>Broj slika <input type="number" id="v11BatchN" min="1" max="50" value="4" /></label>'
      + '<label>Seed ' + tip(TIPS.seedMode, "Seed serije") + ' <select id="v11SeedMode"><option value="random">Nasumični</option><option value="sequential">Uzastopni (seed, seed+1…)</option></select></label>'
      + '</div><label class="lbl" style="margin-top:8px">Više predložaka odjednom (opcionalno) ' + tip(TIPS.multiTpl, "Više predložaka") + '</label><div class="chips" id="v11MultiTpl">'
      + V.templates.map((t) => '<label class="chip"><input type="checkbox" value="' + t.id + '" /> ' + esc(t.name) + "</label>").join("") + "</div>"
      + '<div class="actions"><button type="button" class="btn primary" id="v11Enqueue">Dodaj u red</button></div>'
      + '<div class="hint">Red radi u pozadini jedan po jedan posao i preživi restart Studija.</div></div>';
    const parts = [["v11GenModel", modelHtml], ["v11GenHires", hiresHtml], ["v11GenFace", faceHtml], ["v11GenLora", loraHtml]];
    const own = parts.filter((p) => $(p[0])).map((p) => { $(p[0]).innerHTML = p[1]; return p[0]; });
    box.innerHTML = parts.filter((p) => own.indexOf(p[0]) < 0).map((p) => p[1]).join("") + miscHtml;
    syncStackFromPersona(true);
    bindGen();
    fillVaeOptions();
    try { document.dispatchEvent(new CustomEvent("studio:gen-rendered", { detail: { options: o } })); } catch (e) { /* stari preglednik */ }
  }
  function renderStackUi() {
    const html = stackEditorHtml("gst", V.stack);
    stackMounts().forEach((el) => { el.innerHTML = html; });
    const field = $("genLoraField");
    if (field) {
      const krea = !!(window.StudioCore && typeof window.StudioCore.arch === "function" && window.StudioCore.arch() === "krea2");
      field.hidden = krea;
    }
  }
  function applyGenStack(st, rerender) {
    V.stack = st;
    V.stackTouched = true;
    if (rerender) renderStackUi();
    else {
      const src = document.activeElement && document.activeElement.closest && document.activeElement.closest(".js-lora-stack");
      stackMounts().forEach((el) => {
        if (el !== src) el.innerHTML = stackEditorHtml("gst", V.stack);
      });
    }
  }
  function syncStackFromPersona(force) {
    const c = C();
    const p = c && c.selectedPersona();
    const pid = p ? p.id : null;
    if (!force && pid === V.stackPersona) return;
    V.stackPersona = pid;
    V.stackTouched = false;
    V.stack = (p && Array.isArray(p.lora_stack) ? p.lora_stack : []).map((x) => ({ name: x.name, strength_model: x.strength_model, strength_clip: x.strength_clip }));
    if ($("v11RefMode")) $("v11RefMode").value = "";
    if (p && $("v11IidWeight")) { $("v11IidWeight").value = num(p.instantid_weight, 0.8); $("v11IidVal").textContent = num(p.instantid_weight, 0.8).toFixed(2); }
    renderStackUi();
  }
  let genBound = false;
  function bindGen() {
    const pairs = [["v11HiresScale", "v11HsVal", 2], ["v11HiresDenoise", "v11HdVal", 2], ["v11HiresSteps", "v11HstVal", 0], ["v11IidWeight", "v11IidVal", 2],
      ["v11IidEnd", "v11IidEndVal", 2],
      ["v11FdDenoise", "v11FdDVal", 2], ["v11FdGuide", "v11FdGVal", 0], ["v11FdMax", "v11FdMVal", 0], ["v11FdBbox", "v11FdBVal", 2], ["v11Cfg", "v11CfgVal", 1]];
    pairs.forEach((pr) => { const el = $(pr[0]); if (el) el.addEventListener("input", () => { $(pr[1]).textContent = num(el.value, 0).toFixed(pr[2]); }); });
    const dbox = $("v11DetailLoras");
    if (dbox && dbox.dataset.wBound !== "1") {
      dbox.dataset.wBound = "1";
      dbox.addEventListener("input", (e) => {
        if (!e.target.classList.contains("dt-w")) return;
        const lab = e.target.closest(".dtoggle");
        const val = lab && lab.querySelector(".dt-wval");
        if (val) val.textContent = num(e.target.value, 0).toFixed(2);
      });
    }
    if ($("v11VaeFile") && $("v11VaeFile").dataset.bound !== "1") {
      $("v11VaeFile").dataset.bound = "1";
      $("v11VaeFile").addEventListener("change", () => saveVaeChoice($("v11VaeFile").value));
    }
    $("v11CfgOn").addEventListener("change", () => { $("v11Cfg").disabled = !$("v11CfgOn").checked; $("v11CfgVal").textContent = $("v11CfgOn").checked ? num($("v11Cfg").value, 5).toFixed(1) : "auto"; });
    $("v11Enqueue").addEventListener("click", enqueueBatch);
    $("v11TplManage").addEventListener("click", () => { const ed = $("v11TplEditor"); ed.hidden = !ed.hidden; if (!ed.hidden) renderTplEditor(); });
    $("v11Tpl").addEventListener("change", () => {
      const t = V.templates.find((x) => String(x.id) === $("v11Tpl").value);
      $("v11TplHint").textContent = t ? (t.description || t.name) + (t.size_preset ? " · format " + t.size_preset : "") : "Bez predloška: vrijedi samo tvoj opis scene.";
      if (t && t.size_preset && C()) C().pickSize(t.size_preset);
      if (!$("v11TplEditor").hidden) renderTplEditor();
    });
    if (!genBound) {
      genBound = true;
      stackMounts().forEach((el) => bindStack(el, "gst", applyGenStack));
      const osoba = $("osoba");
      if (osoba) osoba.addEventListener("change", () => setTimeout(() => syncStackFromPersona(false), 0));
    }
    stackMounts().forEach((el) => bindStack(el, "gst", applyGenStack));
  }
  function renderTplEditor(selId) {
    const ed = $("v11TplEditor");
    const t = V.templates.find((x) => String(x.id) === String(selId || $("v11Tpl").value)) || null;
    const f = (k, d) => esc(t ? (t[k] == null ? "" : t[k]) : (d || ""));
    const sizes = ["ig_portrait", "ig_square", "ig_story", "portrait", "portrait_hd", "square", "landscape"];
    ed.innerHTML = '<div class="card pad" style="margin-top:10px">'
      + '<div class="v11-grid2"><label>Ime <input type="text" id="tplName" value="' + f("name") + '" maxlength="120" /></label>'
      + '<label>Vrsta <select id="tplTier"><option value="public_teaser"' + (t && t.tier === "premium" ? "" : " selected") + '>Javni teaser</option><option value="premium"' + (t && t.tier === "premium" ? " selected" : "") + ">Premium sadržaj</option></select></label></div>"
      + '<label>Opis <input type="text" id="tplDesc" value="' + f("description") + '" /></label>'
      + '<label>Prompt prije scene <textarea id="tplPre" style="min-height:60px">' + f("prompt_prefix") + "</textarea></label>"
      + '<label>Prompt poslije scene <textarea id="tplSuf" style="min-height:50px">' + f("prompt_suffix") + "</textarea></label>"
      + '<label>Negativni dodatak <input type="text" id="tplNeg" value="' + f("negative") + '" /></label>'
      + '<div class="v11-grid3"><label>Format <select id="tplSize"><option value="">—</option>' + sizes.map((s) => "<option" + (t && t.size_preset === s ? " selected" : "") + ">" + s + "</option>").join("") + "</select></label>"
      + '<label>Koraci <input type="number" id="tplSteps" min="4" max="60" value="' + f("steps", "30") + '" /></label>'
      + '<label>CFG <input type="number" id="tplCfg" min="1" max="12" step="0.1" value="' + f("cfg", "5") + '" /></label></div>'
      + '<div class="actions">'
      + (t ? '<button type="button" class="btn primary" id="tplSave">Spremi</button><button type="button" class="btn" id="tplDup">Dupliciraj</button><button type="button" class="btn danger" id="tplDel">Obriši</button>' : "")
      + '<button type="button" class="btn' + (t ? "" : " primary") + '" id="tplNew">Spremi kao novi</button></div>'
      + '<div class="hint">' + (t && t.builtin ? "Ugrađeni predložak: možeš ga mijenjati, a duplikat čuva original." : "Vlastiti predložak.") + "</div></div>";
    const payload = () => ({ name: $("tplName").value.trim(), tier: $("tplTier").value, description: $("tplDesc").value, prompt_prefix: $("tplPre").value,
      prompt_suffix: $("tplSuf").value, negative: $("tplNeg").value, size_preset: $("tplSize").value, steps: num($("tplSteps").value, 30), cfg: num($("tplCfg").value, 5) });
    const after = async (id, msg) => { await loadGenOptions(true); $("v11Tpl").innerHTML = tplOptions(id || ""); renderTplEditor(id); toast(msg); };
    const act = async (fn) => { try { await fn(); } catch (e) { toast(e.message, true); } };
    if ($("tplSave")) $("tplSave").onclick = () => act(async () => { await api("PUT", "/api/templates/" + t.id, payload()); await after(t.id, "Predložak spremljen."); });
    if ($("tplDup")) $("tplDup").onclick = () => act(async () => { const d = await post("/api/templates/" + t.id + "/duplicate"); await after(d.template.id, "Napravljena kopija."); });
    if ($("tplDel")) $("tplDel").onclick = () => act(async () => { if (!confirm("Obrisati predložak?")) return; await api("DELETE", "/api/templates/" + t.id); await after("", "Predložak obrisan."); });
    $("tplNew").onclick = () => act(async () => { const d = await post("/api/templates", payload()); await after(d.template.id, "Novi predložak spremljen."); });
  }
  function loadVaeChoice() {
    const d = (V.opts && V.opts.defaults) || {};
    try { return localStorage.getItem("studio.gen_vae") || d.vae || ""; } catch (e) { return d.vae || ""; }
  }
  function saveVaeChoice(v) {
    try { localStorage.setItem("studio.gen_vae", v || ""); } catch (e) { /* ignore */ }
  }
  function currentArch() {
    const c = C();
    return (c && typeof c.arch === "function" && c.arch()) || "sdxl";
  }
  function fillVaeOptions() {
    const sel = $("v11VaeFile");
    if (!sel) return;
    const arch = currentArch();
    const list = (V.opts && V.opts.vaes) || [{ id: "checkpoint", filename: "", label: "Iz checkpointa", arch: "all", available: true }];
    const cur = sel.value || loadVaeChoice();
    const ok = (it) => !it.arch || it.arch === "all" || it.arch === arch;
    const filtered = list.filter((it) => (arch === "krea2" ? it.id === "checkpoint" : ok(it)));
    sel.innerHTML = filtered.map((it) => {
      const val = it.filename || "";
      const miss = it.filename && it.available === false ? " — nije preuzet" : "";
      return '<option value="' + esc(val) + '"' + (val === cur ? " selected" : "") + ">" + esc(it.label || it.filename || "Iz checkpointa") + miss + "</option>";
    }).join("");
    if (cur && ![...sel.options].some((o) => o.value === cur)) {
      sel.insertAdjacentHTML("beforeend", '<option value="' + esc(cur) + '" selected>' + esc(cur) + "</option>");
    }
    if (arch === "krea2") sel.value = "";
    sel.disabled = arch === "krea2";
  }
  function readDetailLoras() {
    const keys = [];
    const weights = {};
    document.querySelectorAll("#v11DetailLoras .dtoggle").forEach((lab) => {
      const on = lab.querySelector(".dt-on, input[type=checkbox]");
      if (!on || !on.checked || !on.value) return;
      keys.push(on.value);
      const w = lab.querySelector(".dt-w");
      if (w) weights[on.value] = num(w.value, 0.5);
    });
    return { keys: keys, weights: weights };
  }
  function genExtras() {
    const out = {};
    const hwq = hwQuickValues();
    if (hwq) Object.assign(out, hwq);
    // Mora ići i kad Napredno još nije učitano: LoRA s Generiranja, profil, VAE, detail LoRA-e.
    const qb = document.querySelector("#quality button.on");
    if (qb && qb.dataset.profile) out.quality_profile = qb.dataset.profile;
    const st = (V.stack || []).filter((x) => x.name);
    if (st.length || V.stackTouched) out.loras = st;
    const dl = readDetailLoras();
    if (dl.keys.length) { out.detail_loras = dl.keys; out.detail_lora_weights = dl.weights; }
    if ($("v11VaeFile")) out.vae = $("v11VaeFile").value;
    else out.vae = loadVaeChoice();
    if ($("ipaEndAt")) out.ipadapter_end_at = num($("ipaEndAt").value, 1.0);
    if ($("v11VramGuard")) out.vram_guard = $("v11VramGuard").checked;
    if (!$("v11Sampler")) return out;
    out.sampler = $("v11Sampler").value;
    out.scheduler = $("v11Scheduler").value;
    if ($("v11CfgOn").checked) out.cfg = num($("v11Cfg").value, 4.3);
    out.hires_scale = num($("v11HiresScale").value, 1.45);
    out.hires_denoise = num($("v11HiresDenoise").value, 0.38);
    out.hires_steps = num($("v11HiresSteps").value, 14);
    out.freeu = $("v11Freeu").checked;
    if ($("v11RefMode").value) out.ref_mode = $("v11RefMode").value;
    out.instantid_weight = num($("v11IidWeight").value, 0.8);
    if ($("v11IidEnd")) out.instantid_end_at = num($("v11IidEnd").value, 0.8);
    out.fd_denoise = num($("v11FdDenoise").value, 0.25);
    out.fd_guide_size = num($("v11FdGuide").value, 384);
    out.fd_max_size = num($("v11FdMax").value, 768);
    out.fd_bbox_threshold = num($("v11FdBbox").value, 0.5);
    const tpl = $("v11Tpl").value;
    if (tpl) out.template_id = Number(tpl);
    return out;
  }
  async function enqueueBatch() {
    const c = C();
    if (!c) return;
    const body = Object.assign(c.payload(), genExtras());
    if (!body.prompt) { toast("Upiši opis scene.", true); return; }
    const tids = [...document.querySelectorAll("#v11MultiTpl input:checked")].map((i) => Number(i.value));
    try {
      const d = await post("/api/queue", { body: body, count: num($("v11BatchN").value, 1), seed_mode: $("v11SeedMode").value, template_ids: tids });
      toast("U red je dodano " + d.jobs.length + " poslova.");
      refreshQueue();
    } catch (e) { toast(e.message, true); }
  }

  /* brzi hardverski prekidači u Generiranju */
  function hwQuickValues() {
    if (!$("v11Safe")) return null;
    return { safe_mode: $("v11Safe").checked, vae_mode: $("v11Vae").value, vae_tile: V.hw ? num(V.hw.settings.hw_vae_tile, 512) : 512 };
  }
  function renderHwQuick() {
    const el = $("v11HwQuick");
    if (!el || !V.hw) return;
    const s = V.hw.settings;
    const p = V.hw.profile || {};
    const vaeLabels = { standard: "standard", tiled: "tiled (512)", cpu: "CPU" };
    el.innerHTML = '<label title="Niža bazna rezolucija pa upscale – stane u 8 GB VRAM-a"><input type="checkbox" id="v11Safe"' + (s.hw_safe_mode === "1" ? " checked" : "") + " /> 8 GB siguran mod</label>"
      + '<label>VAE način <select id="v11Vae">' + ["standard", "tiled", "cpu"].map((m) => '<option value="' + m + '"' + (s.hw_vae_mode === m ? " selected" : "") + ">" + vaeLabels[m] + "</option>").join("") + "</select></label>"
      + "<span>" + esc(p.name || "GPU nepoznat") + (p.vram_gb ? " · " + p.vram_gb + " GB" : "") + ' <span class="v11-badge gold">' + esc(V.hw.effective_backend || "auto") + "</span>"
      + (V.hw.disable_cudnn ? ' <span class="v11-badge ok" title="TORCH_BACKENDS_CUDNN_ENABLED=0">cuDNN isključen</span>' : ' <span class="v11-badge bad">cuDNN uključen</span>') + "</span>";
    const save = async () => {
      try {
        const vae = $("v11Vae").value;
        V.hw = await post("/api/hardware", { hw_safe_mode: $("v11Safe").checked ? "1" : "0", hw_vae_mode: vae });
        if (vae === "cpu") toast("VAE na CPU-u traži restart ComfyUI-ja (Postavke → Hardver).");
      } catch (e) { toast(e.message, true); }
    };
    $("v11Safe").addEventListener("change", save);
    $("v11Vae").addEventListener("change", save);
  }
  async function loadHw(force) {
    if (V.hw && !force) return V.hw;
    try { V.hw = await get("/api/hardware"); } catch (e) { V.hw = null; }
    renderHwQuick();
    return V.hw;
  }

  /* ---------- RED ČEKANJA ---------- */
  const JOB_BADGE = { running: "run", queued: "gold", done: "ok", error: "bad", cancelled: "" };
  const JOB_LABELS = { queued: "Na čekanju", running: "U tijeku", done: "Gotovo", error: "Greška", cancelled: "Otkazano" };
  function jobsHtml(q, compact) {
    if (!q || !q.jobs || !q.jobs.length) return '<div class="hint">Red je prazan.</div>';
    const labels = q.labels || JOB_LABELS;
    return q.jobs.slice(0, compact ? 5 : 40).map((j) => '<div class="v11-job" data-id="' + j.id + '">'
      + "<div>" + esc(j.label || ("Posao #" + j.id)) + ' <span class="v11-badge ' + (JOB_BADGE[j.status] || "") + '">' + esc(labels[j.status] || j.status) + "</span>"
      + (j.error ? '<div class="hint" style="color:var(--bad)">' + esc(j.error) + "</div>" : "") + "</div>"
      + (compact ? "<div></div>" : '<div class="acts">'
        + (j.status === "queued" || j.status === "running" ? '<button type="button" class="btn" data-q="cancel">Otkaži</button>' : "")
        + (j.status === "error" || j.status === "cancelled" ? '<button type="button" class="btn" data-q="retry">Ponovi</button>' : "") + "</div>")
      + (j.status === "running" ? '<div class="bar"><i style="width:' + Math.round((j.progress || 0) * 100) + '%"></i></div>' : "")
      + "</div>").join("");
  }
  async function refreshQueue() {
    const el = $("v11Queue");
    try { V.queue = await get("/api/queue?limit=40"); } catch (e) { return; }
    const q = V.queue;
    const c = q.counts || {};
    if (el) {
      el.innerHTML = (q.jobs || []).length ? '<div class="v11-row-between"><h2 class="sec">Red čekanja</h2><div class="v11-inline">'
        + '<span class="v11-badge run">U tijeku ' + (c.running || 0) + '</span><span class="v11-badge gold">Na čekanju ' + (c.queued || 0) + '</span><span class="v11-badge ok">Gotovo ' + (c.done || 0) + '</span><span class="v11-badge bad">Greška ' + (c.error || 0) + '</span><span class="v11-badge">Otkazano ' + (c.cancelled || 0) + "</span>"
        + '<button type="button" class="btn" id="v11QClear">Očisti gotove</button></div></div>' + jobsHtml(q, false) : "";
    }
    clearTimeout(V.queueTimer);
    if ((c.running || 0) + (c.queued || 0)) V.queueTimer = setTimeout(refreshQueue, 3000);
    if (V.lastDone !== undefined && (c.done || 0) > V.lastDone) loadGallery(true);
    V.lastDone = c.done || 0;
  }
  document.addEventListener("click", async (e) => {
    const b = e.target.closest && e.target.closest("[data-q]");
    if (b) {
      const id = b.closest(".v11-job").dataset.id;
      try { await post("/api/queue/" + id + "/" + b.dataset.q); refreshQueue(); } catch (err) { toast(err.message, true); }
      return;
    }
    if (e.target.id === "v11QClear") {
      try { const d = await post("/api/queue/clear"); toast("Uklonjeno " + d.removed + " završenih poslova."); refreshQueue(); } catch (err) { toast(err.message, true); }
    }
  });

  /* ---------- GALERIJA + OCJENE ---------- */
  const RATED = {};  // gallery_id -> ocjena (da ponovno iscrtavanje rezultata ne izgubi ocjenu)
  function ratingOf(gid) { return gid == null ? 0 : Number(RATED[String(gid)] || 0); }
  function rateBar(r) {
    r = Number(r || 0);
    return '<div class="rate-bar" role="group" aria-label="Ocjena slike">'
      + '<button type="button" class="rate-btn good' + (r > 0 ? " on" : "") + '" data-rate="1" title="Dobra – ide u LoRA dataset osobe" aria-pressed="' + (r > 0) + '">Dobra</button>'
      + '<button type="button" class="rate-btn bad' + (r < 0 ? " on" : "") + '" data-rate="-1" title="Loša – ne ide u LoRA dataset" aria-pressed="' + (r < 0) + '">Loša</button></div>';
  }
  function galCard(it) {
    const r = Number(it.rating || 0);
    RATED[String(it.id)] = r;
    const dl = it.url + (it.url.indexOf("?") >= 0 ? "&" : "?") + "download=1";
    return '<figure class="shot gal-shot' + (r > 0 ? " rated-good" : (r < 0 ? " rated-bad" : "")) + '" data-gid="' + it.id + '" data-persona="' + esc(it.persona_id || "") + '" data-filename="' + esc(it.filename) + '" data-subfolder="' + esc(it.subfolder || "") + '" data-type="' + esc(it.type || "output") + '" data-seed="' + esc(it.seed || "") + '" data-prompt="' + esc(it.prompt || "") + '">'
      + (r ? '<span class="v11-rate v11-badge ' + (r > 0 ? "ok" : "bad") + '">' + (r > 0 ? "Dobra" : "Loša") + "</span>" : "")
      + '<div class="shot-media"><img src="' + esc(it.url) + '" alt="" loading="lazy" decoding="async" data-full="' + esc(it.url) + '" data-dl="' + esc(dl) + '" />' + rateBar(r) + "</div>"
      + '<figcaption><span class="shot-cap">' + (it.source === "character_sheet" ? "Character sheet · " : "") + (it.seed ? "seed " + esc(it.seed) : "") + "</span></figcaption></figure>";
  }
  async function loadGallery(reset) {
    const el = $("v11Gallery");
    if (!el) return;
    if (reset) { V.galOffset = 0; V.galItems = []; }
    const f = $("v11GalFilter") ? $("v11GalFilter").value : "";
    let q = "/api/gallery?limit=24&offset=" + V.galOffset;
    if (f === "1" || f === "-1") q += "&rating=" + f;
    if (f === "sheet") q += "&source=character_sheet";
    try {
      const d = await get(q);
      const items = d.items || [];
      V.galItems = V.galItems.concat(items);
      V.galOffset += items.length;
      if (reset) el.innerHTML = items.map(galCard).join("") || '<div class="hint">Galerija je prazna. Gotove slike se ovdje spremaju automatski.</div>';
      else el.insertAdjacentHTML("beforeend", items.map(galCard).join(""));
      $("v11GalMore").hidden = !d.has_more;
    } catch (e) { /* tiho: galerija nije ključna */ }
  }
  function markLb(r) {
    const g = $("lbGood"), b = $("lbBad");
    if (g) g.classList.toggle("on", Number(r) > 0);
    if (b) b.classList.toggle("on", Number(r) < 0);
  }
  function shotFromFig(fig) {
    return { gid: fig.dataset.gid || "", filename: fig.dataset.filename || "", subfolder: fig.dataset.subfolder || "", type: fig.dataset.type || "output", seed: fig.dataset.seed || "", prompt: fig.dataset.prompt || "", persona: fig.dataset.persona || "" };
  }
  function syncMsg(ls, rating) {
    const st = ls && (ls.action || ls.status);
    if (rating > 0) {
      if (st === "added") return "Dobra ✓ — dodana u LoRA dataset osobe" + (ls.count ? " (" + ls.count + " slika)" : "") + ".";
      if (st === "exists") return "Dobra ✓ — već je u LoRA datasetu.";
      if (st === "deferred") return "Dobra ✓ — trening je u tijeku, uvezi „Dobra” slike kasnije.";
      if (st === "skipped") return "Dobra ✓ — nije dodana u dataset: " + (ls.reason || "preskočeno") + ".";
      if (st === "none") return "Dobra ✓" + (ls && ls.reason ? " — " + ls.reason : ".");
      return "Označeno kao dobra.";
    }
    if (rating < 0) return st === "removed" ? "Loša ✓ — maknuta iz LoRA dataseta." : "Označeno kao loša.";
    return st === "removed" ? "Ocjena uklonjena i slika maknuta iz dataseta." : "Ocjena uklonjena.";
  }
  async function rateShot(s, rating, fig) {
    if (!s || !s.filename) { toast("Otvori sliku iz galerije ili rezultata.", true); return null; }
    const c = C();
    const p = c && c.selectedPersona && c.selectedPersona();
    try {
      const body = { rating: rating, filename: s.filename, subfolder: s.subfolder, type: s.type, prompt: s.prompt, seed: s.seed, persona_id: s.persona ? Number(s.persona) : (p ? p.id : null) };
      if (s.gid) body.gallery_id = Number(s.gid);
      const d = await post("/api/gallery/rate", body);
      s.gid = d.item.id;
      const r = Number(d.item.rating || 0);
      RATED[String(d.item.id)] = r;
      toast(syncMsg(d.lora_sync || d.item.lora_sync, rating));
      V.galItems = V.galItems.map((x) => (x.id === d.item.id ? d.item : x));
      document.querySelectorAll('figure.shot[data-gid="' + d.item.id + '"]').forEach((f) => {
        if (f.closest("#v11Gallery")) { f.outerHTML = galCard(d.item); return; }
        f.querySelectorAll(".rate-btn").forEach((b) => { const on = Number(b.dataset.rate) === r && r !== 0; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
      });
      if (fig && !fig.dataset.gid) {
        fig.dataset.gid = d.item.id;
        fig.querySelectorAll(".rate-btn").forEach((b) => { const on = Number(b.dataset.rate) === r && r !== 0; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
      }
      if (V.lastShot && String(V.lastShot.gid) === String(d.item.id)) markLb(r);
      try { document.dispatchEvent(new CustomEvent("studio:rated", { detail: { item: d.item, lora_sync: d.lora_sync || d.item.lora_sync } })); } catch (e) { /* ignore */ }
      return d;
    } catch (e) { toast(e.message, true); return null; }
  }
  async function rate(rating) {
    const s = V.lastShot;
    if (!s) { toast("Otvori sliku iz galerije ili rezultata.", true); return; }
    await rateShot(s, rating, null);
  }
  /* 1.3.0: gumbi Dobra / Loša izravno na svakoj slici (rezultati, povijest, galerija); ponovni klik briše ocjenu */
  document.addEventListener("click", (e) => {
    const btn = e.target.closest && e.target.closest(".rate-btn");
    if (!btn) return;
    const fig = btn.closest("figure.shot");
    if (!fig) return;
    e.preventDefault();
    e.stopPropagation();
    const want = Number(btn.dataset.rate);
    const rating = btn.classList.contains("on") ? 0 : want;
    rateShot(shotFromFig(fig), rating, fig);
  });
  document.addEventListener("click", (e) => {
    const fig = e.target.closest && e.target.closest("figure.shot");
    if (fig && e.target.closest("img")) {
      V.lastShot = shotFromFig(fig);
      const item = V.galItems.find((x) => String(x.id) === String(fig.dataset.gid));
      markLb(item ? item.rating : 0);
    }
  }, true);

  /* ---------- PREGLED ---------- */
  /* 1.3.0: Početna — 4 glass KPI kartice sa sparkline / prsten grafikonima (SVG, bez vanjskih biblioteka) */
  function spark(vals, color, id) {
    const v = (vals || []).map((x) => num(x, 0));
    if (v.length < 2) return "";
    const W = 220, H = 56, mx = Math.max.apply(null, v.concat([1])), step = W / (v.length - 1);
    const pts = v.map((x, i) => [i * step, H - 4 - (x / mx) * (H - 10)]);
    // glatka krivulja (kubni Bézier kroz sredine), bez vanjskih biblioteka
    let line = "M" + pts[0][0].toFixed(1) + " " + pts[0][1].toFixed(1);
    for (let i = 1; i < pts.length; i++) {
      const p0 = pts[i - 1], p1 = pts[i], mx2 = (p0[0] + p1[0]) / 2;
      line += " C" + mx2.toFixed(1) + " " + p0[1].toFixed(1) + " " + mx2.toFixed(1) + " " + p1[1].toFixed(1) + " " + p1[0].toFixed(1) + " " + p1[1].toFixed(1);
    }
    const area = line + " L" + W + " " + H + " L0 " + H + " Z";
    return '<svg class="kpi-spark" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" aria-hidden="true">'
      + '<defs><linearGradient id="' + id + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="' + color + '" stop-opacity="0.38"/><stop offset="1" stop-color="' + color + '" stop-opacity="0"/></linearGradient></defs>'
      + '<path d="' + area + '" fill="url(#' + id + ')"/><path d="' + line + '" fill="none" stroke="' + color + '" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>';
  }
  function ring(frac, color, label) {
    const f = Math.max(0, Math.min(1, num(frac, 0))), R = 26, L = 2 * Math.PI * R;
    return '<svg class="kpi-ring" viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="' + R + '" fill="none" stroke="rgba(255,255,255,0.09)" stroke-width="7"/>'
      + '<circle cx="32" cy="32" r="' + R + '" fill="none" stroke="' + color + '" stroke-width="7" stroke-linecap="round" stroke-dasharray="' + (f * L).toFixed(1) + " " + L.toFixed(1) + '" transform="rotate(-90 32 32)"/>'
      + '<text x="32" y="36" text-anchor="middle" class="ring-txt">' + esc(label) + "</text></svg>";
  }
  function trend(vals) {
    const v = (vals || []).map((x) => num(x, 0));
    const h = Math.floor(v.length / 2);
    const a = v.slice(0, h).reduce((x, y) => x + y, 0), b = v.slice(h).reduce((x, y) => x + y, 0);
    if (!a && !b) return '<span class="kpi-trend flat">bez promjene</span>';
    if (!a) return '<span class="kpi-trend up">▲ novo</span>';
    const pct = Math.round(((b - a) / a) * 100);
    return '<span class="kpi-trend ' + (pct >= 0 ? "up" : "down") + '">' + (pct >= 0 ? "▲ " : "▼ ") + Math.abs(pct) + " %</span>";
  }
  function homeCard(cls, ico, eyebrow, value, sub, viz) {
    return '<div class="kpi-card ' + cls + '"><div class="kpi-top"><span class="kpi-ico" aria-hidden="true">' + ico + '</span><span class="kpi-eyebrow">' + eyebrow + "</span></div>"
      + '<div class="kpi-body"><div><div class="kpi-num">' + value + '</div><div class="kpi-sub">' + sub + "</div></div>" + viz + "</div></div>";
  }
  function renderHomeKpis(d) {
    const el = $("v13HomeKpis");
    if (!el) return;
    const sum = (a) => (a || []).reduce((x, y) => x + num(y, 0), 0);
    const crm = d.crm || {};
    const rev = d.revenue_series || [], imgs = d.images_series || [];
    const good = num(d.rated_good, 0), bad = num(d.rated_bad, 0);
    const prof = num(d.profiles, 0), withLora = num(d.personas_with_lora, 0);
    const sched = num(d.scheduled_posts, 0), today = num(d.posts_today, 0);
    el.innerHTML = homeCard("k-violet", "€", "Prihodi", money(crm.total_revenue), money(sum(rev)) + " u 14 dana " + trend(rev), spark(rev, "#b893ff", "spRev"))
      + homeCard("k-sky", "▣", "Slike", String(num(d.gallery_total, 0)), sum(imgs) + " novih · Dobra " + good + " · Loša " + bad + " " + trend(imgs), spark(imgs, "#6eb6ff", "spImg"))
      + homeCard("k-mint", "◎", "Aktivne osobe", String(prof), withLora + " s LoRA-om · " + (prof - withLora > 0 ? (prof - withLora) + " bez" : "sve spremne"), ring(prof ? withLora / prof : 0, "#5ce8b0", prof ? Math.round((withLora / prof) * 100) + "%" : "0%"))
      + homeCard("k-coral", "◷", "Zakazano", String(sched), today + " objava danas · red " + num((d.queue || {}).queued, 0), ring(sched ? Math.min(1, today / Math.max(sched, 1)) : 0, "#ff7893", String(today)));
  }
  async function renderOverview() {
    const el = $("v11Kpis");
    if (!el) return;
    let d;
    try { d = await get("/api/v11/overview"); } catch (e) { el.innerHTML = '<div class="err">' + esc(e.message) + "</div>"; return; }
    const h = d.hardware || {};
    const q = d.queue || {};
    const crm = d.crm || {};
    const auto = d.send_mode === "auto";
    el.innerHTML = kpi("ComfyUI", d.comfy.ok ? "Spojen" : "Nije pokrenut", d.comfy.ok ? "" : "Pokreni comfyui-n.bat ili Postavke → restart", d.comfy.ok ? "ok" : "bad")
      + kpi("GPU", esc(h.name || "nepoznat"), esc((h.vram_gb ? h.vram_gb + " GB · " : "") + (h.backend || "") + (h.vram && h.vram.free_gb ? " · slobodno " + h.vram.free_gb + " GB" : "")) + (h.cudnn_off ? ' <span class="v11-badge ok">cuDNN off</span>' : ""))
      + kpi("Red čekanja", (q.running || 0) + " / " + (q.queued || 0), "u tijeku / na čekanju · gotovo " + (q.done || 0) + " · greška " + (q.error || 0))
      + kpi("Objave danas", d.posts_today || 0, "zakazano ili objavljeno")
      + kpi("Nepročitano", crm.unread || 0, "otvorene narudžbe: " + (crm.open_orders || 0))
      + kpi("Zainteresirani fanovi", crm.interested_leads || 0, "od " + (crm.total_contacts || 0) + " kontakata")
      + kpi("Pretplatnici", crm.active_subscribers || 0, "konverzija " + (crm.conversion_rate || 0) + " %")
      + kpi("Prihod", money(crm.total_revenue), "zabilježene kupnje")
      + kpi("Slanje poruka", auto ? "Automatsko" : "Nacrt", '<button type="button" class="btn" id="ovSendToggle">' + (auto ? "Prebaci na nacrt" : "Uključi automatsko") + "</button> · AI: " + esc(d.llm), auto ? "ok" : "")
      + kpi("Galerija", d.gallery_total || 0, "osoba: " + (d.profiles || 0));
    renderHomeKpis(d);
    $("v11OvQueue").innerHTML = jobsHtml({ jobs: d.queue_jobs }, true);
    $("v11OvPosts").innerHTML = (d.upcoming_posts || []).map(postItem).join("") || '<div class="hint">Nema zakazanih objava.</div>';
    const t = $("ovSendToggle");
    if (t) t.onclick = () => setSendMode("global", auto ? "approve" : "auto").then(renderOverview);
  }
  function bindOverview() {
    const f = $("v11Formats");
    if (f) f.addEventListener("click", (e) => {
      const b = e.target.closest("[data-size]");
      if (!b || !C()) return;
      C().showTab("slike");
      setTimeout(() => { if (!C().pickSize(b.dataset.size)) toast("IG formati su dostupni za SDXL i SD 1.5 modele.", true); }, 50);
    });
    const a = $("v11QuickActions");
    if (a) a.addEventListener("click", async (e) => {
      const b = e.target.closest("button");
      if (!b || !C()) return;
      if (b.dataset.go) { C().showTab(b.dataset.go); return; }
      if (b.dataset.act === "rx6600") {
        try { V.hw = await post("/api/hardware/recommend", {}); renderHwQuick(); toast("Primijenjena preporuka za RX 6600. Restartaj ComfyUI u Postavkama da vrijedi."); } catch (err) { toast(err.message, true); }
      }
      if (b.dataset.act === "sheet") C().showTab("influenceri");
    });
  }

  /* ---------- OSOBE ---------- */
  let personaBoxBound = false;
  async function renderPersona() {
    const el = $("v11Persona");
    const c = C();
    if (!el || !c) return;
    const id = c.editingId() || c.state().active_profile_id;
    const p = (c.state().profiles || []).find((x) => x.id === id);
    if (!p) { el.innerHTML = '<div class="hint">Odaberi osobu lijevo za LoRA stack, character sheet i LoRA dataset.</div>'; return; }
    V.pStack = (p.lora_stack || []).map((x) => ({ name: x.name, strength_model: x.strength_model, strength_clip: x.strength_clip }));
    V.pId = p.id;
    let rated = { items: [] };
    try { rated = await get("/api/gallery?persona_id=" + p.id + "&limit=12"); } catch (e) { /* */ }
    const good = (rated.items || []).filter((x) => Number(x.rating) > 0).length;
    const opt = (list, cur) => list.map((x) => '<option value="' + x[0] + '"' + (cur === x[0] ? " selected" : "") + ">" + x[1] + "</option>").join("");
    el.innerHTML = '<h2 class="sec" style="margin-top:0">' + esc(p.name) + " · LoRA, lice, slanje i dataset</h2>"
      + '<div class="v11-grid2"><div>'
      + '<div class="field"><label class="lbl">LoRA stack osobe (do 5)</label><div id="pStackBox">' + stackEditorHtml("pst", V.pStack) + "</div></div>"
      + '<div class="field"><label class="lbl" for="pRefMode">Konzistentnost lica</label><select id="pRefMode">' + opt([["auto", "Automatski"], ["ipadapter", "IP-Adapter"], ["instantid", "InstantID"]], p.ref_mode || "auto") + "</select>"
      + rangeLabel("Jačina InstantID", "pIid", "pIidVal", 0.3, 1.2, 0.05, num(p.instantid_weight, 0.8), 2) + "</div>"
      + '<div class="field"><label class="lbl" for="pSendMode">Slanje poruka za ovu osobu</label><select id="pSendMode">' + opt([["", "Kao globalno / kanal"], ["approve", "Nacrt za odobrenje"], ["auto", "Automatsko slanje odmah"]], p.send_mode || "") + "</select></div>"
      + '<div class="field"><label class="lbl" for="pBio">Kratki bio (za objave i CRM)</label><textarea id="pBio" style="min-height:60px" maxlength="2000">' + esc(p.bio || "") + "</textarea></div>"
      + '<div class="actions"><button type="button" class="btn primary" id="pExtrasSave">Spremi</button></div>'
      + "</div><div>"
      + '<div class="field"><label class="lbl">Character sheet</label><div class="hint">4 kadra iste osobe (lice sprijeda, profil, poluplan, cijela figura) spojena u 2×2 PNG. Ide kroz red čekanja.</div>'
      + '<div class="actions"><button type="button" class="btn" id="pSheet">Generiraj Character Sheet</button></div></div>'
      + '<div class="field"><label class="lbl">LoRA trener</label><div class="hint">Istreniraj vlastitu LoRA-u lica ove osobe izravno u Studiju (15–40 slika, jedan klik, sigurno za 8 GB).</div>'
      + '<div class="actions"><button type="button" class="btn primary" id="pLoraTrainer">LoRA trener</button></div></div>'
      + '<div class="field"><label class="lbl">LoRA dataset (izvoz)</label><div class="hint">Slike označene kao „Dobra” (' + good + " među zadnjih 12) izvoze se u data/lora_datasets/&lt;osoba&gt;/ s captionima i 8 GB Kohya / OneTrainer configom.</div>"
      + '<div class="v11-grid2"><label>Trigger riječ <input type="text" id="pTrigger" placeholder="npr. lunamaric" maxlength="40" /></label><label>Ponavljanja <input type="number" id="pRepeats" min="1" max="100" value="10" /></label></div>'
      + '<div class="actions"><button type="button" class="btn" id="pDataset">Izvezi LoRA dataset</button></div><div class="hint" id="pDatasetOut"></div></div>'
      + '<div class="field"><label class="lbl">Zadnje slike osobe (klikni pa ocijeni Dobra / Loša)</label><div class="gallery v11-gal">' + (rated.items || []).map(galCard).join("") + "</div>"
      + ((rated.items || []).length ? "" : '<div class="hint">Još nema slika ove osobe u galeriji.</div>') + "</div>"
      + "</div></div>";
    V.galItems = V.galItems.concat(rated.items || []);
    if (!personaBoxBound) {
      personaBoxBound = true;
      bindStack(el, "pst", (st, rerender) => { V.pStack = st; if (rerender) $("pStackBox").innerHTML = stackEditorHtml("pst", V.pStack); });
    }
    $("pIid").addEventListener("input", () => { $("pIidVal").textContent = num($("pIid").value, 0.8).toFixed(2); });
    $("pExtrasSave").onclick = async () => {
      try {
        await post("/api/profiles/" + p.id + "/extras", { lora_stack: V.pStack.filter((x) => x.name), ref_mode: $("pRefMode").value, instantid_weight: num($("pIid").value, 0.8), send_mode: $("pSendMode").value, bio: $("pBio").value });
        await c.loadState();
        syncStackFromPersona(true);
        V.sendState = null;
        toast("Spremljeno za " + p.name + ".");
      } catch (e) { toast(e.message, true); }
    };
    $("pLoraTrainer").onclick = () => { if (window.StudioLoraTrainer) window.StudioLoraTrainer.open(p.id); };
    try { if (window.StudioLoraTrainer && window.StudioLoraTrainer.follow) window.StudioLoraTrainer.follow(p.id); } catch (e) { /* */ }
    $("pSheet").onclick = async () => {
      try { const d = await post("/api/character-sheet", { persona_id: p.id }); toast("Character sheet je u redu čekanja (" + d.jobs.length + " kadra)."); refreshQueue(); } catch (e) { toast(e.message, true); }
    };
    $("pDataset").onclick = async () => {
      try {
        const d = await post("/api/lora-dataset/export", { persona_id: p.id, trigger: $("pTrigger").value.trim(), repeats: num($("pRepeats").value, 10) });
        $("pDatasetOut").textContent = "Izvezeno " + d.images + " slika u " + d.folder + (d.skipped ? " (preskočeno " + d.skipped + ")" : "") + ". Trigger: " + d.trigger;
      } catch (e) { toast(e.message, true); }
    };
  }

  /* ---------- KALENDAR ---------- */
  const CH_LABELS = { instagram: "Instagram", facebook: "Facebook", telegram: "Telegram", premium_api: "Premium API" };
  function postItem(pst) {
    return '<div class="v11-post-item" data-post="' + pst.id + '">' + (pst.media_preview ? '<img src="' + esc(pst.media_preview) + '" alt="" loading="lazy" />' : "")
      + "<div><strong>" + esc(pst.scheduled_local ? pst.scheduled_local.replace("T", " ") : "bez termina") + "</strong> " + statusBadge(pst.status, pst.status_label)
      + '<div class="hint">' + esc(pst.post_type_label) + " · " + esc((pst.channels || []).map((c) => CH_LABELS[c] || c).join(", ") || "bez kanala") + " · " + esc((pst.caption || "").slice(0, 60)) + "</div></div></div>";
  }
  function monthKey(d) { return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0"); }
  function isoDay(day) { return day.getFullYear() + "-" + String(day.getMonth() + 1).padStart(2, "0") + "-" + String(day.getDate()).padStart(2, "0"); }
  async function renderCalendar() {
    if (!$("calGrid")) return;
    if (!V.calMonth) { const n = new Date(); V.calMonth = new Date(n.getFullYear(), n.getMonth(), 1); }
    let d;
    try { d = await get("/api/posts?month=" + monthKey(V.calMonth)); } catch (e) { toast(e.message, true); return; }
    V.posts = d.posts || [];
    const first = new Date(V.calMonth);
    $("calTitle").textContent = first.toLocaleDateString("hr-HR", { month: "long", year: "numeric" });
    const start = new Date(first); start.setDate(1 - ((first.getDay() + 6) % 7));
    const today = new Date().toDateString();
    let html = ["Pon", "Uto", "Sri", "Čet", "Pet", "Sub", "Ned"].map((x) => '<div class="dow">' + x + "</div>").join("");
    for (let i = 0; i < 42; i++) {
      const day = new Date(start); day.setDate(start.getDate() + i);
      const iso = isoDay(day);
      const evs = V.posts.filter((p) => (p.scheduled_local || "").slice(0, 10) === iso);
      html += '<div class="day' + (day.getMonth() !== first.getMonth() ? " other" : "") + (day.toDateString() === today ? " today" : "") + '" data-day="' + iso + '"><span class="n">' + day.getDate() + "</span>"
        + evs.map((p) => '<span class="ev ' + esc(p.status) + '" data-post="' + p.id + '" title="' + esc(p.status_label) + '">' + esc((p.scheduled_local || "").slice(11, 16) + " " + (p.caption || p.post_type_label).slice(0, 22)) + "</span>").join("") + "</div>";
    }
    $("calGrid").innerHTML = html;
    $("calUpcoming").innerHTML = (d.upcoming || []).map(postItem).join("") || '<div class="hint">Nema nadolazećih objava.</div>';
    const ch = d.channels || {};
    $("calChannels").innerHTML = "Kanali: " + Object.keys(ch).map((k) => esc(CH_LABELS[k] || k) + " " + (ch[k].configured ? '<span class="v11-badge ok">spreman</span>' : '<span class="v11-badge" title="Nedostaje: ' + esc((ch[k].missing || []).join(", ")) + '">nije podešen</span>')).join(" · ") + " · ključevi se upisuju u Postavkama.";
    if (!V.editPost) renderPostForm(null);
  }
  async function renderPostForm(pst, dayIso) {
    V.editPost = pst;
    const f = $("postForm");
    if (!f) return;
    const c = C();
    const profiles = c ? (c.state().profiles || []) : [];
    try { V.gallery = (await get("/api/gallery?limit=36")).items || []; } catch (e) { V.gallery = V.gallery || []; }
    const when = pst && pst.scheduled_local ? pst.scheduled_local : (dayIso ? dayIso + "T10:00" : "");
    const chans = pst ? (pst.channels || []) : ["instagram"];
    const results = pst && pst.results ? pst.results : {};
    f.innerHTML = '<h2 class="sec" style="margin-top:0">' + (pst ? "Objava #" + pst.id + " " + statusBadge(pst.status, pst.status_label) : "Nova objava") + "</h2>"
      + '<div class="v11-grid2"><label>Osoba <select id="poPersona"><option value="">—</option>' + profiles.map((p) => '<option value="' + p.id + '"' + (pst && pst.persona_id === p.id ? " selected" : "") + ">" + esc(p.name) + "</option>").join("") + "</select></label>"
      + '<label>Vrsta <select id="poType"><option value="public_teaser">Javni teaser</option><option value="premium"' + (pst && pst.post_type === "premium" ? " selected" : "") + ">Premium sadržaj</option></select></label></div>"
      + '<label>Predložak <select id="poTpl">' + tplOptions(pst ? pst.template_id || "" : "") + "</select></label>"
      + '<div class="field"><label class="lbl">Kanali</label><div class="chips">' + Object.keys(CH_LABELS).map((v) => '<label class="chip"><input type="checkbox" class="poCh" value="' + v + '"' + (chans.indexOf(v) >= 0 ? " checked" : "") + " /> " + CH_LABELS[v] + "</label>").join("") + "</div></div>"
      + '<label>Opis objave <textarea id="poCaption" style="min-height:90px" maxlength="2200">' + esc(pst ? pst.caption : "") + "</textarea></label>"
      + '<div class="v11-grid2"><label>Hashtagovi <input type="text" id="poTags" value="' + esc(pst ? pst.hashtags : "") + '" /></label><label>Cijena (Premium, €) <input type="number" id="poPrice" min="0" step="0.5" value="' + esc(pst && pst.price != null ? pst.price : "") + '" /></label></div>'
      + '<label>Termin <input type="datetime-local" id="poWhen" value="' + esc(when) + '" /></label>'
      + '<div class="field"><label class="lbl">Slika</label>' + (pst && pst.media_preview ? '<img src="' + esc(pst.media_preview) + '" alt="" style="max-width:140px;border-radius:10px;display:block;margin-bottom:6px" loading="lazy" />' : "")
      + '<div class="hint">Klikni sliku iz galerije ili učitaj datoteku.</div><div class="v11-pick" id="poPick">' + V.gallery.map((g) => '<img src="' + esc(g.url) + '" data-gid="' + g.id + '" alt="" loading="lazy"' + (pst && pst.gallery_id === g.id ? ' class="on"' : "") + " />").join("") + "</div>"
      + '<input type="file" id="poFile" accept="image/png,image/jpeg,image/webp" style="margin-top:8px" /></div>'
      + '<div class="actions"><button type="button" class="btn" data-po="draft">Spremi kao nacrt</button><button type="button" class="btn primary" data-po="scheduled">Zakaži</button>'
      + '<button type="button" class="btn" data-po="now">Objavi odmah</button>' + (pst ? '<button type="button" class="btn danger" data-po="del">Obriši</button><button type="button" class="btn" data-po="new">Nova</button>' : "") + "</div>"
      + (pst && pst.error ? '<div class="err">' + esc(pst.error) + "</div>" : "")
      + (Object.keys(results).length ? '<div class="v11-pre">' + esc(Object.keys(results).map((k) => (CH_LABELS[k] || k) + ": " + (results[k].ok ? "objavljeno " + (results[k].id || "") : (results[k].error || "greška"))).join("\n")) + "</div>" : "")
      + '<div class="hint">Instagram treba javni URL slike (PUBLIC_MEDIA_BASE_URL, npr. Cloudflare tunel). Javni teaser i Premium sadržaj su SFW: editorial, lifestyle, moda, studio glamour, iza kulisa.</div>';
    f.onclick = async (e) => {
      const img = e.target.closest("#poPick img");
      if (img) { f.querySelectorAll("#poPick img").forEach((x) => x.classList.toggle("on", x === img && !x.classList.contains("on"))); return; }
      const b = e.target.closest("[data-po]");
      if (!b) return;
      const act = b.dataset.po;
      try {
        if (act === "new") { renderPostForm(null); return; }
        if (act === "del") { if (!confirm("Obrisati objavu?")) return; await api("DELETE", "/api/posts/" + pst.id); V.editPost = null; renderCalendar(); return; }
        const picked = f.querySelector("#poPick img.on");
        const body = { persona_id: $("poPersona").value || null, post_type: $("poType").value, template_id: $("poTpl").value || null,
          channels: [...f.querySelectorAll(".poCh:checked")].map((x) => x.value), caption: $("poCaption").value, hashtags: $("poTags").value,
          price: $("poPrice").value, scheduled_at: $("poWhen").value || null, status: act === "scheduled" ? "scheduled" : "draft" };
        if (act === "scheduled" && !body.scheduled_at) { toast("Odaberi termin.", true); return; }
        if (picked) body.gallery_id = Number(picked.dataset.gid);
        const file = $("poFile").files && $("poFile").files[0];
        if (file) {
          body.upload_base64 = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); });
          body.upload_ext = (file.name.split(".").pop() || "png").toLowerCase();
        }
        let d = pst ? await api("PUT", "/api/posts/" + pst.id, body) : await post("/api/posts", body);
        if (act === "now") d = await post("/api/posts/" + d.post.id + "/publish");
        toast(act === "now" ? ("Objava: " + d.post.status_label + (d.post.error ? " – " + d.post.error : "")) : "Spremljeno.", d.post.status === "error");
        await renderCalendar();
        renderPostForm(d.post);
      } catch (err) { toast(err.message, true); }
    };
  }
  function bindCalendar() {
    if ($("calPrev")) $("calPrev").onclick = () => { V.calMonth = new Date(V.calMonth.getFullYear(), V.calMonth.getMonth() - 1, 1); renderCalendar(); };
    if ($("calNext")) $("calNext").onclick = () => { V.calMonth = new Date(V.calMonth.getFullYear(), V.calMonth.getMonth() + 1, 1); renderCalendar(); };
    document.addEventListener("click", (e) => {
      const it = e.target.closest && e.target.closest("[data-post]");
      if (it && (it.closest("#tab-kalendar") || it.closest("#tab-pregled"))) {
        if (it.closest("#tab-pregled") && C()) C().showTab("kalendar");
        get("/api/posts/" + Number(it.dataset.post)).then((d) => renderPostForm(d.post)).catch((err) => toast(err.message, true));
        return;
      }
      const day = e.target.closest && e.target.closest("#calGrid .day");
      if (day) renderPostForm(null, day.dataset.day);
    });
  }

  /* ---------- INBOX I CRM: način slanja ---------- */
  async function setSendMode(scope, mode, extra) {
    try {
      V.sendState = await post("/api/crm/send-mode", Object.assign({ scope: scope, mode: mode }, extra || {}));
      if (scope === "global" && C()) C().syncSendMode(mode);
      renderSendBar(false);
      toast(scope === "global" ? (mode === "auto" ? "Automatsko slanje odmah je uključeno." : "Nacrt za odobrenje je uključen.") : "Način slanja spremljen.");
    } catch (e) { toast(e.message, true); }
  }
  function miniSeg(scope, key, cur) {
    return '<span class="v11-mini" data-scope="' + scope + '" data-key="' + esc(key) + '">'
      + [["", "Kao globalno"], ["approve", "Nacrt"], ["auto", "Auto"]].map((x) => '<button type="button" data-mode="' + x[0] + '"' + ((cur || "") === x[0] ? ' class="on"' : "") + ">" + x[1] + "</button>").join("") + "</span>";
  }
  async function renderSendBar(reload) {
    const el = $("v11SendBar");
    if (!el) return;
    if (!V.sendState || reload) { try { V.sendState = await get("/api/crm/send-mode"); } catch (e) { return; } }
    if (!V.llm || reload) { try { V.llm = await get("/api/crm/llm"); } catch (e) { V.llm = null; } }
    const s = V.sendState;
    const g = s.global === "auto" ? "auto" : "approve";
    const labels = s.labels || {};
    const open = el.querySelector("details") && el.querySelector("details").open;
    el.innerHTML = '<div class="v11-sendmain"><strong>Način slanja AI odgovora</strong>'
      + '<span class="v11-bigtoggle" id="v11BigToggle" role="group" aria-label="Način slanja"><button type="button" class="approve' + (g === "approve" ? " on" : "") + '" data-mode="approve" aria-pressed="' + (g === "approve") + '">Nacrt za odobrenje</button>'
      + '<button type="button" class="auto' + (g === "auto" ? " on" : "") + '" data-mode="auto" aria-pressed="' + (g === "auto") + '">Automatsko slanje odmah</button></span>'
      + '<span class="v11-sendstate">' + (g === "auto" ? "Odgovori se šalju odmah (uz limit na sat i tihe sate)." : "Svaki odgovor čeka tvoje odobrenje.") + "</span>"
      + (V.llm ? '<span class="v11-badge gold" title="Postavke → AI chat">AI: ' + esc(V.llm.active) + "</span>" : "") + "</div>"
      + '<details class="adv" style="margin-top:10px"' + (open ? " open" : "") + "><summary>Po kanalu i po influenceru (nadjačava globalno)</summary><div class=\"v11-scopes\">"
      + '<div><div class="lbl">Kanali</div>' + Object.keys(s.channels || {}).map((ch) => '<div class="v11-scope-row"><span>' + esc(labels[ch] || ch) + "</span>" + miniSeg("channel", ch, s.channels[ch]) + "</div>").join("") + "</div>"
      + '<div><div class="lbl">Influenceri</div>' + (s.profiles || []).map((p) => '<div class="v11-scope-row"><span>' + esc(p.name) + "</span>" + miniSeg("profile", p.id, p.send_mode) + "</div>").join("") + "</div>"
      + '</div><div class="hint">Redoslijed: influencer → kanal → globalno. „Kao globalno” prati glavni prekidač.</div></details>';
  }
  document.addEventListener("click", (e) => {
    const big = e.target.closest && e.target.closest("#v11BigToggle button");
    if (big) { setSendMode("global", big.dataset.mode); return; }
    const mb = e.target.closest && e.target.closest(".v11-mini button");
    if (mb) {
      const seg = mb.closest(".v11-mini");
      const extra = seg.dataset.scope === "channel" ? { platform: seg.dataset.key } : { profile_id: Number(seg.dataset.key) };
      setSendMode(seg.dataset.scope, mb.dataset.mode || "inherit", extra);
    }
  });

  /* ---------- CRM: info o razgovoru ---------- */
  const INTEREST = { low: ["Nizak", ""], medium: ["Srednji", "gold"], high: ["Visok", "ok"], custom_request: ["Custom zahtjev", "ok"], subscriber: ["Pretplatnik", "ok"] };
  const TIER_LABELS = { free: "Besplatno", subscriber: "Pretplatnik", vip: "VIP" };
  function interestBadge(k) { const x = INTEREST[k] || [k || "—", ""]; return '<span class="v11-badge ' + x[1] + '">Interes: ' + esc(x[0]) + "</span>"; }
  const memText = (list) => (list || []).map((m) => esc(m.content || "")).join(" · ");
  let threadPoll = null, lastThread = null;
  async function renderThreadInfo(force) {
    const c = C();
    const el = $("v11ThreadInfo");
    if (!c || !el) return;
    const tid = c.currentThreadId();
    if (!tid) { el.hidden = true; lastThread = null; return; }
    if (tid === lastThread && !force) return;
    lastThread = tid;
    try {
      const ct = (await get("/api/crm/threads/" + tid + "/contact")).contact;
      if (!ct) { el.hidden = true; return; }
      el.hidden = false;
      el.innerHTML = "<strong>" + esc(ct.display_name || "Fan") + "</strong> · " + interestBadge(ct.interest) + ' <span class="v11-badge">' + esc(TIER_LABELS[ct.tier] || ct.tier) + "</span> · potrošeno " + money(ct.total_spent)
        + (ct.suggested_action ? '<div class="hint">Prijedlog: ' + esc(ct.suggested_action) + "</div>" : "")
        + ((ct.memory || []).length ? '<div class="hint">Pamti: ' + memText(ct.memory.slice(0, 5)) + "</div>" : "")
        + '<div class="actions"><button type="button" class="btn" id="tiOrder">Kreiraj custom narudžbu</button><button type="button" class="btn" id="tiOpen">Otvori kontakt</button></div>';
      $("tiOrder").onclick = async () => {
        const desc = window.prompt("Opis personaliziranog SFW portreta ili shoutouta:", "");
        if (!desc) return;
        const price = window.prompt("Cijena (€):", "15");
        try { await post("/api/crm/orders", { contact_id: ct.id, profile_id: ct.profile_id, description: desc, price: price, thread_id: tid }); toast("Narudžba kreirana."); V.crmTab = "orders"; renderCrm(); } catch (err) { toast(err.message, true); }
      };
      $("tiOpen").onclick = () => { V.crmTab = "contacts"; V.contactSel = ct.id; renderCrm(); };
    } catch (e) { el.hidden = true; }
  }

  /* ---------- CRM: kontakti / narudžbe / analitika ---------- */
  async function renderCrm() {
    const el = $("v11Crm");
    if (!el) return;
    const tabs = [["contacts", "Kontakti i memorija"], ["orders", "Custom narudžbe"], ["analytics", "Analitika"], ["sources", "Izvori poruka"]];
    let body = "";
    try {
      if (V.crmTab === "contacts") body = await crmContactsHtml();
      else if (V.crmTab === "orders") body = await crmOrdersHtml();
      else if (V.crmTab === "analytics") body = await crmAnalyticsHtml();
      else body = crmSourcesHtml();
    } catch (e) { body = '<div class="err">' + esc(e.message) + "</div>"; }
    el.innerHTML = '<div class="card pad"><div class="v11-subtabs">' + tabs.map((t) => '<button type="button" data-crm="' + t[0] + '"' + (V.crmTab === t[0] ? ' class="on"' : "") + ">" + t[1] + "</button>").join("") + "</div>" + body + "</div>";
    bindContactDetail();
  }
  async function crmContactsHtml() {
    const list = (await get("/api/crm/contacts")).contacts || [];
    if (!list.length) return '<div class="hint">Još nema kontakata. Simuliraj poruku fana gore ili spoji Instagram, Telegram ili webhook.</div>';
    let html = '<table class="v11-table"><tr><th>Fan</th><th>Kanal</th><th>Interes</th><th>Razina</th><th>Potrošeno</th><th>Zadnje</th></tr>'
      + list.map((ct) => '<tr data-contact="' + ct.id + '"' + (V.contactSel === ct.id ? ' class="sel"' : "") + ' style="cursor:pointer"><td>' + esc(ct.display_name || ct.external_user_id) + (ct.unread ? ' <span class="v11-badge gold">novo</span>' : "") + "</td><td>" + esc(ct.platform) + "</td><td>" + interestBadge(ct.interest) + "</td><td>" + esc(TIER_LABELS[ct.tier] || ct.tier) + "</td><td>" + money(ct.total_spent) + "</td><td>" + fmtTime(ct.last_seen) + "</td></tr>").join("")
      + "</table>";
    if (V.contactSel) {
      try {
        const ct = (await get("/api/crm/contacts/" + V.contactSel)).contact;
        V.contactObj = ct;
        html += '<div class="v11-detail card pad"><h2 class="sec" style="margin-top:0">' + esc(ct.display_name || "Fan") + " " + interestBadge(ct.interest) + "</h2>"
          + (ct.suggested_action ? '<div class="hint">Prijedlog: ' + esc(ct.suggested_action) + "</div>" : "")
          + '<div class="v11-grid3"><label>Razina <select id="ctTier">' + Object.keys(TIER_LABELS).map((t) => '<option value="' + t + '"' + (ct.tier === t ? " selected" : "") + ">" + TIER_LABELS[t] + "</option>").join("") + "</select></label>"
          + '<label>Preferencije <input type="text" id="ctPref" value="' + esc(ct.preferences || "") + '" /></label><label>Bilješke <input type="text" id="ctNotes" value="' + esc(ct.notes || "") + '" /></label></div>'
          + '<div class="actions"><button type="button" class="btn primary" id="ctSave">Spremi</button><button type="button" class="btn" id="ctBuy">Zabilježi kupnju</button></div>'
          + '<div class="lbl">Memorija</div><div class="hint">' + (memText(ct.memory) || "—") + "</div>"
          + '<div class="lbl" style="margin-top:8px">Povijest kupnji</div>' + ((ct.purchases || []).map((p) => '<div class="hint">' + fmtTime(p.created_at) + " · " + esc(p.kind) + " · " + money(p.amount) + " · " + esc(p.channel || "") + "</div>").join("") || '<div class="hint">—</div>')
          + "</div>";
      } catch (e) { V.contactSel = null; V.contactObj = null; }
    }
    return html;
  }
  function bindContactDetail() {
    const ct = V.contactObj;
    if (!ct || !$("ctSave")) return;
    $("ctSave").onclick = async () => { try { await post("/api/crm/contacts/" + ct.id, { tier: $("ctTier").value, preferences: $("ctPref").value, notes: $("ctNotes").value }); toast("Kontakt spremljen."); renderCrm(); } catch (e) { toast(e.message, true); } };
    $("ctBuy").onclick = async () => {
      const kind = window.prompt("Vrsta (subscription / custom / ppv / tip):", "subscription");
      if (!kind) return;
      const amount = window.prompt("Iznos (€):", "9.99");
      try { await post("/api/crm/purchases", { contact_id: ct.id, profile_id: ct.profile_id, kind: kind, amount: amount, channel: ct.platform }); toast("Kupnja zabilježena."); renderCrm(); } catch (e) { toast(e.message, true); }
    };
  }
  async function crmOrdersHtml() {
    const list = (await get("/api/crm/orders")).orders || [];
    if (!list.length) return '<div class="hint">Nema narudžbi. Otvori razgovor i klikni „Kreiraj custom narudžbu”. Narudžbe su personalizirani SFW portreti i shoutouti.</div>';
    const st = { pending: "draft", generating: "publishing", ready: "scheduled", delivered: "published", paid: "published", cancelled: "error" };
    return '<table class="v11-table"><tr><th>#</th><th>Fan</th><th>Opis</th><th>Cijena</th><th>Status</th><th>Slika</th><th></th></tr>'
      + list.map((o) => '<tr data-order="' + o.id + '"><td>' + o.id + "</td><td>" + esc(o.contact_name || "") + "</td><td>" + esc((o.description || "").slice(0, 80)) + "</td><td>" + (o.price != null ? money(o.price) : "—") + "</td><td>" + statusBadge(st[o.status], o.status_label) + "</td><td>"
        + (o.image_url ? '<img src="' + esc(o.image_url) + '" alt="" loading="lazy" style="width:52px;height:52px;object-fit:cover;border-radius:8px" />' : "—") + "</td><td>"
        + (o.status === "pending" || o.status === "ready" ? '<button type="button" class="btn" data-ord="generate">Generiraj</button> ' : "")
        + (o.status === "ready" ? '<select class="ordCh"><option value="auto">Automatski</option><option value="telegram">Telegram</option><option value="premium_api">Premium API</option><option value="local">Lokalni izvoz</option></select> <button type="button" class="btn" data-ord="deliver">Isporuči</button> ' : "")
        + (o.status === "delivered" ? '<button type="button" class="btn" data-ord="paid">Označi plaćeno</button>' : "")
        + (o.error ? '<div class="hint" style="color:var(--bad)">' + esc(o.error) + "</div>" : "") + "</td></tr>").join("") + "</table>";
  }
  async function crmAnalyticsHtml() {
    const a = await get("/api/crm/analytics");
    const rows = (list, key) => (list || []).map((r) => "<tr><td>" + esc(r[key] || "—") + "</td><td>" + r.n + "</td><td>" + money(r.revenue) + "</td></tr>").join("") || '<tr><td colspan="3" class="hint">—</td></tr>';
    const table = (title, head, inner) => '<div><div class="lbl">' + title + '</div><table class="v11-table"><tr><th>' + head + "</th><th>Kupnje</th><th>Prihod</th></tr>" + inner + "</table></div>";
    return '<div class="v11-kpis" style="margin-top:0">' + kpi("Kontakti", a.total_contacts) + kpi("Zainteresirani", a.interested_leads) + kpi("Pretplatnici", a.active_subscribers) + kpi("Kupci", a.buyers, "konverzija " + a.conversion_rate + " %") + kpi("Prihod", money(a.total_revenue)) + kpi("Otvorene narudžbe", a.open_orders) + "</div>"
      + '<div class="v11-two">' + table("Po kanalu", "Kanal", rows(a.by_channel, "channel")) + table("Po vrsti", "Vrsta", rows(a.by_kind, "kind"))
      + table("Javni teaser vs. Premium", "Sadržaj", rows(a.by_content_type, "content_type"))
      + '<div><div class="lbl">Najbolji predlošci</div><table class="v11-table"><tr><th>Predložak</th><th>Korišten</th><th>Prihod</th></tr>' + (a.top_templates || []).map((t) => "<tr><td>" + esc(t.name) + "</td><td>" + (t.uses || 0) + "</td><td>" + money(t.revenue) + "</td></tr>").join("") + "</table></div></div>";
  }
  function crmSourcesHtml() {
    return '<div class="hint">Sve poruke idu u isti inbox: Instagram DM (webhook), Instagram i Facebook komentari (Meta sinkronizacija), Telegram (long polling), Premium platforma i vlastiti sustavi preko webhooka.</div>'
      + '<div class="v11-pre">POST http://127.0.0.1:7860/api/crm/webhook\nHeader: X-Studio-Secret: &lt;CRM_WEBHOOK_SECRET&gt;\n{"platform":"premium","profile_id":1,"user_id":"fan123","name":"Ana","text":"Bok!"}</div>'
      + '<div class="actions"><button type="button" class="btn" id="crmSyncMeta">Sinkroniziraj Meta komentare</button></div><div class="hint" id="crmSyncOut"></div>';
  }
  document.addEventListener("click", async (e) => {
    const t = e.target.closest && e.target.closest("[data-crm]");
    if (t) { V.crmTab = t.dataset.crm; renderCrm(); return; }
    const row = e.target.closest && e.target.closest("tr[data-contact]");
    if (row) { V.contactSel = Number(row.dataset.contact); renderCrm(); return; }
    const ob = e.target.closest && e.target.closest("[data-ord]");
    if (ob) {
      const tr = ob.closest("tr");
      const body = ob.dataset.ord === "deliver" ? { channel: tr.querySelector(".ordCh").value } : {};
      try { const d = await post("/api/crm/orders/" + tr.dataset.order + "/" + ob.dataset.ord, body); toast("Narudžba: " + d.order.status_label); if (ob.dataset.ord === "generate") refreshQueue(); renderCrm(); } catch (err) { toast(err.message, true); }
      return;
    }
    if (e.target.id === "crmSyncMeta") {
      try { const d = await post("/api/crm/sync-meta", {}); $("crmSyncOut").textContent = "Uvezeno novih: " + (d.new || 0) + ((d.errors || []).length ? " · " + d.errors.join("; ") : ""); if (C()) C().refreshInbox(); } catch (err) { $("crmSyncOut").textContent = err.message; }
    }
  });

  /* ---------- POSTAVKE ---------- */
  async function renderHwSettings() {
    const el = $("v11Hw");
    if (!el) return;
    const h = await loadHw(true);
    if (!h) { el.innerHTML = '<div class="err">Ne mogu pročitati hardver.</div>'; return; }
    const s = h.settings, p = h.profile || {}, rec = h.recommended || {}, L = h.launch || {};
    const opt = (list, cur, labels) => list.map((v) => '<option value="' + v + '"' + (cur === v ? " selected" : "") + ">" + esc((labels || {})[v] || v) + "</option>").join("");
    const launchTxt = L.error ? L.error : ("backend: " + (L.backend || "") + "\nzastavice: " + (((L.extra_flags || []).concat(L.low_vram ? ["--lowvram"] : [])).join(" ") || "—")
      + "\nokruženje: " + Object.keys(L.env_keys || {}).map((k) => k + "=" + L.env_keys[k]).join(" "));
    el.innerHTML = '<div class="v11-kpi" style="margin-bottom:12px"><div class="k">Detektirano</div><div class="v" style="font-size:18px">' + esc(p.name || "nepoznat GPU") + '</div><div class="s">'
      + esc([p.vram_gb ? p.vram_gb + " GB VRAM" : "", p.gfx || "", p.source ? "izvor: " + p.source : ""].filter(Boolean).join(" · ")) + (p.is_rx6600 ? ' <span class="v11-badge gold">RX 6600</span>' : "") + "</div>"
      + (rec.why ? '<div class="hint">Preporuka: ' + esc(rec.why) + "</div>" : "") + "</div>"
      + '<div class="v11-grid2">'
      + '<label>Backend <select id="hwBackend">' + opt(h.options.backends, s.hw_backend, { auto: "Automatski", zluda: "ZLUDA (Windows, AMD)", rocm: "ROCm (Linux, AMD)", directml: "DirectML", cuda: "CUDA (NVIDIA)", cpu: "CPU" }) + "</select></label>"
      + '<label>VRAM način <select id="hwVram">' + opt(h.options.vram_modes, s.hw_vram_mode, { auto: "Automatski", lowvram: "--lowvram", medvram: "Srednje (bez zastavice)", normalvram: "--normalvram" }) + "</select></label>"
      + '<label>VAE <select id="hwVae">' + opt(h.options.vae_modes, s.hw_vae_mode, { standard: "Standardni", tiled: "Tiled", cpu: "CPU (--cpu-vae)" }) + "</select></label>"
      + '<label>Tile veličina <input type="number" id="hwTile" min="256" max="1024" step="64" value="' + esc(s.hw_vae_tile) + '" /></label>'
      + '<label>Rezerva VRAM-a (GB) <input type="number" id="hwReserve" min="0" max="4" step="0.1" value="' + esc(s.hw_reserve_vram) + '" /></label>'
      + '<label>ROCm HSA_OVERRIDE_GFX_VERSION <input type="text" id="hwGfx" value="' + esc(s.hw_rocm_gfx) + '" /></label>'
      + "</div>"
      + '<label class="lbl" style="margin-top:8px"><input type="checkbox" id="hwSafe"' + (s.hw_safe_mode === "1" ? " checked" : "") + " /> 8 GB siguran mod (niža bazna rezolucija pa upscale)</label>"
      + '<label>Dodatne varijable okruženja (KEY=VALUE po retku) <textarea id="hwEnv" style="min-height:50px">' + esc(s.hw_env_overrides) + "</textarea></label>"
      + '<label>Dodatni ComfyUI argumenti <input type="text" id="hwArgs" value="' + esc(s.hw_extra_args) + '" placeholder="npr. --use-pytorch-cross-attention" /></label>'
      + '<div class="hint">TORCH_BACKENDS_CUDNN_ENABLED=0 uvijek ostaje postavljen za ZLUDA, da ComfyUI ne zapne na „Compilation is in progress”.</div>'
      + '<div class="lbl" style="margin-top:8px">Pokretanje ComfyUI-ja</div><div class="v11-pre">' + esc(launchTxt) + "</div>"
      + '<div class="actions"><button type="button" class="btn" id="hwSave">Spremi</button><button type="button" class="btn primary" id="hwRec">Primijeni preporuku za RX 6600</button>'
      + '<button type="button" class="btn" id="hwRecRestart">Primijeni i restartaj ComfyUI</button><button type="button" class="btn" id="hwRestart">Restartaj ComfyUI</button><button type="button" class="btn" id="hwDetect">Ponovno detektiraj</button></div>'
      + '<div class="hint" id="hwRestartOut">' + esc(h.restart && h.restart.message ? h.restart.message : "") + "</div>";
    const payload = () => ({ hw_backend: $("hwBackend").value, hw_vram_mode: $("hwVram").value, hw_vae_mode: $("hwVae").value, hw_vae_tile: $("hwTile").value, hw_reserve_vram: $("hwReserve").value,
      hw_rocm_gfx: $("hwGfx").value, hw_safe_mode: $("hwSafe").checked ? "1" : "0", hw_env_overrides: $("hwEnv").value, hw_extra_args: $("hwArgs").value });
    const wrap = (fn) => async () => { try { await fn(); } catch (e) { toast(e.message, true); } };
    const reload = async () => { const c = C(); if (c) await c.loadState(); renderHwSettings(); };
    $("hwSave").onclick = wrap(async () => { await post("/api/hardware", payload()); await reload(); toast("Spremljeno. Vrijedi pri sljedećem pokretanju ComfyUI-ja."); });
    $("hwRec").onclick = wrap(async () => { await post("/api/hardware/recommend", {}); await reload(); toast("Primijenjena preporuka za RX 6600."); });
    $("hwRecRestart").onclick = wrap(async () => { await post("/api/hardware/recommend", { restart: true }); await reload(); pollRestart(); });
    $("hwRestart").onclick = wrap(async () => { await post("/api/hardware/restart", {}); pollRestart(); });
    $("hwDetect").onclick = wrap(async () => { await post("/api/hardware/detect", {}); renderHwSettings(); });
  }
  function pollRestart() {
    let n = 0;
    const tick = async () => {
      try {
        const r = (await get("/api/hardware/restart")).restart || {};
        if ($("hwRestartOut")) $("hwRestartOut").textContent = r.message || r.status || "";
        if (r.status === "running" && n++ < 150) setTimeout(tick, 2000);
        else if (r.status === "done") toast("ComfyUI je ponovno pokrenut.");
        else if (r.status === "error") toast(r.message || "Restart nije uspio.", true);
      } catch (e) { /* */ }
    };
    tick();
  }
  async function renderEnv() {
    const el = $("v11Env");
    if (!el) return;
    try { V.env = await get("/api/env"); } catch (e) { el.innerHTML = '<div class="err">' + esc(e.message) + "</div>"; return; }
    el.innerHTML = V.env.items.map((it) => '<div class="v11-env-row"><div><code>' + esc(it.key) + '</code><div class="hint">' + esc(it.label) + "</div></div>"
      + '<input type="' + (it.secret ? "password" : "text") + '" data-env="' + esc(it.key) + '" placeholder="' + esc(it.set ? (it.masked || "postavljeno") : "nije postavljeno") + '" autocomplete="off" />'
      + (it.set ? '<button type="button" class="btn" data-envclear="' + esc(it.key) + '" title="Obriši vrijednost">Obriši</button>' : "<span></span>") + "</div>").join("")
      + '<div class="actions"><button type="button" class="btn primary" id="envSave">Spremi ključeve</button></div>';
    $("envSave").onclick = async () => {
      const values = {};
      el.querySelectorAll("[data-env]").forEach((i) => { if (i.value.trim()) values[i.dataset.env] = i.value.trim(); });
      if (!Object.keys(values).length) { toast("Nema izmjena."); return; }
      try { const d = await post("/api/env", { values: values }); toast("Spremljeno u data/.env: " + d.changed.join(", ")); renderEnv(); if (C()) C().loadState(); } catch (e) { toast(e.message, true); }
    };
    el.querySelectorAll("[data-envclear]").forEach((b) => { b.onclick = async () => {
      if (!window.confirm("Obrisati " + b.dataset.envclear + " iz data/.env?")) return;
      try { await post("/api/env", { clear: [b.dataset.envclear] }); renderEnv(); } catch (e) { toast(e.message, true); }
    }; });
  }
  async function renderLlm() {
    const el = $("v11Llm");
    if (!el) return;
    try { V.llm = await get("/api/crm/llm"); } catch (e) { el.innerHTML = '<div class="err">' + esc(e.message) + "</div>"; return; }
    const l = V.llm;
    const names = { auto: "Automatski (Ollama → LM Studio → xAI → pravila)", ollama: "Ollama (lokalno)", openai_compat: "LM Studio / OpenAI-kompatibilno", xai: "xAI Grok", rules: "Samo pravila (bez AI-ja)" };
    el.innerHTML = '<label>Pozadina <select id="llmBackend">' + l.options.map((o) => '<option value="' + o + '"' + (l.setting === o ? " selected" : "") + ">" + esc(names[o] || o) + "</option>").join("") + "</select></label>"
      + '<div class="v11-grid2"><label>Ollama model <input type="text" id="llmOllama" value="' + esc(l.ollama_model) + '" placeholder="llama3.1:8b" /></label><label>LM Studio / kompatibilni model <input type="text" id="llmCompat" value="' + esc(l.compat_model) + '" /></label></div>'
      + '<label class="lbl"><input type="checkbox" id="llmAnalysis"' + (l.analysis ? " checked" : "") + " /> AI dodatno procjenjuje interes fana (sporije)</label>"
      + '<div class="hint">Trenutno aktivno: <strong>' + esc(l.active) + "</strong> · Ollama: " + esc(l.ollama_url) + (l.compat_url ? " · LM Studio: " + esc(l.compat_url) : "") + " · xAI ključ: " + (l.xai ? "da" : "ne") + ". URL-ove i ključeve upiši u API ključevi.</div>"
      + '<div class="actions"><button type="button" class="btn primary" id="llmSave">Spremi</button></div>';
    $("llmSave").onclick = async () => {
      try { V.llm = await post("/api/crm/llm", { llm_backend: $("llmBackend").value, ollama_model: $("llmOllama").value, openai_compat_model: $("llmCompat").value, crm_llm_analysis: $("llmAnalysis").checked }); toast("AI chat: " + V.llm.active); renderLlm(); } catch (e) { toast(e.message, true); }
    };
  }

  /* ---------- usmjeravanje kartica ---------- */
  let crmTimer = null;
  function onTab(name) {
    clearInterval(V.ovTimer);
    clearInterval(threadPoll);
    clearInterval(crmTimer);
    if (name === "pregled") { renderOverview(); V.ovTimer = setInterval(renderOverview, 10000); }
    if (name === "slike") { syncStackFromPersona(false); refreshQueue(); }
    if (name === "influenceri") {
      renderPersona();
      try { if (window.StudioLoraTrainer) window.StudioLoraTrainer.render(); } catch (e) { console.warn(e); }
    }
    if (name === "kalendar") renderCalendar();
    if (name === "poruke") {
      renderSendBar(true);
      renderCrm();
      threadPoll = setInterval(() => renderThreadInfo(false), 1500);
      crmTimer = setInterval(() => { if (V.crmTab === "orders") renderCrm(); }, 15000);
    }
    if (name === "postavke") { renderHwSettings(); renderEnv(); renderLlm(); }
  }

  function boot() {
    bindOverview();
    bindCalendar();
    const lbG = $("lbGood"), lbB = $("lbBad");
    if (lbG) lbG.addEventListener("click", (e) => { e.stopPropagation(); rate(lbG.classList.contains("on") ? 0 : 1); });
    if (lbB) lbB.addEventListener("click", (e) => { e.stopPropagation(); rate(lbB.classList.contains("on") ? 0 : -1); });
    if ($("v11GalMore")) $("v11GalMore").addEventListener("click", () => loadGallery(false));
    if ($("v11GalFilter")) $("v11GalFilter").addEventListener("change", () => loadGallery(true));
    if ($("v11GalChips")) $("v11GalChips").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-f]");
      if (!b) return;
      $("v11GalChips").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      if ($("v11GalFilter")) { $("v11GalFilter").value = b.dataset.f; $("v11GalFilter").dispatchEvent(new Event("change")); }
    });
    if ($("v11GalFilter")) $("v11GalFilter").addEventListener("change", () => {
      const v = $("v11GalFilter").value;
      if ($("v11GalChips")) $("v11GalChips").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x.dataset.f === v));
    });
    if ($("v11SaveLegacyHw")) $("v11SaveLegacyHw").addEventListener("click", () => { const c = C(); if (c) c.saveSettings(); setTimeout(() => loadHw(true), 800); });
    const ss = $("saveSettings");
    if (ss) ss.addEventListener("click", () => setTimeout(() => renderSendBar(true), 700));
    document.addEventListener("click", (e) => {
      if (e.target.closest && e.target.closest("#profileList")) setTimeout(renderPersona, 200);
    });
    const pf = $("profileForm");
    if (pf) pf.addEventListener("submit", () => setTimeout(renderPersona, 900));
    loadHw(false);
    renderGen();
    refreshQueue();
    loadGallery(true);
    const c = C();
    if (c && c.currentTab() !== "slike") onTab(c.currentTab());
  }

  window.StudioV11 = { genExtras: genExtras, onTab: onTab, refreshQueue: refreshQueue, loadGallery: loadGallery, ratingOf: ratingOf, renderStackUi: renderStackUi, getStack: function () { return (V.stack || []).slice(); }, onArch: fillVaeOptions, version: "1.3.7" };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();

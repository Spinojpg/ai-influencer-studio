/* AI Influencer Studio – LoRA trener (Osobe). 3 koraka: osoba -> 15–40 slika -> jedan gumb.
   Ovisi o window.StudioCore (index.html). Bez vanjskih biblioteka. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const C = () => window.StudioCore || null;
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const toast = (m, bad) => { const c = C(); if (c) c.toast(m, bad); };

  async function api(method, url, body) {
    const opt = { method: method, cache: "no-store", headers: {} };
    if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    const r = await fetch(url, opt);
    let d = {};
    try { d = await r.json(); } catch (e) { d = {}; }
    if (!r.ok || d.ok === false) { const err = new Error(d.error || ("HTTP " + r.status)); err.status = r.status; throw err; }
    return d;
  }
  const get = (u) => api("GET", u);
  const post = (u, b) => api("POST", u, b || {});

  const L = { built: false, pid: null, status: null, ds: null, preset: "balanced", job: null, pollT: null, instT: null,
    uploading: false, loras: [], personas: [], lastJobStatus: {}, planReq: 0 };

  function fmtDur(sec) {
    sec = Math.max(0, Math.round(Number(sec) || 0));
    if (sec < 90) return sec + " s";
    const m = Math.round(sec / 60);
    if (m < 60) return m + " min";
    return Math.floor(m / 60) + " h " + (m % 60) + " min";
  }
  function tempLabel(t, status) {
    if (t == null || status === "unavailable") return "Senzor temperature nedostupan";
    return "GPU " + Math.round(t) + "°C";
  }

  /* ---------- kostur ---------- */
  function build() {
    const root = $("loraTrainer");
    if (!root || L.built) return !!root;
    L.built = true;
    root.innerHTML = ''
      + '<div class="lt-head"><div class="lt-head-l"><span class="lt-head-ico" aria-hidden="true">✦</span><div><span class="eyebrow">Osobe · LoRA</span><h2 class="sec" style="margin:0">LoRA trener</h2>'
      + '<div class="hint">Nauči Studio lice svoje osobe: ocijeni slike „Dobra” ili dodaj 15–40 slika, klikni jedan gumb, a gotova LoRA se sama doda u profil osobe.</div></div></div>'
      + '<div class="lt-head-r"><div id="ltTemp" class="lt-temp"></div><div id="ltGpu" class="gpu-live lt-gpu" hidden aria-live="polite"></div></div></div>'
      + '<div id="ltSetup" class="lt-banner" hidden></div>'
      + '<div class="lt-steps">'
      + '<div class="lt-step"><div class="lt-num">1</div><div class="lt-body"><h3>Odaberi osobu</h3>'
      + '<select id="ltPersona" aria-label="Osoba za treniranje"></select>'
      + '<div class="lt-ready-row"><span id="ltReady" class="lt-ready">—</span><span id="ltGood" class="lt-good"></span></div>'
      + '<div id="ltPersonaInfo" class="lt-info"></div><div id="ltVersions" class="lt-versions"></div>'
      + '<label class="lt-check lt-sync"><input type="checkbox" id="ltAutoSync" checked /> Slike ocijenjene „Dobra” automatski idu u dataset</label></div></div>'
      + '<div class="lt-step"><div class="lt-num">2</div><div class="lt-body"><h3>Dodaj 15–40 slika</h3>'
      + '<div id="ltDrop" class="lt-drop" tabindex="0" role="button" aria-label="Povuci slike ovdje">'
      + '<b>Povuci slike ovdje</b><span>ili</span><button type="button" class="btn" id="ltPick">Odaberi slike</button>'
      + '<input type="file" id="ltFile" accept="image/jpeg,image/png,image/webp" multiple hidden /></div>'
      + '<div class="lt-row"><button type="button" class="btn" id="ltImportGood">Uvezi ocijenjene „Dobra”</button><button type="button" class="btn" id="ltImport">Uvezi iz galerije osobe</button>'
      + '<span id="ltCount" class="lt-count"></span><span class="lt-grow"></span>'
      + '<button type="button" class="btn ghost" id="ltClear">Obriši sve slike</button></div>'
      + '<div id="ltUpMsg" class="hint"></div>'
      + '<div id="ltGrid" class="lt-grid"></div>'
      + '<details id="ltCaps" class="lt-details"><summary>Pregled opisa</summary>'
      + '<div class="hint">Studio sam napiše kratak opis za svaku sliku (okidač osobe, „adult woman”, izgled, kadar i svjetlo). Možeš ga promijeniti; prazno polje vraća automatski opis.</div>'
      + '<div id="ltCapList"></div></details></div></div>'
      + '<div class="lt-step"><div class="lt-num">3</div><div class="lt-body"><h3>Pokreni treniranje</h3>'
      + '<div class="lt-presets" id="ltPresets" role="radiogroup" aria-label="Profil treniranja"></div>'
      + '<div id="ltPlan" class="lt-plan"></div>'
      + '<details id="ltAdv" class="lt-details"><summary>Napredno</summary><div class="v11-grid2 lt-adv">'
      + '<label>Bazni model<select id="ltBase"></select></label>'
      + '<label>Rezolucija<select id="ltRes"><option value="">Automatski (SDXL 768 / SD 1.5 512)</option><option value="512">512</option><option value="768">768</option><option value="1024">1024 (samo SDXL, na rubu 8 GB)</option></select></label>'
      + '<label>Rank (network dim)<select id="ltRank"><option value="8">8</option><option value="16" selected>16 (preporučeno)</option><option value="32">32</option></select></label>'
      + '<label>Epohe<input type="number" id="ltEpochs" min="1" max="30" placeholder="prema profilu" /></label>'
      + '<label>Ukupno koraka (otprilike)<input type="number" id="ltSteps" min="100" max="6000" step="50" placeholder="prema profilu" /></label>'
      + '<label>Auto-stop na temperaturi (°C)<input type="number" id="ltTempStop" min="60" max="120" step="1" /></label>'
      + '<label class="lt-check"><input type="checkbox" id="ltAutostop" checked /> Automatski zaustavi treniranje kad je GPU prevruć</label>'
      + '<label class="lt-check"><input type="checkbox" id="ltStallAutostop" /> Automatski zaustavi ako se koraci ne pomaknu 20 min</label>'
      + '</div><div class="hint">Sigurne postavke za RX 6600 su uvijek uključene: batch 1, fp16, gradient checkpointing, cache latents (na disk), SDPA bez xformersa, Adafactor. LoRA se sprema nakon svake epohe.</div></details>'
      + '<label class="lt-check lt-resume" id="ltResumeWrap" hidden><input type="checkbox" id="ltResume" checked /> <span id="ltResumeLabel">Nastavi od epohe 0</span></label>'
      + '<div class="actions"><button type="button" class="btn primary lt-go" id="ltStart">Pokreni treniranje</button></div>'
      + '</div></div></div>'
      + '<div id="ltJob" class="lt-job" hidden></div>';
    bind();
    return true;
  }

  function bind() {
    $("ltPersona").addEventListener("change", () => selectPersona(Number($("ltPersona").value)));
    $("ltPick").addEventListener("click", (e) => { e.stopPropagation(); $("ltFile").click(); });
    $("ltFile").addEventListener("change", () => { const f = Array.from($("ltFile").files || []); $("ltFile").value = ""; upload(f); });
    const drop = $("ltDrop");
    drop.addEventListener("click", (e) => { if (e.target === drop || e.target.tagName === "B" || e.target.tagName === "SPAN") $("ltFile").click(); });
    drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("ltFile").click(); } });
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => { const f = Array.from((e.dataTransfer && e.dataTransfer.files) || []); upload(f); });
    $("ltImport").addEventListener("click", importFromPersona);
    $("ltImportGood").addEventListener("click", importGood);
    $("ltAutoSync").addEventListener("change", async () => {
      try { await post("/api/lora-trainer/settings", { auto_sync_good: $("ltAutoSync").checked }); toast($("ltAutoSync").checked ? "„Dobra” slike će se same dodavati u dataset." : "Automatsko dodavanje „Dobra” slika je isključeno."); }
      catch (err) { toast(err.message, true); }
    });
    $("ltClear").addEventListener("click", clearDataset);
    $("ltGrid").addEventListener("click", (e) => {
      const b = e.target.closest("[data-del]");
      if (b) delImage(Number(b.dataset.del));
    });
    $("ltCapList").addEventListener("change", (e) => {
      const inp = e.target.closest("[data-cap]");
      if (inp) saveCaption(Number(inp.dataset.cap), inp.value);
    });
    $("ltPresets").addEventListener("click", (e) => {
      const b = e.target.closest("[data-preset]");
      if (!b) return;
      L.preset = b.dataset.preset;
      renderPresets();
      renderPlan();
    });
    ["ltBase", "ltRes", "ltRank", "ltEpochs", "ltSteps", "ltTempStop", "ltAutostop", "ltStallAutostop", "ltResume"].forEach((id) => { if ($(id)) $(id).addEventListener("change", renderPlan); });
    $("ltStart").addEventListener("click", startTraining);
    $("ltJob").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.act === "stop") stopJob(Number(b.dataset.id));
      if (b.dataset.act === "gen") generateWith(Number(b.dataset.pid));
      if (b.dataset.act === "retry") { const s = $("ltStart"); if (s) s.scrollIntoView({ behavior: "smooth", block: "center" }); }
      if (b.dataset.act === "resume") resumeFromLastEpoch();
    });
    $("ltVersions").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-activate]");
      if (!b) return;
      try {
        await post("/api/lora-trainer/activate", { profile_id: L.pid, lora_id: Number(b.dataset.activate) });
        const c = C(); if (c) { await c.loadState(); if (c.refreshLoras) c.refreshLoras(); }
        toast("Ta LoRA verzija je sada aktivna za osobu.");
        await loadPersonas(); await loadLoras();
      } catch (err) { toast(err.message, true); }
    });
  }

  /* ---------- podaci ---------- */
  async function loadStatus(refresh) {
    try { L.status = await get("/api/lora-trainer/status" + (refresh ? "?refresh=1" : "")); } catch (e) { L.status = null; }
    renderSetup();
    renderTempHead();
    const st = L.status;
    if (st && $("ltBase")) {
      const cur = $("ltBase").value;
      $("ltBase").innerHTML = '<option value="">Automatski (model osobe)</option>' + (st.checkpoints || []).map((c) => '<option value="' + esc(c.name) + '">' + esc(c.name) + " · " + (c.arch === "sdxl" ? "SDXL" : "SD 1.5") + "</option>").join("");
      $("ltBase").value = cur;
      if (!$("ltTempStop").value && st.temp_settings) $("ltTempStop").value = Math.round(st.temp_settings.stop_c);
      if (st.temp_settings) $("ltAutostop").checked = $("ltAutostop").dataset.touched ? $("ltAutostop").checked : !!st.temp_settings.autostop;
      if (st.temp_settings && $("ltStallAutostop") && !$("ltStallAutostop").dataset.touched) {
        $("ltStallAutostop").checked = !!st.temp_settings.stall_autostop;
      }
    }
  }
  async function loadPersonas() {
    try { const d = await get("/api/lora-trainer/personas"); L.personas = d.personas || []; } catch (e) { L.personas = []; }
    const sel = $("ltPersona");
    if (!sel) return;
    const c = C();
    const pref = c ? (c.editingId() || (c.state() || {}).active_profile_id) : null;
    const prefN = pref != null && pref !== "" ? Number(pref) : null;
    if (prefN && L.personas.some((p) => Number(p.id) === prefN)) {
      L.pid = prefN;
    } else if (!L.pid || !L.personas.some((p) => Number(p.id) === Number(L.pid))) {
      L.pid = (L.personas[0] || {}).id || null;
    }
    sel.innerHTML = L.personas.map((p) => '<option value="' + p.id + '"' + (p.id === L.pid ? " selected" : "") + ">" + esc(p.name) + (p.active_lora ? " · ima LoRA-u" : "") + "</option>").join("");
    renderPersonaInfo();
  }
  async function loadDataset() {
    if (!L.pid) { L.ds = null; renderDataset(); return; }
    try { L.ds = await get("/api/lora-trainer/dataset/" + L.pid); } catch (e) { L.ds = null; toast(e.message, true); }
    renderDataset();
  }
  async function loadLoras() {
    if (!L.pid) { L.loras = []; renderVersions(); return; }
    try { L.loras = (await get("/api/lora-trainer/loras?profile_id=" + L.pid)).loras || []; } catch (e) { L.loras = []; }
    renderVersions();
  }

  async function selectPersona(pid) {
    L.pid = pid || null;
    renderPersonaInfo();
    await Promise.all([loadDataset(), loadLoras()]);
    renderPlan();
    refreshJob();
  }

  /* ---------- prikaz ---------- */
  function vramLabel(live, job) {
    const used = (job && (job.gpu_vram_reserved_mb != null || job.gpu_vram_used_mb != null))
      ? (job.gpu_vram_reserved_mb != null ? job.gpu_vram_reserved_mb : job.gpu_vram_used_mb)
      : (live && live.vram_used_mb);
    const total = (job && job.gpu_vram_total_mb != null) ? job.gpu_vram_total_mb : (live && live.vram_total_mb);
    if (used == null && total == null) return "";
    const u = used != null ? Math.round(used) : "?";
    const tot = total != null ? Math.round(total) : "?";
    return "VRAM " + u + " / " + tot + " MB";
  }
  function renderTempHead() {
    const el = $("ltTemp");
    if (!el) return;
    const g = (L.status && L.status.gpu_temp) || {};
    const live = (L.status && L.status.gpu_live) || {};
    const st = g.available ? g.status : "unavailable";
    el.className = "lt-temp " + st;
    let txt = tempLabel(g.temp_c, st);
    const vr = vramLabel(live, L.job);
    if (vr) txt += " · " + vr;
    else if (live.message) txt += " · " + live.message;
    el.innerHTML = '<span class="lt-dot"></span>' + esc(txt);
    const gpu = $("ltGpu");
    if (gpu) {
      if (vr) { gpu.hidden = false; gpu.textContent = vr; }
      else { gpu.hidden = true; gpu.textContent = ""; }
    }
  }
  function renderSetup() {
    const el = $("ltSetup");
    if (!el) return;
    const st = L.status;
    if (!st) { el.hidden = false; el.innerHTML = "Ne mogu dohvatiti stanje trenera."; return; }
    const inst = st.install || {};
    if (st.ready && !inst.running) {
      const t = st.torch || {};
      if (t.ok === false && !st.override_cmd) {
        el.hidden = false;
        el.className = "lt-banner warn";
        el.innerHTML = "PyTorch u treneru se ne pokreće: " + esc(t.error || "") + ' <button type="button" class="btn" id="ltReinstall">Ponovno pripremi okruženje</button>';
        $("ltReinstall").onclick = installBackend;
      } else el.hidden = true;
      return;
    }
    el.hidden = false;
    el.className = "lt-banner";
    if (inst.running) {
      el.innerHTML = "<b>Pripremam okruženje za treniranje…</b> " + esc(inst.step || "")
        + '<div class="bar"><i style="width:' + Math.round((inst.progress || 0) * 100) + '%"></i></div>'
        + '<details class="lt-details"><summary>Prikaži log</summary><pre class="v11-pre lt-log">' + esc((inst.log || []).slice(-30).join("\n")) + "</pre></details>";
      if (!L.instT) L.instT = setInterval(pollInstall, 2000);
      return;
    }
    el.innerHTML = "<b>Okruženje za treniranje još nije pripremljeno.</b> Jednom treba preuzeti kohya sd-scripts i nekoliko paketa (oko 1–2 GB). ComfyUI paketi ostaju netaknuti, a PyTorch (ZLUDA) se koristi isti."
      + (inst.error ? '<div class="err">' + esc(inst.error) + "</div>" : "")
      + '<div class="actions"><button type="button" class="btn primary" id="ltInstall">Pripremi okruženje za treniranje</button></div>'
      + (inst.log && inst.log.length ? '<details class="lt-details"><summary>Prikaži log</summary><pre class="v11-pre lt-log">' + esc(inst.log.slice(-30).join("\n")) + "</pre></details>" : "");
    $("ltInstall").onclick = installBackend;
  }
  async function installBackend() {
    try { await post("/api/lora-trainer/install-backend", {}); toast("Pripremam okruženje za treniranje. To može potrajati nekoliko minuta."); } catch (e) { toast(e.message, true); }
    await loadStatus();
  }
  async function pollInstall() {
    let d = null;
    try { d = await get("/api/lora-trainer/install-backend"); } catch (e) { return; }
    if (!d.install || !d.install.running) {
      clearInterval(L.instT); L.instT = null;
      await loadStatus(true);
      if (d.ready) toast("Okruženje za treniranje je spremno.");
      else if (d.install && d.install.error) toast(d.install.error, true);
      return;
    }
    if (L.status) { L.status.install = d.install; renderSetup(); }
  }

  function renderPersonaInfo() {
    const el = $("ltPersonaInfo");
    if (!el) return;
    const p = L.personas.find((x) => x.id === L.pid);
    if (!p) { el.innerHTML = '<span class="hint">Nema osoba. Napravi profil lijevo.</span>'; return; }
    el.innerHTML = p.active_lora
      ? 'Trenutna LoRA: <b>' + esc(p.active_lora) + "</b>" + (p.trigger ? ' · okidač <code>' + esc(p.trigger) + "</code>" : "") + (p.active_lora_in_use ? ' <span class="v11-badge ok">u upotrebi</span>' : ' <span class="v11-badge gold">nije postavljena kao LoRA profila</span>')
      : "Ova osoba još nema svoju LoRA-u." + (p.trigger ? ' Okidač: <code>' + esc(p.trigger) + "</code>" : "");
  }
  function renderVersions() {
    const el = $("ltVersions");
    if (!el) return;
    if (!L.loras.length) { el.innerHTML = ""; return; }
    el.innerHTML = '<div class="lt-sub">Istrenirane verzije</div>' + L.loras.map((l) => '<div class="lt-ver">'
      + "<span>" + esc(l.lora_filename) + (l.exists ? "" : ' <span class="v11-badge bad">datoteka nedostaje</span>') + "</span>"
      + (l.is_active ? '<span class="v11-badge ok">aktivna</span>' : '<button type="button" class="btn" data-activate="' + l.id + '">Koristi ovu</button>') + "</div>").join("");
  }
  function renderDataset() {
    const ds = L.ds;
    const grid = $("ltGrid"), cnt = $("ltCount"), caps = $("ltCapList");
    if (!grid) return;
    if (!ds) { grid.innerHTML = ""; cnt.textContent = ""; caps.innerHTML = ""; renderStart(); return; }
    const g = ds.guidance || {};
    cnt.className = "lt-count " + (g.color || "");
    cnt.textContent = ds.count + " " + (ds.count === 1 ? "slika" : (ds.count % 10 >= 2 && ds.count % 10 <= 4 && (ds.count % 100 < 12 || ds.count % 100 > 14) ? "slike" : "slika")) + " · " + (g.message || "");
    renderReady(ds);
    grid.innerHTML = (ds.items || []).map((it) => '<figure class="lt-shot"><img loading="lazy" src="' + esc(it.thumb_url) + '" alt="" title="' + esc(it.original_name || "") + '" />'
      + '<button type="button" class="lt-del" data-del="' + it.id + '" title="Ukloni iz dataseta" aria-label="Ukloni">×</button></figure>').join("")
      || '<div class="hint">Još nema slika. Najbolje je 15–40 raznolikih slika iste osobe: različiti kadrovi, svjetlo i odjeća, lice dobro vidljivo.</div>';
    caps.innerHTML = (ds.items || []).map((it) => '<div class="lt-cap"><img loading="lazy" src="' + esc(it.thumb_url) + '" alt="" />'
      + '<input type="text" data-cap="' + it.id + '" maxlength="600" value="' + esc(it.caption_custom || "") + '" placeholder="' + esc(it.caption_auto || "") + '" /></div>').join("");
    renderStart();
  }
  function renderReady(ds) {
    const r = $("ltReady"), g = $("ltGood"), sync = $("ltAutoSync"), ib = $("ltImportGood");
    if (!r) return;
    const n = ds ? Number(ds.count || 0) : 0;
    const st = !ds ? ["", "—"] : n >= 15 ? ["ok", n >= 40 ? "Spremno · " + n + " slika (max 40 se koristi)" : "Spremno za treniranje"] : n >= 8 ? ["warn", "Još " + (15 - n) + " do preporučenih 15"] : ["bad", "Premalo slika (" + n + ")"];
    r.className = "lt-ready " + st[0];
    r.textContent = st[1];
    if (!ds) { if (g) g.textContent = ""; return; }
    const good = Number(ds.good_in_dataset || 0), man = Number(ds.manual_in_dataset != null ? ds.manual_in_dataset : Math.max(0, n - good));
    const miss = Number(ds.good_missing || 0);
    if (g) g.innerHTML = '<span class="lt-chip good">Dobra ' + good + "</span>" + '<span class="lt-chip">ručno ' + man + "</span>"
      + (Number(ds.good_rated || 0) ? '<span class="lt-chip muted">ocijenjeno Dobra ' + Number(ds.good_rated) + "</span>" : "")
      + (Number(ds.bad_rated || 0) ? '<span class="lt-chip bad">Loša ' + Number(ds.bad_rated) + "</span>" : "");
    if (sync && ds.auto_sync_good != null) sync.checked = !!ds.auto_sync_good;
    if (ib) { ib.textContent = miss ? "Uvezi ocijenjene „Dobra” (" + miss + ")" : "Uvezi ocijenjene „Dobra”"; ib.classList.toggle("primary", miss > 0); }
  }
  const PRESET_SHORT = { fast: "Brzo", balanced: "Preporučeno", detailed: "Detaljno" };
  function renderPresets() {
    const el = $("ltPresets");
    if (!el) return;
    const list = (L.status && L.status.presets) || [
      { id: "fast", label: "Brzi test", hint: "" }, { id: "balanced", label: "Preporučeno za RX 6600", hint: "" }, { id: "detailed", label: "Detaljnije", hint: "" }];
    el.innerHTML = list.map((p) => '<button type="button" role="radio" aria-checked="' + (p.id === L.preset) + '" class="lt-preset' + (p.id === L.preset ? " on" : "") + '" data-preset="' + p.id + '">'
      + '<b title="' + esc(p.label) + '">' + esc(PRESET_SHORT[p.id] || p.label) + "</b><span>" + esc(p.hint || p.label || "") + "</span></button>").join("");
  }
  function advanced() {
    const adv = {};
    const v = (id) => ($(id) ? String($(id).value || "").trim() : "");
    if (v("ltBase")) adv.base_model = v("ltBase");
    if (v("ltRes")) adv.resolution = Number(v("ltRes"));
    if (v("ltRank")) adv.rank = Number(v("ltRank"));
    if (v("ltEpochs")) adv.epochs = Number(v("ltEpochs"));
    if (v("ltSteps")) adv.steps = Number(v("ltSteps"));
    if (v("ltTempStop")) adv.temp_stop = Number(v("ltTempStop"));
    if ($("ltAutostop")) { adv.autostop = $("ltAutostop").checked; $("ltAutostop").dataset.touched = "1"; }
    if ($("ltStallAutostop")) { adv.stall_autostop = $("ltStallAutostop").checked; $("ltStallAutostop").dataset.touched = "1"; }
    if ($("ltResume") && $("ltResumeWrap") && !$("ltResumeWrap").hidden) adv.resume = $("ltResume").checked;
    return adv;
  }
  async function renderPlan() {
    const el = $("ltPlan");
    if (!el) return;
    if (!L.pid) { el.innerHTML = ""; const w = $("ltResumeWrap"); if (w) w.hidden = true; renderStart(); return; }
    const req = ++L.planReq;
    try {
      const d = await post("/api/lora-trainer/plan", { profile_id: L.pid, preset: L.preset, advanced: advanced() });
      if (req !== L.planReq) return;
      const p = d.plan;
      L.plan = p; L.planErr = "";
      el.innerHTML = (p.arch === "sdxl" ? "SDXL" : "SD 1.5") + " · " + esc(p.base_model) + " · " + p.resolution + " px · "
        + (p.image_count ? (p.total_steps + " koraka (" + p.epochs + " epoha) · otprilike <b>" + fmtDur(p.eta_seconds) + "</b> na RX 6600") : "dodaj slike za procjenu")
        + (p.warnings || []).map((w) => '<div class="lt-warn">' + esc(w) + "</div>").join("");
      const r = p.resume || {};
      const wrap = $("ltResumeWrap");
      if (wrap) {
        const show = !!r.available;
        if (wrap.hidden && show && $("ltResume")) $("ltResume").checked = true;
        wrap.hidden = !show;
        if (show && $("ltResumeLabel")) $("ltResumeLabel").textContent = "Nastavi od epohe " + r.epoch;
      }
    } catch (e) {
      if (req !== L.planReq) return;
      L.plan = null; L.planErr = e.message;
      el.innerHTML = '<div class="err">' + esc(e.message) + "</div>";
    }
    renderStart();
  }
  function renderStart() {
    const b = $("ltStart");
    if (!b) return;
    const g = (L.ds && L.ds.guidance) || {};
    const busy = L.job && L.job.active;
    const ready = L.status && L.status.ready;
    b.disabled = !L.pid || !g.can_train || !!L.planErr || !!busy || !ready || L.uploading;
    b.title = !ready ? "Prvo pripremi okruženje za treniranje." : (busy ? "Treniranje već traje." : (!g.can_train ? (g.message || "") : ""));
  }

  /* ---------- slike ---------- */
  function readAsDataUrl(file) {
    return new Promise((resolve, reject) => { const fr = new FileReader(); fr.onload = () => resolve(fr.result); fr.onerror = () => reject(new Error("Ne mogu pročitati " + file.name)); fr.readAsDataURL(file); });
  }
  async function shrinkIfHuge(file) {
    if (file.size <= 6 * 1024 * 1024) return readAsDataUrl(file);
    try {
      const url = URL.createObjectURL(file);
      const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
      const k = Math.min(1, 2048 / Math.max(img.naturalWidth, img.naturalHeight));
      const cv = document.createElement("canvas");
      cv.width = Math.round(img.naturalWidth * k); cv.height = Math.round(img.naturalHeight * k);
      cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height);
      URL.revokeObjectURL(url);
      return cv.toDataURL("image/jpeg", 0.92);
    } catch (e) { return readAsDataUrl(file); }
  }
  async function upload(files) {
    files = (files || []).filter((f) => /^image\//.test(f.type) || /\.(jpe?g|png|webp)$/i.test(f.name));
    if (!files.length || !L.pid) return;
    L.uploading = true; renderStart();
    const msg = $("ltUpMsg");
    const skipped = [];
    let added = 0;
    for (let i = 0; i < files.length; i++) {
      msg.textContent = "Učitavam i pripremam " + (i + 1) + "/" + files.length + "…";
      try {
        const data = await shrinkIfHuge(files[i]);
        const d = await post("/api/lora-trainer/dataset/" + L.pid + "/upload", { images: [{ name: files[i].name, data: data }] });
        added += (d.added || []).length;
        (d.skipped || []).forEach((s) => skipped.push(s.reason));
        L.ds = d.dataset; renderDataset();
      } catch (e) { skipped.push(files[i].name + ": " + e.message); }
    }
    L.uploading = false;
    msg.innerHTML = "Dodano: " + added + "." + (skipped.length ? ' <span class="lt-warn-inline">Preskočeno ' + skipped.length + ": " + esc(skipped.slice(0, 4).join(" · ")) + (skipped.length > 4 ? " …" : "") + "</span>" : "");
    await loadPersonas();
    renderPlan();
  }
  async function importGood() {
    if (!L.pid) return;
    const b = $("ltImportGood"); b.disabled = true;
    $("ltUpMsg").textContent = "Uvozim slike ocijenjene „Dobra”…";
    try {
      const d = await post("/api/lora-trainer/dataset/" + L.pid + "/import-good", {});
      L.ds = d.dataset; renderDataset();
      const n = (d.added || []).length;
      $("ltUpMsg").textContent = n ? "Uvezeno „Dobra” slika: " + n + "." : "Nema novih „Dobra” slika — ocijeni slike u Generiranju (gumb Dobra).";
    } catch (e) { $("ltUpMsg").textContent = e.message; }
    b.disabled = false;
    renderPlan();
  }
  async function importFromPersona() {
    if (!L.pid) return;
    const b = $("ltImport"); b.disabled = true;
    $("ltUpMsg").textContent = "Uvozim referentne slike i slike ocijenjene „Dobra”…";
    try {
      const d = await post("/api/lora-trainer/dataset/" + L.pid + "/import", { sources: ["refs", "good"] });
      L.ds = d.dataset; renderDataset();
      $("ltUpMsg").textContent = "Uvezeno: " + (d.added || []).length + (d.skipped && d.skipped.length ? " · preskočeno " + d.skipped.length + " (već u datasetu ili neispravne)" : "") + ".";
    } catch (e) { $("ltUpMsg").textContent = e.message; }
    b.disabled = false;
    renderPlan();
  }
  async function delImage(id) {
    try { L.ds = await api("DELETE", "/api/lora-trainer/dataset/" + L.pid + "/images/" + id); renderDataset(); renderPlan(); } catch (e) { toast(e.message, true); }
  }
  async function clearDataset() {
    if (!L.pid || !L.ds || !L.ds.count) return;
    if (!window.confirm("Obrisati sve slike iz LoRA dataseta ove osobe? (Profil i galerija ostaju.)")) return;
    try { L.ds = await post("/api/lora-trainer/dataset/" + L.pid + "/clear", {}); renderDataset(); renderPlan(); } catch (e) { toast(e.message, true); }
  }
  async function saveCaption(id, text) {
    try { L.ds = await post("/api/lora-trainer/dataset/" + L.pid + "/images/" + id + "/caption", { caption: text }); toast("Opis spremljen."); } catch (e) { toast(e.message, true); }
  }

  /* ---------- treniranje ---------- */
  async function resumeFromLastEpoch() {
    if (!L.pid) return;
    const wrap = $("ltResumeWrap");
    const box = $("ltResume");
    if (wrap) wrap.hidden = false;
    if (box) box.checked = true;
    await renderPlan();
    if ($("ltResumeLabel") && L.job && L.job.resume && L.job.resume.epoch) {
      $("ltResumeLabel").textContent = "Nastavi od epohe " + L.job.resume.epoch;
    }
    const s = $("ltStart");
    if (s) s.scrollIntoView({ behavior: "smooth", block: "center" });
    await startTraining();
  }
  async function startTraining() {
    if (!L.pid) return;
    const b = $("ltStart"); b.disabled = true;
    try {
      const d = await post("/api/lora-trainer/start", { profile_id: L.pid, preset: L.preset, advanced: advanced() });
      L.job = d.job;
      toast("Treniranje je pokrenuto. ComfyUI je oslobodio VRAM; generiranje čeka dok trening traje.");
      renderJob();
      schedulePoll(800);
    } catch (e) { toast(e.message, true); renderStart(); }
  }
  async function stopJob(id) {
    if (!window.confirm("Zaustaviti treniranje? LoRA iz zadnje spremljene epohe ostaje, trenutna epoha se gubi.")) return;
    try { const d = await post("/api/lora-trainer/jobs/" + id + "/cancel", {}); L.job = d.job; renderJob(); toast("Treniranje je zaustavljeno."); } catch (e) { toast(e.message, true); }
  }
  async function generateWith(pid) {
    const c = C();
    if (!c) return;
    try { await c.loadState(); if (c.refreshLoras) await c.refreshLoras(); } catch (e) { /* */ }
    if (c.selectPersonaForGeneration) c.selectPersonaForGeneration(pid);
    c.showTab("slike");
    try { window.scrollTo({ top: 0, behavior: "smooth" }); } catch (e) { window.scrollTo(0, 0); }
    toast("Osoba je odabrana s novom LoRA-om. Upiši scenu i klikni Generiraj.");
  }
  function schedulePoll(ms) {
    clearTimeout(L.pollT);
    L.pollT = setTimeout(refreshJob, ms);
  }
  async function refreshJob() {
    let d = null;
    try { d = await get("/api/lora-trainer/jobs?limit=5" + (L.pid ? "&profile_id=" + L.pid : "")); } catch (e) { return; }
    const job = d.active_job || (d.jobs || [])[0] || null;
    const prev = job ? L.lastJobStatus[job.id] : null;
    L.job = job;
    renderJob();
    renderStart();
    if (job) {
      L.lastJobStatus[job.id] = job.status;
      if (prev && prev !== job.status && !job.active) onJobEnded(job);
      if (job.active) schedulePoll(2000);
    }
  }
  async function onJobEnded(job) {
    const c = C();
    if (job.status === "completed") {
      toast("LoRA je istrenirana i dodana osobi " + (job.profile_name || "") + ".");
      try { if (c) { await c.loadState(); if (c.refreshLoras) c.refreshLoras(); } } catch (e) { /* */ }
      await loadPersonas(); await loadLoras();
    } else if (job.status === "paused_overheat") toast("Treniranje je zaustavljeno zbog temperature GPU-a.", true);
    else if (job.status === "failed") toast("Treniranje nije uspjelo: " + (job.error_message || ""), true);
    loadStatus();
  }
  function renderJob() {
    const el = $("ltJob");
    if (!el) return;
    const j = L.job;
    if (!j) { el.hidden = true; el.innerHTML = ""; return; }
    el.hidden = false;
    const pct = Math.max(0, Math.min(100, Number(j.progress_pct) || 0));
    const tst = j.gpu_temp_status || "unavailable";
    let html = '<div class="lt-job-head"><b>' + esc(j.profile_name || "Osoba") + " · " + esc(j.lora_name || "") + '</b><span class="v11-badge ' + (j.status === "completed" ? "ok" : (j.active ? "run" : "bad")) + '">' + esc(j.status_label || j.status) + "</span></div>";
    if (j.active || j.status === "completed") {
      html += '<div class="bar lt-bar' + (j.status === "preparing" || j.status === "caching" || j.status === "queued" ? " indeterminate" : "") + '"><i style="width:' + pct + '%"></i></div>';
    }
    if (j.active) {
      html += '<div class="lt-kv">'
        + "<span>Faza: <b>" + esc(j.status_label) + "</b></span>"
        + "<span>Korak <b>" + (j.current_step || 0) + "/" + (j.total_steps || "?") + "</b></span>"
        + (j.total_epochs ? "<span>Epoha " + (j.current_epoch || 0) + "/" + j.total_epochs + "</span>" : "")
        + "<span>Preostalo: <b>" + (j.eta_seconds != null ? "~" + fmtDur(j.eta_seconds) : "računam…") + "</b></span>"
        + (j.loss != null ? "<span>Loss " + Number(j.loss).toFixed(4) + "</span>" : "")
        + "<span>Trajanje " + fmtDur(j.elapsed_seconds) + "</span></div>";
      html += '<div class="lt-temp-row ' + tst + '"><span class="lt-dot"></span>' + esc(tempLabel(j.gpu_temp_c, tst))
        + (j.gpu_temp_peak_c != null ? ' <span class="hint">(najviše ' + Math.round(j.gpu_temp_peak_c) + "°C)</span>" : "")
        + (vramLabel((L.status && L.status.gpu_live) || {}, j) ? " · " + esc(vramLabel((L.status && L.status.gpu_live) || {}, j)) : "")
        + "</div>";
      if (j.gpu_warning_message && (tst === "warn" || tst === "critical")) html += '<div class="lt-alert ' + tst + '">' + esc(j.gpu_warning_message) + "</div>";
      if (j.stall_warning && j.stall_message) html += '<div class="lt-alert warn">' + esc(j.stall_message) + ' <button type="button" class="btn" data-act="resume">Nastavi od zadnje epohe</button></div>';
      html += '<div class="hint">Ne zatvaraj Studio dok traje treniranje. Generiranje slika čeka u redu dok trening ne završi.</div>';
      html += '<div class="actions"><button type="button" class="btn danger" data-act="stop" data-id="' + j.id + '">Zaustavi</button></div>';
    } else if (j.status === "completed") {
      html += '<div class="lt-done">Gotovo! LoRA <b>' + esc(j.lora_filename || j.lora_name) + "</b> je automatski dodana u profil osobe "
        + esc(j.profile_name || "") + " (jačina 0.8, okidač <code>" + esc(j.trigger_word || "") + "</code>). Kad odabereš tu osobu u Generiranju, LoRA i okidač se sami primijene.</div>"
        + (j.gpu_temp_peak_c != null ? '<div class="hint">Najviša temperatura GPU-a: ' + Math.round(j.gpu_temp_peak_c) + "°C · trajanje " + fmtDur(j.elapsed_seconds) + "</div>" : "")
        + '<div class="actions"><button type="button" class="btn primary" data-act="gen" data-pid="' + j.profile_id + '">Generiraj s ovom osobom</button></div>';
    } else {
      const canResume = j.resume && j.resume.available;
      html += '<div class="lt-alert ' + (j.status === "paused_overheat" ? "critical" : "warn") + '">' + esc(j.error_message || j.stall_message || j.status_label)
        + (canResume ? " Možeš nastaviti od epohe " + j.resume.epoch + "." : "") + "</div>"
        + '<div class="actions">'
        + (canResume || j.stall_warning ? '<button type="button" class="btn primary" data-act="resume">Nastavi od zadnje epohe</button>' : "")
        + '<button type="button" class="btn" data-act="retry">Pokušaj ponovno</button></div>';
    }
    html += '<details class="lt-details"><summary>Prikaži log</summary><pre class="v11-pre lt-log">' + esc((j.log_lines || []).join("\n")) + "</pre></details>";
    const open = el.querySelector("details[open]");
    el.innerHTML = html;
    if (open) { const d = el.querySelector("details"); if (d) d.open = true; }
  }

  /* ---------- javno ---------- */
  async function render() {
    if (!build()) return;
    renderPresets();
    await loadStatus();
    renderPresets();
    await loadPersonas();
    await Promise.all([loadDataset(), loadLoras()]);
    renderPlan();
    refreshJob();
  }
  async function open(pid) {
    if (!build()) return;
    if (pid) L.pid = Number(pid);
    await render();
    const root = $("loraTrainer");
    if (root) root.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // Prati osobu odabranu lijevo (osim dok traje treniranje).
  function follow(pid, force) {
    pid = pid ? Number(pid) : null;
    if (!L.built) return;
    if (L.job && L.job.active && pid && Number(L.pid) === pid && !force) return;
    if (pid && Number(L.pid) === pid && !force) {
      // svejedno osvježi panele kad korisnik klikne tu osobu
    }
    if (pid && $("ltPersona")) $("ltPersona").value = String(pid);
    selectPersona(pid);
  }

  window.StudioLoraTrainer = { render: render, open: open, follow: follow, state: () => L, version: "1.2.0" };
  function boot() {
    const c = C();
    if (c && c.currentTab && c.currentTab() === "influenceri") render();
    // Aktivno treniranje se prati i kad je otvorena druga kartica.
    get("/api/lora-trainer/jobs?limit=1").then((d) => { if (d.active_job) { if (!L.built) build(); L.pid = d.active_job.profile_id; refreshJob(); } }).catch(() => {});
  }
  // 1.3.0: ocjena „Dobra/Loša” u Generiranju odmah osvježi dataset otvorene osobe
  document.addEventListener("studio:rated", (e) => {
    const it = e.detail && e.detail.item;
    if (L.built && L.pid && it && Number(it.persona_id) === Number(L.pid)) loadDataset().then(renderPlan).catch(() => {});
  });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();

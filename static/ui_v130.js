/* AI Influencer Studio 1.3.0 – objašnjenja (?), RX 6600 profili kvalitete, živi GPU bar i sitnice Početne.
   Ovisi o window.StudioCore (index.html) i window.StudioV11 (static/v11.js). Bez vanjskih biblioteka. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const C = () => window.StudioCore || null;
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const visible = (el) => !!el && !el.hidden && el.offsetParent !== null;

  /* ---------- ? objašnjenja (hover, fokus, klik; Escape zatvara) ---------- */
  let pop = null, popFor = null, pinned = false;
  function ensurePop() {
    if (pop) return pop;
    pop = document.createElement("div");
    pop.className = "tip-pop";
    pop.id = "tipPop";
    pop.setAttribute("role", "tooltip");
    pop.hidden = true;
    document.body.appendChild(pop);
    return pop;
  }
  function showTip(btn, pin) {
    const p = ensurePop();
    if (popFor && popFor !== btn) popFor.classList.remove("on");
    popFor = btn;
    pinned = !!pin;
    p.textContent = btn.dataset.tip || "";
    p.hidden = false;
    btn.classList.add("on");
    btn.setAttribute("aria-describedby", "tipPop");
    const r = btn.getBoundingClientRect();
    const pw = Math.min(320, window.innerWidth - 24);
    p.style.maxWidth = pw + "px";
    const ph = p.offsetHeight, w = p.offsetWidth;
    let left = Math.max(12, Math.min(window.innerWidth - w - 12, r.left + r.width / 2 - w / 2));
    let top = r.top - ph - 10;
    if (top < 8) top = r.bottom + 10;
    p.style.left = left + "px";
    p.style.top = top + "px";
  }
  function hideTip(force) {
    if (!pop || (pinned && !force)) return;
    pop.hidden = true;
    pinned = false;
    if (popFor) { popFor.classList.remove("on"); popFor.removeAttribute("aria-describedby"); }
    popFor = null;
  }
  document.addEventListener("mouseover", (e) => { const t = e.target.closest && e.target.closest(".tip"); if (t && !pinned) showTip(t, false); });
  document.addEventListener("mouseout", (e) => { const t = e.target.closest && e.target.closest(".tip"); if (t && !pinned) hideTip(false); });
  document.addEventListener("focusin", (e) => { const t = e.target.closest && e.target.closest(".tip"); if (t) showTip(t, false); });
  document.addEventListener("focusout", (e) => { const t = e.target.closest && e.target.closest(".tip"); if (t && !pinned) hideTip(false); });
  document.addEventListener("click", (e) => {
    const t = e.target.closest && e.target.closest(".tip");
    if (t) {
      e.preventDefault();   // ? unutar <label> ne smije mijenjati kvačicu
      e.stopPropagation();
      if (popFor === t && pinned) hideTip(true); else showTip(t, true);
      return;
    }
    if (pinned) hideTip(true);
  }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTip(true); });
  window.addEventListener("scroll", () => hideTip(true), { passive: true });

  /* ---------- RX 6600 profili kvalitete ---------- */
  const FALLBACK = {
    realism: { label: "Realizam", badge: "Preporučeno", hint: "Manja baza + brzi hires 1,33× (denoise 0,35), CFG 4,3 za prirodnu kožu.", sampler: "dpmpp_2m_sde", scheduler: "karras", hires: true, hires_scale: 1.33, hires_denoise: 0.35, hires_steps: 8, turbo: false },
    fast: { label: "Brzo", badge: "", hint: "Jedan prolaz, 20 koraka, bez hiresa.", sampler: "dpmpp_2m", scheduler: "karras", hires: false, hires_scale: 1.33, hires_denoise: 0.35, hires_steps: 8, turbo: false },
    turbo: { label: "Turbo 1024", badge: "Najbrže", hint: "Hyper-SDXL 8 koraka, CFG 2,2, euler + sgm_uniform, baza 1024 px.", sampler: "euler", scheduler: "sgm_uniform", hires: false, hires_scale: 1.25, hires_denoise: 0.32, hires_steps: 4, turbo: true }
  };
  let PROFILES = Object.assign({}, FALLBACK);
  const APPLIED_KEY = "studio_v130_profile_applied";
  function setVal(id, v, ev) {
    const el = $(id);
    if (!el || v == null) return;
    if (el.tagName === "SELECT" && ![...el.options].some((o) => o.value === String(v))) return;
    el.value = String(v);
    el.dispatchEvent(new Event(ev || "input", { bubbles: true }));
    if (el.tagName === "SELECT") el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  function activeProfileKey() {
    const b = document.querySelector("#quality button.on");
    return (b && b.dataset.profile) || "realism";
  }
  function renderProfileHint(key, notes) {
    const el = $("qualityProfileHint");
    if (!el) return;
    const p = PROFILES[key] || FALLBACK[key];
    if (!p) { el.innerHTML = ""; return; }
    const arch = C() && C().arch ? C().arch() : "";
    let txt = p.hint || "";
    if (p.turbo && arch && arch !== "sdxl") txt = "Turbo radi samo sa SDXL modelom (npr. RealVisXL) — odaberi SDXL u Napredno → Model.";
    el.innerHTML = (p.badge ? '<span class="ph-badge' + (p.turbo ? " turbo" : "") + '">' + esc(p.badge) + "</span>" : "")
      + "<span>" + esc(txt) + "</span>"
      + (notes && notes.length ? '<span class="ph-notes">8 GB zaštita: ' + esc(notes.join(" · ")) + "</span>" : "");
  }
  function applyProfile(key, opts) {
    const p = PROFILES[key] || FALLBACK[key];
    if (!p) return;
    const o = opts || {};
    setVal("v11Sampler", p.sampler);
    setVal("v11Scheduler", p.scheduler);
    setVal("v11HiresScale", p.hires_scale);
    setVal("v11HiresDenoise", p.hires_denoise);
    setVal("v11HiresSteps", p.hires_steps);
    const cfgOn = $("v11CfgOn");
    if (cfgOn && cfgOn.checked && !o.keepCfg) { cfgOn.checked = false; cfgOn.dispatchEvent(new Event("change", { bubbles: true })); }
    const hf = $("hiresFix");
    const arch = C() && C().arch ? C().arch() : "";
    if (hf && arch !== "krea2" && hf.checked !== !!p.hires) { hf.checked = !!p.hires; hf.dispatchEvent(new Event("change", { bubbles: true })); }
    renderProfileHint(key);
    try { localStorage.setItem(APPLIED_KEY, "1"); } catch (e) { /* privatni način */ }
  }
  const q = $("quality");
  if (q) q.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-profile]");
    if (!b) return;
    setTimeout(() => applyProfile(b.dataset.profile), 0);
  });
  document.addEventListener("studio:gen-rendered", (e) => {
    const o = (e.detail && e.detail.options) || {};
    (o.quality_profiles || []).forEach((p) => { if (p && p.key) PROFILES[p.key] = Object.assign({}, FALLBACK[p.key] || {}, p); });
    let first = false;
    try { first = !localStorage.getItem(APPLIED_KEY); } catch (err) { first = false; }
    // Prvi put (nova instalacija ili nadogradnja na 1.3.0): primijeni preporučeni profil i na Napredno polja.
    if (first) setTimeout(() => applyProfile(activeProfileKey()), 400);
    else renderProfileHint(activeProfileKey());
  });
  document.addEventListener("studio:generated", (e) => {
    const m = (e.detail && e.detail.meta) || {};
    const notes = m.rx_notes || [];
    renderProfileHint(m.quality_profile || activeProfileKey(), notes);
  });

  /* ---------- Živi GPU bar (generiranje i treniranje) ---------- */
  const G = { timer: null, busy: false, last: null };
  function stepLabel(d) {
    if (localGen()) {
      const t = ($("progText") && $("progText").textContent || "").trim();
      const pct = ($("progPct") && $("progPct").textContent || "").trim();
      return t + (pct && t.indexOf(pct) < 0 ? " · " + pct : "");
    }
    const a = (d && d.activity) || {};
    if (a.training) return (a.label || "Treniranje") + (a.step != null && a.total ? " · korak " + a.step + " / " + a.total : "");
    if (a.generating) return (a.label || "Generiranje") + (a.progress ? " · " + Math.round(a.progress * 100) + " %" : "");
    return "";
  }
  function barHtml(d) {
    const usage = d.gpu_usage_pct, temp = d.temp_c, used = d.vram_used_mb, tot = d.vram_total_mb;
    const ts = d.temp_status || "unavailable";
    const step = stepLabel(d);
    const gb = (mb) => (Number(mb) / 1024).toFixed(1);
    const vpct = used != null && tot ? Math.min(100, Math.round((used / tot) * 100)) : null;
    return '<span class="gl-item gl-usage" title="Opterećenje GPU-a"><span class="gl-k">GPU</span>'
      + (usage != null ? '<span class="gl-track"><i style="width:' + Math.max(2, Math.min(100, Math.round(usage))) + '%"></i></span><span class="gl-v">' + Math.round(usage) + " %</span>" : '<span class="gl-na">n/d</span>') + "</span>"
      + '<span class="gl-item gl-temp ' + esc(ts) + '" title="' + esc(d.temp_message || "Temperatura GPU-a") + '"><span class="gl-dot"></span>'
      + (temp != null ? '<span class="gl-v">' + Math.round(temp) + " °C</span>" : '<span class="gl-na">Senzor temperature nedostupan</span>') + "</span>"
      + '<span class="gl-item gl-vram" title="VRAM"><span class="gl-k">VRAM</span>'
      + (vpct != null ? '<span class="gl-track"><i style="width:' + Math.max(2, vpct) + '%"></i></span><span class="gl-v">' + gb(used) + " / " + gb(tot) + " GB</span>"
        : (tot ? '<span class="gl-v">' + gb(tot) + " GB</span>" : '<span class="gl-na">n/d</span>')) + "</span>"
      + (step ? '<span class="gl-item gl-step">' + esc(step) + "</span>" : "");
  }
  // Generiranje je u tijeku dok je traka napretka vidljiva, a gumb Generiraj onemogućen.
  function localGen() { return visible($("progWrap")) && !!($("go") && $("go").disabled); }
  function localTrain() { const j = $("ltJob"); return visible(j) && /v11-badge run|lt-bar/.test(j.innerHTML || ""); }
  function wantedTargets(d) {
    const out = [];
    const genActive = localGen() || !!(d && d.activity && d.activity.generating);
    const trainActive = !!(d && d.activity && d.activity.training) || localTrain();
    if ($("gpuLive") && (genActive || trainActive) && visible($("tab-slike"))) out.push($("gpuLive"));
    if ($("ltGpu") && (trainActive || genActive)) out.push($("ltGpu"));
    return out;
  }
  function hideAll() { ["gpuLive", "ltGpu"].forEach((id) => { if ($(id)) $(id).hidden = true; }); }
  async function tick() {
    if (G.busy) { schedule(800); return; }
    const onTabs = visible($("tab-slike")) || visible($("loraTrainer"));
    if (document.hidden || !onTabs) { hideAll(); schedule(4000); return; }
    const local = localGen() || localTrain();
    const a = (G.last && G.last.activity) || {};
    const serverBusy = !!(a.generating || a.training);
    G.n += 1;
    // Lokalno generiranje/trening: svake ~2,5 s. Inače rijetka lagana provjera (red čekanja ili trening u pozadini).
    if (local || serverBusy || G.n % 3 === 0) await fetchLive(); else hideAll();
    schedule(local || serverBusy ? 2500 : 5000);
  }
  G.n = 0;
  async function fetchLive() {
    G.busy = true;
    try {
      const r = await fetch("/api/gpu-live", { cache: "no-store" });
      const d = await r.json();
      if (d && d.ok !== false) {
        G.last = d;
        const targets = wantedTargets(d);
        ["gpuLive", "ltGpu"].forEach((id) => {
          const el = $(id);
          if (!el) return;
          const on = targets.indexOf(el) >= 0;
          el.hidden = !on;
          if (on) el.innerHTML = barHtml(d);
        });
      }
    } catch (e) { /* Studio se možda restarta */ }
    G.busy = false;
  }
  function schedule(ms) { clearTimeout(G.timer); G.timer = setTimeout(tick, ms); }
  function kick() { clearTimeout(G.timer); G.timer = setTimeout(tick, 60); }
  const pw = $("progWrap"), goB = $("go");
  if (window.MutationObserver) {
    if (pw) new MutationObserver(kick).observe(pw, { attributes: true, attributeFilter: ["hidden"] });
    if (goB) new MutationObserver(kick).observe(goB, { attributes: true, attributeFilter: ["disabled"] });
  }
  document.addEventListener("visibilitychange", kick);
  schedule(1200);

  /* ---------- klizači: ispuna do trenutne vrijednosti ---------- */
  function paintRange(el) {
    const min = parseFloat(el.min || "0"), max = parseFloat(el.max || "100"), v = parseFloat(el.value);
    const pct = max > min ? Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100)) : 0;
    el.style.setProperty("--p", pct.toFixed(1) + "%");
  }
  function paintAll() { document.querySelectorAll('input[type="range"]').forEach(paintRange); }
  document.addEventListener("input", (e) => { if (e.target && e.target.type === "range") paintRange(e.target); }, true);
  document.addEventListener("change", (e) => { if (e.target && e.target.type === "range") paintRange(e.target); }, true);
  document.addEventListener("studio:gen-rendered", () => setTimeout(paintAll, 0));
  document.addEventListener("click", (e) => { if (e.target.closest && e.target.closest(".tabs button, .pcard-actions, details > summary")) setTimeout(paintAll, 120); });
  setTimeout(paintAll, 800);
  setInterval(paintAll, 4000);  // jeftino; hvata klizače koje druge skripte iscrtaju kasnije

  /* ---------- Početna: CTA ---------- */
  document.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest(".home-head [data-go]");
    if (b && C()) C().showTab(b.dataset.go);
  });

  window.StudioUI130 = {
    applyProfile: applyProfile,
    profiles: () => PROFILES,
    gpuRefresh: () => fetchLive(),
    renderGpu: (d) => { ["gpuLive", "ltGpu"].forEach((id) => { const el = $(id); if (el) { el.hidden = false; el.innerHTML = barHtml(d); } }); }
  };
})();

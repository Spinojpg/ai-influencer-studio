/* AI Influencer Studio 1.2.0 – jednostavnije sučelje.
   Samo prikaz: vizualni odabir osobe, kartice osoba i sažetak „Napredno”.
   Sve postojeće kontrole (ID-jevi, događaji, API) ostaju iste; ovaj modul ih samo poziva. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const C = () => window.StudioCore || null;
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const U = { pickSig: "", cardSig: "", advSig: "" };

  function profiles() {
    const c = C();
    try { return (c && c.state().profiles) || []; } catch (e) { return []; }
  }
  function hasLora(p) {
    return !!(p && (p.preferred_lora || (Array.isArray(p.lora_stack) && p.lora_stack.some((x) => x && x.name))));
  }
  function initials(name) {
    const parts = String(name || "?").trim().split(/\s+/).filter(Boolean);
    return ((parts[0] || "?")[0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
  }
  function hue(id) { return (Number(id) * 67) % 360; }
  function avatar(p, cls) {
    const st = 'style="--av-h:' + hue(p.id) + '"';
    if (p.has_reference) {
      const v = encodeURIComponent(String(p.updated_at || p.reference_count || ""));
      return '<span class="' + cls + '" ' + st + '><img src="/api/profiles/' + p.id + "/image?v=" + v + '" alt="" loading="lazy" decoding="async" /></span>';
    }
    return '<span class="' + cls + ' no-img" ' + st + ">" + esc(initials(p.name)) + "</span>";
  }
  function shortModel(name) {
    const base = String(name || "").split(/[\\/]/).pop().replace(/\.(safetensors|ckpt|pt|bin|gguf)$/i, "");
    return base.replace(/[_-]?fp16|[_-]?fp8.*$/i, "").replace(/_/g, " ").trim();
  }
  function snippet(p) {
    let t = String(p.appearance_prompt || "").replace(/^\s*(portrait of\s+)?/i, "");
    t = t.split(",").map((x) => x.trim()).filter((x) => x && !/^(an?\s+)?adult woman$/i.test(x) && !/^\d+$/.test(x)).join(", ");
    return t.length > 110 ? t.slice(0, 107).replace(/[\s,]+\S*$/, "") + "…" : t;
  }
  function ageOf(p) {
    const m = String(p.age_vibe || "").match(/\d{2}/) || String(p.appearance_prompt || "").match(/(^|\D)(\d{2})(\D|$)/);
    return m ? (m[2] || m[0]) : "";
  }

  /* ---------- Generiranje: odabir osobe ---------- */
  function renderPicker(force) {
    const box = $("personaPicker");
    const sel = $("osoba");
    if (!box || !sel) return;
    const list = profiles();
    const cur = sel.value;
    const sig = cur + "|" + list.map((p) => [p.id, p.name, p.has_reference, p.reference_count, hasLora(p), p.updated_at].join(":")).join(",");
    if (!force && sig === U.pickSig) return;
    U.pickSig = sig;
    if (!list.length) {
      box.innerHTML = '<div class="picker-empty">Još nema osoba. <button type="button" class="link-btn" data-ui-new>Dodaj prvu osobu</button></div>';
      return;
    }
    box.innerHTML = list.map((p) => {
      const on = String(p.id) === String(cur);
      const lora = hasLora(p);
      return '<button type="button" class="persona-chip' + (on ? " on" : "") + (lora ? " has-lora" : "") + '" role="radio" aria-checked="' + on + '" data-pid="' + p.id + '" title="' + esc(p.name) + (lora ? " · LoRA aktivna" : "") + '">'
        + avatar(p, "pc-av")
        + '<span class="pc-name">' + esc(p.name) + "</span>"
        + (lora ? '<span class="pc-lora" aria-label="LoRA aktivna"></span>' : "")
        + "</button>";
    }).join("") + '<button type="button" class="persona-chip add" data-ui-new title="Dodaj novu osobu"><span class="pc-av">+</span><span class="pc-name">Nova</span></button>';
    renderStatus();
  }
  function renderStatus() {
    const el = $("personaStatus");
    const sel = $("osoba");
    if (!el || !sel) return;
    const p = profiles().find((x) => String(x.id) === String(sel.value));
    if (!p) { el.innerHTML = ""; return; }
    const n = Number(p.reference_count || 0);
    const bits = [hasLora(p) ? '<span class="pill pill-ok" title="' + esc(p.preferred_lora || "") + '">LoRA aktivna</span>' : '<span class="pill">Bez LoRA-e</span>'];
    bits.push('<span class="pill">' + (n ? n + (n === 1 ? " ref. slika" : (n < 5 ? " ref. slike" : " ref. slika")) : "Bez ref. slika") + "</span>");
    if (p.lock_seed) bits.push('<span class="pill">Zaključan seed</span>');
    el.innerHTML = bits.join("");
  }
  function bindPicker() {
    const box = $("personaPicker");
    const sel = $("osoba");
    if (!box || !sel) return;
    box.addEventListener("click", (e) => {
      if (e.target.closest("[data-ui-new]")) { openProfiles(null, true); return; }
      const b = e.target.closest("[data-pid]");
      if (!b) return;
      if (sel.value !== b.dataset.pid) {
        sel.value = b.dataset.pid;
        sel.dispatchEvent(new Event("change", { bubbles: true }));
      }
      renderPicker(true);
    });
    box.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const chips = Array.from(box.querySelectorAll("[data-pid]"));
      const i = chips.findIndex((x) => x.classList.contains("on"));
      const n = chips[(i + (e.key === "ArrowRight" ? 1 : chips.length - 1)) % chips.length];
      if (n) { e.preventDefault(); n.click(); n.focus(); }
    });
    sel.addEventListener("change", () => renderPicker(true));
    new MutationObserver(() => renderPicker(false)).observe(sel, { childList: true });
    const edit = $("uiEditPersona");
    if (edit) edit.addEventListener("click", () => openProfiles(Number(sel.value) || null, false));
  }

  /* ---------- Generiranje: sažetak „Napredno” ---------- */
  function renderAdvSummary() {
    const el = $("advSummary");
    if (!el) return;
    const parts = [];
    const m = $("model");
    if (m && m.value) parts.push(shortModel(m.value));
    const tpl = $("v11Tpl");
    if (tpl && tpl.value && tpl.selectedOptions[0]) parts.push(tpl.selectedOptions[0].textContent);
    const smp = $("v11Sampler");
    if (smp && smp.value) parts.push(smp.value + ($("v11Scheduler") && $("v11Scheduler").value ? " · " + $("v11Scheduler").value : ""));
    const batch = document.querySelector("#batch button.on");
    if (batch && batch.dataset.n && batch.dataset.n !== "1") parts.push(batch.dataset.n + " slike");
    const lora = $("lora");
    if (lora && lora.value) parts.push("LoRA");
    const sig = parts.join("|");
    if (sig === U.advSig) return;
    U.advSig = sig;
    el.innerHTML = parts.map((x) => '<span class="pill">' + esc(x) + "</span>").join("");
  }

  /* ---------- Osobe: kartice ---------- */
  function editingId() {
    const c = C();
    try { return (c && (c.editingId() || c.state().active_profile_id)) || null; } catch (e) { return null; }
  }
  function renderCards(force) {
    const box = $("personaCards");
    if (!box) return;
    const list = profiles();
    const cur = editingId();
    const sig = cur + "|" + list.map((p) => [p.id, p.name, p.age_vibe, p.appearance_prompt, p.reference_count, p.has_reference, hasLora(p), p.updated_at].join(":")).join(",");
    if (!force && sig === U.cardSig) return;
    U.cardSig = sig;
    if (!list.length) {
      box.innerHTML = '<div class="empty">Još nema osoba. Klikni „Novi profil” gore desno.</div>';
      return;
    }
    box.innerHTML = list.map((p) => {
      const age = ageOf(p);
      const n = Number(p.reference_count || 0);
      const on = Number(cur) === Number(p.id);
      return '<article class="persona-card' + (on ? " on" : "") + '" data-pid="' + p.id + '">'
        + '<button type="button" class="pcard-main" data-act="edit" aria-label="Uredi ' + esc(p.name) + '">'
        + avatar(p, "pcard-av")
        + '<span class="pcard-body"><span class="pcard-name">' + esc(p.name) + (age ? '<span class="pcard-age">' + esc(age) + "</span>" : "") + "</span>"
        + '<span class="pcard-desc">' + (esc(snippet(p)) || '<em>Nema opisa izgleda.</em>') + "</span>"
        + '<span class="pcard-badges">'
        + (hasLora(p) ? '<span class="pill pill-ok">LoRA aktivna</span>' : '<span class="pill">Bez LoRA-e</span>')
        + '<span class="pill">' + (n ? n + (n === 1 ? " ref. slika" : (n < 5 ? " ref. slike" : " ref. slika")) : "Nema ref. slika") + "</span>"
        + "</span></span></button>"
        + '<div class="pcard-actions">'
        + '<button type="button" class="btn primary sm" data-act="gen">Generiraj</button>'
        + '<button type="button" class="btn sm" data-act="edit">Uredi</button>'
        + '<button type="button" class="btn sm" data-act="lora">LoRA trener</button>'
        + "</div></article>";
    }).join("");
  }
  function clickProfileRow(pid) {
    const row = document.querySelector('#profileList [data-id="' + pid + '"]');
    if (row) row.click();
    return !!row;
  }
  function openProfiles(pid, isNew) {
    const c = C();
    if (c) c.showTab("influenceri");
    setTimeout(() => {
      if (isNew && $("newProfile")) $("newProfile").click();
      else if (pid) clickProfileRow(pid);
      const f = $("profileForm");
      if (f) f.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 60);
  }
  function bindCards() {
    const box = $("personaCards");
    if (!box) return;
    box.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-act]");
      const card = e.target.closest("[data-pid]");
      if (!btn || !card) return;
      const pid = Number(card.dataset.pid);
      const c = C();
      if (btn.dataset.act === "edit") {
        clickProfileRow(pid);
        setTimeout(() => { const f = $("profileForm"); if (f) f.scrollIntoView({ behavior: "smooth", block: "start" }); }, 80);
      } else if (btn.dataset.act === "gen") {
        if (c) { c.showTab("slike"); c.selectPersonaForGeneration(pid); }
        renderPicker(true);
        const pr = $("prompt");
        if (pr) setTimeout(() => { try { pr.focus({ preventScroll: false }); } catch (err) { pr.focus(); } }, 50);
      } else if (btn.dataset.act === "lora") {
        clickProfileRow(pid);
        if (window.StudioLoraTrainer) window.StudioLoraTrainer.open(pid);
      }
    });
    const list = $("profileList");
    if (list) new MutationObserver(() => { renderCards(false); renderEditTitle(); }).observe(list, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
    const name = $("pName");
    if (name) name.addEventListener("input", renderEditTitle);
    const np = $("newProfile");
    if (np) np.addEventListener("click", () => setTimeout(() => { renderCards(true); renderEditTitle(); }, 30));
  }
  function renderEditTitle() {
    const el = $("pEditTitle");
    if (!el) return;
    const id = $("pId") ? $("pId").value : "";
    const nm = $("pName") ? $("pName").value.trim() : "";
    el.textContent = id ? (nm || "Bez imena") : "Nova osoba · za izmjenu klikni „Uredi” na kartici";
  }

  // Kad otvoriš Osobe, a obrazac je prazan (nije započeta nova osoba), učitaj aktivnu osobu u obrazac.
  function autoFillProfile() {
    const id = $("pId") ? $("pId").value : "";
    const nm = $("pName") ? $("pName").value.trim() : "";
    if (id || nm) return;
    const c = C();
    let act = null;
    try { act = c && c.state().active_profile_id; } catch (e) { act = null; }
    if (act) clickProfileRow(act);
  }
  function tick() {
    const c = C();
    const tab = c && c.currentTab ? c.currentTab() : "";
    if (tab === "slike") { renderPicker(false); renderAdvSummary(); }
    if (tab === "influenceri") {
      renderCards(false); renderEditTitle();
      if (!U.autoTried && profiles().length) { U.autoTried = true; autoFillProfile(); }
    }
  }
  function boot() {
    bindPicker();
    bindCards();
    const form = $("form");
    if (form) { form.addEventListener("change", renderAdvSummary); form.addEventListener("click", () => setTimeout(renderAdvSummary, 0)); }
    document.querySelectorAll(".tabs button[data-tab]").forEach((b) => b.addEventListener("click", () => {
      setTimeout(tick, 30);
      if (b.dataset.tab === "influenceri") { U.autoTried = true; setTimeout(autoFillProfile, 60); }
    }));
    renderPicker(true);
    renderCards(true);
    renderAdvSummary();
    renderEditTitle();
    setInterval(tick, 1200);
  }
  window.StudioUI120 = { renderPicker: renderPicker, renderCards: renderCards, renderAdvSummary: renderAdvSummary, version: "1.2.0" };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();

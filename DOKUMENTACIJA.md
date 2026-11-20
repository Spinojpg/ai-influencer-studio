# AI Influencer Studio 1.1.0 — dokumentacija

Lokalni studio za fiktivne odrasle AI influencere: generiranje slika preko ComfyUI-ja, osobe (persone), red čekanja, galerija, kalendar objava i Inbox i CRM. Sve radi na tvom računalu na `http://127.0.0.1:7860`. Ključevi i tokeni stoje samo u `data/.env`.

Ciljani setup: Windows, AMD RX 6600 (8 GB), Ryzen 7 5700X, 16 GB RAM-a, ComfyUI-Zluda u `C:\ComfyUI-Zluda` (pokretanje `comfyui-n.bat`).

---

## 1. Kartice

| Kartica | Što radi |
|---|---|
| **Pregled** | Brzi formati (IG Portret 4:5, IG Kvadrat 1:1, IG Story 9:16), brze radnje, brojke (red čekanja, galerija, objave, poruke), sljedeće objave. |
| **Generiranje** | Prompt, osoba, format, napredne postavke, predlošci, red čekanja (batch) i galerija s ocjenama i gumbom „Učitaj još”. |
| **Osobe** | Profili fiktivnih odraslih osoba, referentne slike, LoRA stack, način rada referenci (IP-Adapter / InstantID), Character Sheet, izvoz LoRA dataseta. |
| **Video** | AnimateDiff video (kao u 1.0.20). |
| **Kalendar** | Mjesečni prikaz objava; nacrt, zakazivanje i objava na Instagram, Facebook, Telegram i Premium API. |
| **Inbox i CRM** | Jedinstveni inbox, način slanja (Automatsko slanje odmah / Nacrt za odobrenje), kontakti i memorija, narudžbe, analitika, izvori i webhook. |
| **Modeli** | Preuzimanje checkpointa, LoRA-a i čvorova; sekcija „Preporučene SDXL LoRA-e (realizam i detalji)”. |
| **Postavke** | Hardver i ComfyUI zastavice, ključevi (`data/.env`, maskirano), AI chat (LLM), ažuriranje. |

---

## 2. Hardver (Postavke → Hardver)

- **Detekcija GPU-a**: Studio prepoznaje grafičku karticu (Windows CIM/wmic, nvidia-smi, rocm-smi) i VRAM.
- **Backend**: `auto`, `zluda` (AMD na Windowsu, preporuka za RX 6600), `cuda`, `rocm`, `directml`, `cpu`.
- **VRAM način**: `auto`, `lowvram` (`--lowvram`), `medvram` (ComfyUI nema zasebnu zastavicu, pa radi bez dodatne zastavice), `normalvram` (`--normalvram`).
- **VAE**: standardni, tiled (`VAEDecodeTiled`, zadano) ili CPU.
- **8 GB siguran način**: tiled VAE, manji hires, rezerva VRAM-a, ograničen batch.
- **„Preporuči za RX 6600”** postavi ZLUDA, `--reserve-vram 1.0`, tiled VAE i siguran način, zatim ponudi **restart ComfyUI-ja**.

> **Važno za RX 6600 + ZLUDA:** `TORCH_BACKENDS_CUDNN_ENABLED=0` uvijek ostaje postavljen (kvačica „Isključi cuDNN”). Bez toga ComfyUI zna zapeti na „Compilation is in progress”.

Studio šalje samo zastavice koje tvoja verzija ComfyUI-ja stvarno podržava (čita `comfy/cli_args.py`).

---

## 3. Generiranje

Zadane postavke (SDXL, 8 GB):

- Sampler `dpmpp_2m_sde`, scheduler `karras`.
- **Hires fix**: faktor 1,4–1,5, denoise 0,35–0,45, 12–15 koraka, dekodiranje preko `VAEDecodeTiled`.
- **FreeU_V2**: b1 1,3 · b2 1,4 · s1 0,9 · s2 0,2 (uključi/isključi).
- **Face Detailer** (Impact Pack + Subpack): jačina (denoise), guide size, koraci. Ako čvorovi nisu instalirani, predlošci ga preskoče umjesto da javljaju grešku.
- **Multi-LoRA**: do 5 LoRA-a s vlastitim jačinama (stack osobe + ručno dodane).
- **Reference lica**: izbornik `Bez reference`, `IP-Adapter` ili `InstantID`. Bedž pokazuje što će se stvarno koristiti. InstantID treba čvor ComfyUI_InstantID, antelopev2 i InstantID model; FaceAnalysis radi na CPU-u da štedi VRAM.

### Predlošci (SQLite)

Predlošci su spremljeni u bazi i možeš ih uređivati, duplicirati i brisati. Grupe:

- **Javni teaser**: editorial, lifestyle, moda, studijski glamur, iza kulisa.
- **Premium sadržaj**: personalizirani SFW portreti, shoutout slike, ekskluzivni editorial i lifestyle setovi.

Ugrađeni predlošci i zadani AI promptovi su isključivo SFW. Vlastite promptove, predloške, ComfyUI workflowe i lokalne LoRA-e Studio ne cenzurira ključnim riječima; jedina zaštita koja uvijek vrijedi je da su osobe **odrasle** (vidi 4.).

Ako u predlošku nešto nije postavljeno, vrijedi ono iz forme. Ako u formi eksplicitno odabereš npr. scheduler, on ima prednost, osim kad u batchu odabereš više predložaka: tada svaki predložak nosi svoje postavke.

### Red čekanja i batch

- Svaki posao ima status: **U tijeku**, **Na čekanju**, **Gotovo**, **Greška**, **Otkazano**.
- Red je trajan (SQLite) i nastavlja se nakon restarta Studija.
- Batch: broj ponavljanja, seed (nasumičan / isti / uzastopni) i jedan ili više predložaka.
- Otkaži, Ponovi i Očisti završene.

### Galerija

Galerija prikazuje sve slike iz reda, filtrira ih po osobi, ocjeni i izvoru, a slike se učitavaju lijeno („Učitaj još”). Ocjene **Dobra** i **Loša** možeš dati i u lightboxu.

---

## 4. Osobe (persone)

- Sve osobe su **fiktivne odrasle osobe**. Prompt uvijek počinje s `adult woman, <dob>` (dob 18+), a `child, teen` i slični pojmovi su uvijek u negativnom promptu. Ne koristi lica stvarnih ljudi.
- **LoRA stack** po osobi (do 5) s jačinama.
- **Način referenci**: IP-Adapter ili InstantID, s jačinom InstantID-a.
- **Način slanja po osobi** za CRM (naslijedi / automatsko / nacrt).
- **Character Sheet 2×2**: četiri kadra (sprijeda, tri četvrtine, profil, vani candid) s istim seedom, spojeno u jednu PNG sliku (Pillow, ili čisti Python ako Pillow nije dostupan).
- **Izvoz LoRA dataseta**: slike ocijenjene kao „Dobra” idu u `data/lora_datasets/<osoba>_<vrijeme>/` s caption .txt datotekama, `UPUTE.txt` i konfiguracijama `kohya_sdxl_lora_8gb.json` i `onetrainer_sdxl_lora_8gb.json`, prilagođenima za 8 GB (batch 1, gradient checkpointing, mixed precision).

---

## 5. Preporučene SDXL LoRA-e (realizam i detalji)

Sve su SFW i služe samo za kvalitetu slike. Idu u `models\loras`.

| LoRA | Datoteka | Veličina | Preporučena jačina |
|---|---|---|---|
| Photorealistic slider (ostris) | ostris_photorealistic_slider_xl.safetensors | ~24 MB | 0,5–1,5 |
| Extremely detailed (ntc-ai) | ntc_extremely_detailed_xl.safetensors | ~9 MB | 0,5–1,5 |
| Cinematic lighting (ntc-ai) | ntc_cinematic_lighting_xl.safetensors | ~9 MB | 0,5–1,5 |
| Offset noise (Stability AI) | sdxl_offset_example_lora_1.0.safetensors | ~50 MB | 0,3–0,6 |
| Nice hands (ntc-ai) | ntc_nice_hands_xl.safetensors | ~9 MB | 0,5–1,5 |
| Detail Tweaker XL | add_detail_xl.safetensors | ~228 MB | 0,5–1,5 |

---

## 6. Objave i Kalendar

Kanali:

1. **Instagram**: Graph API, najprije container (`/media`), pa `media_publish`. Instagram mora moći preuzeti sliku s javnog URL-a, pa treba `PUBLIC_MEDIA_BASE_URL`: HTTPS tunel prema Studiju (cloudflared ili ngrok). Studio dijeli samo sliku te objave preko `/public/media/<id>/<token>`.
2. **Facebook Page**: `/photos` (slika) ili `/feed` (tekst).
3. **Telegram**: `sendPhoto` / `sendMessage` na `TELEGRAM_CHAT_ID`.
4. **Premium API**: tvoja platforma; JSON ili multipart na `PREMIUM_API_URL`.

Zakazane objave provjerava raspored svakih 30 sekundi. Ako objava uspije na jednom kanalu, a na drugom ne, ponovni pokušaj šalje samo na kanale gdje nije uspjela.

---

## 7. Inbox i CRM

- **Jedinstveni inbox** za Instagram DM, Telegram, Premium i webhook izvore. Stari `/api/inbox/*` endpointi i dalje rade.
- **Način slanja** (velika traka na vrhu kartice):
  - **Automatsko slanje odmah**: AI odgovor se šalje bez čekanja.
  - **Nacrt za odobrenje**: odgovor čeka da ga pregledaš i pošalješ (zadano).
  - Mijenja se jednim klikom: **globalno**, **po kanalu** i **po influenceru**. Redoslijed važenja je influencer, pa kanal, pa globalno.
- **AI chat (LLM)**: `auto` (Ollama → LM Studio/OpenAI-kompatibilan → xAI → pravila), ili ručno `ollama`, `openai_compat`, `xai`, `rules`. Bez ikakvog ključa radi način **pravila** (jednostavni odgovori), pa simulacija radi i bez xAI-ja.
- **Memorija po fanu**: bilješke, oznake, interesi i povijest kupnji.
- **Prepoznavanje interesa**: pretplata, custom narudžba, cijena, shoutout.
- **Custom narudžbe** (SFW personalizirani portreti i shoutouti): kreiraj iz razgovora, pa Generiraj (ide u red), Isporuči (lokalno, Telegram ili Premium) i Označi plaćeno.
- **Pretplatnici i kupnje**, **analitika** (poruke, odgovori, narudžbe, prihod po kanalu i osobi).
- **Webhook**: `POST /api/crm/webhook`. Ako je postavljen `CRM_WEBHOOK_SECRET`, zahtjev mora imati header `X-Studio-Secret`.

Primjer:
```json
{"event": "message", "platform": "premium", "persona": "Ana", "user_id": "fan123", "name": "Marko", "text": "Bok! Može custom portret?"}
```

---

## 8. Ključevi (`data/.env`)

Unose se u **Postavke → Ključevi** ili ručno u `data/.env` (predložak `.env.example`). U sučelju se tajne prikazuju maskirano. Nikad ih ne dijeli i ne commitaj.

| Ključ | Svrha |
|---|---|
| META_ACCESS_TOKEN, META_IG_USER_ID, META_FB_PAGE_ID | Instagram/Facebook objave |
| PUBLIC_MEDIA_BASE_URL | javni HTTPS URL Studija (tunel) za Instagram slike |
| GRAPH_API_VERSION | npr. v22.0 |
| TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID | Telegram bot i kanal |
| PREMIUM_API_URL, PREMIUM_API_KEY, PREMIUM_AUTH_HEADER, PREMIUM_SEND_MODE, PREMIUM_MESSAGE_URL | Premium platforma |
| CRM_WEBHOOK_SECRET | zaštita webhooka |
| XAI_API_KEY, XAI_MODEL | xAI Grok (opcionalno) |
| OLLAMA_BASE_URL, OLLAMA_MODEL | lokalni Ollama |
| OPENAI_COMPAT_BASE_URL, OPENAI_COMPAT_API_KEY, OPENAI_COMPAT_MODEL | LM Studio ili drugi OpenAI-kompatibilan server |
| IG_VERIFY_TOKEN, IG_APP_SECRET, IG_ACCESS_TOKEN | Instagram Messaging (DM) |

---

## 9. Rješavanje problema

- **ComfyUI visi na „Compilation is in progress”**: provjeri da je „Isključi cuDNN” uključen (`TORCH_BACKENDS_CUDNN_ENABLED=0`) i restartaj ComfyUI iz Postavki.
- **Out of memory**: uključi 8 GB siguran način, tiled VAE, smanji hires na 1,4 ili isključi Face Detailer.
- **Instagram javlja grešku s URL-om**: `PUBLIC_MEDIA_BASE_URL` mora biti javni HTTPS tunel koji radi.
- **InstantID / Face Detailer bedž je siv**: čvorovi nisu učitani; instaliraj ih u kartici Modeli i restartaj ComfyUI.

---

## 10. Za razvoj

- Struktura: `studio.py` (HTTP server), `api_v11.py` (1.1 API), `services/` (hardware, generation, posting, crm), `static/v11.js` i `static/v11.css`.
- Testovi: `python3 tools/test_v110.py` (uz `PW_PYTHON=/tmp/pwenv/bin/python` za headless UI), te `python3 tools/check_ui_js.py`.
- Izdanje: `bash tools/make_release.sh minor "opis"`.

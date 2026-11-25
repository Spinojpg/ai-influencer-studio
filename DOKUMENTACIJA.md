# AI Influencer Studio 1.3.0 — dokumentacija

Lokalni studio za fiktivne odrasle AI influencere: generiranje slika preko ComfyUI-ja, osobe (persone), red čekanja, galerija, kalendar objava i Inbox i CRM. Sve radi na tvom računalu na `http://127.0.0.1:7860`. Ključevi i tokeni stoje samo u `data/.env`.

Ciljani setup: Windows, AMD RX 6600 (8 GB), Ryzen 7 5700X, 16 GB RAM-a, ComfyUI-Zluda u `C:\ComfyUI-Zluda` (pokretanje `comfyui-n.bat`).

---

## 1. Kartice

| Kartica | Što radi |
|---|---|
| **Početna** (prije Pregled) | 4 KPI kartice (Prihodi i Slike sa sparkline grafom za 14 dana, Aktivne osobe i Zakazano s prstenom), brzi formati (IG Portret 4:5, IG Kvadrat 1:1, IG Story 9:16), brze radnje, brojke (red čekanja, galerija, objave, poruke), sljedeće objave. |
| **Generiranje** | Dva stupca: lijevo odabir osobe (avatari), opis scene, format, profil kvalitete (Realizam / Brzo / Turbo) i Generiraj; desno nove slike s gumbima Dobra / Loša, živa GPU traka i galerija s filtrom ocjena. Tehničke postavke su u „Napredno” (5 kartica s objašnjenjima). |
| **Osobe** | Kartice osoba (avatar, ime, dob, kratki opis, oznake LoRA i referentnih slika, brze radnje Generiraj / Uredi / LoRA trener), uređivanje profila, LoRA stack, način rada referenci (IP-Adapter / InstantID), Character Sheet, izvoz LoRA dataseta i LoRA trener. |
| **Video** | AnimateDiff video (kao u 1.0.20). |
| **Kalendar** | Mjesečni prikaz objava; nacrt, zakazivanje i objava na Instagram, Facebook, Telegram i Premium API. |
| **Inbox i CRM** | Jedinstveni inbox, način slanja (Automatsko slanje odmah / Nacrt za odobrenje), kontakti i memorija, narudžbe, analitika, izvori i webhook. |
| **Modeli** | Preuzimanje checkpointa, LoRA-a i čvorova; sekcija „Preporučene SDXL LoRA-e (realizam i detalji)”. |
| **Postavke** | Hardver i ComfyUI zastavice, ključevi (`data/.env`, maskirano), AI chat (LLM), ažuriranje. |

---

## 1a. Sučelje 1.2.0 (jednostavnije i modernije)

Izgled je prerađen, a funkcije su ostale iste: sve kontrole, prečaci i API-ji rade kao prije, samo su drugačije raspoređeni.

- **Tamna minimalistička tema**: mirna tamna podloga, kartice s tankim rubovima, jedan indigo naglasak, a zelena, narančasta i crvena samo za stvarna stanja (spojeno, upozorenje, greška). Gornja traka ima kartice s podcrtom, kompaktne statuse i izbornik influencera.
- **Generiranje – glavni ekran**: samo ono što treba za sliku.
  1. **Osoba**: avatari svih osoba i na vrhu opcija **Bez osobe** (za testiranje promptova: bez LoRA-e osobe, okidača i referenci lica; LoRA stack, VAE i ostale opće postavke i dalje vrijede). Odabrana ima obrub, zelena točka znači da osoba ima LoRA-u. Ispod piše „LoRA aktivna” / „Bez LoRA-e”, broj referentnih slika i kratki opis izgleda. „Uredi profil” vodi u karticu Osobe, a „+ Nova” otvara novi profil.
  2. **Opis scene**: veliko polje (Ctrl+Enter pokreće) i brzi stilovi.
  3. **Format** i **Brzina** (Turbo / Kvaliteta) kao mali gumbi, uz naziv aktivnog modela.
  4. **Generiraj**. Ispod je kratki red s 8 GB sigurnim modom, VAE načinom i GPU-om.
- **„Napredno”** je po zadanom zatvoreno. Kad je zatvoreno, u naslovu se vidi sažetak (model, predložak, sampler). Unutra su grupe:
  - **Model i stil**: model, LoRA i jačina, „Dodatno uz izgled”, težina opisa izgleda, broj slika, seed, negativni prompt, oznake kvalitete i napomene o formatu / Turbu / Krea 2.
  - **Dosljednost i detalji**: jačina referentne slike lica (IP-Adapter), Face Detailer, Hires fix.
  - **Parametri, predlošci, LoRA stack i red čekanja**: predložak sadržaja, sampler, scheduler, CFG, postavke Hires fixa, FreeU_V2, konzistentnost lica (InstantID / IP-Adapter i jačina InstantID-a), postavke Face Detailera, LoRA stack i serija u redu čekanja.
- **Osobe**: na vrhu su kartice osoba s brzim radnjama. Ispod lijevo je **Uređivanje profila** (ime, dob / vibe, izgled, referentne slike i osobnost na vrhu; „Model, LoRA i tehničke postavke” i „Stil poruka i chat” su sklopivi), desno LoRA stack, konzistentnost lica, Character Sheet i dataset, a na dnu **LoRA trener** u istom stilu.
- Ostale kartice (Pregled, Video, Kalendar, Inbox i CRM, Modeli, Postavke) imaju iste razmake, kartice, gumbe i polja.

---

## 1b. Novo u 1.3.0

### Profili kvalitete za RX 6600 (Generiranje → Kvaliteta i brzina)

| Profil | Što radi | Kad ga koristiti |
|---|---|---|
| **Realizam** (zadano) | SDXL: manja baza (npr. 768×960 za IG 4:5) + brzi drugi prolaz (hires 1,33×, denoise 0,35, 8 koraka), 24 koraka, CFG 4,3, dpmpp_2m_sde + karras. SD 1.5: CFG 5,0. | Najprirodnija koža i oštrina uz najmanje VRAM-a. |
| **Brzo** | 20 koraka, jedan prolaz, CFG 4,0, dpmpp_2m + karras, baza do 1024 px. | Brze probe kompozicije. |
| **Turbo 1024** | Hyper-SDXL LoRA, 8 koraka, CFG 2,2, euler + sgm_uniform, baza 1024 px, bez hiresa. Samo SDXL. | Najbrže (cilj ispod ~3 min po slici na RX 6600). |

- Profil popunjava samo polja koja nisi sam postavio: ručni CFG („Ručno”), sampler, koraci ili hires iz „Napredno” uvijek imaju prednost. Klik na profil postavi i polja u „Napredno” da vidiš što se koristi.
- **Prirodan izgled**: uz profil se na kraj prompta dodaju foto oznake (`candid photo, natural skin texture, visible pores, soft natural light, subtle film grain, 35mm photograph`), a zadani negativni prompt dobiva `plastic skin, airbrushed, overly smooth skin, waxy skin, doll-like, cgi, 3d render, oversaturated, overexposed, hdr`. Ako upišeš vlastiti negativni prompt, ostaje točno kakav jest.
- Zašto ne dpmpp_sde: on radi 2 prolaza modela po koraku, pa je na RX 6600 dvostruko sporiji.

### Napredno: 5 kartica s objašnjenjima

1. **Model i sampler**: model, LoRA osobe i jačina, sampler, scheduler, CFG (auto ili ručno), FreeU_V2 (po zadanom isključen), padajući izbornik **VAE** (Iz checkpointa, sdxl_vae, sdxl-vae-fp16-fix; vae-ft-mse-840000 samo za SD 1.5).
2. **Format i hires**: broj slika, Hires pass i njegove postavke (skala 1,2–1,6, denoise 0,25–0,5, koraci 4–16).
3. **Lice i konzistencija**: jačina referentne slike (IP-Adapter, od 0,2), klizač **Kraj utjecaja** (end_at, InstantID zadano 0,8 / IP-Adapter 1,0), Face Detailer (zadani denoise 0,25) i njegove postavke, InstantID jačina, **8 GB zaštita**.
4. **LoRA i detalji**: 1 klik SFW detail LoRA-e s klizačem jačine 0–1,5 (zadano: Prirodna koža 0,5 · Fini detalji 0,4 · Prirodni kontrast 0,35 · Realistična koža 0,5; preuzimaju se u Modeli → Preporučene SDXL LoRA-e, a ako nedostaju, preskaču se uz poruku). Uz uključenu Realističnu kožu Studio jednom doda okidač `Detailed natural skin and blemishes without-makeup and acne`. LoRA stack (do 5, jačina od −2 do 2) je isti i na glavnom ekranu Generiranja (odjeljak **LoRA**, gumb **+ Dodaj LoRA**) i stiže u workflow i kad Napredno nije otvoreno.
5. **Prompt, seed i ostalo**: Dodatno uz izgled, težina izgleda, seed, negativni prompt, oznake kvalitete, predložak sadržaja i serija u redu čekanja.

Uz svaku opciju je „?”: prijeđi mišem, fokusiraj tipkovnicom ili klikni za kratko objašnjenje (Escape zatvara).

**8 GB zaštita** (zadano uključena uz profile): hires se ograniči na ~1,35 MP (1,1 MP uz InstantID) ili preskoči kad je baza već blizu cilja; InstantID + Face Detailer + Hires na SDXL-u → hires isključen; uz SDXL + hires/InstantID generira se 1 slika po pokretanju (za više koristi red čekanja); VAE ide na tiled; Face Detailer denoise ≤ 0,5, guide ≤ 512, max ≤ 768, ≤ 12 koraka. Poruke o tome što je promijenjeno pojave se ispod gumba Generiraj.

### Ocjene Dobra / Loša → LoRA dataset

- Na svakoj novoj slici, u povijesti i u galeriji su gumbi **Dobra** i **Loša** (ponovni klik briše ocjenu). Galerija ima filtar **Sve / Dobra / Loša / Character sheet**.
- **Dobra** odmah doda sliku u LoRA dataset osobe kojoj slika pripada (bez duplikata). **Loša** ili brisanje ocjene makne tu sliku iz dataseta; ručno dodane slike i referentne slike ostaju.
- U LoRA treneru: kvačica „Slike ocijenjene „Dobra” automatski idu u dataset” (zadano uključena) i gumb **„Uvezi ocijenjene „Dobra””** (za slike ocijenjene dok je automatika bila isključena ili dok je trajao trening). Dok osoba trenira, njezin dataset se ne mijenja.
- Baza se nadograđuje sama (stupci `rating`, `rated_at`, indeks `idx_gallery_rating`); migracija je sigurna za ponovno pokretanje.

### Živa GPU traka

Tijekom generiranja (desno, iznad rezultata) i treniranja (u LoRA treneru) prikazuje se: **opterećenje GPU-a** u %, **temperatura** (zeleno do 80°C, žuto do 88°C, crveno iznad), **VRAM** zauzeto / ukupno i **trenutni korak**. Na Windowsu se čitaju GPU brojači (`Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine` i `GPUAdapterMemory`, isto što koristi Upravitelj zadataka), rezerva su amd-smi / rocm-smi / nvidia-smi, a VRAM iz ComfyUI-ja ima prednost. Mjerenje ide u pozadini s kešom od 2,5 s; ako brojač nije dostupan, piše „n/d”. API: `GET /api/gpu-live`.

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
- **Hires**: od 1.3.0 zadano 1,33×, denoise 0,35, 8 koraka (brzi drugi prolaz preko manje baze), dekodiranje preko `VAEDecodeTiled`; raspon u Napredno 1,2–1,6 / 0,25–0,5 / 4–16.
- **FreeU_V2**: po zadanom isključen (i na profilu Realizam). Parametri ako ga uključiš: b1 1,3 · b2 1,4 · s1 0,9 · s2 0,2.
- **VAE**: zadano „Iz checkpointa”. Za SDXL možeš odabrati `sdxl_vae.safetensors` ili `sdxl-vae-fp16-fix` (madebyollin); za SD 1.5 `vae-ft-mse-840000`. Preuzimanje je u kartici Modeli → „VAE (dekoder slike)”. Odabrani VAE ide u sve VAEDecode/VAEEncode čvorove i u Face Detailer.
- **Face Detailer** (Impact Pack + Subpack): zadani denoise 0,25 (klizač i dalje od 0,1). Kad je InstantID uključen, Face Detailer prima isti positive/negative kao i KSampler (izlaz ApplyInstantID). Ako čvorovi nisu instalirani, predlošci ga preskoče umjesto da javljaju grešku.
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

Galerija prikazuje sve slike iz reda, filtrira ih po osobi, ocjeni (Sve / Dobra / Loša) i izvoru, a slike se učitavaju lijeno („Učitaj još”). Ocjene **Dobra** i **Loša** daješ izravno na slici ili u lightboxu; „Dobra” ide u LoRA dataset osobe (vidi 1b).

---

## 4. Osobe (persone)

- Sve osobe su **fiktivne odrasle osobe**. Prompt uvijek počinje s `adult woman, <dob>` (dob 18+), a `child, teen` i slični pojmovi su uvijek u negativnom promptu. Ne koristi lica stvarnih ljudi.
- **LoRA stack** po osobi (do 5) s jačinama.
- **Način referenci**: IP-Adapter ili InstantID, s jačinom InstantID-a.
- **Način slanja po osobi** za CRM (naslijedi / automatsko / nacrt).
- **Character Sheet 2×2**: četiri kadra (sprijeda, tri četvrtine, profil, vani candid) s istim seedom, spojeno u jednu PNG sliku (Pillow, ili čisti Python ako Pillow nije dostupan).
- **Izvoz LoRA dataseta**: slike ocijenjene kao „Dobra” idu u `data/lora_datasets/<osoba>_<vrijeme>/` s caption .txt datotekama, `UPUTE.txt` i konfiguracijama `kohya_sdxl_lora_8gb.json` i `onetrainer_sdxl_lora_8gb.json`, prilagođenima za 8 GB (batch 1, gradient checkpointing, mixed precision).


### 4a. LoRA trener (Osobe → LoRA trener)

Vlastita LoRA lica osobe, istrenirana izravno u Studiju i prilagođena za **RX 6600 (8 GB) + ComfyUI-Zluda**.

1. **Odaberi osobu**: vidi se trenutna LoRA, okidač (npr. `chr_ana`) i istrenirane verzije (gumb „Koristi ovu”).
2. **Dodaj 15–40 slika**: povuci slike, „Odaberi slike” ili „Uvezi iz galerije osobe” (referentne slike + slike ocijenjene „Dobra”). Brojač je zelen kod 15–40 („Idealno”), žut ispod 15 ili iznad 40, a ispod 5 ili iznad 60 treniranje nije moguće. Studio sam ispravi EXIF rotaciju, pretvori u RGB, odbaci slike manje od 256 px i duplikate, izreže kvadrat (SDXL 768, SD 1.5 512, SDXL 1024 opcionalno) i napiše opis za svaku sliku (`<okidač>, adult woman, <dob> years old, izgled, kadar, svjetlo`). Opisi se mogu urediti pod „Pregled opisa”.
3. **Pokreni treniranje**: profili **Brzo**, **Preporučeno** (zadano, za RX 6600) i **Detaljno** kao pill gumbi i jedan gumb „Pokreni treniranje”. Oznaka spremnosti pokazuje je li dataset spreman (15–40 slika), a brojač koliko je slika iz ocjena „Dobra”, a koliko ručno dodano. Pod „Napredno”: bazni model, rezolucija, rank, epohe, koraci i temperatura auto-stopa.

**Sigurne postavke za 8 GB (uvijek uključene):** batch 1, fp16, gradient checkpointing, cache latents na disk (SDXL i izlazi text encodera na disk, trenira se samo UNet), network dim 16 / alpha 8, Adafactor (`scale_parameter=False, relative_step=False, warmup_init=False`), `constant_with_warmup`, SDPA (nikad xformers), `no_half_vae`, bez bitsandbytes. Okruženje treninga: `TORCH_BACKENDS_CUDNN_ENABLED=0`, `PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:128`, `PYTHONUTF8=1`. Prije starta Studio pozove ComfyUI `/free` (istovari modele), a dok trening traje generiranje slika i videa čeka (HTTP 409 / red čekanja stoji). Istovremeno može raditi samo jedno treniranje.

**Temperatura GPU-a:** čita se preko AMD ADL-a (atiadlxx.dll), zatim LibreHardwareMonitor / OpenHardwareMonitor WMI (ako je pokrenut), pa amd-smi / rocm-smi / nvidia-smi; na Linuxu sysfs. Ako se ne može pročitati, piše „Senzor temperature nedostupan” (bez izmišljenih brojeva). Na 80°C upozorenje, na 88°C kritično, na 92°C (podesivo) treniranje se automatski zaustavlja sa statusom „Zaustavljeno zbog temperature”.

**Okruženje:** gumb „Pripremi okruženje za treniranje” jednom preuzme kohya-ss/sd-scripts (v0.13.1) u `data/trainer/sd-scripts` i napravi zaseban venv `data/trainer/venv` koji koristi PyTorch (ZLUDA) iz ComfyUI-ja, tako da se ComfyUI paketi ne mijenjaju. bitsandbytes i xformers se preskaču.

**Rezultat:** `ComfyUI/models/loras/char_<osoba>_vN.safetensors` (ako ComfyUI mapa ne postoji: `data/trained_loras`). LoRA se automatski postavi kao LoRA osobe (jačina 0.8) i okidač se sam dodaje u prompt kad generiraš s tom osobom. Svaka osoba ima svoju mapu (`data/lora_training/persona_<id>/`), svoj okidač i svoje verzije. „Zaustavi” gasi cijelo stablo procesa (Windows `taskkill /F /T`). Ne zatvaraj Studio dok traje treniranje: gašenje Studija zaustavlja trening.

---

## 5. Preporučene SDXL LoRA-e (realizam i detalji)

Sve su SFW i služe samo za kvalitetu slike. Idu u `models\loras`. Skin Realism se preuzima s Civitaija; ako preuzimanje zatraži prijavu, upiši `CIVITAI_TOKEN` u `data/.env` (ključ s https://civitai.com/user/account).

| LoRA | Datoteka | Veličina | Preporučena jačina |
|---|---|---|---|
| Photorealistic slider (ostris) | ostris_photorealistic_slider_xl.safetensors | ~24 MB | 0,5–1,5 |
| Extremely detailed (ntc-ai) | ntc_extremely_detailed_xl.safetensors | ~9 MB | 0,5–1,5 |
| Cinematic lighting (ntc-ai) | ntc_cinematic_lighting_xl.safetensors | ~9 MB | 0,5–1,5 |
| Offset noise (Stability AI) | sdxl_offset_example_lora_1.0.safetensors | ~50 MB | 0,3–0,6 |
| Nice hands (ntc-ai) | ntc_nice_hands_xl.safetensors | ~9 MB | 0,5–1,5 |
| Detail Tweaker XL | add_detail_xl.safetensors | ~228 MB | 0,5–1,5 |
| Realistična koža (Skin Realism) | skin_realism_xl.safetensors | ~218 MB | 0,3–0,7 |

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
- **Out of memory**: ostavi uključenu 8 GB zaštitu (Napredno → Lice i konzistencija), koristi profil Realizam ili Turbo, smanji hires skalu ili isključi Face Detailer.
- **GPU traka pokazuje „n/d”**: Windows GPU brojači nisu dostupni (stari driver ili isključene performanse) i nema amd-smi; generiranje radi normalno.
- **Instagram javlja grešku s URL-om**: `PUBLIC_MEDIA_BASE_URL` mora biti javni HTTPS tunel koji radi.
- **InstantID / Face Detailer bedž je siv**: čvorovi nisu učitani; instaliraj ih u kartici Modeli i restartaj ComfyUI.
- **LoRA trener javi out of memory**: zatvori druge programe koji koriste GPU, ostavi 768 (SDXL) / 512 (SD 1.5), probaj „Brzi test” ili rank 8.
- **LoRA trener: „Zaustavljeno zbog temperature”**: provjeri ventilatore i protok zraka; prag auto-stopa je pod „Napredno”.

---

## 10. Za razvoj

- Struktura: `studio.py` (HTTP server), `api_v11.py` (1.1 API), `api_lora.py` (`/api/lora-trainer/*`), `services/` (hardware, generation, posting, crm, lora_trainer), `static/v11.js`, `static/v11.css`, `static/lora_trainer.js`, `static/lora_trainer.css` te `static/ui_v120.css` i `static/ui_v120.js` (izgled 1.2.0: avatari osoba, kartice osoba, sažetak „Napredno”) i `static/ui_v130.css` / `static/ui_v130.js` (1.3.0: glass tema, puna širina, ? objašnjenja, profili kvalitete, živa GPU traka; učitavaju se zadnji).
- Testovi: `python3 tools/test_v110.py`, `python3 tools/test_lora_trainer.py` , `python3 tools/test_ui_v120.py`, `python3 tools/test_v130.py` i `python3 tools/test_ui_v130.py` (uz `PW_PYTHON=/tmp/pwenv/bin/python` za headless UI; `UI_V130_SHOTS=/mapa` sprema snimke zaslona), te `python3 tools/check_ui_js.py`. LoRA trener se testira bez GPU-a: `STUDIO_LORA_TRAINER_CMD` (lažni trener `tools/fixtures/fake_lora_trainer.py`), `STUDIO_GPU_TEMP` / `STUDIO_GPU_TEMP_FILE` za temperaturu, `STUDIO_GPU_USAGE`, `STUDIO_GPU_VRAM_USED_MB` i `STUDIO_GPU_VRAM_TOTAL_MB` za živu GPU traku.
- Izdanje: `bash tools/make_release.sh minor "opis"`.

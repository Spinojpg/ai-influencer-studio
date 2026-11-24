# AI Influencer Studio — handoff za Claudea

**Datum:** 24. studenoga 2026. (Europa/Zagreb, UTC+1) — dopunjeno nakon izdanja v1.3.0  
**Repo:** privatni GitHub `Spinojpg/ai-influencer-studio` (grana `main`)  
**Objavljena verzija aplikacije:** **v1.3.0** (commit `3d5b0aac0dbe61be4ef78ed3b37973739299d16c`, tag `v1.3.0`) — RX 6600 profili kvalitete i brzine, grupirano Napredno s objašnjenjima, živa GPU traka, ocjene Dobra/Loša → LoRA dataset, widescreen glass redizajn.  
**studio.zip sha256 (v1.3.0):** `d572441e05d41bbcf680cb7588af3f06a4c8cd54829b9d6da5599df7f01b7afd` (718 510 bajtova, 89 datoteka)  
**Izdanje:** https://github.com/Spinojpg/ai-influencer-studio/releases/tag/v1.3.0  
**main:** release commit `3d5b0aa` (tag v1.3.0) + odmah iza njega dokumentacijski commit s ovim `HANDOFF.md` (bez izmjena koda). Detalji: poglavlje 10.9 (prethodno izdanje v1.2.0: 10.8).

Ovaj dokument je sastavljen da Claude može privremeno preuzeti posao na aplikaciji dok Sven nema usage na Grok Botu. **Kod u repou ima prednost nad ovim sažetkom.** Ako se nešto ne slaže, vjeruj kodu (`DOKUMENTACIJA.md`, `services/`, `api_v11.py`, `image_gen.py`, `video.py`, `static/v11.js`).

Ovaj `HANDOFF.md` živi u korijenu repoa, ali **ne ide u `studio.zip`** (`tools/make_release.sh` ga isključuje). Isto vrijedi za `tools/setup_dev_windows.ps1`. To ne mijenja rad aplikacije. Nikad ne commitaj `data/.env`, tokene, ključeve ni tajne; Sven ih nikad ne lijepi u chat.

Kako Grok i Claude rade na istom repou, tko smije raditi release i koje su razvojne putanje, vidi **poglavlje 10. Suradnja Grok + Claude**.

---

## 1. Prompt za početak razgovora s Claudeom

Kopiraj sve između crta i zalijepi kao prvu poruku.

-----

Ti preuzimaš razvoj i održavanje aplikacije **AI Influencer Studio**, lokalnog Windows studija za fiktivne odrasle AI influencere. Vlasnik je **Sven Benko**. Do sada je posao radio Grok Bot; Sven je ostao bez usagea pa te privremeno koristi. Imaš isti pristup: privatni GitHub repo `Spinojpg/ai-influencer-studio` i njegov PC.

Najprije pročitaj `HANDOFF.md` u korijenu repoa (ovaj dokument, uključujući **poglavlje 10. Suradnja Grok + Claude**), zatim `DOKUMENTACIJA.md`, `.env.example`, `CHANGELOG.md`, `version.json` i `tools/make_release.sh`. Kod ima prednost nad handoffom. Objavljena verzija aplikacije je **v1.3.0** (tag/commit `3d5b0aa`). Na `main` mogu biti noviji dokumentacijski commiti bez bumpa verzije — provjeri `git log` i poglavlje 10.

**Tko je Sven i kako komuniciraš**
- Odgovaraj na **hrvatskom**, ležernim tonom, na „ti“.
- Windows PC: AMD RX 6600 (8 GB VRAM), Ryzen 7 5700X, 16 GB RAM 3200 MHz, Brave, više monitora, Starlink. Windows korisnik `svenb` (`C:\Users\svenb`). Živi blizu Jastrebarskog.
- GitHub račun: **Spinojpg**.
- **Obavezno pravilo:** prije svakog novog zadatka/prompta kratko procijeni koliko bi to bilo posla (trud / usage) i **nemoj ništa raditi dok Sven eksplicitno ne potvrdi**. Rekao je: „Nemoj nista raditi ako ti ja ne potvrdim.“

**Okruženje**
- ComfyUI-Zluda je u `C:\ComfyUI-Zluda`, pali se s `comfyui-n.bat`. Obavezno: `TORCH_BACKENDS_CUDNN_ENABLED=0` (inače ZLUDA zapne na „Compilation is in progress“).
- Instalirana aplikacija: `%LOCALAPPDATA%\AIInfluencerStudio\` (kod u `app\`, podaci u `data\`). Logovi: `data\logs\comfyui.log`, `studio.log`, `launcher.log`, `updater.log`.
- Tajne stoje samo u `data\.env` na njegovom PC-u. Nikad ne traži da ih lijepi u chat.
- Studio se sam ažurira s GitHub Releases pri paljenju ili preko gumba „Provjeri update“.
- Razvojni checkout na Svenovom Windowsu: `C:\Users\svenb\dev\ai-influencer-studio` (nije instalacijska mapa). Priprema: `tools/setup_dev_windows.ps1`, zatim po potrebi `gh auth login` (on sam, bez lijepljenja tokena).
- Rad na kodu na Grokovom računalu (box): `/workspace/simple-studio`. `gh` je tamo prijavljen kao Spinojpg.
- Na jednom zadatku radi samo jedan agent; prije rada `git pull`, nakon rada `push`. Release radi samo agent koji je napravio izmjenu. Detalji: poglavlje 10.

**Što je gotovo**
v1.2.0 je objavljen 24. 11. 2026.: **character LoRA trener** u kartici Osobe (RX 6600, 8 GB, ZLUDA; 15–40 slika, automatska priprema, sigurne 8 GB postavke, praćenje napretka i temperature, gotova LoRA se sama doda osobi) i **pojednostavljeno, modernizirano sučelje** (glavni ekran: osoba + scena + Generiraj, sve tehničko u zatvorenom „Napredno”, kartice osoba). v1.1.0 (20. 11.) je donio `services/`, kartice, hardver/RX 6600, predloške, red čekanja, galeriju, Kalendar, Inbox i CRM; v1.0.20 SDXL AnimateDiff motion module. Ništa od toga **nije** još potvrđeno na njegovom Windowsu — čekamo feedback i logove ako nešto pukne.

**Što je otvoreno — ne počinji bez potvrde**
LoRA trener i pojednostavljenje UI-ja su **gotovi u v1.2.0**. Otvoreno: test v1.2.0 na Windowsu, prvo stvarno treniranje na RX 6600 (priprema sd-scripts venva), provjera očitanja temperature AMD GPU-a, Instagram setup, opcijski xAI ključ, ideja „Dodatni ComfyUI“ za dijeljenje poslova na dva PC-a, poznati nedostatak da odabir predloška vizualno ne popuni kontrole forme.

**Pravila sadržaja (dogovoreno sa Svenom)**
- Osobe su samo odrasle i fiktivne: prompt počinje s `adult woman, <dob>` (18+); `child, teen` idu u negativni prompt. Samo izmišljena lica, ne lica stvarnih ljudi.
- Ugrađeni predlošci, zadani chat promptovi i kurirane LoRA-e ostaju SFW.
- **Ne** uvodi filter ključnih riječi na njegove vlastite promptove, workflowe ili lokalne LoRA-e. On ima punu kontrolu nad onime što sam ubaci.
- CRM način slanja može biti „Automatsko slanje odmah“; zadano je „Nacrt za odobrenje“, prekidač je već u v1.1.0.

**Izdanja**
Postupak je strogo: testovi, pa `bash tools/make_release.sh patch|minor "bilješke"`, commit, `git push origin HEAD:main`, zatim `gh release create`. Detalji su u `HANDOFF.md`. Nemoj raditi release dok te Sven ne zamoli.

Ako trebaš kontekst, pitaj. Nemoj nagađati tajne ni dirati `data/` korisnika.

-----

---

## 2. Tko je Sven i pravila rada

- Ime: **Sven Benko**. Piše ležerni hrvatski (često bez dijakritika); odgovaraj na hrvatskom, na „ti“, jasno i bez suvišnog formalizma.
- GitHub: **Spinojpg**. Privatni repo aplikacije: `Spinojpg/ai-influencer-studio`.
- Windows korisnik: `svenb` (`C:\Users\svenb`).
- Živi blizu Jastrebarskog (Čeglje), Hrvatska. Vremenska zona: **Europa/Zagreb**.
- Hardver i okolina:
  - Windows
  - AMD **RX 6600, 8 GB VRAM**
  - Ryzen 7 5700X
  - 16 GB RAM, 3200 MHz
  - Brave, više monitora; aplikacija se mora otvarati u Braveu na **Display 1** (glavni monitor)
  - Starlink (obično 200+ Mbps)
- Ima i laptop (spominjao 64 GB RAM + RTX 4070 Laptop) — nije glavni stroj za Studio; glavni je desktop s RX 6600.

**Pravilo potvrde (i dalje na snazi):**  
Prije rada na novom promptu/zadatku kratko reci koliko bi to otprilike bilo posla. **Ne radi ništa dok on ne potvrdi** (npr. „ok napravi stavku 2“, „napravi oboje“, „kreni“). To je eksplicitno zatražio.

**Sigurnost:** Sven **nikad** ne lijepi tokene ni ključeve u chat. Tajne žive u `data\.env` na njegovom PC-u (nakon instalacije: `%LOCALAPPDATA%\AIInfluencerStudio\data\.env`). U sučelju su maskirane. Ne ispisuj ih u logove. `GITHUB_TOKEN` (fine-grained, samo ovaj repo, Contents: Read-only) služi auto-updateu s privatnog repoa; upute su u `TOKEN_UPUTE.txt`, bez da ikad tražiš da token zalijepi ovdje.

---

## 3. Okruženje i putanje

### ComfyUI

- Instalacija: `C:\ComfyUI-Zluda`
- Pokretanje: `comfyui-n.bat` (Studio pravi wrapper `comfyui-studio.bat` iz njega, bez `--auto-launch`; original se ne dira)
- **Obavezno za RX 6600 + ZLUDA:** `TORCH_BACKENDS_CUDNN_ENABLED=0` prije paljenja. Bez toga ComfyUI zna zauvijek visjeti na „Compilation is in progress“. U Postavkama je to kvačica „Isključi cuDNN“ i ostaje uključena.
- ComfyUI sluša na `:8188`. Studio na `http://127.0.0.1:7860`.
- Za AMD/ROCm: `HSA_OVERRIDE_GFX_VERSION=10.3.0` (RX 6600 = gfx1032). Zadano u `services/hardware_service.py` (`DEFAULT_ROCM_GFX`).

### Instalacija Studija na Windowsu

- Aplikacija: `%LOCALAPPDATA%\AIInfluencerStudio\app`
- Podaci (ne diraju se pri updateu): `%LOCALAPPDATA%\AIInfluencerStudio\data\`
  - `studio.db` (SQLite)
  - `.env` (tajne)
  - `profiles/`, `outputs/`, `uploads/`, `lora_datasets/`
  - `logs\` — **comfyui.log**, **studio.log**, **launcher.log**, **updater.log**
- Auto-update: pri paljenju ili gumb „Provjeri update“. Skida `studio.zip` + `studio.zip.sha256` s GitHub Releases, primjenjuje iz helper procesa, s backupom i rollbackom. Korisnički `data` ostaje netaknut.

**Tri putanje — ne miješaj ih**

- **Instalirana aplikacija** (to **nije** git checkout): `%LOCALAPPDATA%\AIInfluencerStudio\app`. Odatle se ne radi razvoj, commit ni release. Ne kloniraj repo u tu mapu.
- **Razvojni checkout na Svenovom Windowsu:** `C:\Users\svenb\dev\ai-influencer-studio`, grana `main`. Priprema jednom preko `tools/setup_dev_windows.ps1` (skripta sama klonira ili napravi `git pull --ff-only`, provjeri alate, testove i ovisnosti za `make_release.sh`, i piše izvještaj u `C:\Users\svenb\dev\setup_report.txt`). Ako `gh` nije prijavljen, Sven sam pokrene `gh auth login`.
- **Checkout na Grokovom računalu (box):** `/workspace/simple-studio`. Nakon releasea obično se osvježi i `/workspace/simple-studio.zip`.

Ako nešto na Windowsu ne radi, prvo traži te logove — ne nagađaj.

---

## 4. Posao koji Claude preuzima

Ovo je cijeli posao koji je Grok Bot radio na ovom projektu, i koji sada preuzimaš. Nisi tu samo za jedan feature: održavaš aplikaciju, gradiš što Sven potvrdi, objavljuješ izdanja, debuggiraš s njegovog Windowsa, pomažeš oko modela/LoRA-a/workflowa i postavljanja objava/CRM-a, i odgovaraš na pitanja. **Nijedan novi feature se ne počinje bez njegove potvrde.**

### 4.1 Odgovornosti (stalni posao)

1. **Održavanje aplikacije**  
   Kod je u privatnom repou `Spinojpg/ai-influencer-studio`, grana `main`. Lokalni rad: na boxu `/workspace/simple-studio`, na Svenovom PC-u `C:\Users\svenb\dev\ai-influencer-studio`. Ne commitaj korisničke podatke, `.env`, bazu ni `dist/`. `HANDOFF.md` i `tools/setup_dev_windows.ps1` ostaju u repou, ali ne u `studio.zip`. Pravila suradnje: poglavlje 10.

2. **Izrada značajki**  
   Kad Sven potvrdi zadatak: implementiraj, uskladi UI (`index.html`, `static/v11.js`, `static/v11.css`, `static/ui_v120.css`/`.js`, `static/lora_trainer.*`) i backend (`studio.py`, `api_v11.py`, `services/`, postojeći moduli), dopuni `DOKUMENTACIJA.md` / `CHANGELOG.md` po potrebi, napiši ili proširi testove, pa idi na tok izdanja (poglavlje 6).

3. **Izdanja**  
   Strogo prati postupak u poglavlju 6. Ne radi release „usput“ i ne bumpaj verziju bez namjere da ide na GitHub Releases (jer se auto-update hrani time). Nakon `gh release create` korisnik na Windowsu dobiva update u aplikaciji.

4. **Debugging s Windowsa**  
   v1.2.0, v1.1.0 i v1.0.20 **još nisu potvrđeni** na njegovom PC-u. Ako nešto pukne, zatraži relevantne logove (`comfyui.log`, `studio.log`, `launcher.log`, `updater.log`) i točan korak koji je radio. Tipične stvari: ZLUDA/cuDNN visak, OOM na 8 GB, čvorovi koji se nisu učitali, updater koji nije zamijenio datoteke, prazno sučelje zbog JS greške (zato `tools/check_ui_js.py` mora proći prije pakiranja).

5. **Modeli, LoRA-e i workflowi**  
   Kartica Modeli već umije preuzeti checkpointe, LoRA-e, čvorove i AnimateDiff motion module. Pomozi mu oko odabira i 8 GB postavki, instalacije čvorova (IP-Adapter, InstantID, Impact Pack, AnimateDiff-Evolved, VHS) i vlastitih LoRA-a/workflowa. Ne cenzuriraj ono što sam ubaci. Ugrađene preporuke i predlošci ostaju SFW. Osobe uvijek odrasle i fiktivne.

6. **Objave i CRM setup**  
   Instagram/Facebook (Meta Graph), Telegram, Premium API, webhook, tunel za `PUBLIC_MEDIA_BASE_URL`. Ključeve unosi on sam u Postavke ili `data\.env`. Možeš ga voditi korak po korak, ali **ne** traži da token zalijepi u chat. CRM chat radi i bez xAI-ja (Ollama, LM Studio / OpenAI-compat, ili način „pravila“).

7. **Odgovaranje na pitanja**  
   Objašnjavaj arhitekturu, modele, hardver, prompt/encoder, video, CRM itd. na hrvatskom. Nedavno je pitano: koji encoder pretvara prompt u ono što model vidi (CLIP / ConditioningConcat / Krea CLIPLoader); što je Qwen3.8-Flash-Next i stane li na laptop 64 GB + RTX 4070 — realno ne (preporuka za CRM: lokalni 14–32B Qwen preko Ollame ili LM Studija). Ta Q&A pitanja su odgovorena; nisu otvoreni zadaci za kod.

### 4.1a Što je napravljeno nakon prvog handoffa (bez releasea)

- 22. 11. 2026.: u repo dodani ovaj dokument (prvi `HANDOFF.md`) i kasnije **poglavlje 10** plus `tools/setup_dev_windows.ps1`. Nema bumpa verzije, nema `gh release create`, kod aplikacije nije diran. Objavljena verzija i dalje je v1.1.0.
- Cilj te pripreme: Claude na Svenovom PC-u dobije isti razvojni tok (checkout izvan instalacijske mape, git/gh, testovi, `make_release.sh` pod Git Bashom) i da oba agenta objavljuju izdanja preko GitHub Releases, ali **ne istovremeno** i uz obavezan `git pull` + `gh release list` prije releasea.

- 24. 11. 2026.: Sven je potvrdio oboje („radi slobodno … sam delaj“). Grok je napravio **LoRA trener** (commit `d15422f`) i **pojednostavljeno sučelje**, pa objavio **v1.2.0** (commit `127e98d`). Detalji u 4.2 A i 10.8.
- 24. 11. 2026.: Sven je naručio i potvrdio („Kreni i odradi sve odjednom kao v1.3.0“) kvalitetu/brzinu za RX 6600, grupirano Napredno s objašnjenjima, widescreen redizajn, jednostavniji LoRA trening preko ocjena Dobra/Loša i GPU info. Grok je objavio **v1.3.0** (commit `3d5b0aa`). Detalji u 4.2 J i 10.9.

### 4.2 Otvorene i čekajuće stavke — status i kako nastaviti

#### A) LoRA trener + pojednostavljenje UI-ja — **GOTOVO, objavljeno u v1.2.0** (čeka test na Windowsu)

**Stavka 1 — character LoRA trener (commit `d15422f`)**
- `services/lora_trainer_service.py`, `api_lora.py` (`/api/lora-trainer/*`), `static/lora_trainer.js`/`.css`, kartica Osobe → LoRA trener (3 koraka).
- Dataset po osobi (15–40 slika: upload, povuci-ispusti, uvoz iz galerije osobe), Pillow priprema (EXIF, RGB, izrez 768/512), opisi s okidačem i „adult woman”, Kohya struktura.
- Sigurne 8 GB postavke: batch 1, fp16, gradient checkpointing, cache latents na disk, Adafactor, SDPA bez xformersa/bitsandbytes, cuDNN=0. Profili Brzi test / Preporučeno za RX 6600 / Detaljnije, ostalo pod „Napredno”.
- Praćenje: korak, epoha, ETA, loss, log, temperatura GPU-a (ADL / LibreHardwareMonitor / smi alati; bez lažnih brojeva), upozorenje 80°C, auto-stop 92°C.
- Gotova LoRA `char_<osoba>_vN.safetensors` ide u `ComfyUI/models/loras` i sama se doda osobi (0.8 + okidač). Generiranje čeka dok trening traje.
- Jednokratna priprema okruženja: kohya sd-scripts v0.13.1 u `data/trainer`, venv koji koristi PyTorch iz ComfyUI-Zlude.

**Stavka 2 — pojednostavljeno, modernizirano sučelje (commit `127e98d`)**
- Samo izgled i raspored: svi ID-jevi, događaji i API-ji su isti (provjerava `tools/test_ui_v120.py` + svi stari testovi).
- `static/ui_v120.css` (učitava se zadnji): tamna tema `#0b0d12`, kartice `#12161f`/`#171c28`, tanki rubovi, jedan indigo naglasak `#7c8cff`, semantičke boje samo za stanja; stari „zlatni” naglasak prebačen u indigo i u `index.html`/`v11.css`/`lora_trainer.css`. Globalno `[hidden] { display: none !important; }`.
- `static/ui_v120.js` (samo prikaz, koristi `window.StudioCore`): avatari osoba na Generiranju (klik postavlja `#osoba` i šalje `change`), status „LoRA aktivna / Bez LoRA-e” + broj ref. slika, sažetak u naslovu „Napredno”, kartice osoba u Osobama (Generiraj / Uredi / LoRA trener — „Uredi” klikne skriveni red u `#profileList`, pa sve staro radi), automatsko učitavanje aktivne osobe u prazan obrazac.
- Generiranje: glavni ekran = osoba (avatari) + opis scene + brzi stilovi + format + brzina + Generiraj + mali hardverski red. `<details class="adv">` „Napredno” (zatvoreno) ima grupe *Model i stil* (model, LoRA, Dodatno uz izgled, težina izgleda, broj slika, seed, negativni prompt, kvaliteta, napomene), *Dosljednost i detalji* (IP-Adapter jačina, Face Detailer, Hires fix) i ugniježđeni `#v11GenBox` (predložak, sampler, scheduler, CFG, hires parametri, FreeU, InstantID, Face Detailer postavke, LoRA stack, serija u redu čekanja).
- Osobe: kartice osoba; obrazac s osnovnim poljima na vrhu (ime, dob/vibe, izgled, referentne slike, osobnost), sklopivo „Model, LoRA i tehničke postavke” (`#pfTech`) i „Stil poruka i chat” (`#pfChat`); desno `#v11Persona`; dolje LoRA trener.
- Testna ograničenja za daljnji UI rad: `test_v112` traži da su `#activeModelLine` i `#go` prije prvog `<details class="adv">` (točno taj string, bez dodatnih atributa); `test_v109`/`test_v114` traže model/seed/negativni/kvaliteta/hires unutar tog bloka i `#lora` između `id="model"` i „Broj slika”; `test_v117` traži „IG Portret” u vidljivom tekstu (zato je `#sizes` na glavnom ekranu); `test_v110` čita `#v11HwQuick` innerText (zato je izvan zatvorenog „Napredno”).

**Što još treba (otvoreno):** test v1.2.0 na Windowsu (izgled u Braveu, auto-update s v1.1.0), prvo stvarno treniranje na RX 6600 (gumb „Pripremi okruženje za treniranje”, provjera da venv vidi ZLUDA PyTorch, OOM / vrijeme po profilu), provjera očitanja temperature AMD GPU-a (ADL / LibreHardwareMonitor; bez senzora UI kaže da senzor nije dostupan). Sitnica: trener na prazan dataset zove `/api/lora-trainer/plan` koji vrati 400 (samo crveni zapis u konzoli preglednika, UI radi).

#### B) „Dodatni ComfyUI“ — dijeljenje poslova na dva PC-a — **samo ideja, nije početo**

Ponuda: opcija da se poslovi šalju i na drugi ComfyUI (npr. laptop s RTX 4070), ne samo na `C:\ComfyUI-Zluda`. Treba mrežno dostupan drugi ComfyUI i njegov GPU. Sven to još nije potvrdio.

Kako nastaviti: ako zatraži, procijeni, potvrdi, zatim Postavke (URL/port drugog Comfyja), red čekanja koji umije poslati posao na odabrani backend, jasne greške ako je drugi stroj ugašen. Ne počinji sam.

#### C) Instagram setup — **i dalje otvoreno, čeka Svena**

Kod za Graph API već postoji (container `/media` pa `media_publish`; slika mora biti na javnom HTTPS URL-u preko `PUBLIC_MEDIA_BASE_URL`, npr. cloudflared/ngrok tunel na `:7860`; Studio dijeli samo sliku te objave preko `/public/media/<id>/<token>`). Treba Business/Creator račun spojen na Facebook Page, Meta app, i ključevi u `.env`: `META_ACCESS_TOKEN`, `META_IG_USER_ID`, `META_FB_PAGE_ID`, `PUBLIC_MEDIA_BASE_URL`, po potrebi i Messaging (`IG_VERIFY_TOKEN`, `IG_APP_SECRET`, `IG_ACCESS_TOKEN`).

Kako nastaviti: vodi ga kroz Postavke i `.env.example` / `DOKUMENTACIJA.md` poglavlje 6 i 8. On unosi tajne kod sebe. Kad zapne, traži poruku greške iz UI-ja/logova, ne token.

#### D) Treniranje face LoRA-e — **ugrađeno u v1.2.0 (LoRA trener), čeka prvi stvarni trening na RX 6600**

Konzistentnost lica već ima: do 8 referentnih slika, IP-Adapter Plus Face, InstantID, LoRA stack po osobi, Character Sheet 2×2, izvoz dataseta iz ocjena „Dobra“. Od v1.2.0 treniranje radi u aplikaciji (Osobe → LoRA trener, vidi 4.2 A). Izvoz dataseta za vanjski Kohya/OneTrainer i dalje postoji.

#### E) xAI ključ za CRM chat — **opcijski, nije postavljen**

CRM radi bez njega: `auto` ide Ollama → LM Studio/OpenAI-compat → xAI → pravila. Način „pravila“ omogućuje simulaciju bez ključa. Ako želi Grok u CRM-u, sam upisuje `XAI_API_KEY` i `XAI_MODEL` (u `.env.example` je predložen `grok-4`) u Postavkama. Ne lijepi ključ u chat. Nije blokirajuće za ostali rad.

#### F) Feedback s Windowsa za v1.2.0, v1.1.0 i v1.0.20 — **čeka Svena**

Ako javi da nešto ne radi: verzija iz `version.json` (vidi se u UI-ju), što je kliknuo, i logovi. Za video: je li skinut pravi motion modul (`mm_sd_v15_v2` vs `mm_sdxl_v10_beta`). Za OOM: 8 GB siguran način, tiled VAE, manji hires, isključiti Face Detailer; za SDXL video 512×512, max 16 sličica (zadano 12).

#### G) Poznati nedostatak: predložak ne popunjava formu — **poznato, nije zasebno naručeno**

Odabir predloška primijeni vrijednosti na serveru pri generiranju, ali kontrole u formi vizualno ne skoče na te vrijednosti. Nije dirano u v1.2.0 (zadatak je bio samo izgled). Popravi uz njegovu suglasnost ili ako to posebno zatraži.

#### H) Ocjenjivanje Dobra/Loša — **već u v1.1.0, u v1.3.0 spojeno s LoRA datasetom**

Implementirano (galerija, lightbox, a od 1.3.0 i gumbi izravno na novim slikama i povijesti). Od 1.3.0 „Dobra” automatski ide u LoRA dataset osobe. Ne radi ponovno.

#### J) v1.3.0 — kvaliteta/brzina RX 6600, Napredno, redizajn, ocjene → LoRA, GPU traka — **GOTOVO, objavljeno** (čeka test na Windowsu)

- **Profili** (`services/generation_service.py` `RX_PROFILES`, `prepare_rx6600`): realism (zadano; 24 koraka, CFG 4,3 SDXL / 5,0 SD1.5, dpmpp_2m_sde+karras, manja baza `rx_base_for` npr. 768×960 + hires 1,33× / 0,35 / 8 koraka), fast (20, dpmpp_2m, bez hiresa), turbo (Hyper-SDXL 8 koraka, CFG 2,2, euler+sgm_uniform, baza 1024, samo SDXL). Profil je opt-in na serveru (`quality_profile` u payloadu) i popunjava samo polja koja klijent nije poslao. UI klikom na profil postavi i polja u Napredno; pri prvom učitavanju jednom primijeni Realizam (`localStorage studio_v130_profile_applied`).
- **Prirodan izgled** (`image_gen.py` `NATURAL_QUALITY`/`NATURAL_NEGATIVE`, `build_positive_prompt(quality_text=)`): foto oznake na kraj prompta, „plastic skin…” u zadani negativni; korisnikov vlastiti negativni prompt se ne dira.
- **8 GB zaštita** (`VRAM_GUARD`, `vram_guard()`), **detail LoRA-e** (`DETAIL_LORA_PRESETS`: skin/detail/light, SFW, preskaču se ako nisu preuzete), `ui_options()` → `GET /api/gen/options`.
- **Napredno**: 5 `class="adv-group"` blokova (`data-group` model / lora / format / face / misc — `#v11GenBox` je misc) s `?` tooltipovima (`button.tip[data-tip]`, popover `#tipPop` u `static/ui_v130.js`; `TIPS` rječnik u `static/v11.js`). ID-jevi forme nisu mijenjani.
- **Redizajn**: `static/ui_v130.css` + `static/ui_v130.js` (učitavaju se zadnji). Glass tema, puna širina, plutajuća navigacija; Pregled → **Početna** (`data-tab="pregled"` ostaje) s KPI karticama (`renderHomeKpis` u v11.js, `dashboard_series()` u overview API-ju).
- **Ocjene → LoRA**: `rate_image` vraća `lora_sync`; `lora_trainer_service.sync_gallery_rating` (`added|exists|removed|deferred|skipped|none`), postavka `lora_auto_sync_good` (zadano uključeno), `POST /api/lora-trainer/dataset/<pid>/import-good`. Događaji: `studio:generated`, `studio:gen-rendered`, `studio:rated`.
- **GPU traka**: `hardware_service.gpu_live()` (Windows CIM GPUEngine + GPUAdapterMemory, rezerva amd-smi/rocm-smi/nvidia-smi/sysfs, pozadinska nit, TTL 2,5 s), `GET /api/gpu-live`, prikaz `#gpuLive` (Generiranje) i `#ltGpu` (trener). Test hookovi `STUDIO_GPU_USAGE`, `STUDIO_GPU_TEMP`, `STUDIO_GPU_VRAM_USED_MB`, `STUDIO_GPU_VRAM_TOTAL_MB`.
- **Treba provjeriti na pravom RX 6600**: stvarne sekunde po slici za Turbo i Realizam; da Windows GPUEngine brojač pod ZLUDA-om pokazuje opterećenje (Compute vs 3D engine — kod uzima najveći engine po adapteru); latencija PowerShella (1–3 s, skrivena u pozadinskoj niti); detail LoRA-e treba preuzeti u Modeli prije uključivanja.

#### I) Sporedno, nije Studio

Postojala je ponuda da Researcher rjeđe vrti Alibaba RFQ rutinu. To nije dio ove aplikacije; samo da znaš da visi kao neodgovorena, nevezana stavka.

### 4.3 Što sada NE radiš

- Ne počinješ novi feature dok ga Sven ne potvrdi (trainer i UI su gotovi u v1.2.0).
- Ne objavljuješ novo izdanje samo zbog ovog dokumenta (handoff nije release).
- Ne dodaješ filtere sadržaja na njegove promptove, workflowe ili lokalne LoRA-e.
- Ne tražiš tajne u chatu.
- Ne tvrdiš da su v1.2.0 / v1.1.0 provjereni na njegovom Windowsu — nisu.

---

## 5. Stanje aplikacije (kod ima prednost)

Cilj: lokalni studio za fiktivne odrasle AI influencere — generiranje preko ComfyUI-ja, konzistentnost lika (LoRA / reference), red čekanja, galerija, kalendar objava, Inbox i CRM. Sve na `http://127.0.0.1:7860`.

### 5.1 Struktura koda (v1.3.0)

| Dio | Uloga |
|---|---|
| `studio.py` | HTTP poslužitelj, starije rute, paljenje UI-ja |
| `api_v11.py` | API 1.1 (`/api/hardware`, `/api/templates`, `/api/queue`, `/api/gallery`, `/api/posts`, `/api/crm/*`, `/api/env`, …). `studio.py` zove `handle()` prije svojih ruta; stari `/api/*` i `/api/inbox/*` i dalje rade |
| `services/hardware_service.py` | detekcija GPU/VRAM, backend, VAE/VRAM zastavice, RX 6600 preset, env za ComfyUI |
| `services/generation_service.py` | predlošci, opcije workflowa, red čekanja, galerija, ocjene, Character Sheet, izvoz LoRA dataseta |
| `services/posting_service.py` | IG/FB/Telegram/Premium, kalendar, scheduler (svakih 30 s) |
| `services/crm_service.py` | inbox, način slanja, LLM, memorija, narudžbe, analitika, webhook |
| `services/common.py`, `services/__init__.py` | zajedničko; `init_schema()`, `start_workers()`, `stop_workers()` |
| `static/v11.js`, `static/v11.css` | sučelje 1.1 (Pregled, Kalendar, CRM, Postavke, red čekanja, galerija) |
| `static/ui_v120.css`, `static/ui_v120.js` | izgled 1.2.0: avatari osoba, kartice osoba, sažetak „Napredno” |
| `static/ui_v130.css`, `static/ui_v130.js` | 1.3.0 (učitavaju se zadnji): glass tema, puna širina, `?` tooltipovi, profili kvalitete, živa GPU traka |
| `api_lora.py`, `services/lora_trainer_service.py`, `static/lora_trainer.js`, `static/lora_trainer.css` | LoRA trener (1.2.0) |
| `index.html` | školjka UI-ja (inline + static) |
| `image_gen.py` | txt2img workflow (SD 1.5 / SDXL / Krea 2), prompt, CLIP, LoRA, hires, FreeU |
| `video.py`, `video_install.py` | AnimateDiff video, izbor motion modula, instalacija čvorova |
| `character.py` | osobe, Face Detailer, reference |
| `inbox.py` | stari inbox, `DATA_DIR`, postavke, SQLite putanje |
| `launcher.py`, `comfy_launch.py`, `comfy_ws.py` | paljenje Studija/ComfyUI-ja, websocket progres |
| `updater.py`, `apply_helper.py` | auto-update |
| `model_download.py`, `installed_models.py`, `node_install.py`, `character_install.py` | modeli i čvorovi |
| `DOKUMENTACIJA.md`, `.env.example`, `CHANGELOG.md`, `KRATKO_UPUTE.txt`, `TOKEN_UPUTE.txt`, `version.json` | dokumentacija i verzija |
| `tools/make_release.sh`, `tools/check_ui_js.py`, `tools/test_*.py` | izdanje i testovi |
| `workflows/krea2_turbo_fp8.json` | Krea 2 predložak |

Stari moduli i dalje rade i delegiraju u `services/`.

**Kartice (v1.3.0):** Početna (prije Pregled), **Generiranje** (zadani tab; lijevo osoba + scena + profil + Generiraj, desno rezultati s Dobra/Loša i GPU trakom; ostalo u „Napredno” s 5 kartica), Osobe (kartice + LoRA trener), Video, Kalendar, Inbox i CRM, Modeli, Postavke.

### 5.2 Hardver

- Detekcija GPU-a i VRAM-a (Windows CIM/wmic, nvidia-smi, rocm-smi).
- Backend: `auto`, `zluda`, `cuda`, `rocm`, `directml`, `cpu`.
- VRAM način: `auto`, `lowvram` (`--lowvram`), `medvram` (bez dodatne zastavice — ComfyUI nema zasebnu), `normalvram` (`--normalvram`).
- VAE: `standard`, `tiled` (zadano, `VAEDecodeTiled`, tile 512), `cpu`.
- Zadane hardware postavke u kodu: tiled VAE, `hw_reserve_vram=1.0`, `hw_safe_mode=1` (8 GB siguran način uključen).
- 8 GB siguran način: tiled VAE, manji hires, rezerva VRAM-a, ograničen batch; SDXL bazne rezolucije po omjeru (npr. IG 4:5 → 768×960 pa izlaz 1080×1350) — vidi `SAFE_SDXL_BASES`.
- Gumb **„Preporuči za RX 6600“**: ZLUDA, `--reserve-vram 1.0`, tiled VAE, siguran način, zatim ponuda **restarta ComfyUI-ja**.
- Studio šalje samo zastavice koje lokalni ComfyUI stvarno podržava (čita `comfy/cli_args.py`).

### 5.3 Generiranje slika

Zadano za SDXL / 8 GB:

- Sampler `dpmpp_2m_sde`, scheduler `karras`.
- Od 1.3.0 zadano ide preko profila Realizam / Brzo / Turbo (vidi 4.2 J i `DOKUMENTACIJA.md` 1b).
- Hires: skala **1,33** (raspon 1,2–1,6), denoise **0,35** (0,25–0,5), **8** koraka (4–16) preko manje baze (`rx_base_for`), LatentUpscale na točne dimenzije pa ImageScale na cilj (npr. 768×960 → 1016×1272 → 1080×1350), dekodiranje `VAEDecodeTiled`. (Do 1.2.0 bilo 1,45 / 0,38 / 14.)
- FreeU_V2 SDXL: b1 1,3 · b2 1,4 · s1 0,9 · s2 0,2. Za SD 1.5: b1 1,5 · b2 1,6 · s1 0,9 · s2 0,2.
- Face Detailer (Impact Pack + Subpack): zadani denoise 0,4, guide size 384, max size 768, bbox threshold 0,5. Ako čvorova nema, predlošci ga preskoče umjesto greške.
- **Multi-LoRA:** do **5** (`MAX_LORA_STACK`), jačine; stack osobe + ručno dodane.
- Reference: `Bez reference`, `IP-Adapter` ili `InstantID`, s bedžom što će se stvarno koristiti. InstantID: čvor ComfyUI_InstantID, antelopev2, InstantID model; FaceAnalysis na CPU-u radi uštede VRAM-a. IP-Adapter Plus Face (cubiq) — do 8 referentnih slika (od 1.0.18); preko 4 se embedovi usrednjavaju. Na Krea 2 se IP-Adapter ne koristi.
- Quality prefix: `RAW photo, best quality, highly detailed skin` (može se isključiti).
- Formati uključuju IG Portret 4:5, IG Kvadrat 1:1, IG Story 9:16.

**Predlošci (SQLite):** uređivanje, dupliciranje, brisanje. Grupe: Javni teaser (editorial, lifestyle, moda, studijski glamur, iza kulisa) i Premium sadržaj (personalizirani SFW portreti, shoutout, ekskluzivni editorial/lifestyle). Ako u predlošku nešto nije postavljeno, vrijedi forma. Eksplicitan odabir u formi ima prednost, osim u batchu s više predložaka — tada svaki predložak nosi svoje postavke. **Poznato:** odabir predloška ne popunjava vizualno kontrole forme.

**Red čekanja:** trajan u SQLite, preživljava restart. Statusi: U tijeku, Na čekanju, Gotovo, Greška, Otkazano. Batch: ponavljanja, seed (nasumičan / isti / uzastopni), jedan ili više predložaka. Otkaži, Ponovi, Očisti završene.

**Galerija:** filter po osobi, ocjeni (čipovi Sve / Dobra / Loša / Character sheet) i izvoru; lijeno učitavanje („Učitaj još“); ocjene **Dobra** / **Loša** na kartici i u lightboxu; „Dobra” ide u LoRA dataset osobe.

### 5.4 Osobe

- Uvijek fiktivne odrasle osobe. Pozitivni prompt počinje s `adult woman` ili `adult woman, <dob>` (18+). U zadanom negativnom promptu su i `child, teen`.
- LoRA stack do 5, način referenci, način slanja CRM-a po osobi (naslijedi / automatsko / nacrt).
- Character Sheet 2×2: sprijeda, tri četvrtine, profil, vani candid; isti seed; spajanje u jedan PNG (Pillow, ili čisti Python ako Pillow nema).
- Izvoz LoRA dataseta: vidi 4.2 D.
- LoRA trener (v1.2.0): vidi 4.2 A.

### 5.5 Preporučene SDXL LoRA-e (kartica Modeli, sve SFW, kvaliteta slike)

Idu u `models\loras`:

| LoRA | Datoteka | Orijentirana veličina | Jačina |
|---|---|---|---|
| Photorealistic slider (ostris) | `ostris_photorealistic_slider_xl.safetensors` | ~24 MB | 0,5–1,5 |
| Extremely detailed (ntc-ai) | `ntc_extremely_detailed_xl.safetensors` | ~9 MB | 0,5–1,5 |
| Cinematic lighting (ntc-ai) | `ntc_cinematic_lighting_xl.safetensors` | ~9 MB | 0,5–1,5 |
| Offset noise (Stability AI) | `sdxl_offset_example_lora_1.0.safetensors` | ~50 MB | 0,3–0,6 |
| Nice hands (ntc-ai) | `ntc_nice_hands_xl.safetensors` | ~9 MB | 0,5–1,5 |
| Detail Tweaker XL | `add_detail_xl.safetensors` | ~228 MB | 0,5–1,5 |

LoRA izbornik (od 1.0.19) čita `models\loras` s podmapama i spaja s popisom iz ComfyUI-ja. Ništa se ne skriva: prvo kompatibilne s odabranim modelom, ostale pod „Ostalo / možda nekompatibilno“. Interna Turbo LoRA ide samo preko Brzina → Turbo.

### 5.6 Video (logika iz v1.0.20, i dalje u v1.1.0)

Modul: AnimateDiff-Evolved + Video Helper Suite. Motion moduli žive u `models/animatediff_models` (gleda se i mapa čvora).

Odabir **isključivo po arhitekturi checkpointa** (`video.pick_motion_model`) — nikad krivi par:

- **SD 1.5** (redoslijed): `mm_sd_v15_v2.ckpt` / `.safetensors`, zatim `v3_sd15_mm`, zatim `mm_sd_v15.ckpt`.
- **SDXL** (redoslijed): `mm_sdxl_v10_beta.ckpt` / `.safetensors` (~906 MB, guoyww), fallback **Hotshot-XL** `hsxl_temporal_layers.f16.safetensors` / `.safetensors` (~453 MB).

Ako odgovarajući modul nije instaliran, Studio **ne šalje** zadatak: jasna poruka i gumb „Preuzmi … motion modul“. Preuzimanje je paralelno, s nastavkom prekinutog skidanja.

Zadane 8 GB postavke (`recommend_settings`):

- SD 1.5: 512×512, 16 sličica, 16 koraka, 8 fps, cfg 7, denoise 0,7. 24 sličice mogu zapeti na VRAM-u.
- SDXL: 512×512, **12** sličica, **12** koraka, 8 fps, cfg 7, denoise 0,7, max praktično 16 sličica; upozorenje u UI-ju. SD 1.5 je sigurniji i brži na RX 6600.

Čvorovi: `ComfyUI-AnimateDiff-Evolved`, `ComfyUI-VideoHelperSuite`. Najpouzdanije na ZLUDA + 8 GB: SD 1.5 (npr. Realistic Vision) + `mm_sd_v15_v2`.

### 5.7 Text encoder (što prompt zapravo vidi)

Implementacija je u `image_gen.py` (ne zasebni vanjski encoder servis).

- **SD 1.5:** `CheckpointLoaderSimple` učita checkpoint; tekst ide u `CLIPTextEncode` preko ugrađenog CLIP-a (ViT-L).
- **SDXL:** isto `CheckpointLoaderSimple`; u checkpointu su **dva CLIP-a** (ViT-L + OpenCLIP bigG). `CLIPTextEncode` u ComfyUI-ju to koristi kao dual-CLIP conditioning. Nema zasebnog učitavanja encodera.
- **Krea 2 Turbo FP8:** nije jedan checkpoint nego `UNETLoader` + `CLIPLoader` (`type=krea2`) + `VAELoader`. CLIP datoteka: `qwen3vl_4b_fp8_scaled.safetensors`, UNET: `krea2_turbo_fp8_scaled.safetensors`, VAE: `qwen_image_vae.safetensors`. Turbo zadano: 8 koraka, cfg 1, euler + simple, bez Hyper-SDXL LoRA i bez hires fixa. Ako stariji ComfyUI nema tip `krea2`, Studio javi jasnu poruku.
- Dugačak opis izgleda **ne smije potisnuti scenu**. Prompt se cijepa u komade oko limita `CLIP_TOKEN_WARN = 75` (gruba procjena tokena) i spaja s **`ConditioningConcat`**: prvi komad je `adult woman[, dob]` + scena (scena je naglašena, `SCENE_WEIGHT = 1.3`), izgled ide u sljedeći komad, zatim quality tagovi. Ako `ConditioningConcat` nije u `object_info`, ponašanje je namjerno oprezno — ne zbijaj sve slijepo u jedan `CLIPTextEncode` dok katalog nije spreman.

### 5.8 Objave i Kalendar

Kanali: Instagram (Graph: container pa `media_publish` + javni HTTPS tunel), Facebook Page (`/photos` ili `/feed`), Telegram (`sendPhoto` / `sendMessage` na `TELEGRAM_CHAT_ID`), Premium API (`PREMIUM_API_URL`, JSON ili multipart). Scheduler svakih 30 s. Djelomični uspjeh: ponovni pokušaj šalje samo na kanale koji nisu uspjeli.

### 5.9 Inbox i CRM

- Jedinstveni inbox: Instagram DM, Telegram, Premium, webhook. Stari `/api/inbox/*` ostaje.
- Način slanja (traka na vrhu kartice): **Automatsko slanje odmah** (`auto`) ili **Nacrt za odobrenje** (`approve`, **zadano**). Može se postaviti globalno, po kanalu i po osobi. Redoslijed: osoba → kanal → globalno. Implementacija: `crm_service.set_send_mode` / `effective_send_mode`.
- LLM: `auto` (Ollama → LM Studio/OpenAI-compat → xAI → pravila) ili ručno `ollama`, `openai_compat`, `xai`, `rules`.
- Memorija po fanu, prepoznavanje interesa (pretplata, custom narudžba, cijena, shoutout), custom narudžbe (SFW portreti/shoutouti: kreiraj, Generiraj u red, Isporuči, Označi plaćeno), pretplatnici/kupnje, analitika.
- Webhook: `POST /api/crm/webhook`; ako postoji `CRM_WEBHOOK_SECRET`, treba header `X-Studio-Secret`.

Ključevi i varijable okoline navedeni su u `.env.example` i `DOKUMENTACIJA.md` poglavlje 8 — koristi ta imena, nikad primjere s pravim vrijednostima.

### 5.10 Poznati nedostaci

- Odabir predloška ne popunjava vizualno kontrole forme (vrijednosti se primijene na serveru).
- v1.2.0, v1.1.0 (i v1.0.20) još nisu potvrđeni testom na Svenovom Windowsu.
- LoRA trener još nije stvarno trenirao na RX 6600; očitanje temperature AMD GPU-a nije provjereno na njegovom PC-u.

---

## 6. Tok izdanja (točno ovako)

Radi iz svježeg checkouta `main`: na boxu `/workspace/simple-studio`, na Svenovom PC-u `C:\Users\svenb\dev\ai-influencer-studio`. **Release radi samo agent koji je napravio izmjenu.** Prije bilo kakvog rada: `git pull`. Prije `make_release.sh` još jednom `git pull` i `gh release list`, da nitko u međuvremenu nije objavio istu (ili noviju) verziju. Nakon posla dopuni ovo poglavlje i poglavlje 10 (što je napravljeno, trenutna verzija/commit, što je otvoreno), pa `git push`.

1. Napravi izmjene i dopuni dokumentaciju po potrebi.
2. **Testovi** (prilagodi skup onome što si dirao; za puni release vrti relevantne):
   - `python3 tools/check_ui_js.py` — obavezno (provjerava inline JS u `index.html` **i** `static/*.js` preko `node --check`). `make_release.sh` ovo sam pokrene ako postoji `node`.
   - `python3 tools/test_v102.py`, `test_v105.py`, `test_v107.py` … `python3 tools/test_v120.py` (uključujući `test_v110.py` za 1.1.0 i `test_v120.py` za video/motion module)
   - `python3 tools/test_lora_trainer.py` (LoRA trener), `python3 tools/test_ui_v120.py` (sučelje 1.2.0), `python3 tools/test_pythonw_stdio.py`
   - `python3 tools/test_updater.py`
   - Playwright: na boxu `PW_PYTHON=/tmp/pwenv/bin/python` (npr. unutar `tools/test_v110.py` za headless UI). Na Windowsu taj path ne postoji; testovi sami preskoče Playwright ako nije instaliran.
3. `bash tools/make_release.sh patch|minor "bilješke"`  
   (`patch` = 1.1.0 → 1.1.1, `minor` = 1.1.0 → 1.2.0; može i točan broj `1.2.3`). To bumpa `version.json`, dopisuje `CHANGELOG.md`, piše `dist/RELEASE_NOTES.md` i pakira `dist/studio.zip` + `dist/studio.zip.sha256`.  
   Na Windowsu skriptu pokreni iz **Git Basha**. Treba naredba `python3` (ne samo `python`).  
   **`HANDOFF.md` i `tools/setup_dev_windows.ps1` se ne pakiraju u zip.** U zip ne idu ni `data/`, `.git`, `dist/`, `.env`, baze, screenshotovi, `__pycache__`.
4. Pregledaj `dist/RELEASE_NOTES.md` i `CHANGELOG.md`.
5. Commit (poruke u repou su na hrvatskom).
6. `git push origin HEAD:main`
7. ```bash
   gh release create vX.Y.Z \
     dist/studio.zip \
     dist/studio.zip.sha256 \
     --title "AI Influencer Studio X.Y.Z" \
     --notes-file dist/RELEASE_NOTES.md
   ```
   (`make_release.sh` na kraju ispiše točnu naredbu s brojem verzije.)
8. Po želji osvježi `/workspace/simple-studio.zip`.

Ne radi korak 7 dok testovi ne prođu i dok Sven želi izdanje (za bugfix koji je zatražio, izdanje je dio posla nakon što je potvrdio rad).

**Zadnje objavljene verzije:**

| Verzija | Tag / commit | Napomena |
|---|---|---|
| **v1.2.0** | `127e98d52c0b4f22dd7ebe4964176fbf0953e73a` (24. 11. 2026., ~05:00 Europa/Zagreb) | LoRA trener + novo sučelje, sha256 `fc8c0c2a…f48af8` |
| **v1.1.0** | `ee901068357a73f2a1ff4ed22f3fb20cee8dbab9` (20. 11. 2026., ~04:49 Europa/Zagreb) | sha256 `a19fee2c…c85804` |
| **v1.0.20** | `81e067a1e08486af3f8acd1b96541e5d2c5aa69d` (19. 11. 2026., ~03:59 Europa/Zagreb) | SDXL motion modul |

---

## 7. Pravila sadržaja (dogovoreno sa Svenom)

- Osobe su **samo odrasle** i **samo fiktivne**. Prefix: `adult woman, <dob>` (dob 18+). U negativnom promptu ostaju `child, teen` (i ostali zadani quality/anatomy tagovi). Ne koristi lica stvarnih ljudi.
- Ugrađeni predlošci, zadani AI/chat promptovi i kurirane/preporučene LoRA-e ostaju **SFW**.
- **Nema filtera ključnih riječi** na njegove vlastite promptove, predloške, ComfyUI workflowe ili lokalne LoRA-e. On smije sam ubaciti što želi, bez blokiranja iz aplikacije. Jedina stalna zaštita je odraslost osoba.
- CRM način slanja: može uključiti **„Automatsko slanje odmah“**; zadano je nacrt za odobrenje; prekidač je globalno / po kanalu / po osobi. To je prihvatio i već je u v1.1.0.

---

## 8. Kratka povijest verzija i većih ispravaka

Sve je izašlo u kratkom rasponu (18.–24. studenoga 2026.). Detalji su u `CHANGELOG.md`.

- **1.0.0** — prva Windows aplikacija u `%LOCALAPPDATA%\AIInfluencerStudio`, prečaci, auto-update s privatnog repoa, kartice Slike / Poruke / Influenceri.
- **1.0.1** — pythonw je rušio server praznim stdout; log + pouzdanije paljenje ComfyUI-ja.
- **1.0.2** — `TORCH_BACKENDS_CUDNN_ENABLED=0`, websocket progres, SDXL, preuzimanje modela (RealVisXL itd.).
- **1.0.3** — updater zamjenjuje datoteke na mjestu (`os.replace`); mapa app se više ne preimenuje (na Windowsu je to vraćalo staru verziju). Ako netko zapne na 1.0.1/1.0.2, `popravi_update.bat` / `instaliraj.bat`.
- **1.0.4** — ruta za preuzimanje modela i prikaz predloženog modela kad ComfyUI nije upaljen.
- **1.0.5** — Brave na primarnom monitoru, pouzdanije paljenje ComfyUI-ja.
- **1.0.6** — pouzdaniji Brave prozor, skriveni ComfyUI, gašenje sa zatvaranjem prozora.
- **1.0.7** — opcije duljine, slanga, emojija i jezika u profilu.
- **1.0.8** — ne gasi ComfyUI usred generiranja, pouzdanije zatvaranje prozora, Low VRAM.
- **1.0.9** — Video (AnimateDiff), Turbo 8 koraka, čišći ekran slika, bolje pridržavanje scene.
- **1.0.10** — hitni ispravak greške 500 pri generiranju.
- **1.0.11** — Juggernaut XL Ragnarok, bolje pridržavanje scene.
- **1.0.12** — aktivni model uz Generiraj i na karticama slika.
- **1.0.13** — Krea 2 Turbo FP8, nova ikona, osvježavanje prečaca.
- **1.0.14** — izbornik LoRA-e i kartica Osoba umjesto Izgleda.
- **1.0.15** — instalirani modeli, ispravak duplih slika, čišća galerija.
- **1.0.16** — konzistentnost lika (IP-Adapter, referentne slike, LoRA po osobi), IG formati.
- **1.0.17** — hitni ispravak sintaksne greške u JS-u koja je ubila cijeli UI; od tada `check_ui_js.py` prije svakog izdanja.
- **1.0.18** — do 8 referentnih slika, brže preuzimanje modela (paralelni rasponi, resume).
- **1.0.19** — LoRA izbornik vidi sve LoRA-e s diska (i podmape), popravak instalacije IP-Adapter/Impact čvorova, dijagnostika iz `comfyui.log`, svjež ComfyUI pri paljenju, gumb „Popravi“.
- **1.0.20** — SDXL AnimateDiff motion modul u aplikaciji, auto-odabir po arhitekturi, 8 GB video postavke, `tools/test_v120.py`.
- **1.1.0** — modularni servisi, novo sučelje s 8 kartica, hardver/RX 6600, predlošci, red čekanja, galerija s ocjenama, Character Sheet, izvoz dataseta, Kalendar, Inbox i CRM, dokumentacija.
- **1.2.0** — character LoRA trener za RX 6600 (8 GB) u kartici Osobe; pojednostavljeno, modernizirano sučelje (osoba + scena + Generiraj, „Napredno”, kartice osoba), `tools/test_lora_trainer.py`, `tools/test_ui_v120.py`.
- **1.3.0** — RX 6600 profili Realizam / Brzo / Turbo 1024, prirodniji prompt i negativni, 8 GB zaštita, 1 klik detail LoRA-e; Napredno u 5 kartica s `?` objašnjenjima; widescreen glass redizajn (Početna s KPI karticama); Dobra/Loša na slikama → automatski u LoRA dataset, jednostavniji trener; živa GPU traka (`/api/gpu-live`); `tools/test_v130.py`, `tools/test_ui_v130.py`.

---

## 9. Što prvo otvoriti

1. Ovaj `HANDOFF.md` (posebno poglavlje 10 ako preuzimaš posao uz Groka)
2. `DOKUMENTACIJA.md` — korisnički opis 1.2.0 (uključujući poglavlje 1a: sučelje)
3. `.env.example` — imena varijabli (bez vrijednosti)
4. `CHANGELOG.md` i `version.json`
5. `tools/make_release.sh`, `tools/check_ui_js.py` i `tools/setup_dev_windows.ps1`
6. `services/`, `api_v11.py`, `api_lora.py`, `static/v11.js`, `static/ui_v120.js`, `static/lora_trainer.js`, `image_gen.py`, `video.py`

Ako nešto u ovom dokumentu odstupa od koda, **ispravi ponašanje prema kodu** i po želji dopuni ovaj handoff u istom commitu.

---

## 10. Suradnja Grok + Claude

Grok Bot i Claude imaju jednak pristup repou `Spinojpg/ai-influencer-studio` i smiju oboje objavljivati update preko GitHub Releases, ali **ne istovremeno** i ne jedan preko drugoga. Ovo poglavlje je dogovoreni radni režim. Pravilo potvrde od Svena, sigurnosna pravila i pravila sadržaja iz poglavlja 2 i 7 **ostaju nepromijenjena**.

### 10.1 Jedan agent po zadatku

- Na istom zadatku radi **samo jedan agent u isto vrijeme**. Ne dijelite jedan feature/commit/release na dva paralelna rada.
- Prije početka rada: `git pull` (ff-only ako je moguće) i provjeri da si na `main` i da je stablo čisto.
- Nakon rada: commit (poruke na hrvatskom), `git push origin HEAD:main`.
- Ako `git pull --ff-only` ne prođe, stani i uskladi se; ne radi `push --force` na `main`.

### 10.2 Release radi samo agent koji je napravio izmjenu

- `tools/make_release.sh` bumpa `version.json` i pakira `studio.zip`. Auto-update na Svenovom PC-u hrani se GitHub Releases, zato se verzija ne bumpa „usput“.
- Release (`make_release.sh` + `gh release create`) radi **samo agent koji je napravio tu izmjenu**, i samo kad je Sven to potvrdio (ili kad je bugfix koji je zatražio i izdanje je dogovoreni dio posla).
- **Prije** `bash tools/make_release.sh` obavezno:
  1. `git pull`
  2. `gh release list` — provjeri da ta verzija (npr. v1.1.1) **nije već objavljena** i da nitko u međuvremenu nije izdao noviju.
- Nakon uspješnog releasea dopuni ovaj dokument (tablica u poglavlju 6 i sažetak ovdje) i gurni commit ako si u handoffu još nešto dopisao. Ne ostavljaj `dist/` u gitu (mapa je u `.gitignore`).

### 10.3 Nakon svakog posla dopuni ovaj dokument

Agent koji je radio zadatak, u istom ili odmah sljedećem commitu, dopuni `HANDOFF.md`:

- što je napravljeno
- trenutna **objavljena** verzija i tag, plus trenutni commit na `main`
- što je ostalo otvoreno ili čeka Svenovu potvrdu

Bez toga sljedeći agent ne može pouzdano preuzeti posao.

### 10.4 Putanje

| Što | Putanja | Napomena |
|---|---|---|
| Razvojni checkout na Windowsu | `C:\Users\svenb\dev\ai-influencer-studio` | git, grana `main` |
| Checkout na Grokovom računalu (box) | `/workspace/simple-studio` | git, grana `main`; `gh` prijavljen kao Spinojpg |
| Instalirana aplikacija | `%LOCALAPPDATA%\AIInfluencerStudio\app` | **nije** checkout; ne raditi tu commit/release, ne klonirati repo u tu mapu |
| Korisnički podaci na PC-u | `%LOCALAPPDATA%\AIInfluencerStudio\data` | `.env`, baza, logovi; ne commitati |
| Izvještaj Windows setupa | `C:\Users\svenb\dev\setup_report.txt` | piše ga `setup_dev_windows.ps1`; nije dio repoa |

### 10.5 Kako Claude postavlja okruženje na Svenovom PC-u

1. Sven jednom pokrene `tools/setup_dev_windows.ps1` (ako checkout još ne postoji, skriptu može skinuti iz repoa ili pokrenuti nakon ručnog klona). Preporučeni način:
   `powershell -ExecutionPolicy Bypass -File tools\setup_dev_windows.ps1`  
   Ako ExecutionPolicy blokira skriptu: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
2. Skripta provjeri git, gh, Python (`py`/`python`), Node i Git Bash (`C:\Program Files\Git\bin\bash.exe`). Ako nešto fali, ponudi winget instalaciju i pita **d/n** prije svake. Paketi: `Git.Git`, `GitHub.cli`, `Python.Python.3.12`, `OpenJS.NodeJS.LTS`.
3. Ako `gh` nije prijavljen, skripta **ne dira tokene**. Sven sam pokrene `gh auth login` (GitHub.com, HTTPS, prijava preko preglednika), zatim ponovo skriptu.
4. Checkout ide isključivo u `C:\Users\svenb\dev\ai-influencer-studio`. Ako bi putanja pala unutar `%LOCALAPPDATA%\AIInfluencerStudio`, skripta odbija rad.
5. Ako mapa ne postoji, klonira repo; ako postoji, radi `git fetch`, `checkout main` i `git pull --ff-only`.
6. Pokreće `tools/check_ui_js.py` i testove koji su pokretljivi na Windowsu (uključujući `test_v110.py`, `test_v120.py`, `test_updater.py`). Playwright dijelove ne forsiramo (`PW_PYTHON=/tmp/pwenv` je s boxa i na Windowsu ne postoji); ti testovi sami preskoče UI korak ako Playwright nije instaliran.
7. Ovisnosti `tools/make_release.sh` provjerava u Git Bashu naredbom `command -v` — **skriptu za release ne pokreće**.
8. Piše i ispisuje izvještaj u `C:\Users\svenb\dev\setup_report.txt` (verzije, prolaz/pad po provjeri, što fali).

**Što na Windowsu često zapne** (iz pregleda testova, ne iz pokretanja na ovom PC-u):

- `tools/test_updater.py` u jednom koraku zove `bash tools/make_release.sh` u **kopiji** stabla; treba `bash` na PATH-u (setup skripta doda Git Bash ako ga nađe).
- `make_release.sh` zove **`python3`**, ne `python`. Ako u Git Bashu postoji samo `python`, release skripta neće raditi dok ne bude i `python3`.
- `zip` i `sha256sum` **nisu** potrebni: paket i hash rade se u Pythonu.
- `node` je poželjan za `check_ui_js.py`; bez njega `make_release.sh` upozori i nastavi, ali UI greška može ući u zip.
- `test_v105.py` koristi hardkodirane putanje `/tmp/fake-brave/...` samo kao lažne objekte u mocku, ne stvara te mape.
- `test_v115.py` radi `symlink_to`; na Windowsu to često treba Developer Mode ili administratorska prava.

### 10.6 Pravila koja se ne mijenjaju

- **Potvrda:** prije novog zadatka procijeni opseg rada i **ne radi ništa dok Sven eksplicitno ne potvrdi.**
- **Sigurnost:** nikad tokene ni ključeve u repo, u ovaj dokument, u chat ili u izvještaj setup skripte. Sven ih ne lijepi. `gh auth login` radi on sam.
- **Sadržaj:** osobe samo odrasle i fiktivne; ugrađeni predlošci i kurirane LoRA-e ostaju SFW; nema filtera ključnih riječi na njegove vlastite promptove, workflowe ili lokalne LoRA-e. Detalji ostaju u poglavlju 7.

### 10.7 Stanje nakon pripreme suradnje (22. 11. 2026., Europa/Zagreb) — povijesno

- Dodani `tools/setup_dev_windows.ps1` i ovo poglavlje. `make_release.sh` isključuje tu skriptu iz `studio.zip`.
- Kod aplikacije nije mijenjan. Verzija **nije** bumpana. Release **nije** rađen. Objavljeno je i dalje **v1.1.0**.
- Otvoreno ostaje isto kao u poglavlju 4.2: LoRA trainer + pojednostavljenje UI-ja čeka Svenovu potvrdu; feedback za v1.1.0/v1.0.20 na Windowsu; Instagram setup, face LoRA, opcijski xAI ključ, ideja „Dodatni ComfyUI“.

### 10.8 Stanje nakon izdanja v1.2.0 (24. 11. 2026., Europa/Zagreb)

- Radio: **Grok** (na boxu, `/workspace/simple-studio`). Sven je potvrdio oba dijela zadatka.
- **Objavljeno: v1.2.0**, tag `v1.2.0` na release commitu `127e98d52c0b4f22dd7ebe4964176fbf0953e73a`. Izdanje: https://github.com/Spinojpg/ai-influencer-studio/releases/tag/v1.2.0 (assets `studio.zip` + `studio.zip.sha256`).
- `studio.zip`: 660 850 bajtova, sha256 `fc8c0c2a8b2e05a307cef1af1350f7807caffaabde92ae38ae23a066e4f48af8`.
- Napravljeno: LoRA trener (`d15422f`) + pojednostavljeno, modernizirano sučelje (`127e98d`), `DOKUMENTACIJA.md` (poglavlje 1a), `CHANGELOG.md` (jedan unos `## 1.2.0`), `make_release.sh` traži i `static/ui_v120.*`. Nakon toga samo dokumentacijski commit s ovim poglavljem (zadnji commit na `origin/main`).
- Testovi prije objave (box, `PW_PYTHON=/tmp/pwenv/bin/python`): `check_ui_js`, `test_lora_trainer`, `test_ui_v120`, `test_v102`, `test_v105`, `test_v107`–`test_v120`, `test_updater`, `test_pythonw_stdio` — **svi prošli (21/21)**.
- Otvoreno: test v1.2.0 na Windowsu (auto-update s v1.1.0, izgled u Braveu); prvo stvarno treniranje na RX 6600 i provjera sd-scripts venva; provjera očitanja temperature AMD GPU-a; Instagram setup; opcijski xAI ključ; ideja „Dodatni ComfyUI” / dva PC-a; poznati nedostatak da predložak vizualno ne popuni formu.

### 10.9 Stanje nakon izdanja v1.3.0 (24. 11. 2026., Europa/Zagreb)

- Radio: **Grok** (na boxu, `/workspace/simple-studio`). Sven je potvrdio cijeli opseg: „Kreni i odradi sve odjednom kao v1.3.0“.
- **Objavljeno: v1.3.0**, tag `v1.3.0` na release commitu `3d5b0aac0dbe61be4ef78ed3b37973739299d16c`, objavljeno 24. 11. 2026. u 06:46 (Europa/Zagreb). Izdanje: https://github.com/Spinojpg/ai-influencer-studio/releases/tag/v1.3.0 (assets `studio.zip` + `studio.zip.sha256`).
- `studio.zip`: 718 510 bajtova, 89 datoteka, sha256 `d572441e05d41bbcf680cb7588af3f06a4c8cd54829b9d6da5599df7f01b7afd`. Sadrži `static/ui_v130.*`, `tools/test_v130.py`, `tools/test_ui_v130.py`; ne sadrži `HANDOFF.md` ni `tools/setup_dev_windows.ps1`.
- Napravljeno (detalji u 4.2 J): profili kvalitete i brzine za RX 6600, prirodni prompt/negativni, 8 GB zaštita, detail LoRA-e; Napredno u 5 glass kartica s hrvatskim `?` objašnjenjima; widescreen glass redizajn svih kartica; Dobra/Loša → LoRA dataset + pojednostavljen trener; živa GPU traka. `make_release.sh` traži i `static/ui_v130.*`. U `tools/test_v110.py` očekivani hires promijenjen s 1,45 na 1,33 (novi zadani profil). Nakon toga samo dokumentacijski commit s ovim poglavljem.
- Testovi prije i poslije pakiranja (box, `PW_PYTHON=/tmp/pwenv/bin/python`): `check_ui_js`, `test_lora_trainer`, `test_pythonw_stdio`, `test_ui_v120`, `test_ui_v130`, `test_updater`, `test_v102`, `test_v105`, `test_v107`–`test_v120`, `test_v130` — **svi prošli (23/23)**. UI snimke (1728×928): `UI_V130_SHOTS=/mapa python3 tools/test_ui_v130.py`.
- Napomena: profil se primijeni jednom pri prvom učitavanju (Realizam uključuje Hires pass u formi); nakon toga vrijedi ono što Sven sam odabere.
- Otvoreno: test v1.3.0 na Windowsu (auto-update s v1.2.0, izgled u Braveu na širokom monitoru); stvarne sekunde Turbo/Realizam na RX 6600; Windows GPU brojač pod ZLUDA-om (opterećenje i VRAM u GPU traci); prvo stvarno treniranje LoRA-e; ostale stavke iz 10.8 (Instagram setup, opcijski xAI ključ, „Dodatni ComfyUI”, predložak ne popunjava formu vizualno).

# AI Influencer Studio — handoff za Claudea

**Datum:** 22. studenoga 2026. (Europa/Zagreb, UTC+1)  
**Repo:** privatni GitHub `Spinojpg/ai-influencer-studio` (grana `main`)  
**Trenutna verzija:** **v1.1.0** (commit `ee901068357a73f2a1ff4ed22f3fb20cee8dbab9`, tag `v1.1.0`)  
**studio.zip sha256:** `a19fee2ca5de4549965c0e86b3cdbacd888adda6a6c93c7179d039c652c85804` (579 003 bajtova)  
**Izdanje:** https://github.com/Spinojpg/ai-influencer-studio/releases/tag/v1.1.0

Ovaj dokument je sastavljen da Claude može privremeno preuzeti posao na aplikaciji dok Sven nema usage na Grok Botu. **Kod u repou ima prednost nad ovim sažetkom.** Ako se nešto ne slaže, vjeruj kodu (`DOKUMENTACIJA.md`, `services/`, `api_v11.py`, `image_gen.py`, `video.py`, `static/v11.js`).

Ovaj `HANDOFF.md` živi u korijenu repoa, ali **ne ide u `studio.zip`** (`tools/make_release.sh` ga isključuje). Ne mijenja rad aplikacije. Nikad ne commitaj `data/.env`, tokene, ključeve ni tajne; Sven ih nikad ne lijepi u chat.

---

## 1. Prompt za početak razgovora s Claudeom

Kopiraj sve između crta i zalijepi kao prvu poruku.

-----

Ti preuzimaš razvoj i održavanje aplikacije **AI Influencer Studio**, lokalnog Windows studija za fiktivne odrasle AI influencere. Vlasnik je **Sven Benko**. Do sada je posao radio Grok Bot; Sven je ostao bez usagea pa te privremeno koristi. Imaš isti pristup: privatni GitHub repo `Spinojpg/ai-influencer-studio` i njegov PC.

Najprije pročitaj `HANDOFF.md` u korijenu repoa (ovaj dokument), zatim `DOKUMENTACIJA.md`, `.env.example`, `CHANGELOG.md`, `version.json` i `tools/make_release.sh`. Kod ima prednost nad handoffom. Trenutna verzija je **v1.1.0** na `main` (commit `ee90106`).

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
- Rad na kodu (ako radiš na istoj box mašini): `/workspace/simple-studio`. `gh` je prijavljen kao Spinojpg.

**Što je gotovo**
v1.1.0 je objavljen 20. 11. 2026. (modularni `services/`, kartice, hardver/RX 6600, predlošci, red čekanja, galerija s ocjenama, osobe, Character Sheet, izvoz LoRA dataseta, Kalendar/objave, Inbox i CRM). v1.0.20 pokriva SDXL AnimateDiff motion module. To **nije** još potvrđeno na njegovom Windowsu — čekamo feedback i logove ako nešto pukne.

**Što je otvoreno — ne počinji bez potvrde**
Predloženi sljedeći prompt (još nije krenuo):
1) jednostavan character LoRA trainer za RX 6600;
2) pojednostavljenje UI-ja (glavni ekran: osoba + scena + Generiraj, ostalo pod „Napredno“, bez promjene funkcionalnosti).
Ostalo otvoreno: Instagram setup, treniranje face LoRA-e (izvoz dataseta već postoji), opcijski xAI ključ, ideja „Dodatni ComfyUI“ za dijeljenje poslova na dva PC-a, poznati nedostatak da odabir predloška vizualno ne popuni kontrole forme.

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
- Radni checkout na boxu (za razvoj/release): `/workspace/simple-studio`. Nakon releasea obično se osvježi i `/workspace/simple-studio.zip`.

Ako nešto na Windowsu ne radi, prvo traži te logove — ne nagađaj.

---

## 4. Posao koji Claude preuzima

Ovo je cijeli posao koji je Grok Bot radio na ovom projektu, i koji sada preuzimaš. Nisi tu samo za jedan feature: održavaš aplikaciju, gradiš što Sven potvrdi, objavljuješ izdanja, debuggiraš s njegovog Windowsa, pomažeš oko modela/LoRA-a/workflowa i postavljanja objava/CRM-a, i odgovaraš na pitanja. **Nijedan novi feature se ne počinje bez njegove potvrde.**

### 4.1 Odgovornosti (stalni posao)

1. **Održavanje aplikacije**  
   Kod je u privatnom repou `Spinojpg/ai-influencer-studio`, grana `main`. Lokalni rad (na boxu): `/workspace/simple-studio`. Ne commitaj korisničke podatke, `.env`, bazu ni `dist/`. `HANDOFF.md` ostaje u repou, ali ne u `studio.zip`.

2. **Izrada značajki**  
   Kad Sven potvrdi zadatak: implementiraj, uskladi UI (`index.html`, `static/v11.js`, `static/v11.css`) i backend (`studio.py`, `api_v11.py`, `services/`, postojeći moduli), dopuni `DOKUMENTACIJA.md` / `CHANGELOG.md` po potrebi, napiši ili proširi testove, pa idi na tok izdanja (poglavlje 6).

3. **Izdanja**  
   Strogo prati postupak u poglavlju 6. Ne radi release „usput“ i ne bumpaj verziju bez namjere da ide na GitHub Releases (jer se auto-update hrani time). Nakon `gh release create` korisnik na Windowsu dobiva update u aplikaciji.

4. **Debugging s Windowsa**  
   v1.1.0 i v1.0.20 **još nisu potvrđeni** na njegovom PC-u. Ako nešto pukne, zatraži relevantne logove (`comfyui.log`, `studio.log`, `launcher.log`, `updater.log`) i točan korak koji je radio. Tipične stvari: ZLUDA/cuDNN visak, OOM na 8 GB, čvorovi koji se nisu učitali, updater koji nije zamijenio datoteke, prazno sučelje zbog JS greške (zato `tools/check_ui_js.py` mora proći prije pakiranja).

5. **Modeli, LoRA-e i workflowi**  
   Kartica Modeli već umije preuzeti checkpointe, LoRA-e, čvorove i AnimateDiff motion module. Pomozi mu oko odabira i 8 GB postavki, instalacije čvorova (IP-Adapter, InstantID, Impact Pack, AnimateDiff-Evolved, VHS) i vlastitih LoRA-a/workflowa. Ne cenzuriraj ono što sam ubaci. Ugrađene preporuke i predlošci ostaju SFW. Osobe uvijek odrasle i fiktivne.

6. **Objave i CRM setup**  
   Instagram/Facebook (Meta Graph), Telegram, Premium API, webhook, tunel za `PUBLIC_MEDIA_BASE_URL`. Ključeve unosi on sam u Postavke ili `data\.env`. Možeš ga voditi korak po korak, ali **ne** traži da token zalijepi u chat. CRM chat radi i bez xAI-ja (Ollama, LM Studio / OpenAI-compat, ili način „pravila“).

7. **Odgovaranje na pitanja**  
   Objašnjavaj arhitekturu, modele, hardver, prompt/encoder, video, CRM itd. na hrvatskom. Nedavno je pitano: koji encoder pretvara prompt u ono što model vidi (CLIP / ConditioningConcat / Krea CLIPLoader); što je Qwen3.8-Flash-Next i stane li na laptop 64 GB + RTX 4070 — realno ne (preporuka za CRM: lokalni 14–32B Qwen preko Ollame ili LM Studija). Ta Q&A pitanja su odgovorena; nisu otvoreni zadaci za kod.

### 4.2 Otvorene i čekajuće stavke — status i kako nastaviti

#### A) Predloženi sljedeći prompt: LoRA trainer + pojednostavljenje UI-ja — **NIJE POČETO, čeka potvrdu**

Sven je poslao prompt s dvije stavke, zatim izričito rekao da se ne radi ništa dok ne potvrdi, i tražio samo grubu procjenu potrošnje. **Nijedna stavka nije implementirana.** Još nije rekao hoće li stavku 1, stavku 2 ili oboje.

**Stavka 1 — jednostavan character LoRA trainer za RX 6600**

Što je tražio:

- upload 15–40 slika
- automatski resize i caption
- postavke za 8 GB: gradient checkpointing, mali batch, fp16, cache latents
- progres i upozorenje na temperaturu GPU-a
- nakon treniranja automatski dodati LoRA na osobu
- jednostavan UI, podrška za više osoba

Što već postoji (nemoj duplicirati): u v1.1.0 kartica Osobe ima **izvoz LoRA dataseta** — slike ocijenjene „Dobra“ idu u `data/lora_datasets/<osoba>_<vrijeme>/` s caption `.txt`, `UPUTE.txt` i konfiguracijama `kohya_sdxl_lora_8gb.json` i `onetrainer_sdxl_lora_8gb.json` (batch 1, gradient checkpointing, mixed precision). To je priprema za vanjski Kohya/OneTrainer, **nije** ugrađeni trainer.

Kako nastaviti, **tek kad kaže da radiš stavku 1**:

1. Ponovi kratku procjenu truda i čekaj potvrdu ako već nije jasna za ovu stavku.
2. Predloži i uskladi pristup koji stane na RX 6600 8 GB + ZLUDA (realno: omotač oko Kohya ili sličnog, ne težak custom trainer od nule ako to ne stane na stroj). Reci mu što točno planiraš prije pisanja većeg koda, ako plan nije očit iz prompta.
3. UI: upload, pregled, progres, upozorenje na temperaturu, rezultat se veže na odabranu osobu (`lora_stack`, do 5). Više osoba = odabir osobe, ne jedan globalni model.
4. Testovi + dokumentacija, zatim tok izdanja (npr. minor ako je nova značajka).
5. Na Windowsu provjeriti OOM, putanje i da se nova LoRA vidi u izborniku.

**Stavka 2 — pojednostavljenje i modernizacija UI-ja**

Što je tražio:

- minimalan glavni ekran: **osoba + scena + Generiraj**
- napredne postavke pod **„Napredno“**
- jasniji profili
- **ne mijenjati funkcionalnost** — samo organizacija i preglednost

Kako nastaviti, **tek kad kaže da radiš stavku 2**:

1. Procjena, pa potvrda.
2. Zadrži sve kartice i API-je; premjesti gustoću s kartice Generiranje. Zadani tab i dalje može biti Generiranje, ali prvi pogled treba biti osoba, scena/prompt i gumb Generiraj.
3. Sampler, hires, FreeU, Face Detailer, LoRA stack, reference, VAE itd. pod „Napredno“ (dio toga već je u Napredno — treba dodatno stanjiti glavni ekran).
4. Profili/Osobe: pregledniji prikaz, bez gubitka polja (LoRA stack, reference, način slanja, character sheet, izvoz dataseta).
5. Vizualna regresija: Playwright (`PW_PYTHON=/tmp/pwenv/bin/python`) + `tools/check_ui_js.py` + `tools/test_v110.py`. Posebno pripazi na stari bug iz 1.0.16 (sintaksna greška u JS-u je ubila cijeli UI).
6. Poželjno uz to popraviti poznati nedostatak da odabir predloška **ne popuni kontrole forme** (vrijednosti se primijene na serveru). To nije bilo u originalnom promptu — spomeni i pitaj smije li ući u isti UI rad, ne ubacuj tiho ako on želi strogo „samo layout“.

Ako kaže „napravi oboje“, prvo uskladi redoslijed (često je UI prvi jer trainer dodaje novi ekran; ili trainer pa UI oko njega) i opet kratko potvrdi plan.

#### B) „Dodatni ComfyUI“ — dijeljenje poslova na dva PC-a — **samo ideja, nije početo**

Ponuda: opcija da se poslovi šalju i na drugi ComfyUI (npr. laptop s RTX 4070), ne samo na `C:\ComfyUI-Zluda`. Treba mrežno dostupan drugi ComfyUI i njegov GPU. Sven to još nije potvrdio.

Kako nastaviti: ako zatraži, procijeni, potvrdi, zatim Postavke (URL/port drugog Comfyja), red čekanja koji umije poslati posao na odabrani backend, jasne greške ako je drugi stroj ugašen. Ne počinji sam.

#### C) Instagram setup — **i dalje otvoreno, čeka Svena**

Kod za Graph API već postoji (container `/media` pa `media_publish`; slika mora biti na javnom HTTPS URL-u preko `PUBLIC_MEDIA_BASE_URL`, npr. cloudflared/ngrok tunel na `:7860`; Studio dijeli samo sliku te objave preko `/public/media/<id>/<token>`). Treba Business/Creator račun spojen na Facebook Page, Meta app, i ključevi u `.env`: `META_ACCESS_TOKEN`, `META_IG_USER_ID`, `META_FB_PAGE_ID`, `PUBLIC_MEDIA_BASE_URL`, po potrebi i Messaging (`IG_VERIFY_TOKEN`, `IG_APP_SECRET`, `IG_ACCESS_TOKEN`).

Kako nastaviti: vodi ga kroz Postavke i `.env.example` / `DOKUMENTACIJA.md` poglavlje 6 i 8. On unosi tajne kod sebe. Kad zapne, traži poruku greške iz UI-ja/logova, ne token.

#### D) Treniranje face LoRA-e — **djelomično pokriveno, trainer nije ugrađen**

Konzistentnost lica već ima: do 8 referentnih slika, IP-Adapter Plus Face, InstantID, LoRA stack po osobi, Character Sheet 2×2, izvoz dataseta iz ocjena „Dobra“. Samo treniranje u aplikaciji je stavka 1 iz točke A i čeka potvrdu. Do tada mu možeš reći da označi dobre slike i izveze dataset pa trenira u Kohyi/OneTraineru prema `UPUTE.txt` iz izvoza.

#### E) xAI ključ za CRM chat — **opcijski, nije postavljen**

CRM radi bez njega: `auto` ide Ollama → LM Studio/OpenAI-compat → xAI → pravila. Način „pravila“ omogućuje simulaciju bez ključa. Ako želi Grok u CRM-u, sam upisuje `XAI_API_KEY` i `XAI_MODEL` (u `.env.example` je predložen `grok-4`) u Postavkama. Ne lijepi ključ u chat. Nije blokirajuće za ostali rad.

#### F) Feedback s Windowsa za v1.1.0 i v1.0.20 — **čeka Svena**

Ako javi da nešto ne radi: verzija iz `version.json` (vidi se u UI-ju), što je kliknuo, i logovi. Za video: je li skinut pravi motion modul (`mm_sd_v15_v2` vs `mm_sdxl_v10_beta`). Za OOM: 8 GB siguran način, tiled VAE, manji hires, isključiti Face Detailer; za SDXL video 512×512, max 16 sličica (zadano 12).

#### G) Poznati nedostatak: predložak ne popunjava formu — **poznato, nije zasebno naručeno**

Odabir predloška primijeni vrijednosti na serveru pri generiranju, ali kontrole u formi vizualno ne skoče na te vrijednosti. Popravi kad radiš UI (uz njegovu suglasnost) ili ako to posebno zatraži.

#### H) Ocjenjivanje Dobra/Loša — **već u v1.1.0, nije otvoren zadatak**

To je implementirano (galerija i lightbox). Ne radi ponovno.

#### I) Sporedno, nije Studio

Postojala je ponuda da Researcher rjeđe vrti Alibaba RFQ rutinu. To nije dio ove aplikacije; samo da znaš da visi kao neodgovorena, nevezana stavka.

### 4.3 Što sada NE radiš

- Ne počinješ trainer ni UI refactor dok ne kaže koju stavku.
- Ne objavljuješ novo izdanje samo zbog ovog dokumenta (handoff nije release).
- Ne dodaješ filtere sadržaja na njegove promptove, workflowe ili lokalne LoRA-e.
- Ne tražiš tajne u chatu.
- Ne tvrdiš da je v1.1.0 provjeren na njegovom Windowsu — nije.

---

## 5. Stanje aplikacije (kod ima prednost)

Cilj: lokalni studio za fiktivne odrasle AI influencere — generiranje preko ComfyUI-ja, konzistentnost lika (LoRA / reference), red čekanja, galerija, kalendar objava, Inbox i CRM. Sve na `http://127.0.0.1:7860`.

### 5.1 Struktura koda (v1.1.0)

| Dio | Uloga |
|---|---|
| `studio.py` | HTTP poslužitelj, starije rute, paljenje UI-ja |
| `api_v11.py` | API 1.1 (`/api/hardware`, `/api/templates`, `/api/queue`, `/api/gallery`, `/api/posts`, `/api/crm/*`, `/api/env`, …). `studio.py` zove `handle()` prije svojih ruta; stari `/api/*` i `/api/inbox/*` i dalje rade |
| `services/hardware_service.py` | detekcija GPU/VRAM, backend, VAE/VRAM zastavice, RX 6600 preset, env za ComfyUI |
| `services/generation_service.py` | predlošci, opcije workflowa, red čekanja, galerija, ocjene, Character Sheet, izvoz LoRA dataseta |
| `services/posting_service.py` | IG/FB/Telegram/Premium, kalendar, scheduler (svakih 30 s) |
| `services/crm_service.py` | inbox, način slanja, LLM, memorija, narudžbe, analitika, webhook |
| `services/common.py`, `services/__init__.py` | zajedničko; `init_schema()`, `start_workers()`, `stop_workers()` |
| `static/v11.js`, `static/v11.css` | sučelje 1.1 |
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

**Kartice (v1.1.0):** Pregled, **Generiranje** (zadani tab), Osobe, Video, Kalendar, Inbox i CRM, Modeli, Postavke.

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
- Hires fix: skala **1,45** (raspon 1,4–1,5), denoise **0,38** (0,35–0,45), **14** koraka (12–15), dekodiranje `VAEDecodeTiled`.
- FreeU_V2 SDXL: b1 1,3 · b2 1,4 · s1 0,9 · s2 0,2. Za SD 1.5: b1 1,5 · b2 1,6 · s1 0,9 · s2 0,2.
- Face Detailer (Impact Pack + Subpack): zadani denoise 0,4, guide size 384, max size 768, bbox threshold 0,5. Ako čvorova nema, predlošci ga preskoče umjesto greške.
- **Multi-LoRA:** do **5** (`MAX_LORA_STACK`), jačine; stack osobe + ručno dodane.
- Reference: `Bez reference`, `IP-Adapter` ili `InstantID`, s bedžom što će se stvarno koristiti. InstantID: čvor ComfyUI_InstantID, antelopev2, InstantID model; FaceAnalysis na CPU-u radi uštede VRAM-a. IP-Adapter Plus Face (cubiq) — do 8 referentnih slika (od 1.0.18); preko 4 se embedovi usrednjavaju. Na Krea 2 se IP-Adapter ne koristi.
- Quality prefix: `RAW photo, best quality, highly detailed skin` (može se isključiti).
- Formati uključuju IG Portret 4:5, IG Kvadrat 1:1, IG Story 9:16.

**Predlošci (SQLite):** uređivanje, dupliciranje, brisanje. Grupe: Javni teaser (editorial, lifestyle, moda, studijski glamur, iza kulisa) i Premium sadržaj (personalizirani SFW portreti, shoutout, ekskluzivni editorial/lifestyle). Ako u predlošku nešto nije postavljeno, vrijedi forma. Eksplicitan odabir u formi ima prednost, osim u batchu s više predložaka — tada svaki predložak nosi svoje postavke. **Poznato:** odabir predloška ne popunjava vizualno kontrole forme.

**Red čekanja:** trajan u SQLite, preživljava restart. Statusi: U tijeku, Na čekanju, Gotovo, Greška, Otkazano. Batch: ponavljanja, seed (nasumičan / isti / uzastopni), jedan ili više predložaka. Otkaži, Ponovi, Očisti završene.

**Galerija:** filter po osobi, ocjeni i izvoru; lijeno učitavanje („Učitaj još“); ocjene **Dobra** / **Loša** i u lightboxu.

### 5.4 Osobe

- Uvijek fiktivne odrasle osobe. Pozitivni prompt počinje s `adult woman` ili `adult woman, <dob>` (18+). U zadanom negativnom promptu su i `child, teen`.
- LoRA stack do 5, način referenci, način slanja CRM-a po osobi (naslijedi / automatsko / nacrt).
- Character Sheet 2×2: sprijeda, tri četvrtine, profil, vani candid; isti seed; spajanje u jedan PNG (Pillow, ili čisti Python ako Pillow nema).
- Izvoz LoRA dataseta: vidi 4.2 D.

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
- v1.1.0 (i v1.0.20) još nisu potvrđeni testom na Svenovom Windowsu.

---

## 6. Tok izdanja (točno ovako)

Radi iz `/workspace/simple-studio` (ili svježeg checkouta `main`).

1. Napravi izmjene i dopuni dokumentaciju po potrebi.
2. **Testovi** (prilagodi skup onome što si dirao; za puni release vrti relevantne):
   - `python3 tools/check_ui_js.py` — obavezno (provjerava inline JS u `index.html` **i** `static/*.js` preko `node --check`). `make_release.sh` ovo sam pokrene ako postoji `node`.
   - `python3 tools/test_v109.py` … `python3 tools/test_v120.py` (uključujući `test_v110.py` za 1.1.0 i `test_v120.py` za video/motion module)
   - `python3 tools/test_updater.py`
   - Playwright: `PW_PYTHON=/tmp/pwenv/bin/python` (npr. unutar `tools/test_v110.py` za headless UI)
3. `bash tools/make_release.sh patch|minor "bilješke"`  
   (`patch` = 1.1.0 → 1.1.1, `minor` = 1.1.0 → 1.2.0; može i točan broj `1.2.3`). To bumpa `version.json`, dopisuje `CHANGELOG.md`, piše `dist/RELEASE_NOTES.md` i pakira `dist/studio.zip` + `dist/studio.zip.sha256`.  
   **`HANDOFF.md` se ne pakira u zip.** U zip ne idu ni `data/`, `.git`, `dist/`, `.env`, baze, screenshotovi, `__pycache__`.
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
| **v1.1.0** | `ee901068357a73f2a1ff4ed22f3fb20cee8dbab9` (20. 11. 2026., ~04:49 Europa/Zagreb) | trenutni `main`, sha256 `a19fee2c…c85804` |
| **v1.0.20** | `81e067a1e08486af3f8acd1b96541e5d2c5aa69d` (19. 11. 2026., ~03:59 Europa/Zagreb) | SDXL motion modul |

---

## 7. Pravila sadržaja (dogovoreno sa Svenom)

- Osobe su **samo odrasle** i **samo fiktivne**. Prefix: `adult woman, <dob>` (dob 18+). U negativnom promptu ostaju `child, teen` (i ostali zadani quality/anatomy tagovi). Ne koristi lica stvarnih ljudi.
- Ugrađeni predlošci, zadani AI/chat promptovi i kurirane/preporučene LoRA-e ostaju **SFW**.
- **Nema filtera ključnih riječi** na njegove vlastite promptove, predloške, ComfyUI workflowe ili lokalne LoRA-e. On smije sam ubaciti što želi, bez blokiranja iz aplikacije. Jedina stalna zaštita je odraslost osoba.
- CRM način slanja: može uključiti **„Automatsko slanje odmah“**; zadano je nacrt za odobrenje; prekidač je globalno / po kanalu / po osobi. To je prihvatio i već je u v1.1.0.

---

## 8. Kratka povijest verzija i većih ispravaka

Sve je izašlo u kratkom rasponu (18.–20. studenoga 2026.). Detalji su u `CHANGELOG.md`.

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

---

## 9. Što prvo otvoriti

1. Ovaj `HANDOFF.md`
2. `DOKUMENTACIJA.md` — korisnički opis 1.1.0
3. `.env.example` — imena varijabli (bez vrijednosti)
4. `CHANGELOG.md` i `version.json`
5. `tools/make_release.sh` i `tools/check_ui_js.py`
6. `services/`, `api_v11.py`, `static/v11.js`, `image_gen.py`, `video.py`

Ako nešto u ovom dokumentu odstupa od koda, **ispravi ponašanje prema kodu** i po želji dopuni ovaj handoff u istom commitu.


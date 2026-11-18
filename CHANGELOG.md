# Promjene

## 1.0.15 — 2026-11-18
- Kartica Modeli: odjeljak „Instalirani modeli” prikazuje sve datoteke u mapi ComfyUI models (checkpointi, diffusion modeli, text encoderi, VAE, LoRA, AnimateDiff…). Vidiš ime, mapu, veličinu i ukupnu zauzetost diska. Svaku možeš obrisati uz potvrdu. Studio upozorava ako je to trenutno odabrani model ili datoteka potrebna za Turbo LoRA odnosno Krea 2 paket. Ako je datoteka zaključana (ComfyUI je koristi), javlja jasnu poruku da pokušaš nakon generiranja ili restarta. Predloženi modeli sada pokazuju status Instalirano / Djelomično.
- Ispravak: pri generiranju 2 slike više se ne prikazuju 4. Uzrok je bio što je ComfyUI u povijesti zadatka uz konačne SaveImage izlaze (type=output) često stavio i privremene preview slike s VAEDecode čvora (type=temp). Studio sada zadržava samo konačne izlaze i uklanja duplikate po imenu, podmapi i tipu.
- Galerija rezultata je čišća: ujednačene kartice, lagani fade-in, skeletni prikaz dok traje generiranje, i na prelasku miša akcije Otvori, Preuzmi, Kopiraj prompt, Kopiraj seed i Obriši. Ispod slike ostaju model i seed. Klik i dalje otvara lightbox.

## 1.0.14 — 2026-11-18
- Kartica Slike: pod Napredno, odmah ispod modela, izbornik LoRA-e iz models/loras (usklađene s arhitekturom modela; nepoznate pod Ostalo). Zadano „Bez LoRA-e”, klizač jačine 0,0–1,5 (zadano 0,8). Izbor se pamti po modelu. Interna Turbo LoRA nije na popisu, ali se i dalje spaja kad uključiš Turbo, zajedno s odabranom LoRA-om. Kod Krea 2 izbornik je skriven.
- Polje Izgled zamijenjeno izbornikom Osoba: odabereš personu (zadano aktivna), Studio sam povuče izgled s profila (kosa, oči, tetovaže…). Ispod vidiš kratki sažetak, a Dodatno je za privremene dopune. Ti upišeš samo što osoba radi. Pravila za odrasle (adult woman, eventualno dob) i poredak scene ostaju.

## 1.0.13 — 2026-11-18
- Kartica Modeli: paket Krea 2 Turbo (FP8) s Hugging Facea (Comfy-Org/Krea-2) — diffusion model 13,1 GB u models/diffusion_models, Qwen3-VL encoder 5,24 GB u text_encoders i VAE 254 MB u vae (ukupno ~18,6 GB, resume je podržan). Studio ga pali kao poseban arh: UNETLoader + CLIPLoader (type=krea2) + VAELoader, bez Load Checkpoint. 8 koraka, cfg 1, euler/simple, zadano 1024×1024. Hires i Hyper-SDXL LoRA se ne koriste. Ako CLIPLoader nema tip krea2, ažuriraj ComfyUI na 0.45.0 ili noviji. Na RX 6600 (8 GB) ovaj model vjerojatno nije izvediv: sam fp8 UNET je 13 GB, a na ZLUDA/RDNA2 se fp8 često pretvara u fp16 (~26 GB). Samostalni ComfyUI workflow je u workflows/krea2_turbo_fp8.json (službeni latent je EmptyLatentImage).
- Nova ikona aplikacije (crni zaobljeni kvadrat, zlatni crtež lica) s prozirnim uglovima, ICO 16/24/32/48/64/128/256 px, i kao favicon. Nakon ažuriranja pokretač ponovo napiše prečace na radnoj površini i u Start izborniku te isprazni Windows cache ikona (SHChangeNotify / ie4uinit).

## 1.0.12 — 2026-11-18
- Na ekranu Slike, uz gumb Generiraj (izvan Napredno) vidi se kratko ime aktivnog modela (npr. RealVisXL V5, Juggernaut XL) i bedž Turbo kad je uključen.
- Ispod svake slike, pored seeda, stoji isti model i Turbo ako je korišten. Povijest to pamti; stare stavke bez tih podataka ostaju samo sa seedom.

## 1.0.11 — 2026-11-18
- Kartica Modeli: Juggernaut XL Ragnarok (fp16, ~6,6 GB) s Hugging Facea (Kandoo/Juggernaut-XL-Ragnarok), javni URL. SDXL, preporuka 30 koraka, cfg 5, dpmpp_2m karras; radi i s Turbo LoRA.
- Prompt: scena ostaje sama u prvom CLIPTextEncode i kad object_info još nije spreman (ConditioningConcat se tada ipak koristi). Scena je naglašena, s izgleda se skidaju „portrait of” i studio/pozni tropi, na kraju je kratki odjek scene — da opis (npr. leži na krevetu) ne postane običan nasmiješeni portret.
- Testovi: /api/generate end-to-end (regresija greške 500 iz 1.0.9), poredak scene uz dugi izgled, ispravak tvrdnje u test_v102 (zadani SDXL portret je 768×1152).

## 1.0.10 — 2026-11-18
- Popravak: 'Unutarnja greška poslužitelja' pri generiranju (Turbo i Kvaliteta) u 1.0.9.

## 1.0.9 — 2026-11-18
- Kartica Video: na RX 6600 (8 GB) realan je AnimateDiff-Evolved + SD 1.5 (Realistic Vision) + mm_sd_v15_v2, 512×512, 16 sličica / 2 s. Gumb „Instaliraj video podršku” klonira čvorove, instalira requirements u venv i preuzima modele; zatim ponovo pokreni ComfyUI. Klip iz zadnje slike ili opisa, sprema se mp4. LTX-Video / Wan / SVD-XT nisu praktični na 8 GB.
- Turbo (8 koraka): Hyper-SDXL CFG LoRA u kartici Modeli (~750 MB), euler + sgm_uniform, cfg 5. Na RX 6600 (~17 s/korak) slika padne s ~8–9 min na ~2–2,5 min. Triton test (nema stdio.h / Visual Studio) nije ključan za brzinu.
- Slike su čišće: veliki opis scene, formati, Turbo/Kvaliteta i gumb Generiraj; model, seed, negativni prompt i hires su pod Napredno.
- Prompt: scena ide prva, zatim izgled (bez vodećeg „portrait of”), pa oznake kvalitete. „adult woman” ostaje na početku. Brojač tokena upozori oko 75; višak se spaja preko ConditioningConcat da CLIP ne odreže scenu.

## 1.0.8 — 2026-11-18
- Gašenje više ne ubija ComfyUI usred generiranja: pokretač ne gasi sesiju dok /queue na :8188 ima posla ili Studio generira sliku.
- Zatvaranje prozora se potvrđuje po procesima preglednika s našim --user-data-dir (PowerShell ili WMIC), ne samo po prvom PID-u koji je pokretač otvorio. pagehide/goodbye i tišina heartbeat-a (sada 120 s) su samo nagovještaj; nakon kratkog čekanja ponovno se provjerava. Razlog gašenja ide u data/logs/launcher.log.
- Za RX 6600 (8 GB): wrapper dodaje --use-split-cross-attention (ako original već nema attention zastavicu). U postavkama je Low VRAM (--lowvram, vrijedi pri sljedećem paljenju ComfyUI-ja). Zadani SDXL portret je 768×1152 (sigurnije na 8 GB); 832×1216 ostaje kao Portret HD.

## 1.0.7 — 2026-11-18
- U editoru influencera Duljina poruka, Slang, Emoji i Jezik imaju više unaprijed ponuđenih opcija (chipovi, hrvatski natpisi) i i dalje Prilagođeno za slobodan tekst. Emoji može biti i odabrani set. Stari spremljeni profili se i dalje učitavaju (npr. long, heavy, MIX, slobodan tekst). Te vrijednosti idu u prompt za chat. Polje Primjeri poruka sada jasno pokazuje format Fan: … / Luna: ….

## 1.0.6 — 2026-11-18
- Preglednik se otvara čim Studio sluša na :7860, bez čekanja da ComfyUI završi učitavanje. Brave se pali odvojeno od pythonw (DETACHED_PROCESS, vlastiti stdio) s --no-first-run --no-default-browser-check, bez --start-maximized uz poziciju (samo veličina na primarnom monitoru). Ako Brave padne ili izađe unutar 3 s, slijedi Edge, pa Chrome, pa webbrowser.open / os.startfile. Svaki pokušaj i returncode ide u data/logs/launcher.log.
- ComfyUI se pali skriveno (cmd /c call comfyui-studio.bat, CREATE_NO_WINDOW, cwd u C:\ComfyUI-Zluda, izlaz u data/logs/comfyui.log). Kad zatvoriš prozor aplikacije, gasi se Studio i ComfyUI stablo koje je pokretač sam upalio (taskkill /T /F /PID; tuđi ručno pokrenuti ComfyUI se ne dira). Zatvaranje se vidi po procesu preglednika (vlastiti profil) i po heartbeat-u stranice (ping svakih 5 s, 20 s tišine ili goodbye).

## 1.0.5 — 2026-11-18
- Pokretač uvijek otvara Studio u Braveu (app način) na primarnom monitoru (Display 1), s vlastitim profilom u data/browser-profile da se ne prikači na postojeći Brave na drugom ekranu. Ako Brave nije instaliran, koristi se Edge, zatim Chrome, zatim zadani preglednik. Preglednik se bira u Postavkama (zadano Brave).
- Ispravak paljenja ComfyUI-ja: pokretač ga pali i kada Studio već radi na :7860 (prije je u tom slučaju samo otvorio prozor, pa je UI javio "ComfyUI nije pokrenut"). Wrapper comfyui-studio.bat sada radi cd /d "%~dp0" da relativni pushd zluda radi, čisti --auto-launch i iz COMMANDLINE_ARGS=..., i pali se preko start /MIN /D da konzola ima ispravan cwd i stdio čak i iz pythonw. Koraci su u data/logs/launcher.log i data/logs/comfyui.log.

## 1.0.4 — 2026-11-18
- Popravljeno preuzimanje modela (gumb Preuzmi / Preuzmi URL) i prikaz predlozenog modela kad ComfyUI nije upaljen.

## 1.0.3 — 2026-11-18
- Ispravak updatera: datoteke se zamjenjuju pojedinačno (os.replace s ponovnim pokušajima). Mapa app se više ne preimenuje — na Windowsu preimenovanje često padne ako je mapa radni dir ili ima otvorene datoteke, pa se stara verzija vratila nakon restarta.
- Primjena ide iz zasebnog helper procesa u mapi data, tek nakon što Studio i launcher izađu. Uspjeh se javlja samo ako version.json na disku odgovara novoj verziji. Koraci su u data/logs/updater.log.
- Sučelje prikazuje verziju isključivo iz version.json i ne tvrdi da je update uspio prije potvrde s diska.
- Ako si na 1.0.1 ili 1.0.2, update unutar aplikacije možda opet neće ostati jer stari updater ima isti bug. Raspakiraj ovaj paket i pokreni popravi_update.bat ili instaliraj.bat — instalira 1.0.3 u AppData, tvoji podaci ostaju.

## 1.0.2 — 2026-11-18
- cuDNN se isključuje u okruženju ComfyUI procesa (TORCH_BACKENDS_CUDNN_ENABLED=0); wrapper comfyui-studio.bat nastaje iz comfyui-n.bat bez --auto-launch, original ostaje netaknut.
- Napredak slike ide preko ComfyUI websocketa; ako progres nema, animirana traka i proteklo vrijeme, plus upozorenje da prvo pokretanje može trajati dulje.
- Bolje zadane postavke: RAW photo prefix (uključen po zadanom, može se isključiti), novi negativni prompt, Portret, 30 koraka, dpmpp_2m karras, cfg 5,5 (SD 1.5) odnosno cfg 5 i veći formati za SDXL.
- Podrška za SDXL (detekcija po imenu, override na profilu), hires fix za SD 1.5 (1,5× latent, denoise 0.4; upozorenje na VRAM za SDXL), --lowvram napomena.
- Kartica Modeli: jedan klik preuzima RealVisXL V5.0 fp16 s Hugging Facea (javni URL, stream + resume) u models/checkpoints, ili zalijepi bilo koji izravni URL.
- Čistiji izgled, veća galerija, preuzimanje i zoom, Ponovi s istim seedom, čipovi stilova, toasti.

## 1.0.1 — 2026-11-18
- Ispravak: pythonw više ne ruši poslužitelj (ERR_EMPTY_RESPONSE) jer stdout/stderr idu u rotirajući log; HTTP greške vraćaju 500 umjesto praznog odgovora; pokretač pali ComfyUI u novom minimiziranom konzolnom prozoru i čeka :8188 do 5 minuta.

## 1.0.0 — 2026-11-18

- Instalacija kao Windows aplikacija u `%LOCALAPPDATA%\AIInfluencerStudio` (app + odvojeni podaci).
- Prečaci na radnoj površini i u izborniku Start, pokretanje u Edge/Chrome app prozoru.
- Automatsko ažuriranje s privatnog repozitorija Spinojpg/ai-influencer-studio (studio.zip + sha256, token u data/.env), uz sigurnosnu kopiju i povrat na staru verziju ako nešto pođe po zlu.
- Korisnički podaci (SQLite, profili, .env, uploadovi) ostaju u mapi `data` i ne diraju se pri updateu.
- Kartice Slike, Poruke (Grok) i Influenceri, plus pokus videa preko ComfyUI.

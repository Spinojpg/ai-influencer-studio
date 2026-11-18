# Promjene

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

# Promjene

## 1.3.6 — 2026-11-24
- Na glavnom ekranu Generiranja je odjeljak LoRA s gumbom + Dodaj LoRA (ista lista kao u Napredno, jačina od −2 do 2; LoRA osobe i dalje ide zasebno).
- U kartici Modeli je dodana Realistična koža (Skin Realism, SDXL) za preuzimanje; Detail Tweaker XL je već bio u katalogu (Hugging Face).
- Preuzimanja s Civitaija podržavaju opcionalni CIVITAI_TOKEN iz data/.env (dodaje se kao ?token=, nikad se ne ispisuje).

## 1.3.5 — 2026-11-24
- LoRA se sada sprema nakon svake epohe (čuvaju se zadnje 3), pa zastoj više ne briše sav napredak.
- Ako trening stane, „Pokušaj ponovno” nudi nastavak od zadnje epohe (kvačica „Nastavi od epohe N”, zadano uključena).
- Koraci, loss i preostalo vrijeme u sučelju se osvježavaju uživo, ne samo na kraju epohe.
- Ako se korak ne pomakne 10 minuta nakon početka treniranja, pojavi se upozorenje da je vjerojatno VRAM pun. U Napredno je opcija da se tada sam zaustavi nakon 20 minuta (zadano samo upozorenje).
- Prekinuti trening ostavlja upotrebljivu LoRA-u (npr. char_osoba_v5-e2.safetensors) u ComfyUI models/loras i dodaje je osobi.

## 1.3.4 — 2026-11-24
- LoRA trener se sada pokreće kroz ComfyUI-Zluda zluda.exe (kao ComfyUI), pa koristi RX 6600 umjesto procesora. Prije je pisalo 'GPU nije pronađen' i trening je išao na CPU.

## 1.3.3 — 2026-11-24
- Popravak LoRA treniranja na AMD/ZLUDA: kad fp16 autocast ne radi, slojevi sami usklade preciznost ulaza i težina (više nema 'Half != float' na koraku 0).

## 1.3.2 — 2026-11-24
- Popravak LoRA treniranja na AMD/ZLUDA: accelerate nije uključivao fp16 način (greške 'Half != float' i 'scaler _unscale_grads_'). Pokretač ga sada prisilno uključuje i osvježava se kod svakog treninga.

## 1.3.1 — 2026-11-24
- Popravak LoRA treniranja: greška 'expected m1 and m2 to have the same dtype (Half != float)' na koraku 0 na AMD/ZLUDA. Trener sada koristi full_fp16.

## 1.3.0 — 2026-11-24
- RX 6600 kvaliteta i brzina: tri profila na glavnom ekranu Generiranja — **Realizam** (zadano: manja baza 768×960 za IG 4:5 + brzi hires 1,33×, denoise 0,35, 8 koraka; CFG 4,3; dpmpp_2m_sde + karras), **Brzo** (20 koraka, jedan prolaz, dpmpp_2m) i **Turbo 1024** (Hyper-SDXL 8 koraka, CFG 2,2, euler + sgm_uniform, baza 1024 px, bez hiresa; cilj ispod 3 min po slici na RX 6600). Profil popuni samo ono što nisi ručno postavio u Napredno.
- Prirodniji izgled: uz profile se na kraj prompta dodaju foto oznake (candid photo, natural skin texture, visible pores, soft natural light, subtle film grain, 35mm) umjesto „best quality”, a zadani negativni prompt dobiva zaštitu od plastične kože (plastic skin, airbrushed, waxy skin, doll-like, cgi, 3d render, oversaturated…). „child, teen” uvijek ostaju u negativnom promptu. Tvoj vlastiti negativni prompt, promptovi, workflowi i lokalne LoRA-e se ne mijenjaju i ne filtriraju.
- 1 klik sigurni prekidači: Face Detailer, InstantID i tri kurirane SFW detail LoRA-e (Prirodna koža, Fini detalji, Prirodni kontrast) uz **8 GB zaštitu**: ograničen hires (≈1,35 MP, 1,1 MP uz InstantID), InstantID + Face Detailer + Hires → hires isključen, SDXL + hires/InstantID → 1 slika po pokretanju, tiled VAE, Face Detailer denoise ≤ 0,5 / guide ≤ 512 / max ≤ 768 / ≤ 12 koraka. Što je zaštita promijenila piše ispod gumba Generiraj.
- „Napredno” je složeno u 5 jasnih glass kartica (Model i sampler · Format i hires · Lice i konzistencija · LoRA i detalji · Prompt, seed i ostalo). Svaka opcija ima „?” s kratkim objašnjenjem na hrvatskom (hover, fokus ili klik; Escape zatvara). Otvoreno Napredno se širi preko cijele širine ekrana. Svi ID-jevi i nazivi polja ostali su isti.
- Novi widescreen „glass” izgled svih kartica: tamno-ljubičasti gradijent, staklene kartice, plutajuća navigacija s pill aktivnom karticom, puna širina ekrana (bez praznih rubova na 1440–1920 px). Generiranje u dva stupca (lijevo osoba + scena + Generiraj, desno rezultati). Kartica Pregled je sada **Početna** s 4 KPI kartice (Prihodi i Slike sa sparkline grafom za 14 dana, Aktivne osobe i Zakazano s prstenom).
- Ocjene slika za LoRA: gumbi **Dobra / Loša** izravno na svakoj novoj slici, u povijesti i galeriji (i dalje u lightboxu), filtar galerije Sve / Dobra / Loša / Character sheet. „Dobra” sliku odmah doda u LoRA dataset te osobe (bez duplikata; prekidač „automatski” je zadano uključen), „Loša” ili brisanje ocjene je makne iz dataseta (ručno dodane slike ostaju). Migracija baze je automatska i sigurna za ponovno pokretanje.
- Jednostavniji LoRA trener: osoba + oznaka spremnosti, brojač „Dobra / ručno”, povuci-i-ispusti, gumb „Uvezi ocijenjene „Dobra””, profili Brzo / Preporučeno / Detaljno kao pill gumbi i jedan gumb „Pokreni treniranje”; tehničke postavke su pod sklopljenim „Napredno”. Sve 8 GB zaštite treniranja ostaju (batch 1, fp16, gradient checkpointing, cache na disk, Adafactor, SDPA, no_half_vae, cuDNN isključen, ComfyUI /free, auto-stop na temperaturi).
- Živa GPU traka tijekom generiranja i treniranja: opterećenje GPU-a (Windows GPU brojači, rezerva amd-smi / rocm-smi / nvidia-smi), temperatura u boji (zeleno / žuto / crveno), zauzeti VRAM i trenutni korak. Novi endpoint `GET /api/gpu-live` s kešom od 2,5 s; mjerenje ide u pozadini i nikad ne izmišlja brojeve („n/d” kad brojač nije dostupan).

## 1.2.0 — 2026-11-24
- Character LoRA trener za RX 6600 (8 GB) i pojednostavljeno, modernizirano sučelje.
- Novo sučelje: tamna minimalistička tema s jednim indigo naglaskom, više prostora, čista gornja traka s karticama i kompaktnim statusima. Sve postojeće funkcije, prečaci i API-ji ostaju isti.
- Generiranje: glavni ekran je samo odabir osobe (avatari s oznakom LoRA-e), opis scene, format / brzina i Generiraj. Sve tehničke postavke (model, LoRA, seed, negativni prompt, sampler, CFG, Hires fix, FreeU, IP-Adapter / InstantID jačina, Face Detailer, predlošci, LoRA stack, red čekanja) su u zatvorenom dijelu „Napredno”, grupirane i sa sažetkom kad je zatvoreno.
- Osobe: preglednije kartice (avatar, ime, dob, kratki opis, oznake „LoRA aktivna” i broj referentnih slika) s brzim radnjama Generiraj / Uredi / LoRA trener. U uređivanju profila osnovna polja su na vrhu, a model / LoRA / tehničke postavke i stil poruka su sklopivi.
- LoRA trener u kartici Osobe: odaberi osobu, dodaj 15–40 slika (povuci, odaberi ili uvezi iz galerije osobe), jedan klik za treniranje. Automatska priprema slika (EXIF, RGB, izrez 768/512, opisi s okidačem i „adult woman”), Kohya struktura i sigurne 8 GB postavke za RX 6600 (batch 1, fp16, gradient checkpointing, cache na disk, Adafactor, SDPA bez xformersa i bitsandbytes, cuDNN isključen).
- Praćenje uživo: korak X/Y, epoha, preostalo vrijeme, loss, log i temperatura GPU-a (ADL / LibreHardwareMonitor / smi alati, bez lažnih brojeva). Upozorenje na 80°C, auto-stop na 92°C (podesivo), gumb Zaustavi gasi cijelo stablo procesa.
- Gotova LoRA (`char_<osoba>_vN.safetensors` u ComfyUI/models/loras) automatski se dodaje osobi (jačina 0.8), a okidač ide u prompt kad generiraš s tom osobom. ComfyUI `/free` prije treninga; generiranje čeka dok trening traje.
- Jednokratna priprema okruženja (kohya sd-scripts v0.13.1 u data/trainer) koja koristi PyTorch iz ComfyUI-Zlude i ne dira ComfyUI pakete.

## 1.1.0 — 2026-11-20
- Nova struktura: modularni servisi (services/: hardver, generiranje, objave, CRM) i novo sučelje s karticama Pregled, Generiranje, Osobe, Video, Kalendar, Inbox i CRM, Modeli, Postavke.
- Hardver: detekcija GPU-a i VRAM-a, izbor backenda (ZLUDA/CUDA/ROCm/DirectML/CPU), VAE i VRAM način, 8 GB siguran način, gumb „Preporuči za RX 6600” uz restart ComfyUI-ja. TORCH_BACKENDS_CUDNN_ENABLED=0 i dalje ostaje za RX 6600.
- Generiranje: dpmpp_2m_sde + karras, hires fix 1,4–1,5 / 0,35–0,45 / 12–15 koraka s VAEDecodeTiled, FreeU_V2 (1,3 / 1,4 / 0,9 / 0,2), postavke Face Detailera, do 5 LoRA-a, InstantID ili IP-Adapter s bedžom.
- Predlošci u bazi (Javni teaser i Premium sadržaj, SFW) s uređivanjem i dupliciranjem; trajni red čekanja s batchom i statusima U tijeku / Na čekanju / Gotovo / Greška / Otkazano; galerija s ocjenama Dobra/Loša i „Učitaj još”.
- Osobe: LoRA stack, način referenci, Character Sheet 2×2, izvoz LoRA dataseta za Kohya/OneTrainer (8 GB).
- Modeli: sekcija „Preporučene SDXL LoRA-e (realizam i detalji)” sa 6 SFW LoRA-a.
- Kalendar i objave: Instagram (container → media_publish), Facebook, Telegram, Premium API, raspored svakih 30 s; ključevi u data/.env, maskirano u sučelju.
- Inbox i CRM: istaknut prekidač Automatsko slanje odmah / Nacrt za odobrenje (globalno, po kanalu, po influenceru, jednim klikom), webhook, simulacija bez xAI ključa, LLM preko Ollame, LM Studija, xAI-ja ili pravila, memorija po fanu, prepoznavanje interesa, custom narudžbe, pretplatnici i analitika.
- Nova dokumentacija: DOKUMENTACIJA.md.

## 1.0.20 — 2026-11-19
- Kartica Modeli: AnimateDiff motion modul za SDXL (mm_sdxl_v10_beta.ckpt, guoyww, oko 906 MB) i opcijski manji Hotshot-XL (oko 453 MB). Oba idu u models/animatediff_models, preuzimanje je paralelno s nastavkom prekinutog skidanja.
- Video sam bira motion modul prema odabranom checkpointu (SD 1.5 → mm_sd_v15_v2, SDXL → mm_sdxl_v10_beta). Ako odgovarajući modul nije instaliran, Studio ne šalje zadatak nego pokaže jasnu poruku i gumb za preuzimanje.
- SDXL video je težak na 8 GB: koristi 512×512 i do 16 sličica, s upozorenjem u sučelju. Ako javi out of memory, odaberi 1 s (8 sličica) ili ostani na SD 1.5.

## 1.0.19 — 2026-11-18
- LoRA izbornik u Slikama (Napredno) sada pokazuje iste LoRA-e kao kartica Modeli. Prije je popis dolazio samo iz ComfyUI-ja (ili s diska bez podmapa) i zatim se filtrirao po arhitekturi, pa su LoRA-e prepoznate kao SD 1.5 (ili SDXL dok ComfyUI još nije spreman) bile skrivene.
- Popis LoRA-a čita models\loras s podmapama i spaja ga s popisom iz ComfyUI-ja. Ništa se više ne skriva: prvo su LoRA-e za odabrani model, ostale su pod „Ostalo / možda nekompatibilno”. Interna Turbo LoRA i dalje ide samo preko Brzina → Turbo.
- Uz izbornik je gumb „↻ Osvježi”, a popis se osvježi i kad otvoriš karticu Slike. Ako u mapi imaš samo Turbo LoRA ili nijednu, ispod piše što napraviti.
- IP-Adapter i Face Detailer: čvorovi se uvijek instaliraju u custom_nodes mapu koju ComfyUI stvarno učitava (provjerava se i u comfyui.log), uz provjeru __init__.py. Ugniježđene mape se izravnaju, a nepotpune preimenuju u .disabled (ComfyUI-Manager i ostali čvorovi ostaju netaknuti).
- Bez Gita se čvorovi preuzimaju kao zip s GitHuba.
- Python paketi čvorova (requirements.txt i install.py za Impact Pack/Subpack) instaliraju se u ComfyUI venv, a torch i numpy ostaju zaključani na postojećim verzijama.
- Novi gumb „Popravi” ponovno provjeri mapu čvora i instalira pakete. Ako ComfyUI ne učita čvor, Studio iz comfyui.log pokaže točan razlog (npr. nedostaje Python paket) ili javi da ComfyUI mapu uopće nije vidio.
- Pri pokretanju Studio ugasi zaostali ComfyUI iz prošle sesije (ili onaj koji čeka restart nakon instalacije čvorova) i pokrene novi, da se novi čvorovi stvarno učitaju. Studio sada svakih 30 sekundi ponovno provjerava popis čvorova u ComfyUI-ju.

## 1.0.18 — 2026-11-18
- Referentne slike lica: sada do 8 po osobi (prije 3). Možeš odabrati više odjednom ili ih ispustiti u okvir, poredati, obrisati i uključiti/isključiti svaku.
- Najbolje su 4-8 jasnih slika lica, različiti kutovi i svjetlo, bez naočala/filtera.
- Pri spremanju Studio izreže kvadrat oko 512–640 px (sredina ili područje lica) i zadrži original, da štedi VRAM na 8 GB.
- Više uključenih slika ide u IP-Adapter zajedno; preko 4 se ugniježđeni embedovi usrednjavaju da ne skoči potrošnja memorije.
- Stari profili s 1–3 slike ostaju netaknuti i i dalje se koriste.
- Preuzimanje modela je brže: paralelni rasponi (do 8 veza, dijelovi 32–64 MB), nastavak prekinutog preuzimanja, veći spremnik i prikaz brzine u MB/s. Ako poslužitelj ne podržava Range, ide jedna veza kao dosad. Provjera veličine i sha256 ostaje.

## 1.0.17 — 2026-11-18
- Hitni ispravak: u 1.0.16 jedna greška u kodu sučelja (krivi navodnik kod gumba referentnih slika) zaustavila je cijelo sučelje, pa su Osoba i Influencer bili prazni, verzija je pisala „v…“, a status je zapeo na „Provjeravam…“.
- Sučelje se opet normalno učitava, sa svim novostima iz 1.0.16 (referentne slike, IG formati, model i LoRA po osobi).
- Postojeće osobe i postavke ostaju netaknute.
- Dodana automatska provjera koda sučelja prije svakog izdanja, da se ovo ne ponovi.

## 1.0.16 — 2026-11-18
- Konzistentnost lika: u profilu osobe možeš staviti 1–3 referentne slike lica (pregled, brisanje, redoslijed). Studio ih primjenjuje preko IP-Adapter Plus Face (čvor cubiq, bez InsightFace), s klizačem jačine 0,6–1,0 (zadano 0,8) po osobi i u Napredno. Na Krea 2 se ne koristi.
- U kartici Modeli je paket „IP-Adapter Plus Face” s Hugging Facea (h94/IP-Adapter): CLIP Vision ViT-H (oko 2,35 GB) u models/clip_vision i Plus Face modeli za SDXL (oko 808 MB) i SD 1.5 (oko 94 MB) u models/ipadapter, ukupno oko 3,2 GB. Gumb „Instaliraj IP-Adapter” klonira čvor (treba Git) i preuzme paket; zatim zatvori Studio i ponovo ga pokreni.
- Opis izgleda s profila ide u prompt kao (izgled:1,3); klizač 1,0–1,5 vidiš u profilu i u Napredno. CLIP poredak (scena prva) i ConditioningConcat ostaju.
- Kad odabereš osobu, postave se njezin preferirani model i LoRA (s jačinom). Za tu sliku i dalje možeš promijeniti izbor u Napredno.
- Opcionalni Face Detailer (Impact Pack + Subpack + face_yolov8m.pt) po osobi i u Napredno, zadano isključen jer na 8 GB VRAM-a može biti tijesan i spor. Ako instalacija ne uspije, opcija ostaje skrivena.
- Zaključaj seed po osobi da serije slika ostanu sličnije.
- Sažetak uz Osobu pokazuje broj referentnih slika, model i LoRA.
- Novi IG formati u izboru Formata: IG Portret 4:5 (1080×1350), IG Kvadrat 1:1 (1080×1080) i IG Story/Reels 9:16 (1080×1920). Generiraju se na manjem, VRAM-sigurnom platnu (SDXL npr. 896×1120, 1024×1024, 768×1368; SD 1.5 još manje), zatim se slika poveća lanczosom na točne IG piksele.

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

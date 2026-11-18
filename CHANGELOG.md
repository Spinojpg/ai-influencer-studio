# Promjene

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

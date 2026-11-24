#!/usr/bin/env bash
# Napravi studio.zip + sha256 + upis u CHANGELOG, spremno za:
#   gh release create "v$VER" dist/studio.zip dist/studio.zip.sha256 --title "$VER" --notes-file dist/RELEASE_NOTES.md
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Bez ispravnog inline JS-a UI je mrtav (1.0.16) - ne pakiraj takav paket.
if command -v node >/dev/null 2>&1; then
  python3 tools/check_ui_js.py || { echo "Prekid: UI JS ima sintaksnu grešku." >&2; exit 1; }
else
  echo "UPOZORENJE: node nije instaliran, preskačem provjeru UI JS-a." >&2
fi

CURRENT="$(python3 - <<'PY'
import json
from pathlib import Path
p = Path("version.json")
print((json.loads(p.read_text(encoding="utf-8")).get("version") if p.is_file() else "0.0.0") or "0.0.0")
PY
)"

BUMP="${1:-patch}"
NOTES="${2:-}"

NEXT="$(python3 - "$CURRENT" "$BUMP" <<'PY'
import sys, re
cur, bump = sys.argv[1], sys.argv[2]
raw = cur.strip()
if re.match(r"^v\d", raw, re.I):
    raw = raw[1:]
parts = [int(p) for p in re.split(r"[^\d]+", raw) if p != ""][:3]
while len(parts) < 3:
    parts.append(0)
major, minor, patch = parts
if re.fullmatch(r"\d+\.\d+\.\d+", bump):
    print(bump)
    raise SystemExit
if bump in ("major", "major+"):
    major, minor, patch = major + 1, 0, 0
elif bump in ("minor", "minor+"):
    minor, patch = minor + 1, 0
elif bump in ("patch", "patch+", ""):
    patch += 1
else:
    raise SystemExit(f"Nepoznat bump: {bump} (koristi patch|minor|major ili 1.2.3)")
print(f"{major}.{minor}.{patch}")
PY
)"

python3 - "$NEXT" <<'PY'
import json, sys
from pathlib import Path
ver = sys.argv[1]
path = Path("version.json")
data = {}
if path.is_file():
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}
if not isinstance(data, dict):
    data = {}
data["version"] = ver
data.setdefault("name", "AI Influencer Studio")
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("version.json ->", ver)
PY

python3 - "$NEXT" "$NOTES" <<'PY'
import datetime, sys
from pathlib import Path
ver, notes = sys.argv[1], sys.argv[2]
path = Path("CHANGELOG.md")
text = path.read_text(encoding="utf-8") if path.is_file() else "# Promjene\n"
date = datetime.date.today().isoformat()
entry = f"## {ver} — {date}\n"
if notes.strip():
    for line in notes.strip().splitlines():
        if line.startswith("- "):
            entry += f"{line}\n"
        else:
            entry += f"- {line}\n"
else:
    entry += "- Interno izdanje (dopuni ovaj unos prije objave).\n"
entry += "\n"
if f"## {ver} " in text or f"## {ver}\n" in text:
    print("CHANGELOG već ima", ver, "- ne diram.")
else:
    if text.startswith("# "):
        # umetni nakon naslova
        parts = text.split("\n", 1)
        rest = parts[1].lstrip("\n") if len(parts) > 1 else ""
        path.write_text(parts[0] + "\n\n" + entry + rest, encoding="utf-8")
    else:
        path.write_text("# Promjene\n\n" + entry + text, encoding="utf-8")
    print("CHANGELOG.md dopunjen")
# Kratke bilješke za gh --notes-file
from pathlib import Path as P
# izvuci tu sekciju
body = path.read_text(encoding="utf-8")
chunk = []
grab = False
for line in body.splitlines():
    if line.startswith("## "):
        if grab:
            break
        if line.startswith(f"## {ver}"):
            grab = True
            continue
        continue
    if grab:
        chunk.append(line)
notes_md = f"AI Influencer Studio {ver}\n\n" + "\n".join(chunk).strip() + "\n"
P("dist").mkdir(exist_ok=True)
P("dist/RELEASE_NOTES.md").write_text(notes_md, encoding="utf-8")
PY

# Pakiraj app datoteke (bez korisničkih podataka)
python3 - "$ROOT" "$NEXT" <<'PY'
import hashlib, sys, zipfile
from pathlib import Path

root = Path(sys.argv[1])
ver = sys.argv[2]
dist = root / "dist"
dist.mkdir(exist_ok=True)
zpath = dist / "studio.zip"

exclude_dirs = {
    "data", "__pycache__", ".git", "dist", "pending-update", "backup",
    ".app-staging", ".app-previous",
}
exclude_files = {
    ".env", "studio.db", "studio.pid", "update-result.json",
    "profiles.json", "persona.json",
    "HANDOFF.md",
    "setup_dev_windows.ps1",
}
exclude_suffixes = {".pyc", ".pyo"}
exclude_prefixes = {"screenshot"}

def skip(path: Path) -> bool:
    rel = path.relative_to(root)
    parts = rel.parts
    if any(p in exclude_dirs or p.startswith(".app-") for p in parts[:-1] or ()):
        return True
    if path.name in exclude_files:
        return True
    if path.suffix in exclude_suffixes:
        return True
    if path.name.startswith("screenshot"):
        return True
    return False

files = []
for p in sorted(root.rglob("*")):
    if not p.is_file():
        continue
    if skip(p):
        continue
    files.append(p)

# 1.1.0: obavezni dijelovi paketa (services/, static/, DOKUMENTACIJA.md) — bez njih nema izdanja
rels = {p.relative_to(root).as_posix() for p in files}
required = ["services/__init__.py", "services/common.py", "services/hardware_service.py", "services/generation_service.py",
            "services/posting_service.py", "services/crm_service.py", "static/v11.js", "static/v11.css", "DOKUMENTACIJA.md", "api_v11.py",
            "services/lora_trainer_service.py", "api_lora.py", "static/lora_trainer.js", "static/lora_trainer.css"]
missing = [r for r in required if r not in rels]
if missing:
    raise SystemExit("GRESKA: u paketu nedostaje: " + ", ".join(missing))

# ZIP s korijenskim folderom simple-studio/ (updater ga odvija)
with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        arc = Path("simple-studio") / p.relative_to(root)
        zf.write(p, arcname=str(arc).replace("\\", "/"))

digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
(dist / "studio.zip.sha256").write_text(f"{digest}  studio.zip\n", encoding="ascii")
print(f"Napisao {zpath} ({zpath.stat().st_size} bajtova, {len(files)} datoteka)")
print(f"sha256  {digest}")
PY

cat <<EOF

Spremno za objavu:

  gh release create "v${NEXT}" \\
    "${ROOT}/dist/studio.zip" \\
    "${ROOT}/dist/studio.zip.sha256" \\
    --title "AI Influencer Studio ${NEXT}" \\
    --notes-file "${ROOT}/dist/RELEASE_NOTES.md"

Trenutna verzija je sada ${NEXT} (prije ${CURRENT}).
U data/update.json na Windowsu stavi owner/repo ovog GitHub repozitorija.
EOF

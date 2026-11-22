#!/usr/bin/env python3
"""Build one zip per skill in dist/, ready to upload in claude.ai (Customize > Skills > Upload a skill).
Each zip holds one top-level folder with a single SKILL.md. Tests and caches are left out."""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "plugins" / "local-business-tools" / "skills"
SKIP = {"__pycache__", "tests", "data", "out"}

(ROOT / "dist").mkdir(exist_ok=True)
for skill in sorted(p for p in SKILLS.iterdir() if (p / "SKILL.md").exists()):
    target = ROOT / "dist" / f"{skill.name}.zip"
    files = [f for f in skill.rglob("*") if f.is_file() and not (set(f.relative_to(skill).parts) & SKIP) and f.suffix != ".pyc"]
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, Path(skill.name) / f.relative_to(skill))
    print(f"{target.name}: {len(files)} files, {target.stat().st_size // 1024} KB")

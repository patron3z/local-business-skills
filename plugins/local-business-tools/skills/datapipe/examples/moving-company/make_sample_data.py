#!/usr/bin/env python3
"""Genere des donnees FICTIVES pour essayer datapipe (une petite entreprise de demenagement imaginaire).
Generates FICTIONAL data to try datapipe. Nothing here comes from a real business.
Les donnees sont volontairement salies : formats de dates et de montants melanges, doublons, valeurs manquantes, valeurs extremes.
"""
import csv, random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)
OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)

SERVICES = [("Déménagement résidentiel", 0.50, 520, 5.5), ("Livraison", 0.20, 140, 1.8), ("Débarras", 0.20, 260, 3.0), ("Déménagement commercial", 0.10, 980, 8.0)]
CITIES = ["Montréal", "Montréal", "Montréal", "Laval", "Laval", "Longueuil", "Brossard", "Terrebonne", "Repentigny", "Châteauguay"]
SOURCES = [("Google", 0.34), ("Site web", 0.22), ("Bouche à oreille", 0.18), ("Facebook", 0.14), ("Kijiji", 0.12)]
CONV = {"Google": 0.46, "Site web": 0.40, "Bouche à oreille": 0.72, "Facebook": 0.22, "Kijiji": 0.16}
SEASON = {1: .55, 2: .6, 3: .7, 4: .85, 5: 1.05, 6: 1.5, 7: 1.9, 8: 1.2, 9: 1.0, 10: .8, 11: .6, 12: .5}


def pick(pairs):
    r, acc = random.random(), 0
    for item, w in pairs:
        acc += w
        if r <= acc:
            return item
    return pairs[-1][0]


def money(v):
    style = random.choice(["plain", "dollar", "comma", "space"])
    if style == "plain":
        return f"{v:.2f}"
    if style == "dollar":
        return f"{v:,.2f} $".replace(",", " ")
    if style == "comma":
        return f"{v:.2f}".replace(".", ",")
    return f"{v:,.0f} $".replace(",", " ")


def messy_date(d):
    return random.choice([d.isoformat(), d.strftime("%d/%m/%Y"), d.isoformat()])


start, end = date(2025, 9, 1), date(2026, 10, 31)
leads, jobs, n_lead, n_job = [], [], 0, 0
d = start
while d <= end:
    per_day = 3.2 * SEASON[d.month] * (0.6 if d.weekday() == 6 else 1.0)
    for _ in range(int(per_day) + (1 if random.random() < per_day % 1 else 0)):
        n_lead += 1
        src = pick(SOURCES)
        svc = pick([(s[0], s[1]) for s in SERVICES])
        won = random.random() < CONV[src]
        leads.append([f"L{n_lead:05d}", messy_date(d), src, svc, "oui" if won else "non"])
        if won:
            n_job += 1
            base, hrs = next((s[2], s[3]) for s in SERVICES if s[0] == svc)
            h = max(1.0, round(random.gauss(hrs, hrs * 0.25), 1))
            rev = round(h * (base / hrs) * random.uniform(0.85, 1.2), 2)
            jobs.append([f"J{n_job:05d}", f"L{n_lead:05d}", messy_date(d + timedelta(days=random.randint(1, 20))), svc, random.choice(CITIES),
                         money(rev), str(h).replace(".", random.choice([".", ","])), random.choice(["Équipe A", "Équipe B", "Équipe C"])])
    d += timedelta(days=1)

# salissures : doublons, valeurs manquantes, valeurs extremes
for _ in range(9):
    jobs.append(random.choice(jobs[:200]))
for _ in range(6):
    random.choice(jobs)[5] = ""
for _ in range(3):
    random.choice(jobs)[5] = money(random.uniform(9000, 14000))

with open(OUT / "jobs.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["ID Job", "Lead ID", "Date", "Service", "Ville", "Revenu", "Heures", "Équipe"])
    w.writerows(jobs)
with open(OUT / "leads.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Lead ID", "Date", "Source", "Service", "Converti"])
    w.writerows(leads)
with open(OUT / "expenses.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Date", "Catégorie", "Montant"])
    m = date(2025, 9, 1)
    while m <= end:
        s = SEASON[m.month]
        for cat, base in (("Essence", 1500 * s), ("Salaires", 9000 * (0.6 + 0.4 * s)), ("Assurance", 950), ("Entretien camions", 700 + random.uniform(0, 900))):
            w.writerow([m.replace(day=min(28, 10)).isoformat(), cat, money(base * random.uniform(0.93, 1.08))])
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
print(f"{len(jobs)} jobs, {len(leads)} leads ->", OUT)

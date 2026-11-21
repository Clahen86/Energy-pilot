"""Two backtests side by side, as Markdown for the job summary - totals only, never a single home.

    python training/compare.py base.json cand.json base_name cand_name"""
import json
import sys

base, cand = (json.load(open(p)) for p in sys.argv[1:3])
bn, cn = sys.argv[3], sys.argv[4]
print(f"## Prøvekørsel: {cn} mod {bn}\n")
if not cand.get("days"):
    homes = cand.get("homes") or 0
    print(f"{homes} huse har sendt time-tal, men ingen hele dage endnu." if homes else "Ingen data endnu - time-tallene samles fra 0.97.0.")
    sys.exit(0)
print(f"{cand['days']} dage fra {cand['homes']} huse.\n")
print("| | " + bn + " | " + cn + " |\n|---|---|---|")
for k, label in (("cost", "Strøm købt"), ("selfuse", "Batteriet alene"), ("none", "Uden batteri")):
    print(f"| {label} | {base[k]:.0f} | {cand[k]:.0f} |")
gain_b, gain_c = base["selfuse"] - base["cost"], cand["selfuse"] - cand["cost"]
print(f"| **Energipilots egen andel** | **{gain_b:.0f}** | **{gain_c:.0f}** |\n")
worse = [c for c, v in cand["by_country"].items() if v < base["by_country"].get(c, 0) - 1]
print(("⚠️ Dårligere i: " + ", ".join(worse)) if worse else "✅ Ingen lande fik det dårligere.")
if gain_c < gain_b - 1:
    print("\n❌ Den nye version sparer mindre end den udgivne.")
    sys.exit(1)

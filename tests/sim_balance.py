"""Headless balance sim: play many full runs per class, record death stats."""
import json
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import idlerpg as g

HS = os.path.join(tempfile.gettempdir(), "idledragons_sim_hs.json")

# Kill all UI overhead: dummy Live, silent death screen, hero snapshot spy.
class DummyLive:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def stop(self): pass
    def update(self, *a, **k): pass

g.Live = DummyLive
g.death_screen = lambda *a, **k: None
snap = {}
_orig_build = g.build_layout
def spy(hero, *a, **k):
    snap["hero"] = {"level": hero["level"], "depth": hero.get("depth", 1),
                    "turns": hero["turns"], "kills": hero["kills"]}
    return _orig_build(hero, *a, **k)
g.build_layout = spy

CAP = 20000
N = 20
summary = {}
for cls in g.CLASS_LIST:
    rows = []
    for seed in range(N):
        if os.path.exists(HS):
            os.remove(HS)
        g.HIGHSCORE_FILE = HS
        snap.clear()
        random.seed(10_000 + seed)
        g.run_game("Sim", cls, tick=0, demo_ticks=CAP)
        try:
            with open(HS) as f:
                scores = json.load(f)
        except FileNotFoundError:
            scores = []
        if scores:
            s = scores[0]
            rows.append({"fate": "died", "level": s["level"], "depth": s["depth"],
                         "turns": s["turns"], "killer": s["died_to"]})
        else:
            h = snap.get("hero", {})
            rows.append({"fate": "SURVIVED", "level": h.get("level"), "depth": h.get("depth"),
                         "turns": h.get("turns"), "killer": None})
    summary[cls] = rows

for cls, rows in summary.items():
    died = [r for r in rows if r["fate"] == "died"]
    surv = [r for r in rows if r["fate"] != "died"]
    lv = sorted(r["level"] for r in died)
    dp = sorted(r["depth"] for r in died)
    tn = sorted(r["turns"] for r in died)
    def med(xs):
        return xs[len(xs) // 2] if xs else None
    reach_d20 = sum(1 for r in rows if r["depth"] >= 20)
    reach_l20 = sum(1 for r in rows if r["level"] >= 20)
    print(f"{cls}: died {len(died)}/{N}, survived {len(surv)}/{N} | "
          f"reach depth20: {reach_d20}/{N}, reach level20: {reach_l20}/{N}")
    if died:
        print(f"   death level  min {lv[0]}  med {med(lv)}  max {lv[-1]}")
        print(f"   death depth  min {dp[0]}  med {med(dp)}  max {dp[-1]}")
        print(f"   turns        min {tn[0]}  med {med(tn)}  max {tn[-1]}")
        from collections import Counter
        print(f"   top killers: {Counter(r['killer'] for r in died).most_common(3)}")
    for r in surv:
        print(f"   SURVIVOR: level {r['level']} depth {r['depth']} turns {r['turns']}")
print("SIM DONE")

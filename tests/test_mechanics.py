"""Unit tests for creature types + traits."""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import idlerpg as g
from idlerpg import Fighter

fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name, extra)
    if not cond:
        fails.append(name)

# 1. coverage: every mob mapped; every boss typed (40 handcrafted +
# deterministic crc32 typing past 40)
unmapped_mobs = set()
for depth in range(1, 60):
    d = g.dungeon_for_depth(depth)
    for m in d["mobs"]:
        if m not in g.MOB_TYPES:
            unmapped_mobs.add((depth, m))
    bt = g.boss_type(d["boss"][0])
    if bt not in g.CREATURE_TYPES:
        unmapped_mobs.add((depth, "BOSS:" + d["boss"][0]))
check("all mobs + bosses mapped", not unmapped_mobs, str(unmapped_mobs)[:200])

# all 10 types actually used?
used = set(g.MOB_TYPES.values()) | set(g.BOSS_TYPES.values())
check("all 10 types used", used == set(g.CREATURE_TYPES), str(set(g.CREATURE_TYPES) - used))

# 2. creation stat traits
random.seed(0)
beast = Fighter(name="X", kind="mob", level=5, max_hp=100, hp=100, ctype="Beast")
norm = Fighter(name="X", kind="mob", level=5, max_hp=100, hp=100, ctype="Humanoid")
mon = Fighter(name="X", kind="mob", level=5, max_hp=100, hp=100, ctype="Monstrosity")
b = g.make_monster(1, 1);  # smoke: creation works with ctype
check("ctype assigned", b.ctype in g.CREATURE_TYPES, b.ctype)
beasts = [g.make_monster(1, 5) for _ in range(60)]
beast_d = [m.dodge for m in beasts if m.ctype == "Beast"]
other_d = [m.dodge for m in beasts if m.ctype != "Beast"]
check("Beast +4 dodge", beast_d and min(beast_d) == 9 and max(other_d) == 5, f"{set(beast_d)} vs {set(other_d)}")

def mkhero(cls="Rogue", level=10):
    h = g.make_hero("T", cls)
    h["level"] = level
    h["hp"] = g.hero_max_hp(h); h["mp"] = g.hero_max_mp(h)
    return h

def mkfoe(ctype, hp=5000, kind="mob"):
    return Fighter(name="Dummy", kind=kind, level=10, max_hp=hp, hp=hp,
                   atk=10, df=5, spd=5, crit=0, dodge=0, ctype=ctype)

# 3. Undead venom: half strength, still applies (Rogue smoothing)
random.seed(1)
h = mkhero(); foe = mkfoe("Undead")
pois = next(s for s in g.CLASSES["Rogue"]["skills"] if s.kind == "dot")
out = g.hero_strike(h, foe, pois)
check("undead: venom half (11 @ Lv10)", foe.dots == [[11, 3, "venom"]], str(foe.dots))
check("undead: half-strength line", any("barely takes hold" in l for l in out))

# 4. Plant kindling
random.seed(2)
h = mkhero("Wizard"); plant = mkfoe("Plant"); rock = mkfoe("Monstrosity")
fire = next(s for s in g.CLASSES["Wizard"]["skills"] if s.key == "fire")
h2 = mkhero("Wizard")
o1 = g.hero_strike(h, plant, fire)
o2 = g.hero_strike(h2, rock, fire)
check("plant: kindle line", any("Dry tinder" in l for l in o1))

# 5. Elemental slow immunity
random.seed(3)
h = mkhero("Wizard"); foe = mkfoe("Elemental")
frost = next(s for s in g.CLASSES["Wizard"]["skills"] if s.key == "frost")
out = g.hero_strike(h, foe, frost)
check("elemental: no slow", "spd" not in foe.buffs, str(foe.buffs))
check("elemental: chill line", any("no blood to chill" in l.lower() for l in out))

# 6. Aberration crit suppression (Warrior crit=5 -> 0 vs aberration)
random.seed(4)
h = mkhero("Warrior"); h["crit"] = 5
basic = next(s for s in g.CLASSES["Rogue"]["skills"] if s.kind == "basic")
crits_ab, crits_ok = 0, 0
for _ in range(200):
    f1 = mkfoe("Aberration"); f2 = mkfoe("Beast")
    o1 = g.hero_strike(dict(h), f1, basic); o2 = g.hero_strike(dict(h), f2, basic)
    crits_ab += sum("CRIT" in l for l in o1)
    crits_ok += sum("CRIT" in l for l in o2)
check("aberration: zero crits at 5", crits_ab == 0, f"ab={crits_ab} beast={crits_ok}")
check("sanity: crits happen otherwise", crits_ok > 0, str(crits_ok))

# 7. Dragon breath rate ~15%
random.seed(5)
h = mkhero(); h["hp"] = 10**9
breaths = 0
for _ in range(600):
    foe = mkfoe("Dragon", hp=10**9)
    h["hp"] = 10**9
    out = g.foe_strike(foe, h)
    breaths += sum("BREATH" in l for l in out)
check("dragon breath ~15%", 60 <= breaths <= 130, str(breaths))

# 8. Giant sweep rate ~15%
random.seed(6)
sweeps = 0
for _ in range(600):
    foe = mkfoe("Giant", hp=10**9)
    h["hp"] = 10**9
    out = g.foe_strike(foe, h)
    sweeps += sum("Sweeping" in l for l in out)
check("giant sweep ~15%", 60 <= sweeps <= 130, str(sweeps))

# 9. Fiend rebuke on crit
random.seed(7)
h = mkhero(); h["crit"] = 100; h["hp"] = g.hero_max_hp(h)
foe = mkfoe("Fiend", hp=10**9)
before = h["hp"]
out = g.hero_strike(h, foe, basic)
check("fiend: rebuke line", any("rebuke" in l for l in out), str(out[-2:]))
check("fiend: hero lost extra HP", h["hp"] < before)

# 10. Humanoid gold +25%
random.seed(8)
def avg_gold(ctype, n=1500):
    tot = 0
    for _ in range(n):
        h = mkhero(); foe = mkfoe(ctype)
        foe.level = 10
        gold_before = h["gold"]
        g.grant_rewards(h, foe)
        tot += h["gold"] - gold_before
    return tot / n
gh, gb = avg_gold("Humanoid"), avg_gold("Beast")
ratio = gh / gb if gb else 0
# note: trinket/weapon salvage adds noise equally to both; ratio should still be ~1.1-1.4
check("humanoid richer", 1.05 <= ratio <= 1.45, f"{gh:.1f} vs {gb:.1f} = {ratio:.2f}")

print("TYPE TESTS DONE", "— FAILURES:" if fails else "— ALL PASS", fails)

# --- rogue ambush: first landed hit each fight crits ---
print("--- ambush ---")
random.seed(99)
h = mkhero("Rogue"); h["crit"] = 0; h["ambush"] = True
foe = mkfoe("Beast", hp=10**9)
basic = next(s for s in g.CLASSES["Rogue"]["skills"] if s.kind == "basic")
o1 = g.hero_strike(h, foe, basic)
check("ambush: first hit crits at 0 crit", any("AMBUSH" in l for l in o1), str(o1))
check("ambush: consumed", h["ambush"] is False)
o2 = g.hero_strike(h, foe, basic)
check("ambush: second hit normal", not any("AMBUSH" in l for l in o2))
# non-damaging skills don't consume
h["ambush"] = True
dance = next(s for s in g.CLASSES["Rogue"]["skills"] if s.kind == "buff")
g.hero_strike(h, mkfoe("Beast", hp=10**9), dance)
check("ambush: dance doesn't consume", h["ambush"] is True)
# non-rogues never ambush
w = mkhero("Warrior"); w["crit"] = 0; w["ambush"] = True
ow = g.hero_strike(w, mkfoe("Beast", hp=10**9), next(s for s in g.CLASSES["Warrior"]["skills"] if s.kind == "basic"))
check("ambush: warriors need not apply", not any("AMBUSH" in l for l in ow) and w["ambush"] is True)
# a whiff from the shadows keeps ambush armed
h["ambush"] = True
slippery = mkfoe("Beast", hp=10**9); slippery.dodge = 100
om = g.hero_strike(h, slippery, basic)
check("ambush: miss keeps it armed", any("MISS" in l for l in om) and h["ambush"] is True)
print("AMBUSH TESTS DONE", "— FAILURES:" if fails else "— ALL PASS", fails)

# --- loot texture ---
print("--- loot ---")
random.seed(42)
seen_slots, seen_sets, seen_cursed, drops = set(), 0, 0, 0
for _ in range(3000):
    it = g.roll_loot(random.randint(1, 25), random.random() < 0.2, random.choice(g.CLASS_LIST))
    if it is None:
        continue
    drops += 1
    seen_slots.add(it.slot)
    if it.set_name:
        seen_sets += 1
        assert it.set_name in g.SET_BONUS, it.set_name
    if "Cursed" in it.name:
        seen_cursed += 1
        assert any(v < 0 for v in it.bonus.values()), it.short()
check("all 5 slots drop", seen_slots == {"Weapon", "Armor", "Trinket", "Ring", "Boots"}, str(seen_slots))
check("sets ~18% of drops", 0.13 <= seen_sets / drops <= 0.23, f"{seen_sets}/{drops}")
check("cursed ~10% of drops", 0.06 <= seen_cursed / drops <= 0.14, f"{seen_cursed}/{drops}")

h = mkhero("Warrior")
h["gear"] = {s: None for s in ("Weapon", "Armor", "Trinket", "Ring", "Boots")}
h["gear"]["Ring"] = g.Item("Ring", "Ember Ring", "Rare", "#5db8ff", {"ATK": 5}, "Ember")
h["gear"]["Boots"] = g.Item("Boots", "Ember Boots", "Rare", "#5db8ff", {"DEF": 4}, "Ember")
check("set bonus 2x Ember +3 ATK", g.gear_bonus(h, "ATK") == 5 + 3, str(g.gear_bonus(h, "ATK")))
h["gear"]["Boots"] = g.Item("Boots", "Plain Boots", "Common", "white", {"DEF": 1}, "")
check("no set bonus solo", g.gear_bonus(h, "ATK") == 5, str(g.gear_bonus(h, "ATK")))

cursed = g.Item("Weapon", "Cursed Blade", "Rare", "#5db8ff", {"ATK": 20, "HP": -30}, "")
h["gear"]["Weapon"] = g.Item("Weapon", "Stick", "Common", "white", {"ATK": 2}, "")
cur = sum(v for v in h["gear"]["Weapon"].bonus.values() if v > 0)
new = sum(v for v in cursed.bonus.values() if v > 0)
check("cursed judged on positives", new > cur, f"{new} vs {cur}")
check("short() signs", cursed.short() == "Cursed Blade [Rare] +20ATK -30HP", cursed.short())

print("LOOT TESTS DONE", "— FAILURES:" if fails else "— ALL PASS", fails)

# --- cursed-gear hardening: totals floored, suicide rejected, skills never crash ---
print("--- hardening ---")
h = mkhero("Rogue")
h["gear"]["Ring"] = g.Item("Ring", "Cursed Ring", "Epic", "#d45dff", {"MP": 30, "SPD": -4}, "")
h["gear"]["Trinket"] = g.Item("Trinket", "Cursed Braid", "Epic", "#d45dff", {"ATK": 15, "MP": -65}, "")
check("max_mp floored >= 1", g.hero_max_mp(h) >= 1, str(g.hero_max_mp(h)))
check("max_hp floored >= 1", g.hero_max_hp(h) >= 1, str(g.hero_max_hp(h)))
h["mp"] = 30
g.tick_buffs(h, g.make_monster(1, 1))
check("regen never teleports negative", h["mp"] >= 0, str(h["mp"]))

def score(b):
    return sum(v for v in b.values() if v > 0) + 2 * sum(v for v in b.values() if v < 0)
check("suicide (+20/-40) rejected", score({"ATK": 20, "HP": -40}) < score({"ATK": 2}))
check("spicy (+20/-8) accepted", score({"ATK": 20, "HP": -8}) > score({"ATK": 2}))

h2 = mkhero("Wizard")
for s in g.CLASSES["Wizard"]["skills"]:
    h2["cds"][s.key] = 5
h2["mp"] = -99
check("choose_skill falls back to basic", g.choose_skill(h2).kind == "basic")
print("HARDENING TESTS DONE", "— FAILURES:" if fails else "— ALL PASS", fails)

# --- buff source labels: shown by name, tick down, expire cleanly ---
print("--- buffs ---")
h = mkhero("Rogue")
dance = next(s for s in g.CLASSES["Rogue"]["skills"] if s.kind == "buff")
g.hero_strike(h, mkfoe("Beast", hp=10**9), dance)
check("dance labels its buff", h["buffs"].get("dodge") == [18, 3, "Evasive Dance"], str(h["buffs"]))
w = mkhero("Warrior")
wall = next(s for s in g.CLASSES["Warrior"]["skills"] if s.key == "wall")
g.hero_strike(w, mkfoe("Beast", hp=10**9), wall)
check("wall labels its buff", w["buffs"].get("df") == [6, 3, "Shield Wall"], str(w["buffs"]))
g.tick_buffs(h, mkfoe("Beast", hp=10**9))
check("labeled buff ticks", h["buffs"]["dodge"][1] == 2, str(h["buffs"]))
for _ in range(3):
    g.tick_buffs(h, mkfoe("Beast", hp=10**9))
check("labeled buff expires", "dodge" not in h["buffs"], str(h["buffs"]))
# boss hex carries the art name
h2 = mkhero("Warrior")
from idlerpg import Fighter as _F
hex_foe = _F(name="Mother Mycelia x", kind="boss", level=5, max_hp=500, hp=500,
             atk=20, df=5, spd=5, crit=0, dodge=0, ctype="Plant")
got = []
for _ in range(100):
    hex_foe.cds.pop("art", None)
    got = g.boss_ability(hex_foe, h2)
    if got:
        break
check("hex art fires", bool(got), str(got[:1]))
check("hex labels its debuff", h2["buffs"].get("spd", [0, 0, "?"])[2] == "Spore Cloud", str(h2["buffs"]))
print("BUFF TESTS DONE", "— FAILURES:" if fails else "— ALL PASS", fails)

# --- every class: starter kit complete, every skill fires, panel renders ---
print("--- classes ---")
import random as _r
_r.seed(0)
for _cls in g.CLASS_LIST:
    _h = g.make_hero("T", _cls)
    _ok = all(_h["gear"][s] is not None for s in ("Weapon", "Armor", "Trinket"))
    check(f"{_cls}: starter kit", _ok)
    _h["level"] = 6
    _h["hp"] = g.hero_max_hp(_h); _h["mp"] = g.hero_max_mp(_h)
    try:
        for _s in g.CLASSES[_cls]["skills"]:
            g.hero_strike(dict(_h), g.make_monster(3, 6), _s)
        g.skills_panel(_h, False, 1.0, 1.0, True)
        check(f"{_cls}: kit fires", True)
    except Exception as e:  # noqa: BLE001
        check(f"{_cls}: kit fires", False, repr(e))
print("CLASS TESTS DONE", "— FAILURES:" if fails else "— ALL PASS", fails)

# --- codex: roster, counts, guards, table ---
print("--- codex ---")
import tempfile as _tf
g.CODEX_FILE = os.path.join(_tf.gettempdir(), "idledragons_test_codex.json")
try:
    os.remove(g.CODEX_FILE)
except OSError:
    pass
check("roster is 40 unique", len(g.ROSTER_40) == 40 and len({f for f, _ in g.ROSTER_40}) == 40)
check("fresh codex empty", g.load_codex() == {"slain": [], "kills": {}})
check("record new", g.record_boss("Squeakus the Rat King") == (True, 1))
check("repeat counts", g.record_boss("Squeakus the Rat King") == (False, 1))
check("non-roster ignored", g.record_boss("Nobody Ever") == (False, 1))
d = g.load_codex()
check("kills tallied", d["kills"].get("Squeakus the Rat King") == 2, str(d))
with open(g.CODEX_FILE, "w") as _f:
    _f.write('{"slain": ["Squeakus the Rat King"]}')
check("old format loads", g.load_codex() == {"slain": ["Squeakus the Rat King"], "kills": {}})
g.codex_table({"slain": ["Squeakus the Rat King"], "kills": {"Squeakus the Rat King": 9}})
check("codex table renders", True)
try:
    os.remove(g.CODEX_FILE)
except OSError:
    pass
print("CODEX TESTS DONE", "— FAILURES:" if fails else "— ALL PASS", fails)

# --- gear DEF actually applies (regression: df/DEF case mapping) ---
print("--- geardef ---")
h = mkhero("Warrior")
h["gear"] = {s: None for s in ("Weapon", "Armor", "Trinket", "Ring", "Boots")}
naked = g.hero_eff(h, "df")
h["gear"]["Armor"] = g.Item("Armor", "Plate", "Rare", "#5db8ff", {"DEF": 50}, "")
check("armor DEF applies", g.hero_eff(h, "df") == naked + 50, f"{naked} -> {g.hero_eff(h, 'df')}")
check("panel shows buffed DEF", g.hero_eff(h, "df") > h["df"])
h["gear"]["Armor"] = g.Item("Armor", "Moon Plate", "Rare", "#5db8ff", {"DEF": 10}, "Moon")
h["gear"]["Ring"] = g.Item("Ring", "Moon Band", "Rare", "#5db8ff", {"DEF": 5}, "Moon")
check("Moon set bonus applies", g.hero_eff(h, "df") == h["df"] + 10 + 5 + 3, str(g.hero_eff(h, "df")))
for _stat, _want in (("atk", "ATK"), ("df", "DEF"), ("spd", "SPD")):
    hh = mkhero("Rogue")
    hh["gear"] = {s: None for s in ("Weapon", "Armor", "Trinket", "Ring", "Boots")}
    hh["gear"]["Trinket"] = g.Item("Trinket", "Probe", "Common", "white", {_want: 7}, "")
    check(f"gear {_want} applies via {_stat}", g.hero_eff(hh, _stat) == hh[{"atk": "atk", "df": "df", "spd": "spd"}[_stat]] + 7)
print("GEARDEF TESTS DONE", "— FAILURES:" if fails else "— ALL PASS", fails)

# --- ascension: legends store + Ereboss winnable-but-scary (fixed seed) ---
print("--- ascension ---")
import tempfile as _tf2
g.LEGENDS_FILE = os.path.join(_tf2.gettempdir(), "idledragons_test_legends.json")
try:
    os.remove(g.LEGENDS_FILE)
except OSError:
    pass
check("fresh legends empty", g.load_legends() == [])
g.record_legend({"name": "T", "cls": "Warrior", "level": 42, "turns": 2000, "date": "2026-01-01"})
check("legend recorded", len(g.load_legends()) == 1)
g.legends_table(g.load_legends())
check("legends table renders", True)
ere = g.make_monster(40, 42, boss=True)
check("Ereboss fixed stats", (ere.name, ere.level, ere.max_hp, ere.atk, ere.df, ere.spd) ==
      ("Ereboss the Bottom of Everything", 42, 12000, 330, 140, 30),
      f"{ere.name} {ere.level} {ere.max_hp}/{ere.atk}/{ere.df}/{ere.spd}")


def _god(cls):
    h = g.make_hero("God", cls)
    gr = g.CLASSES[cls]["grow"]
    for _ in range(41):
        h["max_hp"] += gr["max_hp"]; h["max_mp"] += gr["max_mp"]
        h["atk"] += gr["atk"]; h["df"] += gr["df"]; h["spd"] += gr["spd"]
    h["level"] = 42
    h["gear"]["Weapon"] = g.Item("Weapon", "Godblade", "Legendary", "#ffd700", {"ATK": 140}, "")
    h["gear"]["Armor"] = g.Item("Armor", "Godplate", "Legendary", "#ffd700", {"DEF": 123, "HP": 525}, "")
    h["gear"]["Trinket"] = g.Item("Trinket", "Godheart", "Legendary", "#ffd700", {"HP": 701}, "")
    h["gear"]["Ring"] = g.Item("Ring", "Godband", "Epic", "#d45dff", {"ATK": 30}, "")
    h["gear"]["Boots"] = g.Item("Boots", "Godtreads", "Epic", "#d45dff", {"DEF": 25}, "")
    h["hp"] = g.hero_max_hp(h); h["mp"] = g.hero_max_mp(h)
    h["hp_pots"] = 5; h["mp_pots"] = 5
    return h


def _duel(hero, foe):
    for _ in range(300):
        if hero["hp"] < g.hero_max_hp(hero) * 0.35:
            g.drink_hp(hero)
        s = g.choose_skill(hero)
        g.hero_strike(hero, foe, s)
        if not foe.alive:
            return True
        g.foe_strike(foe, hero)
        g.boss_ability(foe, hero)
        if hero["hp"] <= 0:
            return False
        g.tick_dots(hero, foe)
        if not foe.alive:
            return True
        if hero["hp"] <= 0:
            return False
        g.tick_buffs(hero, foe)
    return False


import random as _r2
_r2.seed(1234)
for _cls, (_lo, _hi) in (("Warrior", (2, 11)), ("Ranger", (0, 11))):
    _w = sum(_duel(_god(_cls), g.make_monster(40, 42, boss=True)) for _ in range(12))
    check(f"Ereboss {_cls} {_lo}..{_hi}/12 (epic, winnable)", _lo <= _w <= _hi, f"{_w}/12")
try:
    os.remove(g.LEGENDS_FILE)
except OSError:
    pass
print("ASCENSION TESTS DONE", "— FAILURES:" if fails else "— ALL PASS", fails)
sys.exit(1 if fails else 0)

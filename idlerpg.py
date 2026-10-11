#!/usr/bin/env python3
"""
IDLEDRAGONS — a pretty DnD-themed terminal idleRPG.
Single-screen watcher: pick a name + class, then watch the dive unfold.

Run:
    uv run --with rich python idlerpg.py
    # or
    pip install rich && python idlerpg.py

Controls (during the run — a pure watcher, no combat input):
    SPACE .... pause / resume       +/- .. game speed (0.5x-8x)
    A ........ auto-potions on/off  Q .... quit (abandon run, not scored)
    Potions quaff themselves when needed. Sit back and watch.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import random
import select
import sys
import time
import zlib
from collections import deque
from dataclasses import dataclass, field

try:
    from rich import box
    from rich.align import Align
    from rich.console import Console, Group
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError:  # pragma: no cover
    print("This game needs the 'rich' library.")
    print("  uv run --with rich python idlerpg.py")
    print("  pip install rich && python idlerpg.py")
    sys.exit(1)

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

HIGHSCORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "highscores.json")
TICK_DEFAULT = 1.0
SPEEDS = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]   # multipliers on the base tick; +/- steps through these
DEFAULT_SPEED_IDX = 1                      # ...starting at 1x
ROOMS_PER_LEVEL = 5          # normal fights per dungeon level, then the boss
MAX_LOG = 12
MAX_POTIONS_BASE = 3
POTION_HP_PRICE = 40
POTION_MP_PRICE = 30
POTION_HP_PCT = 0.45
POTION_MP_PCT = 0.50

TITLE_ART = r"""
  ___ ___  _    ___ ___ ___   _   ___  ___  _  _ ___
 |_ _|   \| |  | __|   \ _ \ /_\ / __|/ _ \| \| / __|
  | || |) | |__| _|| |) /   // _ \ (_ | (_) | .` \__ \
 |___|___/|____|___|___/___/_/ \_\___|\___/|_|\_|___/
"""

D20 = "\u25c8"  # diamond used as d20-ish glyph

RARITIES = [
    ("Common",    "white",         1.00),
    ("Uncommon",  "#5dff7a",       1.18),
    ("Rare",      "#5db8ff",       1.40),
    ("Epic",      "#d45dff",       1.70),
    ("Legendary", "#ffd700",       2.10),
]
RARITY_RANK = {n: i for i, (n, _, _) in enumerate(RARITIES)}

WEAPON_NAMES = {
    "Warrior": ["Shortsword", "Hand Axe", "Warhammer", "Longsword", "Greataxe", "Dragonslayer Blade"],
    "Rogue":   ["Dagger", "Stiletto", "Short Bow", "Poisoned Fang", "Shadow Shiv", "Nightwhisper Blade"],
    "Cleric":  ["Mace", "War Maul", "Blessed Flail", "Sunforged Mace", "Dawnbringer"],
    "Wizard":  ["Oak Staff", "Apprentice Wand", "Runed Staff", "Stormcaller Rod", "Archmage Staff"],
}
ARMOR_NAMES = ["Cloth Rags", "Leather Jerkin", "Chain Shirt", "Scale Mail", "Plate Cuirass",
               "Mithral Mail", "Dragonscale Armor"]
TRINKET_NAMES = ["Bone Charm", "Lucky Coin", "Wolf Fang", "Moonstone Ring", "Amulet of Embers",
                 "Eye of the Oracle", "Dragon Heart Pendant"]
RING_NAMES = ["Copper Band", "Bone Ring", "Serpent Ring", "Moonstone Band",
              "Ring of Embers", "Archlich Band"]
BOOT_NAMES = ["Traveler's Boots", "Silent Moccasins", "Iron Greaves",
              "Boots of Striding", "Dragonscale Boots"]
# Gear sets: wear 2+ pieces sharing a set for the bonus. Items opt in at roll.
SET_BONUS = {
    "Ember": {"ATK": 3},
    "Moon": {"DEF": 3},
    "Storm": {"SPD": 2},
    "Grave": {"HP": 25},
}

# --------------------------------------------------------------------------- #
# Dungeons — every level has a theme + a NAMED boss
# --------------------------------------------------------------------------- #

DUNGEONS = [
    {"name": "The Whispering Cellar", "icon": "\U0001f42d", "color": "#9a9a9a",
     "desc": "Damp stone, skittering claws.",
     "mobs": ["Cellar Rat", "Giant Centipede", "Kobold Sneak", "Cave Bat Swarm"],
     "boss": ("Squeakus", "the Rat King")},
    {"name": "Goblin Warrens", "icon": "\U0001f47a", "color": "#5dff7a",
     "desc": "Crude totems, war-drum echoes.",
     "mobs": ["Goblin Cutter", "Goblin Slinger", "Worg Pup", "Hobgoblin Grunt"],
     "boss": ("Griznak", "One-Eye, Goblin Chieftain")},
    {"name": "The Fungal Grotto", "icon": "\U0001f344", "color": "#7affd4",
     "desc": "Spores drift like snow.",
     "mobs": ["Myconid Sprout", "Spore Bat", "Cave Fisher", "Gas Spore"],
     "boss": ("Mother Mycelia", "the Bloom That Hungers")},
    {"name": "The Sunken Crypt", "icon": "\U0001f480", "color": "#5db8ff",
     "desc": "Flooded sarcophagi, old oaths.",
     "mobs": ["Skeleton Warrior", "Drowned Zombie", "Crypt Ghoul", "Wight Acolyte"],
     "boss": ("Lord Vexmar", "the Twice-Buried")},
    {"name": "Ember Depths", "icon": "\U0001f525", "color": "#ff7a3c",
     "desc": "Obsidian glass, rivers of slag.",
     "mobs": ["Magma Mephit", "Fire Snake", "Ash Zombie", "Duergar Deserter"],
     "boss": ("Cinder Maw", "the Furnace Given Teeth")},
    {"name": "The Drow Vaults", "icon": "\U0001f573", "color": "#d45dff",
     "desc": "Webs between black pillars.",
     "mobs": ["Giant Spider", "Drow Scout", "Drider Spawn", "Shadow Mastiff"],
     "boss": ("Vexalyth", "Priestess of the Eighth House")},
    {"name": "Stormspire Ruins", "icon": "\U0001f329", "color": "#aee9ff",
     "desc": "Broken towers chew lightning.",
     "mobs": ["Air Elemental Wisp", "Gargoyle", "Kenku Stormcaller", "Blue Dragon Wyrmling"],
     "boss": ("Sussurax", "the Wing That Splits Clouds")},
    {"name": "The Throne of Teeth", "icon": "\U0001f451", "color": "#ffd700",
     "desc": "A dragon's hoard. Something breathes.",
     "mobs": ["Ogre Brute", "Troll Regenerator", "Mind Flayer Exile", "Young Red Dragon"],
     "boss": ("Vermithrax Pejorative", "the Hoardfather")},
]

BOSS_FIRST = ["Morgath", "Yx", "Bal", "Khar", "Zul", "Thar", "Oom", "Vex", "Drak", "Skar"]
BOSS_LAST = ["gore", "mirax", "thune", "zarr", "phage", "drex", "morth", "qua", "zoth", "lish"]
BOSS_TITLES = ["the Unsleeping", "the Maw Below", "the Ninth Hunger", "the Crown of Worms",
               "the Pale Tyrant", "the Echo of Ruin", "the Deep Ordained", "the Last Argument"]


# Fixed named bosses for depths 9-40: the same challenge for every hero,
# every run. (Depths 1-8 live in DUNGEONS; past 40 the Deep Dark names
# its own — still deterministic per depth, so those never change either.)
DEEP_BOSSES = [
    (9,  "Tharzarr",  "the Echo of Ruin"),
    (10, "Drakphage", "the Unsleeping"),
    (11, "Yxmirax",   "the Deep Ordained"),
    (12, "Balgore",   "the Maw Below"),
    (13, "Oomzarr",   "the Pale Tyrant"),
    (14, "Kharvex",   "the Crown of Worms"),
    (15, "Zulphage",  "the Render"),
    (16, "Tharquam",  "the Wingless Dread"),
    (17, "Mordrex",   "the Throne of Flies"),
    (18, "Vexmorth",  "the Last Argument"),
    (19, "Skarlith",  "the Ember Saint"),
    (20, "Xarzoth",   "the God Below Rent"),
    (21, "Balzoth",   "the Hollow King"),
    (22, "Oomthune",  "the Starved Choir"),
    (23, "Yxquath",   "the Mouth of the Deep"),
    (24, "Tharzoth",  "the Twice-Drowned King"),
    (25, "Vexmirax",  "the Ninth Hunger"),
    (26, "Drakovex",  "the Chain of Night"),
    (27, "Skardrex",  "the Furnace Cold"),
    (28, "Morgath",   "the Father of Echoes"),
    (29, "Kharzarr",  "the Siege Eternal"),
    (30, "Thulzarr",  "the Tide That Hates"),
    (31, "Yxlim",     "the Smallest God"),
    (32, "Drexbal",   "the Anvil of Teeth"),
    (33, "Vexthune",  "the Elegy"),
    (34, "Skalphage", "the Map-Eater"),
    (35, "Oomgore",   "the Red Silence"),
    (36, "Balqua",    "the Thirsting Dark"),
    (37, "Zulmorth",  "the Penultimate"),
    (38, "Kharqua",   "the Warden of the Last Door"),
    (39, "Drextharr", "the Almost God"),
    (40, "Ereboss",   "the Bottom of Everything"),
]
assert [d for d, _, _ in DEEP_BOSSES] == list(range(9, 41))


# --------------------------------------------------------------------------- #
# Creature types — every monster is something: goblin, spider, dragon...
# Each type has a small combat trait (see hero_strike / foe_strike).
# --------------------------------------------------------------------------- #

CREATURE_TYPES = {
    "Aberration": "#d45dff",
    "Beast": "#9db36a",
    "Dragon": "#ff5b5b",
    "Elemental": "#ff9a3c",
    "Fiend": "#b03a2e",
    "Giant": "#c9a227",
    "Humanoid": "#5db8ff",
    "Monstrosity": "#e08e45",
    "Plant": "#5dff7a",
    "Undead": "#9a9a9a",
}

MOB_TYPES = {
    "Cellar Rat": "Beast", "Giant Centipede": "Beast",
    "Kobold Sneak": "Humanoid", "Cave Bat Swarm": "Beast",
    "Goblin Cutter": "Humanoid", "Goblin Slinger": "Humanoid",
    "Worg Pup": "Beast", "Hobgoblin Grunt": "Humanoid",
    "Myconid Sprout": "Plant", "Spore Bat": "Beast",
    "Cave Fisher": "Monstrosity", "Gas Spore": "Plant",
    "Skeleton Warrior": "Undead", "Drowned Zombie": "Undead",
    "Crypt Ghoul": "Undead", "Wight Acolyte": "Undead",
    "Magma Mephit": "Elemental", "Fire Snake": "Elemental",
    "Ash Zombie": "Undead", "Duergar Deserter": "Humanoid",
    "Giant Spider": "Beast", "Drow Scout": "Humanoid",
    "Drider Spawn": "Monstrosity", "Shadow Mastiff": "Monstrosity",
    "Air Elemental Wisp": "Elemental", "Gargoyle": "Elemental",
    "Kenku Stormcaller": "Humanoid", "Blue Dragon Wyrmling": "Dragon",
    "Ogre Brute": "Giant", "Troll Regenerator": "Giant",
    "Mind Flayer Exile": "Aberration", "Young Red Dragon": "Dragon",
    "Depth Horror": "Aberration", "Starved Abomination": "Monstrosity",
    "Whisper Spawn": "Fiend", "Chitin Stalker": "Beast",
    # The Drowned Halls (9-12)
    "Silt Crab": "Beast", "Drowned Sailor": "Undead",
    "Brine Hag": "Monstrosity", "Wreck Revenant": "Undead",
    # The Ashen Wastes (13-16)
    "Cinder Imp": "Fiend", "Ash Serpent": "Elemental",
    "Charred Husk": "Undead", "Slag Golem": "Elemental",
    # The Hollow Deep (17-20)
    "Nothic Whisperer": "Aberration", "Choker": "Aberration",
    "Darkmantle": "Monstrosity", "Grell": "Aberration",
    # The Frozen Tomb (21-24)
    "Ice Mephit": "Elemental", "Frost Wight": "Undead",
    "Winter Wolf": "Monstrosity", "Yeti": "Monstrosity",
    # The Brass Hells (25-28)
    "Lemure": "Fiend", "Spined Devil": "Fiend",
    "Hell Hound": "Fiend", "Ashen Cultist": "Humanoid",
    # The Shattered Peaks (29-32)
    "Hill Giant": "Giant", "Stone Giant": "Giant",
    "Wyvern": "Dragon", "Griffon": "Monstrosity",
    # The Starless Vault (33-36)
    "Beholderkin": "Aberration", "Intellect Devourer": "Aberration",
    "Cloaker": "Aberration", "Aboleth Spawn": "Aberration",
    # The Throne Below (37-40)
    "Death Knight": "Undead", "Balor Spawn": "Fiend",
    "Elder Wyrm": "Dragon", "Void Titan": "Aberration",
}

BOSS_TYPES = {
    "Squeakus": "Beast", "Griznak": "Humanoid",
    "Mother Mycelia": "Plant", "Lord Vexmar": "Undead",
    "Cinder Maw": "Elemental", "Vexalyth": "Humanoid",
    "Sussurax": "Dragon", "Vermithrax Pejorative": "Dragon",
    "Tharzarr": "Aberration", "Drakphage": "Dragon",
    "Yxmirax": "Aberration", "Balgore": "Fiend",
    "Oomzarr": "Undead", "Kharvex": "Fiend",
    "Zulphage": "Monstrosity", "Tharquam": "Dragon",
    "Mordrex": "Fiend", "Vexmorth": "Aberration",
    "Skarlith": "Elemental", "Xarzoth": "Dragon",
    "Balzoth": "Undead", "Oomthune": "Aberration",
    "Yxquath": "Aberration", "Tharzoth": "Undead",
    "Vexmirax": "Dragon", "Drakovex": "Dragon",
    "Skardrex": "Elemental", "Morgath": "Undead",
    "Kharzarr": "Giant", "Thulzarr": "Elemental",
    "Yxlim": "Aberration", "Drexbal": "Monstrosity",
    "Vexthune": "Undead", "Skalphage": "Aberration",
    "Oomgore": "Fiend", "Balqua": "Fiend",
    "Zulmorth": "Undead", "Kharqua": "Monstrosity",
    "Drextharr": "Dragon", "Ereboss": "Aberration",
}


def boss_type(first: str) -> str:
    """Creature type of a boss by first name. Handcrafted to depth 40;
    deeper names are generated — typed deterministically (crc32) so the
    same depth is still the same challenge every run."""
    if first in BOSS_TYPES:
        return BOSS_TYPES[first]
    return sorted(CREATURE_TYPES)[zlib.crc32(first.encode()) % len(CREATURE_TYPES)]


def dungeon_for_depth(depth: int) -> dict:
    if depth <= len(DUNGEONS):
        return DUNGEONS[depth - 1]
    if 9 <= depth <= 40:
        _, first, title = next(e for e in DEEP_BOSSES if e[0] == depth)
        boss = (first, title)
        theme = STRATA[(depth - 9) // 4]
        return {"name": theme["name"], "icon": theme["icon"],
                "color": theme["color"], "desc": theme["desc"],
                "mobs": theme["mobs"], "boss": boss}
    rng = random.Random(10_000 + depth)
    boss = (f"{rng.choice(BOSS_FIRST)}{rng.choice(BOSS_LAST)}".title(),
            rng.choice(BOSS_TITLES))
    return {
        "name": f"The Deep Dark — Stratum {depth}",
        "icon": "\U0001f573",
        "color": "#d45dff",
        "desc": "No map survives past this point.",
        "mobs": [f"Depth Horror", "Starved Abomination", "Whisper Spawn", "Chitin Stalker"],
        "boss": boss,
    }


# Themed strata bands for depths 9-40 (4 depths each): the Deep Dark
# gets geography, not just grey Strata numbers.
STRATA = [
    {"name": "The Drowned Halls", "icon": "\U0001f30a", "color": "#5db8ff",
     "desc": "Black water laps at drowned pews.",
     "mobs": ["Silt Crab", "Drowned Sailor", "Brine Hag", "Wreck Revenant"]},
    {"name": "The Ashen Wastes", "icon": "\U0001f30b", "color": "#ff7a3c",
     "desc": "Grey snow, ember wind.",
     "mobs": ["Cinder Imp", "Ash Serpent", "Charred Husk", "Slag Golem"]},
    {"name": "The Hollow Deep", "icon": "\U0001f578", "color": "#d45dff",
     "desc": "Hollow dark. Things walk it.",
     "mobs": ["Nothic Whisperer", "Choker", "Darkmantle", "Grell"]},
    {"name": "The Frozen Tomb", "icon": "\u2744\ufe0f", "color": "#aee9ff",
     "desc": "Breath freezes mid-prayer.",
     "mobs": ["Ice Mephit", "Frost Wight", "Winter Wolf", "Yeti"]},
    {"name": "The Brass Hells", "icon": "\U0001f608", "color": "#ff5b5b",
     "desc": "The walls are warm.",
     "mobs": ["Lemure", "Spined Devil", "Hell Hound", "Ashen Cultist"]},
    {"name": "The Shattered Peaks", "icon": "\u26f0\ufe0f", "color": "#c9a227",
     "desc": "Clouds below, teeth above.",
     "mobs": ["Hill Giant", "Stone Giant", "Wyvern", "Griffon"]},
    {"name": "The Starless Vault", "icon": "\U0001f52e", "color": "#7a5dff",
     "desc": "The stars here are eyes.",
     "mobs": ["Beholderkin", "Intellect Devourer", "Cloaker", "Aboleth Spawn"]},
    {"name": "The Throne Below", "icon": "\U0001f451", "color": "#ffd700",
     "desc": "Kneel.",
     "mobs": ["Death Knight", "Balor Spawn", "Elder Wyrm", "Void Titan"]},
]


# --------------------------------------------------------------------------- #
# Classes & skills
# --------------------------------------------------------------------------- #

@dataclass
class Skill:
    key: str
    name: str
    icon: str
    desc: str
    mp: int
    cd: int
    unlock: int
    kind: str          # basic / nuke / dot / heal / shield / buff / drain / slow
    power: float = 1.0
    heal_pct: float = 0.0


CLASSES: dict[str, dict] = {
    "Warrior": {
        "icon": "\u2694\ufe0f", "color": "#ff6b6b",
        "flavor": "Sword-and-board veteran. Huge HP, shrugs off blows.",
        "base": {"max_hp": 120, "max_mp": 30, "atk": 14, "df": 10, "spd": 7, "crit": 10, "dodge": 5},
        "grow": {"max_hp": 22, "max_mp": 3, "atk": 3.2, "df": 2.2, "spd": 0.5},
        "skills": [
            Skill("slash", "Sundering Slash", "\u2694\ufe0f", "Reliable heavy cut.", 0, 0, 1, "basic", 1.0),
            Skill("wall", "Shield Wall", "\U0001f6e1\ufe0f", "+6 DEF for 3 turns. 1HP regen.", 10, 4, 1, "buff", 0.0),
            Skill("sunder", "Sunder Armor", "\U0001f4a5", "1.8x dmg, shred 3 foe DEF (3t).", 14, 4, 3, "nuke", 1.8),
            Skill("whirl", "Whirlwind", "\U0001f300", "2.6x sweeping devastation.", 24, 6, 5, "nuke", 2.6),
        ],
    },
    "Rogue": {
        "icon": "\U0001f5e1\ufe0f", "color": "#5dff7a",
        "flavor": "Strikes from shadow. Crits and dodges everything. First landed hit each fight always crits (Ambush).",
        "base": {"max_hp": 88, "max_mp": 36, "atk": 15, "df": 6, "spd": 13, "crit": 25, "dodge": 15},
        "grow": {"max_hp": 15, "max_mp": 4, "atk": 3.6, "df": 1.4, "spd": 1.0},
        "skills": [
            Skill("stab", "Quick Stab", "\U0001f5e1\ufe0f", "Fast reliable strike.", 0, 0, 1, "basic", 1.0),
            Skill("back", "Backstab", "\U0001f479", "2.1x dmg from the shadows.", 12, 4, 1, "nuke", 2.1),
            Skill("pois", "Poison Blade", "\u2620\ufe0f", "1.1x + venom burn (3t).", 12, 5, 3, "dot", 1.1),
            Skill("dance", "Evasive Dance", "\U0001f4a8", "+18% dodge for 3 turns.", 16, 6, 5, "buff", 0.0),
        ],
    },
    "Cleric": {
        "icon": "\U0001f64f", "color": "#ffd166",
        "flavor": "Light of the Dawn. Smites foes, mends self.",
        "base": {"max_hp": 104, "max_mp": 55, "atk": 11, "df": 9, "spd": 8, "crit": 8, "dodge": 6},
        "grow": {"max_hp": 18, "max_mp": 8, "atk": 2.7, "df": 1.9, "spd": 0.6},
        "skills": [
            Skill("mace", "Sacred Mace", "\U0001f528", "Blessed bludgeon.", 0, 0, 1, "basic", 1.0),
            Skill("smite", "Holy Smite", "\u2728", "1.5x radiant dmg + heal 10%.", 14, 3, 1, "drain", 1.5),
            Skill("heal", "Greater Heal", "\U0001f49a", "Restore 32% HP.", 22, 5, 3, "heal", 0.0, 0.32),
            Skill("sanc", "Sanctuary", "\U0001f54c", "Ward: -40% dmg taken, 3t.", 26, 7, 5, "shield", 0.0),
        ],
    },
    "Wizard": {
        "icon": "\U0001f9d9", "color": "#5db8ff",
        "flavor": "Glass cannon of the Arcane. Deletes rooms, naps after.",
        "base": {"max_hp": 96, "max_mp": 80, "atk": 18, "df": 5, "spd": 9, "crit": 15, "dodge": 7},
        "grow": {"max_hp": 13, "max_mp": 10, "atk": 4.2, "df": 1.1, "spd": 0.7},
        "skills": [
            Skill("zap", "Staff Jab", "\U0001fa84", "A reluctant bonk.", 0, 0, 1, "basic", 1.0),
            Skill("fire", "Fireball", "\U0001f525", "1.9x fire. The classic.", 16, 3, 1, "nuke", 1.9),
            Skill("frost", "Frost Nova", "\u2744\ufe0f", "1.3x + slow foe (-4 SPD 3t).", 18, 5, 3, "slow", 1.3),
            Skill("surge", "Arcane Surge", "\U0001f320", "3.0x cataclysm.", 34, 7, 5, "nuke", 3.0),
        ],
    },
}

CLASS_LIST = list(CLASSES.keys())

# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #

@dataclass
class Item:
    slot: str
    name: str
    rarity: str
    color: str
    bonus: dict = field(default_factory=dict)
    set_name: str = ""   # gear set, e.g. "Ember" (2+ pieces worn = bonus)

    def short(self) -> str:
        b = " ".join(f"{v:+}{k}" for k, v in self.bonus.items())
        return f"{self.name} [{self.rarity}] {b}"


@dataclass
class Fighter:
    name: str
    kind: str            # 'hero' or 'mob'/'boss'
    level: int
    max_hp: int
    hp: int
    max_mp: int = 0
    mp: int = 0
    atk: int = 5
    df: int = 5
    spd: int = 5
    crit: int = 10       # percent
    dodge: int = 5       # percent
    ctype: str = ""      # creature type: Beast, Dragon, Undead... (mobs/bosses only)
    cds: dict = field(default_factory=dict)  # boss art cooldowns: art -> ticks left
    buffs: dict = field(default_factory=dict)   # stat -> [amount, turns]
    dots: list = field(default_factory=list)    # [dmg, turns, label]

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def eff(self, stat: str) -> float:
        base = getattr(self, stat)
        if stat in self.buffs:
            base += self.buffs[stat][0]
        # slow debuff is stored as negative spd buff
        return max(0, base)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def bar(cur: float, mx: float, width: int = 20, fill: str = "\u2588", empty: str = "\u2591") -> str:
    if mx <= 0:
        return empty * width
    p = max(0.0, min(1.0, cur / mx))
    n = int(round(p * width))
    return fill * n + empty * (width - n)


def xp_needed(level: int) -> int:
    return int(70 + level * 55 + (level ** 1.55) * 18)


def roll_loot(depth: int, boss: bool, hero_cls: str) -> Item | None:
    r = random.random()
    if boss:
        roll = random.random()
        rarity = "Legendary" if roll < 0.12 else "Epic" if roll < 0.40 else "Rare"
    else:
        if r > 0.20:
            return None
        roll = random.random()
        if roll < 0.50:
            rarity = "Common"
        elif roll < 0.78:
            rarity = "Uncommon"
        elif roll < 0.94:
            rarity = "Rare"
        elif roll < 0.99:
            rarity = "Epic"
        else:
            rarity = "Legendary"
    rmap = {n: m for n, _, m in RARITIES}
    mult = rmap[rarity]
    slot = random.choice(["Weapon", "Armor", "Trinket", "Ring", "Boots"])
    if slot == "Weapon":
        nm = random.choice(WEAPON_NAMES.get(hero_cls, WEAPON_NAMES["Warrior"]))
        bonus = {"ATK": int((3 + depth * 1.6) * mult)}
        if rarity in ("Epic", "Legendary") and random.random() < 0.5:
            bonus["SPD"] = int(1 + depth * 0.3)
    elif slot == "Armor":
        nm = random.choice(ARMOR_NAMES)
        bonus = {"DEF": int((3 + depth * 1.4) * mult)}
        if rarity in ("Epic", "Legendary") and random.random() < 0.5:
            bonus["HP"] = int((10 + depth * 6) * mult)
    elif slot == "Ring":
        nm = random.choice(RING_NAMES)
        k = random.choice(["ATK", "DEF", "HP", "MP", "SPD"])
        base = {"ATK": 1 + int(depth * 0.5), "DEF": 1 + int(depth * 0.5),
                "HP": 8 + depth * 4, "MP": 6 + depth * 3,
                "SPD": 1 + depth // 4}[k]
        bonus = {k: max(1, int(base * mult))}
    elif slot == "Boots":
        nm = random.choice(BOOT_NAMES)
        k = random.choice(["SPD", "SPD", "DEF", "HP"])
        base = {"SPD": 1 + depth // 4, "DEF": 1 + int(depth * 0.5),
                "HP": 8 + depth * 4}[k]
        bonus = {k: max(1, int(base * mult))}
    else:
        nm = random.choice(TRINKET_NAMES)
        bonus = random.choice([{"HP": 0}, {"MP": 0}, {"ATK": 0}, {"DEF": 0}])
        k = list(bonus.keys())[0]
        base = {"HP": 14 + depth * 8, "MP": 8 + depth * 4,
                "ATK": 2 + int(depth * 0.8), "DEF": 2 + int(depth * 0.8)}[k]
        bonus = {k: int(base * mult)}
    color = {n: c for n, c, _ in RARITIES}[rarity]
    prefix = {"Common": "", "Uncommon": "Fine ", "Rare": "Runed ",
              "Epic": "Mythic ", "Legendary": "DRAGONFORGED "}[rarity]
    set_name = ""
    if random.random() < 0.18:
        set_name = random.choice(list(SET_BONUS))
        nm = f"{set_name} {nm}"
    cursed = random.random() < 0.10
    if cursed:
        # big positives, nasty downside — tempting, at a price
        bonus = {k: int(v * 1.7) + 1 for k, v in bonus.items()}
        pool = {"HP": -(10 + depth * 5), "MP": -(8 + depth * 3),
                "DEF": -(2 + int(depth * 0.7)), "SPD": -(1 + depth // 4),
                "ATK": -(1 + int(depth * 0.5))}
        for k in list(bonus):
            pool.pop(k, None)
        dk, dv = random.choice(list(pool.items()))
        bonus[dk] = dv
        nm = f"Cursed {nm}"
    return Item(slot, prefix + nm, rarity, color, bonus, set_name)


# --------------------------------------------------------------------------- #
# Highscores
# --------------------------------------------------------------------------- #

def load_scores() -> list:
    try:
        with open(HIGHSCORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_score(entry: dict) -> list:
    scores = load_scores()
    scores.append(entry)
    scores.sort(key=lambda s: (-s.get("depth", 0), -s.get("level", 0), -s.get("kills", 0)))
    scores = scores[:50]
    with open(HIGHSCORE_FILE, "w", encoding="utf-8") as f:
        json.dump(scores, f, indent=2)
    return scores


def scores_table(scores: list, highlight: int = -1, limit: int = 10) -> Table:
    t = Table(box=box.ROUNDED, expand=True, show_lines=False)
    t.add_column("#", width=3, justify="right")
    t.add_column("Name", style="bold white")
    t.add_column("Class")
    t.add_column("Depth", justify="right")
    t.add_column("Level", justify="right")
    t.add_column("Died to", style="red")
    medal = {1: "\U0001f947", 2: "\U0001f948", 3: "\U0001f949"}
    for i, s in enumerate(scores[:limit], 1):
        mark = medal.get(i, "  ")
        row = [f"{mark}{i}", str(s.get("name", "?")), str(s.get("cls", "?")),
               str(s.get("depth", 0)), str(s.get("level", 0)), str(s.get("died_to", "?"))[:30]]
        if i - 1 == highlight:
            t.add_row(*row, style="bold yellow")
        else:
            t.add_row(*row)
    if not scores:
        t.add_row("", "[dim]No legends yet. You could be the first.[/]", "", "", "", "")
    return t


# --------------------------------------------------------------------------- #
# Hero + monster factories
# --------------------------------------------------------------------------- #

# Every hero starts with humble Common starter gear (quickly outgrown,
# but nobody faces the Cellar bare-handed).
STARTER_GEAR: dict[str, list[tuple[str, str, dict]]] = {
    "Warrior": [("Weapon", "Worn Shortsword", {"ATK": 2}),
                ("Armor", "Dented Jerkin", {"DEF": 2}),
                ("Trinket", "Soldier's Lucky Coin", {"HP": 6})],
    "Rogue":   [("Weapon", "Chipped Dagger", {"ATK": 2}),
                ("Armor", "Patchwork Cloak", {"DEF": 1}),
                ("Trinket", "Cat's-Eye Marble", {"SPD": 1})],
    "Cleric":  [("Weapon", "Plain Mace", {"ATK": 2}),
                ("Armor", "Initiate Robes", {"DEF": 2}),
                ("Trinket", "Wooden Holy Symbol", {"MP": 6})],
    "Wizard":  [("Weapon", "Cracked Oak Staff", {"ATK": 2}),
                ("Armor", "Frayed Apprentice Robes", {"DEF": 1}),
                ("Trinket", "Faded Cantrip Scroll", {"MP": 8})],
}


def make_hero(name: str, cls: str) -> dict:
    c = CLASSES[cls]
    b = c["base"]
    hero = {
        "name": name, "cls": cls, "level": 1, "xp": 0,
        "max_hp": b["max_hp"], "hp": b["max_hp"],
        "max_mp": b["max_mp"], "mp": b["max_mp"],
        "atk": b["atk"], "df": b["df"], "spd": b["spd"],
        "crit": b["crit"], "dodge": b["dodge"],
        "gold": 30, "hp_pots": 3, "mp_pots": 2,
        "gear": {"Weapon": None, "Armor": None, "Trinket": None,
                 "Ring": None, "Boots": None},
        "ambush": False,
        "cds": {}, "buffs": {}, "dots": [],
        "kills": 0, "boss_kills": 0, "turns": 0, "potions_used": 0,
    }
    for slot, gname, bonus in STARTER_GEAR[cls]:
        hero["gear"][slot] = Item(slot, gname, "Common", "white", bonus)
    # Top off vitals in case a starter trinket grants HP/MP.
    hero["hp"] = hero_max_hp(hero)
    hero["mp"] = hero_max_mp(hero)
    return hero


def gear_bonus(hero: dict, stat: str) -> int:
    tot = 0
    for it in hero["gear"].values():
        if it and stat in it.bonus:
            tot += it.bonus[stat]
    # set bonus: 2+ worn pieces sharing a set
    counts: dict[str, int] = {}
    for it in hero["gear"].values():
        if it and it.set_name:
            counts[it.set_name] = counts.get(it.set_name, 0) + 1
    for s, n in counts.items():
        if n >= 2 and stat in SET_BONUS.get(s, {}):
            tot += SET_BONUS[s][stat]
    return tot


def worn_sets(hero: dict) -> dict[str, int]:
    """Set name -> pieces worn, for completed (2+) sets only."""
    counts: dict[str, int] = {}
    for it in hero["gear"].values():
        if it and it.set_name:
            counts[it.set_name] = counts.get(it.set_name, 0) + 1
    return {s: n for s, n in counts.items() if n >= 2}


def hero_eff(hero: dict, stat: str) -> float:
    key = {"atk": "atk", "df": "df", "spd": "spd"}.get(stat, stat)
    base = hero[key] + gear_bonus(hero, stat.upper())
    if stat in hero["buffs"]:
        base += hero["buffs"][stat][0]
    return max(0, base)


def hero_max_hp(hero: dict) -> int:
    # Totals never drop below 1 no matter how cursed the jewelry gets —
    # otherwise regen/clamp lines teleport vitals into nonsense.
    return max(1, hero["max_hp"] + gear_bonus(hero, "HP"))


def hero_max_mp(hero: dict) -> int:
    return max(1, hero["max_mp"] + gear_bonus(hero, "MP"))


def make_monster(depth: int, hero_level: int, boss: bool = False) -> Fighter:
    d = dungeon_for_depth(depth)
    # The Deep gets meaner faster than heroes grow: flat for depths 1-2,
    # then ~2%/level compounded. x1.0 @2, x1.2 @10, x1.4 @20, x1.7 @30.
    # Boss fights stay short (lean HP) but hit harder with depth;
    # attrition, not one-shots, should end runs. Depth 20 = a good run.
    power = 1.02 ** max(0, depth - 2)
    tank = power ** 0.5
    if boss:
        first, title = d["boss"]
        name = f"{first} {title}"
        ctype = boss_type(first)
        # Boss level comes from the dungeon, not the hero: depth 20 always
        # fields a level-22 boss, so every character faces the same wall.
        # (depth + 2 mirrors the hero level a typical run has on arrival.)
        lvl = depth + 2
        # Bosses ramp with depth instead of spiking early (Griznak mercy rule).
        # Lean HP (short, violent fights) + attack that grows with depth.
        hp = int((55 + depth * 34 + lvl * 14) * (1.5 + depth * 0.03) * power)
        atk = int((7 + depth * 2.6 + lvl * 1.5) * (1.05 + depth * 0.012) * power)
        df_ = int((4 + depth * 1.8 + lvl * 0.9) * tank)
        spd = int(6 + depth * 0.7 + lvl * 0.3)
        kind = "boss"
    else:
        name = random.choice(d["mobs"])
        ctype = MOB_TYPES.get(name, "Monstrosity")
        lvl = max(1, hero_level + random.randint(-1, 1))
        hp = int((30 + depth * 20 + lvl * 11 + random.randint(0, 12)) * power)
        atk = int((5 + depth * 1.9 + lvl * 1.2 + random.randint(0, 3)) * power)
        df_ = int((2 + depth * 1.2 + lvl * 0.7) * tank)
        spd = int(5 + depth * 0.5 + lvl * 0.35 + random.randint(-1, 2))
        kind = "mob"
    # Type traits baked into stats: Beasts are skittish, Monstrosities all teeth.
    base_crit = 8 if not boss else 14
    base_dodge = 5 if not boss else 8
    return Fighter(name=name, kind=kind, level=lvl, max_hp=hp, hp=hp,
                   atk=atk, df=df_, spd=spd, ctype=ctype,
                   crit=base_crit + (5 if ctype == "Monstrosity" else 0),
                   dodge=base_dodge + (4 if ctype == "Beast" else 0))


# --------------------------------------------------------------------------- #
# Combat math
# --------------------------------------------------------------------------- #

def attack_roll_str(attacker: str, defender_ac: int, bonus: int) -> tuple[bool, int]:
    d20 = random.randint(1, 20)
    crit_roll = (d20 == 20)
    hit = crit_roll or (d20 == 1 and False) or (d20 + bonus >= defender_ac)
    return hit, d20


def hero_strike(hero: dict, foe: Fighter, skill: Skill) -> list[str]:
    """Resolve one hero action. Returns log lines."""
    out: list[str] = []
    cname = CLASSES[hero["cls"]]["color"]
    msgs = out.append

    # pay + cooldown
    if skill.mp:
        hero["mp"] -= skill.mp
    if skill.cd:
        hero["cds"][skill.key] = skill.cd

    atk = hero_eff(hero, "atk")
    crit_c = hero["crit"] + (5 if hero["cls"] == "Rogue" else 0)
    if foe.ctype == "Aberration":
        crit_c = max(0, crit_c - 5)  # mortal minds fray before the unreal

    if skill.kind == "heal":
        amt = int(hero_max_hp(hero) * skill.heal_pct)
        hero["hp"] = min(hero_max_hp(hero), hero["hp"] + amt)
        msgs(f"[{cname}]\u2728 {skill.name}[/] — restored [green]{amt} HP[/].")
        return out
    if skill.kind == "buff":
        if hero["cls"] == "Warrior":
            hero["buffs"]["df"] = [6, 3]
            hero["hp"] = min(hero_max_hp(hero), hero["hp"] + 8 + hero["level"] * 2)
            msgs(f"[{cname}]\U0001f6e1\ufe0f {skill.name}[/] — [cyan]+6 DEF[/] for 3 turns, braced!")
        else:
            hero["buffs"]["dodge"] = [18, 3]
            msgs(f"[{cname}]\U0001f4a8 {skill.name}[/] — [cyan]+18% dodge[/] for 3 turns!")
        return out
    if skill.kind == "shield":
        hero["buffs"]["ward"] = [40, 3]
        msgs(f"[{cname}]\U0001f54c {skill.name}[/] — a dome of dawnlight ([cyan]-40% damage[/], 3t).")
        return out

    # damaging skills
    mult = skill.power
    ambush = hero.get("cls") == "Rogue" and hero.get("ambush", False)
    is_crit = True if ambush else random.randint(1, 100) <= crit_c
    foe_dodge = foe.dodge - (4 if skill.kind == "slow" else 0)
    if random.randint(1, 100) <= max(2, foe_dodge):
        msgs(f"[{cname}]{skill.icon} {skill.name}[/] — [dim]{foe.name} slips aside! MISS.[/]")
        return out  # whiffed from the shadows — ambush stays armed
    raw = atk * mult * random.uniform(0.88, 1.15) - foe.df * 0.55
    dmg = max(1, int(raw * (1.75 if is_crit else 1.0)))
    kindled = skill.key == "fire" and foe.ctype == "Plant"
    if kindled:
        dmg = int(dmg * 1.25)  # dry tinder
    foe.hp = max(0, foe.hp - dmg)
    d20 = random.randint(1, 20)
    if ambush:
        hero["ambush"] = False
        crit_txt = " [bold yellow]\u2605AMBUSH\u2605[/]"
    else:
        crit_txt = " [bold yellow]\u2605CRIT\u2605[/]" if is_crit else ""
    msgs(f"[{cname}]{skill.icon} {skill.name}[/] [{d20:>2}{D20}] → [bold red]{dmg}[/] to {foe.name}.{crit_txt}")
    if kindled:
        msgs(f"[green]  \U0001f525 Dry tinder! {foe.name} burns extra.[/]")

    if skill.key == "sunder":
        foe.buffs["df"] = [foe.buffs.get("df", [0, 0])[0] - 3, 3]
        msgs(f"[dim]  {foe.name}'s armor cracks (-3 DEF, 3t).[/]")
    if skill.kind == "dot":
        venom = int(4 + hero["level"] * 1.8)
        if foe.ctype == "Undead":
            venom = max(1, venom // 2)  # dead blood, thin purchase
            foe.dots.append([venom, 3, "venom"])
            msgs(f"[green]  \u2620\ufe0f Venom barely takes hold of {foe.name} (half, 3t).[/]")
        else:
            foe.dots.append([venom, 3, "venom"])
            msgs(f"[green]  \u2620\ufe0f Venom courses through {foe.name} (3t).[/]")
    if skill.kind == "slow":
        if foe.ctype == "Elemental":
            msgs(f"[dim]  \u2744\ufe0f No blood to chill — {foe.name} barely notices.[/]")
        else:
            foe.buffs["spd"] = [foe.buffs.get("spd", [0, 0])[0] - 4, 3]
            msgs(f"[cyan]  \u2744\ufe0f {foe.name} is slowed (-4 SPD, 3t).[/]")
    if skill.kind == "drain":
        heal = int(hero_max_hp(hero) * 0.10)
        hero["hp"] = min(hero_max_hp(hero), hero["hp"] + heal)
        msgs(f"[yellow]  \u2728 Radiance mends you for {heal} HP.[/]")
    if is_crit and foe.ctype == "Fiend" and foe.alive:
        rebuke = max(1, dmg // 10)
        hero["hp"] = max(0, hero["hp"] - rebuke)
        msgs(f"[red]  \U0001f608 Hellish rebuke! {rebuke} damage recoils onto you.[/]")
    return out


def foe_strike(foe: Fighter, hero: dict) -> list[str]:
    out: list[str] = []
    msgs = out.append
    # dodge?
    dodge = hero.get("dodge", 5) + hero_eff(hero, "dodge") * 0 - 0  # base
    # buff dodge stored separately
    dd = hero["dodge"] + (hero["buffs"].get("dodge", [0, 0])[0])
    if random.randint(1, 100) <= dd:
        msgs(f"[dim]\U0001f4a8 You twist away from {foe.name}'s attack! DODGED.[/]")
        return out
    atk = foe.eff("atk")
    dfs = hero_eff(hero, "df")
    is_crit = random.randint(1, 100) <= foe.crit
    raw = atk * random.uniform(0.85, 1.15) - dfs * 0.55
    # boss enrage under 30% hp
    if foe.kind == "boss" and foe.hp < foe.max_hp * 0.3:
        raw *= 1.25
    dmg = max(1, int(raw * (1.6 if is_crit else 1.0)))
    ward = hero["buffs"].get("ward", [0, 0])[0]
    if ward:
        dmg = max(1, int(dmg * (1 - ward / 100)))
    breath = ""
    if foe.ctype == "Dragon" and random.randint(1, 100) <= 12:
        if hero.get("cls") == "Rogue":
            dmg = int(dmg * 1.1)
            breath = " [red]\U0001f525 BREATH[/] [dim](evaded most of it!)[/]"
        else:
            dmg = int(dmg * 1.4)
            breath = " [red]\U0001f525 BREATH[/]"
    hero["hp"] = max(0, hero["hp"] - dmg)
    crit_txt = " [bold yellow]\u2605CRIT\u2605[/]" if is_crit else ""
    enrage = " [red]\U0001f621 ENRAGED[/]" if foe.kind == "boss" and foe.hp < foe.max_hp * 0.3 else ""
    icon = "\U0001f480" if foe.kind == "boss" else "\u2694\ufe0f"
    msgs(f"[red]{icon} {foe.name}[/] hits you for [bold red]{dmg}[/].{crit_txt}{breath}{enrage}")
    if foe.ctype == "Giant" and hero["hp"] > 0 and random.randint(1, 100) <= 15:
        sweep = max(1, dmg // 2)
        hero["hp"] = max(0, hero["hp"] - sweep)
        msgs(f"[red]  \U0001f4a5 Sweeping blow! A second {sweep} damage.[/]")
    return out


# --------------------------------------------------------------------------- #
# Boss arts — signature moves. The 8 handcrafted bosses get unique ones;
# deep bosses improvise from their creature type.
# kinds: strike(mult) / drain(base+per_lvl, heals self) / buff_atk /
#        bulwark(once under hp threshold) / hex_spd / hex_dodge / hex_atk
# --------------------------------------------------------------------------- #

BOSS_ARTS = {
    "Squeakus":       {"art": "Summon the Brood", "icon": "\U0001f400", "chance": 0.15, "cd": 5, "kind": "strike", "mult": 0.5},
    "Griznak":        {"art": "War Drum", "icon": "\U0001f941", "chance": 0.15, "cd": 6, "kind": "buff_atk", "amount": 3, "dur": 3},
    "Mother Mycelia": {"art": "Spore Cloud", "icon": "\U0001f344", "chance": 0.15, "cd": 6, "kind": "hex_spd", "amount": 4, "dur": 3},
    "Lord Vexmar":    {"art": "Soul Siphon", "icon": "\U0001f480", "chance": 0.15, "cd": 6, "kind": "drain", "base": 6, "per_lvl": 1.0},
    "Cinder Maw":     {"art": "Magma Hide", "icon": "\U0001faa8", "chance": 1.0, "cd": 999, "kind": "bulwark", "threshold": 0.5, "amount": 6},
    "Vexalyth":       {"art": "Shadow Web", "icon": "\U0001f578", "chance": 0.15, "cd": 6, "kind": "hex_dodge", "amount": 10, "dur": 3},
    "Sussurax":       {"art": "Stormcall", "icon": "\U0001f329", "chance": 0.15, "cd": 5, "kind": "strike", "mult": 0.8},
    "Vermithrax Pejorative": {"art": "Hoardfire", "icon": "\U0001f525", "chance": 0.15, "cd": 6, "kind": "strike", "mult": 1.4},
}

TYPE_ARTS = {
    "Dragon":     {"art": "Ruinous Breath", "icon": "\U0001f525", "chance": 0.14, "cd": 6, "kind": "strike", "mult": 1.2},
    "Undead":     {"art": "Grave Chill", "icon": "\u2744\ufe0f", "chance": 0.15, "cd": 6, "kind": "drain", "base": 5, "per_lvl": 1.2},
    "Fiend":      {"art": "Hellfire", "icon": "\U0001f608", "chance": 0.15, "cd": 6, "kind": "strike", "mult": 1.1},
    "Aberration": {"art": "Mind Shatter", "icon": "\U0001f441", "chance": 0.15, "cd": 6, "kind": "hex_atk", "amount": 4, "dur": 3},
    "Elemental":  {"art": "Elemental Surge", "icon": "\u26a1", "chance": 0.15, "cd": 6, "kind": "buff_atk", "amount": 4, "dur": 3},
    "Monstrosity": {"art": "Savage Frenzy", "icon": "\U0001f9b7", "chance": 0.15, "cd": 6, "kind": "strike", "mult": 0.6},
    "Giant":      {"art": "Earthquake Stomp", "icon": "\U0001f30b", "chance": 0.14, "cd": 6, "kind": "strike", "mult": 1.0},
    "Plant":      {"art": "Ensnaring Roots", "icon": "\U0001f33f", "chance": 0.15, "cd": 6, "kind": "hex_spd", "amount": 4, "dur": 2},
    "Beast":      {"art": "Blood Frenzy", "icon": "\U0001fa78", "chance": 1.0, "cd": 999, "kind": "rage", "threshold": 0.4, "amount": 5},
    "Humanoid":   {"art": "Dirty Trick", "icon": "\U0001f3ad", "chance": 0.15, "cd": 6, "kind": "hex_dodge", "amount": 8, "dur": 2},
}


def boss_ability(foe: Fighter, hero: dict) -> list[str]:
    """One boss signature move, if its cooldown and the dice allow."""
    out: list[str] = []
    # handcrafted bosses keyed by first name ("Mother Mycelia" matches
    # "Mother Mycelia the Bloom That Hungers"); deep bosses by type.
    art = None
    for key, candidate in BOSS_ARTS.items():
        if foe.name.startswith(key):
            art = candidate
            break
    if art is None:
        art = TYPE_ARTS.get(foe.ctype)
    if art is None or foe.cds.get("art", 0) > 0:
        return out
    kind = art["kind"]
    if kind in ("bulwark", "rage"):
        if foe.hp / max(1, foe.max_hp) > art["threshold"]:
            return out
    elif random.random() > art["chance"]:
        return out
    foe.cds["art"] = art["cd"]
    tag = f"[bold red]{art['icon']} {foe.name} — {art['art']}![/]"
    if kind == "strike":
        dmg = max(1, int(foe.eff("atk") * art["mult"] * random.uniform(0.9, 1.1)))
        ward = hero["buffs"].get("ward", [0, 0])[0]
        if ward:
            dmg = max(1, int(dmg * (1 - ward / 100)))
        hero["hp"] = max(0, hero["hp"] - dmg)
        out.append(tag)
        out.append(f"[red]  \U0001f4a5 {dmg} damage![/]")
    elif kind == "drain":
        dmg = max(1, int(art["base"] + foe.level * art["per_lvl"]))
        hero["hp"] = max(0, hero["hp"] - dmg)
        foe.hp = min(foe.max_hp, foe.hp + dmg)
        out.append(tag)
        out.append(f"[red]  \U0001f9db {dmg} siphoned — {foe.name} feeds.[/]")
    elif kind == "buff_atk":
        foe.buffs["atk"] = [foe.buffs.get("atk", [0, 0])[0] + art["amount"], art["dur"]]
        out.append(tag)
        out.append(f"[red]  \U0001f4aa {foe.name} swells with power (+{art['amount']} ATK, {art['dur']}t).[/]")
    elif kind == "bulwark":
        foe.buffs["df"] = [foe.buffs.get("df", [0, 0])[0] + art["amount"], 999]
        out.append(tag)
        out.append(f"[red]  \U0001faa8 Hide hardens like cooling slag (+{art['amount']} DEF).[/]")
    elif kind == "rage":
        foe.buffs["atk"] = [foe.buffs.get("atk", [0, 0])[0] + art["amount"], 999]
        out.append(tag)
        out.append(f"[red]  \U0001fa78 Bloodied and beyond pain (+{art['amount']} ATK).[/]")
    elif kind in ("hex_spd", "hex_dodge", "hex_atk"):
        stat = {"hex_spd": "spd", "hex_dodge": "dodge", "hex_atk": "atk"}[kind]
        hero["buffs"][stat] = [hero["buffs"].get(stat, [0, 0])[0] - art["amount"], art["dur"]]
        out.append(tag)
        out.append(f"[red]  \U0001f577 You are diminished (-{art['amount']} {stat.upper()}, {art['dur']}t).[/]")
    return out


def tick_dots(hero: dict, foe: Fighter) -> list[str]:
    out = []
    for owner, target_is_foe in ((foe, True),):
        keep = []
        for dmg, turns, label in owner.dots:
            tick = max(1, int(dmg * random.uniform(0.85, 1.1)))
            owner.hp = max(0, owner.hp - tick)
            out.append(f"[green]\u2620\ufe0f {label.title()} burns {owner.name} for {tick}.[/]")
            if turns - 1 > 0 and owner.hp > 0:
                keep.append([dmg, turns - 1, label])
        owner.dots = keep
    return out


def tick_buffs(hero: dict, foe: Fighter) -> None:
    for obj in (hero, foe):
        buffs = obj["buffs"] if isinstance(obj, dict) else obj.buffs
        dead = []
        for k, (amt, t) in buffs.items():
            if t - 1 <= 0:
                dead.append(k)
            else:
                buffs[k][1] = t - 1
        for k in dead:
            del buffs[k]
    # cooldowns
    for k in list(hero["cds"].keys()):
        hero["cds"][k] -= 1
        if hero["cds"][k] <= 0:
            del hero["cds"][k]
    for k in list(foe.cds.keys()):
        foe.cds[k] -= 1
        if foe.cds[k] <= 0:
            del foe.cds[k]
    # regen a little mana every tick
    hero["mp"] = min(hero_max_mp(hero), hero["mp"] + max(2, hero_max_mp(hero) // 18))


def choose_skill(hero: dict) -> Skill:
    skills = CLASSES[hero["cls"]]["skills"]
    avail = [s for s in skills if hero["level"] >= s.unlock
             and hero["mp"] >= s.mp and s.key not in hero["cds"]]
    basics = [s for s in avail if s.kind == "basic"]
    # emergency heal
    pct = hero["hp"] / max(1, hero_max_hp(hero))
    for s in avail:
        if s.kind == "heal" and pct < 0.45:
            return s
        if s.kind == "drain" and pct < 0.6 and random.random() < 0.7:
            return s
    if pct < 0.32:
        # prefer shield/buff defensively
        for s in avail:
            if s.kind in ("shield", "buff"):
                return s
    nukes = [s for s in avail if s.kind in ("nuke", "slow", "dot", "drain")]
    if nukes and random.random() < 0.75:
        return max(nukes, key=lambda s: s.power)
    if avail and random.random() < 0.35:
        nonbasic = [s for s in avail if s.kind != "basic"]
        if nonbasic:
            return random.choice(nonbasic)
    if basics:
        return basics[0]
    # Paranoia: basics cost 0 MP and unlock at 1, so reaching here means
    # something is deeply off — but a hero must always be able to act.
    return next(s for s in skills if s.kind == "basic")


# --------------------------------------------------------------------------- #
# Potions / rewards
# --------------------------------------------------------------------------- #

def max_potions(hero: dict) -> int:
    return MAX_POTIONS_BASE + hero["level"] // 3


def drink_hp(hero: dict) -> str | None:
    # Potions quaff themselves — this is a watcher, not a sipper.
    if hero["hp_pots"] <= 0:
        return None
    if hero["hp"] >= hero_max_hp(hero):
        return None
    hero["hp_pots"] -= 1
    hero["potions_used"] += 1
    amt = int(hero_max_hp(hero) * POTION_HP_PCT)
    hero["hp"] = min(hero_max_hp(hero), hero["hp"] + amt)
    return f"[red]\U0001f9ea HP potion auto-quaff[/] — [green]+{amt} HP[/] ({hero['hp_pots']} left)."


def drink_mp(hero: dict) -> str | None:
    if hero["mp_pots"] <= 0:
        return None
    if hero["mp"] >= hero_max_mp(hero):
        return None
    hero["mp_pots"] -= 1
    hero["potions_used"] += 1
    amt = int(hero_max_mp(hero) * POTION_MP_PCT)
    hero["mp"] = min(hero_max_mp(hero), hero["mp"] + amt)
    return f"[blue]\U0001f9ea MP potion[/] — [cyan]+{amt} MP[/] ({hero['mp_pots']} left)."


def grant_rewards(hero: dict, foe: Fighter) -> list[str]:
    out = []
    boss = foe.kind == "boss"
    xp = int((18 + foe.level * 14 + (8 if boss else 0)) * (1 + foe.level * 0.02))
    if boss:
        xp = int(xp * 2.2)
    gold = int(random.randint(8, 20) + foe.level * 6 + (60 if boss else 0))
    if foe.ctype == "Humanoid":
        gold = int(gold * 1.25)  # they carry purses
    hero["xp"] += xp
    hero["gold"] += gold
    hero["kills"] += 1
    if boss:
        hero["boss_kills"] += 1
    out.append(f"[dim]\u2728 +{xp} XP[/]   [yellow]\U0001f4b0 +{gold}g[/]")
    # potion drops
    if random.random() < (0.55 if boss else 0.16):
        if random.random() < 0.6 and hero["hp_pots"] < max_potions(hero) + 2:
            hero["hp_pots"] += 1
            out.append("[red]\U0001f9ea Found a health potion![/]")
        else:
            hero["mp_pots"] += 1
            out.append("[blue]\U0001f9ea Found a mana potion![/]")
    # loot
    item = roll_loot(max(1, hero.get("depth", 1)), boss, hero["cls"])
    if item:
        cur = hero["gear"][item.slot]

        def score(bonus: dict) -> int:
            pos = sum(v for v in bonus.values() if v > 0)
            neg = sum(v for v in bonus.values() if v < 0)
            return pos + 2 * neg  # downsides weigh double: spicy equips, never suicide

        # compare positives only, so tempting cursed pieces get their hearing
        cur_score = score(cur.bonus) if cur else -1
        new_score = score(item.bonus)
        if new_score > cur_score:
            hero["gear"][item.slot] = item
            cursed_txt = " \U0001f608 [red]cursed… at what cost?[/]" if "Cursed" in item.name else ""
            set_txt = f" [gold1]⟪{item.set_name}⟫[/]" if item.set_name else ""
            out.append(f"[{item.color}]\U0001f455 LOOT: {item.short()}[/]{set_txt} — equipped!{cursed_txt}")
        else:
            vend = max(0, int(sum(v for v in item.bonus.values() if v > 0) * 4 + 10))
            hero["gold"] += vend
            out.append(f"[dim]\U0001f455 {item.short()} — salvaged for {vend}g.[/]")
    # level ups (possibly multiple)
    while hero["xp"] >= xp_needed(hero["level"]):
        hero["xp"] -= xp_needed(hero["level"])
        hero["level"] += 1
        g = CLASSES[hero["cls"]]["grow"]
        hero["max_hp"] += g["max_hp"]
        hero["max_mp"] += g["max_mp"]
        hero["atk"] += g["atk"]
        hero["df"] += g["df"]
        hero["spd"] += g["spd"]
        hero["hp"] = hero_max_hp(hero)
        hero["mp"] = hero_max_mp(hero)
        new_skills = [s for s in CLASSES[hero["cls"]]["skills"] if s.unlock == hero["level"]]
        out.append(f"[bold yellow]\U0001f386 LEVEL UP! Now level {hero['level']}[/] — fully restored!")
        for s in new_skills:
            out.append(f"[bold cyan]\u2728 New skill: {s.icon} {s.name}[/] — {s.desc}")
    # normalize floats from growth
    hero["atk"] = round(hero["atk"], 1)
    hero["df"] = round(hero["df"], 1)
    hero["spd"] = round(hero["spd"], 1)
    return out


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

console = Console()


def hp_color(p: float) -> str:
    return "green" if p > 0.55 else "yellow" if p > 0.28 else "red"


def eff_int(hero: dict, stat: str) -> str:
    v = hero_eff(hero, stat)
    base = hero[{"atk": "atk", "df": "df", "spd": "spd"}[stat]]
    iv = int(round(v))
    if v > base:
        return f"[cyan]{iv}[/]"
    if v < base:
        return f"[red]{iv}[/]"
    return str(iv)


def hero_panel(hero: dict) -> Panel:
    c = CLASSES[hero["cls"]]
    mxhp, mxmp = hero_max_hp(hero), hero_max_mp(hero)
    php, pmp = hero["hp"] / max(1, mxhp), hero["mp"] / max(1, mxmp)
    need = xp_needed(hero["level"])
    pxp = hero["xp"] / max(1, need)
    buff_txt = " ".join(f"[magenta]{k}{v[0]:+}({v[1]}t)[/]" for k, v in hero["buffs"].items()) or "[dim]—[/]"
    g = hero["gear"]
    def gear_line(slot: str) -> str:
        it = g[slot]
        if not it:
            return "[dim]empty[/]"
        b = " ".join(f"{v:+}{k}" for k, v in it.bonus.items())
        set_txt = f" [gold1]⟪{it.set_name}⟫[/]" if it.set_name else ""
        return f"[{it.color}]{it.name}[/]{set_txt} [dim]{b}[/]"
    sets = worn_sets(hero)
    set_txt = " ".join(f"[gold1]⟪{s}⟫×{n}[/]" for s, n in sets.items()) or "[dim]—[/]"

    body = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    body.add_column(style="dim", width=5)
    body.add_column()
    body.add_row("LV", f"[bold yellow]{hero['level']}[/]  [dim]{hero['xp']}/{need} XP[/] [cyan]{bar(hero['xp'], need, 12)}[/]")
    body.add_row("HP", f"[{hp_color(php)}]{bar(hero['hp'], mxhp, 12)}[/] [bold]{hero['hp']}/{mxhp}[/]")
    body.add_row("MP", f"[blue]{bar(hero['mp'], mxmp, 12)}[/] [bold]{hero['mp']}/{mxmp}[/]")
    body.add_row("ATK", f"{eff_int(hero, 'atk')}   DEF {eff_int(hero, 'df')}   SPD {eff_int(hero, 'spd')}")
    body.add_row("CRT", f"{hero['crit']}%   DDG {hero['dodge'] + hero['buffs'].get('dodge', [0, 0])[0]}%")
    body.add_row("\U0001f4b0", f"[yellow]{hero['gold']}g[/]   \U0001f9ea [red]{hero['hp_pots']}[/]/[blue]{hero['mp_pots']}[/]")
    body.add_row("\U0001f455", f"[dim]W:[/] {gear_line('Weapon')}")
    body.add_row("", f"[dim]A:[/] {gear_line('Armor')}")
    body.add_row("", f"[dim]T:[/] {gear_line('Trinket')}")
    body.add_row("", f"[dim]R:[/] {gear_line('Ring')}")
    body.add_row("", f"[dim]B:[/] {gear_line('Boots')}")
    body.add_row("\u2728", buff_txt)
    body.add_row("[gold1]SET[/]", set_txt)
    return Panel(body, title=f"{c['icon']} [bold {c['color']}]{hero['name']}[/] · {hero['cls']}",
                 border_style=c["color"], box=box.ROUNDED)


def foe_panel(foe: Fighter | None, depth: int, room: int, boss_room: bool) -> Panel:
    if foe is None:
        return Panel(Align.center("[dim]…the dark is quiet…[/]"), title="\U0001f47e Encounter",
                     border_style="dim", box=box.ROUNDED)
    p = foe.hp / max(1, foe.max_hp)
    tag = " [red]\U0001f480 BOSS[/]" if foe.kind == "boss" else ""
    dots = (" " + " ".join(f"[green]{d[2]}({d[1]})[/]" for d in foe.dots)) if foe.dots else ""
    debuff = ""
    if "df" in foe.buffs and foe.buffs["df"][0] < 0:
        debuff += f" [red]BRKN({foe.buffs['df'][1]})[/]"
    if "spd" in foe.buffs and foe.buffs["spd"][0] < 0:
        debuff += f" [cyan]SLOW({foe.buffs['spd'][1]})[/]"
    body = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    body.add_column(style="dim", width=5)
    body.add_column()
    body.add_row("LV", f"[bold]{foe.level}[/]{tag}{dots}{debuff}")
    body.add_row("HP", f"[{hp_color(p)}]{bar(foe.hp, foe.max_hp, 14)}[/] [bold]{foe.hp}/{foe.max_hp}[/]")
    body.add_row("DMG", f"[red]{int(foe.eff('atk'))}[/]   ARM {int(foe.eff('df'))}   SPD {int(foe.eff('spd'))}")
    style = "bold red" if foe.kind == "boss" else "red"
    room_txt = "BOSS" if boss_room else f"{room}/{ROOMS_PER_LEVEL}"
    tcolor = CREATURE_TYPES.get(foe.ctype, "white")
    tlabel = f"[{tcolor}]{foe.ctype}[/]" if foe.ctype else ""
    return Panel(body, title=f"[{style}]\U0001f479 {foe.name}[/] [dim]· Lv{foe.level} · {room_txt}[/] {tlabel}",
                 border_style="red" if foe.kind == "boss" else "#8a7a6a", box=box.ROUNDED)


def arena_panel(depth: int, room: int, boss_room: bool, turn: int, state: str) -> Panel:
    d = dungeon_for_depth(depth)
    lines = Text()
    lines.append(f"{d['icon']}  {d['name']}\n", style=f"bold {d['color']}")
    lines.append(f"{d['desc']}\n", style="dim italic")
    lines.append(f"Depth {depth}  •  ", style="bold white")
    if state == "rest":
        lines.append("catching breath…", style="green")
    elif boss_room:
        lines.append("BOSS ROOM — hide!", style="bold red")
    else:
        lines.append(f"Room {room}/{ROOMS_PER_LEVEL}", style="dim")
    lines.append(f"\nTurn {turn}", style="dim")
    # progress map: cleared rooms, current position, boss gate
    lines.append("\n\n")
    cleared = ROOMS_PER_LEVEL if boss_room else max(0, room - 1)
    cells = []
    for i in range(1, ROOMS_PER_LEVEL + 1):
        if i <= cleared:
            cells.append("[green]✓[/]")
        elif i == room and not boss_room:
            cells.append("[bold yellow]▶[/]")
        else:
            cells.append("[dim]·[/]")
    cells.append("[black on yellow] \U0001f479 [/]" if boss_room else "[dim]\U0001f479[/]")
    lines.append_text(Text.from_markup("─".join(cells) + "\n"))
    # depth trail with the ★20 goal
    trail = []
    for dd in range(max(1, depth - 2), depth + 3):
        if dd < depth:
            trail.append(f"[green]{dd}✓[/]")
        elif dd == depth:
            trail.append(f"[black on yellow] {dd} [/]")
        else:
            trail.append(f"[dim]{dd}·[/]")
    if depth < 20:
        goal = "  [gold1]★20 good run[/]"
    elif depth == 20:
        goal = "  [bold gold1]★20![/]"
    else:
        goal = "  [gold1]★20 ✓[/]"
    lines.append_text(Text.from_markup(" ".join(trail) + goal))
    return Panel(Align.center(lines), title="\U0001f5fa\ufe0f Whereabouts", border_style=d["color"], box=box.ROUNDED)


def skills_panel(hero: dict, paused: bool, speed: float, base_tick: float, auto_pots: bool) -> Panel:
    t = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    t.add_column(width=16)
    t.add_column()
    if hero["cls"] == "Rogue":
        armed = hero.get("ambush", False)
        t.add_row("[bold yellow]\U0001f5e1\ufe0f Ambush[/]" if armed else "[dim]\U0001f5e1\ufe0f Ambush[/]",
                  "[green]armed[/]" if armed else "[dim]spent[/]")
    for s in CLASSES[hero["cls"]]["skills"]:
        if hero["level"] < s.unlock:
            t.add_row(f"[dim]{s.icon} {s.name}[/]", f"[dim]Lv{s.unlock}[/]")
            continue
        if s.key in hero["cds"]:
            t.add_row(f"[dim]{s.icon} {s.name}[/]", f"[yellow]CD {hero['cds'][s.key]}[/]")
        elif hero["mp"] < s.mp:
            t.add_row(f"[dim]{s.icon} {s.name}[/]", f"[blue]MP {s.mp}[/]")
        else:
            t.add_row(f"[white]{s.icon} {s.name}[/]", f"[dim]{s.mp}MP[/]" if s.mp else "[green]ready[/]")
    t.add_row("", "")
    t.add_row("[dim]\U0001f9ea potions quaff themselves[/]", "[dim][Space]pause  [Q]quit[/]")
    t.add_row(f"[dim]speed {speed:g}x ({base_tick / speed:.2f}s) [+/-][/]", "[green]AUTO-POTS ON[/]" if auto_pots else "[red]AUTO-POTS OFF [A][/]")
    if paused:
        t.add_row("[bold yellow]\u23f8\ufe0f PAUSED[/]", "")
    return Panel(t, title="\u2728 Skills & Keys", border_style="cyan", box=box.ROUNDED)


def log_panel(log: deque) -> Panel:
    if not log:
        txt = "[dim]Your tale begins…[/]"
    else:
        txt = "\n".join(log)
    return Panel(txt, title="\U0001f4dc Chronicle", border_style="#8a7a6a", box=box.ROUNDED)


def build_layout(hero, foe, log, depth, room, boss_room, turn, speed, base_tick, paused, auto_pots, state) -> Layout:
    lay = Layout()
    lay.split_column(
        Layout(name="head", size=3),
        Layout(name="mid", ratio=1),
        Layout(name="bot", ratio=1),
    )
    lay["mid"].split_row(
        Layout(name="left", ratio=34),
        Layout(name="center", ratio=26),
        Layout(name="right", ratio=34),
    )
    lay["bot"].split_row(
        Layout(name="log", ratio=62),
        Layout(name="sk", ratio=38),
    )
    d = dungeon_for_depth(depth)
    lay["head"].update(Panel(
        Align.center(Text.from_markup(
            f"[bold gold1]⚔ IDLEDRAGONS ⚔[/]   [dim]│[/]   "
            f"[{d['color']}]{d['icon']} {d['name']} — Depth {depth}[/]   [dim]│[/]   "
            f"[yellow]\U0001f480 {hero['boss_kills']} slain[/]   [dim]│[/]   [red]\u2620\ufe0f {hero['kills']} kills[/]"
        )),
        box=box.HEAVY, border_style="gold1",
    ))
    lay["left"].update(hero_panel(hero))
    lay["center"].update(arena_panel(depth, room, boss_room, turn, state))
    lay["right"].update(foe_panel(foe, depth, room, boss_room))
    lay["log"].update(log_panel(log))
    lay["sk"].update(skills_panel(hero, paused, speed, base_tick, auto_pots))
    return lay


# --------------------------------------------------------------------------- #
# Keyboard (non-blocking single keypress)
# --------------------------------------------------------------------------- #

class Keyboard:
    def __init__(self):
        self.fd = None
        self.old = None
        self.active = False

    def __enter__(self):
        try:
            if os.name == "nt":
                import msvcrt  # noqa
                self.active = True
                return self
            self.fd = sys.stdin.fileno()
            import termios
            import tty
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            self.active = True
        except Exception:
            self.active = False
        return self

    def __exit__(self, *a):
        try:
            if self.old is not None:
                import termios
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
        except Exception:
            pass
        self.active = False

    def poll(self) -> str | None:
        try:
            if os.name == "nt":
                import msvcrt
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    return ch.lower()
                return None
            if not self.active:
                return None
            r, _, _ = select.select([sys.stdin], [], [], 0)
            if r:
                ch = os.read(self.fd, 1).decode("utf-8", "ignore")
                return ch.lower() if ch else None
        except Exception:
            return None
        return None


# --------------------------------------------------------------------------- #
# Character creation
# --------------------------------------------------------------------------- #

def creation_screen(args) -> tuple[str, str]:
    c = Console()
    c.clear()
    c.print(Align.center(Text(TITLE_ART, style="bold gold1")))
    c.print(Align.center(Text("~ a pretty little terminal idleRPG ~", style="italic dim")))
    c.print()
    t = Table(title="\U0001f3b2 Choose thy class", box=box.ROUNDED, expand=False)
    t.add_column("#", justify="right", style="bold yellow")
    t.add_column("Class", style="bold white")
    t.add_column("HP/MP/ATK/DEF/SPD")
    t.add_column("Flavor", style="dim")
    t.add_column("Signature", style="cyan")
    for i, cn in enumerate(CLASS_LIST, 1):
        d = CLASSES[cn]
        b = d["base"]
        sig = ", ".join(s.name for s in d["skills"] if s.unlock >= 3)
        t.add_row(str(i), f"[{d['color']}]{d['icon']} {cn}[/]",
                  f"{b['max_hp']}/{b['max_mp']}/{b['atk']}/{b['df']}/{b['spd']}",
                  d["flavor"], sig)
    c.print(Align.center(t))
    c.print()
    scores = load_scores()
    if scores and not args.demo:
        c.print(Align.center(Text("— HALL OF FALLEN HEROES —", style="bold gold1")))
        c.print(scores_table(scores, limit=5))
        c.print()
    if args.demo:
        return "Demo" + random.choice(["na", "ric", "lia"]), random.choice(CLASS_LIST)
    try:
        name = c.input("[bold yellow]Name thy hero[/] [dim](Enter=random)[/]: ").strip()
    except (EOFError, KeyboardInterrupt):
        name = ""
    if not name:
        name = random.choice(["Kaelis", "Brynna", "Oz", "Tam", "Seraphine", "Dain", "Mira", "Jorah"]) + \
            " " + random.choice(["Ashdown", "Thorn", "Blackbarrow", "Lightfoot", "Stormborn"])
    c.print()
    while True:
        try:
            raw = c.input(f"[bold yellow]Pick a class[/] [dim](1-{len(CLASS_LIST)})[/]: ").strip()
        except (EOFError, KeyboardInterrupt):
            raw = "1"
        if raw.isdigit() and 1 <= int(raw) <= len(CLASS_LIST):
            return name, CLASS_LIST[int(raw) - 1]
        c.print("[red]Enter a number from the table.[/]")


def death_screen(c: Console, hero: dict, foe_name: str, scores: list, rank: int) -> None:
    c.clear()
    c.print(Align.center(Text("\U0001f480  YOU DIED  \U0001f480", style="bold red")))
    c.print(Align.center(Text(f"{hero['name']} the {hero['cls']} · Level {hero['level']} · Depth {hero['depth']} · {hero['turns']} turns",
                              style="dim")))
    c.print(Align.center(Text(f"Slain by {foe_name}", style="italic red")))
    c.print()
    stats = Table(box=box.ROUNDED, title="\u2728 Saga summary")
    stats.add_column("Deed", style="dim")
    stats.add_column("Tally", justify="right", style="bold white")
    stats.add_row("Dungeon depth", str(hero["depth"]))
    stats.add_row("Character level", str(hero["level"]))
    stats.add_row("Monsters slain", str(hero["kills"]))
    stats.add_row("Bosses slain", str(hero["boss_kills"]))
    stats.add_row("Gold hoarded", f"{hero['gold']}g")
    stats.add_row("Potions quaffed", str(hero["potions_used"]))
    c.print(Align.center(stats))
    c.print()
    c.print(Align.center(Text(f"— Rank #{rank + 1} in the Hall of Fallen Heroes —", style="bold gold1")))
    c.print(scores_table(scores, highlight=rank))
    c.print()
    c.print(Align.center(Text("Press Enter to return to the tavern…", style="dim")))
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass


# --------------------------------------------------------------------------- #
# Game loop
# --------------------------------------------------------------------------- #

def run_game(name: str, cls: str, tick: float, demo_ticks: int = 0) -> None:
    hero = make_hero(name, cls)
    hero["depth"] = 1
    log: deque = deque(maxlen=MAX_LOG)
    c = CLASSES[cls]
    log.append(f"[bold {c['color']}]\U0001f388 {name}, {cls} of the {random.choice(['Silver Marches','Dalelands','Sword Coast','Underdark Exiles'])}[/], enters the dark.")
    log.append(f"[dim]{D20} The innkeep wishes thee luck. Potions stocked: {hero['hp_pots']}HP/{hero['mp_pots']}MP.[/]")
    kit = ", ".join(hero["gear"][s].name for s in ("Weapon", "Armor", "Trinket"))
    log.append(f"[dim]\U0001f455 Starter kit issued: {kit}. Try not to bleed on it.[/]")

    depth = 1
    room = 1
    boss_room = False
    foe: Fighter | None = None
    state = "combat"      # combat | rest (breather on the landing)
    rest_left = 0
    turn = 0
    paused = False
    auto_pots = True
    base_tick = tick
    speed_idx = DEFAULT_SPEED_IDX
    demo_left = demo_ticks

    def new_foe() -> Fighter:
        nonlocal boss_room
        boss_room = (room > ROOMS_PER_LEVEL)
        m = make_monster(depth, hero["level"], boss=boss_room)
        hero["ambush"] = True  # Rogue: first landed hit each fight crits
        if m.kind == "boss":
            log.append(f"[bold red]\U0001f480 A NAMED FOE bars the stair: {m.name}![/] [dim](Lv{m.level})[/]")
            log.append(f"[dim italic]\"{random.choice(['Your bones will pave my hall.','Another candle gutters out.','The dark keeps what it catches.', 'Kneel, little spark.'])}\"[/]")
        else:
            log.append(f"[{dungeon_for_depth(depth)['color']}]— Room {room}: {m.name}[/] [dim](Lv{m.level}) stalks forth…[/]")
        return m

    foe = new_foe()

    with Keyboard() as kb, Live(build_layout(hero, foe, log, depth, room, boss_room, turn,
                                             SPEEDS[speed_idx], base_tick, paused, auto_pots, state),
                                console=console, refresh_per_second=8, screen=True) as live:
        def handle_key(key: str | None) -> bool:
            """Process one keypress. Returns True if the run should quit."""
            nonlocal paused, auto_pots, speed_idx
            if not key:
                return False
            if key in ("q", "\x03"):
                live.stop()
                console.clear()
                console.print("[dim]You slip back to the tavern. The dungeon waits…[/]")
                console.print(f"[dim]{hero['name']} · Lv{hero['level']} · Depth {depth} (abandoned, not scored)[/]")
                return True
            elif key == " ":
                paused = not paused
            elif key == "a":
                auto_pots = not auto_pots
                log.append("[green]Auto-potions ON.[/]" if auto_pots else "[yellow]Auto-potions OFF.[/]")
            elif key in ("+", "="):
                if speed_idx < len(SPEEDS) - 1:
                    speed_idx += 1
                    log.append(f"[cyan]⏩ Speed: {SPEEDS[speed_idx]:g}x ({base_tick / SPEEDS[speed_idx]:.2f}s/tick).[/]")
                else:
                    log.append("[dim]⏩ Already at max speed.[/]")
            elif key in ("-", "_"):
                if speed_idx > 0:
                    speed_idx -= 1
                    log.append(f"[cyan]⏪ Speed: {SPEEDS[speed_idx]:g}x ({base_tick / SPEEDS[speed_idx]:.2f}s/tick).[/]")
                else:
                    log.append("[dim]⏪ Already at slowest.[/]")
            return False

        def drain_keys() -> bool:
            """Process every pending keypress. Returns True if quitting."""
            for _ in range(16):  # cap so a stuck key can't wedge the loop
                k = kb.poll()
                if not k:
                    break
                if handle_key(k):
                    return True
            return False

        while True:
            # ---- input (before tick) ----
            if drain_keys():
                return

            if paused:
                live.update(build_layout(hero, foe, log, depth, room, boss_room, turn,
                                         SPEEDS[speed_idx], base_tick, paused, auto_pots, state))
                time.sleep(0.1)
                continue

            t0 = time.time()
            time.sleep(base_tick / SPEEDS[speed_idx])
            # keys pressed during sleep — same handler, nothing dropped
            if drain_keys():
                return
            if paused:
                live.update(build_layout(hero, foe, log, depth, room, boss_room, turn,
                                         SPEEDS[speed_idx], base_tick, paused, auto_pots, state))
                continue

            turn += 1
            hero["turns"] += 1
            elapsed_note = time.time() - t0

            # ---------------- landing breather between levels ----------------
            if state == "rest":
                rest_left -= 1
                if rest_left == 3:
                    log.append("\U0001f3d8\ufe0f [green]You bar the door on the landing and catch your breath. Wounds bound.[/]")
                    # auto-shop
                    bought = 0
                    while hero["hp_pots"] < max_potions(hero) and hero["gold"] >= POTION_HP_PRICE:
                        hero["gold"] -= POTION_HP_PRICE
                        hero["hp_pots"] += 1
                        bought += 1
                    while hero["mp_pots"] < max_potions(hero) and hero["gold"] >= POTION_MP_PRICE:
                        hero["gold"] -= POTION_MP_PRICE
                        hero["mp_pots"] += 1
                        bought += 1
                    if bought:
                        log.append(f"[yellow]\U0001f6d2 A deep-gnome peddler unrolls a canvas: {bought} potion(s). Purse: {hero['gold']}g.[/]")
                    hero["hp"] = min(hero_max_hp(hero), hero["hp"] + hero_max_hp(hero) // 3)
                    hero["mp"] = hero_max_mp(hero)
                elif rest_left <= 0:
                    depth += 1
                    hero["depth"] = depth
                    room = 1
                    state = "combat"
                    d = dungeon_for_depth(depth)
                    log.append(f"[bold {d['color']}]\U0001f53b Descending… {d['icon']} {d['name']}[/] [dim]— {d['desc']}[/]")
                    foe = new_foe()
                live.update(build_layout(hero, foe if state == "combat" else None, log, depth, room,
                                         boss_room, turn, SPEEDS[speed_idx], base_tick, paused, auto_pots, state))
                if demo_left and (demo_left := demo_left - 1) <= 0:
                    return
                continue

            # ---------------- combat tick ----------------
            assert foe is not None
            # auto potions before acting
            if auto_pots:
                if hero["hp"] < hero_max_hp(hero) * 0.35:
                    m = drink_hp(hero)
                    if m:
                        log.append(m)
                if hero["mp"] < 10 and hero["mp"] < hero_max_mp(hero) * 0.5:
                    m = drink_mp(hero)
                    if m:
                        log.append(m)

            # initiative: faster acts first each round
            hero_spd = hero_eff(hero, "spd")
            foe_spd = foe.eff("spd")
            hero_first = hero_spd >= foe_spd

            def hero_act():
                skill = choose_skill(hero)
                for line in hero_strike(hero, foe, skill):
                    log.append(line)

            def foe_act():
                if foe.alive and hero["hp"] > 0:
                    for line in foe_strike(foe, hero):
                        log.append(line)
                    if foe.kind == "boss" and foe.alive and hero["hp"] > 0:
                        for line in boss_ability(foe, hero):
                            log.append(line)

            # clamp hp/mp display
            hero["hp"] = max(0, min(hero["hp"], hero_max_hp(hero)))
            if hero_first:
                hero_act()
                if foe.alive:
                    foe_act()
            else:
                foe_act()
                if hero["hp"] > 0:
                    hero_act()

            for line in tick_dots(hero, foe):
                log.append(line)
            tick_buffs(hero, foe)

            # ---- death? ----
            if hero["hp"] <= 0:
                killer = f"{foe.name} · {foe.ctype}" if foe.ctype else foe.name
                live.stop()
                entry = {"name": hero["name"], "cls": hero["cls"], "depth": depth,
                         "level": hero["level"], "kills": hero["kills"],
                         "boss_kills": hero["boss_kills"], "gold": hero["gold"],
                         "died_to": killer, "turns": hero["turns"],
                         "date": datetime.date.today().isoformat()}
                scores = save_score(entry)
                rank = next((i for i, s in enumerate(scores)
                             if s["name"] == entry["name"] and s["date"] == entry["date"]
                             and s["died_to"] == killer and s["depth"] == depth
                             and s["level"] == hero["level"]), 0)
                death_screen(console, hero, killer, scores, rank)
                return

            # ---- foe slain? ----
            if not foe.alive:
                was_boss = foe.kind == "boss"
                log.append(f"[bold green]\u2620\ufe0f {foe.name} falls![/]")
                for line in grant_rewards(hero, foe):
                    log.append(line)
                if was_boss:
                    d = dungeon_for_depth(depth)
                    log.append(f"[bold gold1]\U0001f3c6 {d['name']} cleansed! The stair yawns deeper…[/]")
                    state = "rest"
                    rest_left = 4
                    foe = None
                else:
                    room += 1
                    foe = new_foe()

            live.update(build_layout(hero, foe, log, depth, room, boss_room, turn,
                                     SPEEDS[speed_idx], base_tick, paused, auto_pots, state))
            if demo_left and (demo_left := demo_left - 1) <= 0:
                return


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(description="IDLEDRAGONS — a pretty DnD terminal idleRPG")
    ap.add_argument("--tick", type=float, default=TICK_DEFAULT, help="seconds per tick (default 1.0)")
    ap.add_argument("--highscores", action="store_true", help="show hall of fallen heroes and exit")
    ap.add_argument("--reset-highscores", action="store_true", help="wipe highscores and exit")
    ap.add_argument("--demo", type=int, default=0, metavar="TICKS",
                    help="auto-run N ticks with a random hero (no input needed, for testing)")
    args = ap.parse_args()

    if args.reset_highscores:
        if os.path.exists(HIGHSCORE_FILE):
            os.remove(HIGHSCORE_FILE)
        print("Highscores wiped.")
        return
    if args.highscores:
        scores = load_scores()
        console.print(Align.center(Text("— HALL OF FALLEN HEROES —", style="bold gold1")))
        console.print(scores_table(scores, limit=10))
        return

    if args.demo:
        random.seed(7)
        run_game("Demo" + random.choice(["na", "ric"]), random.choice(CLASS_LIST),
                 tick=0.01, demo_ticks=args.demo)
        print("demo OK")
        return

    name, cls = creation_screen(args)
    console.clear()
    run_game(name, cls, tick=args.tick)


if __name__ == "__main__":
    main()

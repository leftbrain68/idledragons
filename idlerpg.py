#!/usr/bin/env python3
"""
IDLEDRAGONS — a DnD-themed terminal idleRPG.
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
from collections import Counter, deque
from dataclasses import dataclass, field

try:
    from rich import box
    from rich.align import Align
    from rich.columns import Columns
    from rich.console import Console
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
CODEX_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codex.json")
LEGENDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "legends.json")
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
    "Ranger":  ["Hunting Bow", "Longbow", "Yew Bow", "Thornbow", "Wyrmslayer Bow"],
    "Paladin": ["Oath Sword", "Warhammer", "Silvered Blade", "Dawnblade", "Justicar"],
    "Barbarian": ["Greataxe", "Maul", "Bone Cleaver", "Frostbrand Axe", "Worldsplitter"],
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

# Short mechanic reminder per type, shown in the monster panel.
TRAIT_BLURB = {
    "Aberration": "your crits -5",
    "Beast": "+4 dodge",
    "Dragon": "fiery breath",
    "Elemental": "ignores slow",
    "Fiend": "rebukes crits",
    "Giant": "sweeping blows",
    "Humanoid": "fat purse",
    "Monstrosity": "+5 crit",
    "Plant": "burns easily",
    "Undead": "no venom",
}

# Flavor per type; named bosses of note get their own line.
TYPE_BLURB = {
    "Aberration": "It should not be. Do not meet its eyes.",
    "Beast": "Teeth, hunger, and no malice at all.",
    "Dragon": "Fire made flesh, and proud of it.",
    "Elemental": "The world, angry and ambulatory.",
    "Fiend": "It collects. Souls preferred.",
    "Giant": "The ground notices when it walks.",
    "Humanoid": "Cruel in the clever way.",
    "Monstrosity": "Nature's rough draft, armed.",
    "Plant": "It photosynthesizes. It also plots.",
    "Undead": "Death was a suggestion.",
}

BOSS_BLURBS = {
    "Squeakus": "A thousand rats. One crown. Zero mercy.",
    "Griznak": "Lost an eye. Found a grudge.",
    "Mother Mycelia": "The bloom that hungers.",
    "Lord Vexmar": "Twice-buried, still collecting rent.",
    "Cinder Maw": "The furnace, given teeth.",
    "Vexalyth": "Eighth House. First knife.",
    "Sussurax": "The wing that splits clouds.",
    "Vermithrax Pejorative": "The Hoardfather counts your bones already.",
    "Ereboss": "That which waits below. It is done waiting.",
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

# One icon per monster for the foe panel title (unique within its dungeon;
# duplicates across far-apart dungeons are fine — bats look alike).
MOB_ICONS = {
    "Cellar Rat": "\U0001f400", "Giant Centipede": "\U0001f41b",
    "Kobold Sneak": "\U0001f98e", "Cave Bat Swarm": "\U0001f987",
    "Goblin Cutter": "\U0001f5e1", "Goblin Slinger": "→",
    "Worg Pup": "\U0001f43a", "Hobgoblin Grunt": "\U0001f479",
    "Myconid Sprout": "\U0001f344", "Spore Bat": "\U0001f987",
    "Cave Fisher": "\U0001f3a3", "Gas Spore": "\U0001f4a8",
    "Skeleton Warrior": "\U0001f480", "Drowned Zombie": "\U0001f9df",
    "Crypt Ghoul": "\U0001f47b", "Wight Acolyte": "\U0001f9db",
    "Magma Mephit": "\U0001f525", "Fire Snake": "\U0001f40d",
    "Ash Zombie": "\U0001f9df", "Duergar Deserter": "\u26cf",
    "Giant Spider": "\U0001f577", "Drow Scout": "\U0001f319",
    "Drider Spawn": "\U0001f578", "Shadow Mastiff": "\U0001f43a",
    "Air Elemental Wisp": "✨", "Gargoyle": "\U0001f5ff",
    "Kenku Stormcaller": "\U0001f426", "Blue Dragon Wyrmling": "\U0001f409",
    "Ogre Brute": "\U0001f44a", "Troll Regenerator": "\U0001f9cc",
    "Mind Flayer Exile": "\U0001f9e0", "Young Red Dragon": "\U0001f432",
    "Depth Horror": "\U0001f441", "Starved Abomination": "\U0001f37d",
    "Whisper Spawn": "\U0001f32b", "Chitin Stalker": "\U0001f41e",
    "Silt Crab": "\U0001f980", "Drowned Sailor": "\U0001f30a",
    "Brine Hag": "\U0001f9d9", "Wreck Revenant": "\U0001f30a",
    "Cinder Imp": "\U0001f608", "Ash Serpent": "\U0001f40d",
    "Charred Husk": "\U0001f32b", "Slag Golem": "\U0001f5ff",
    "Nothic Whisperer": "\U0001f9ff", "Choker": "\U0001f4aa",
    "Darkmantle": "\U0001f302", "Grell": "\U0001f419",
    "Ice Mephit": "\U0001f9ca", "Frost Wight": "❄️",
    "Winter Wolf": "\U0001f43a", "Yeti": "⛰",
    "Lemure": "\U0001f4a9", "Spined Devil": "\U0001f994",
    "Hell Hound": "\U0001f525", "Ashen Cultist": "\U0001f56f",
    "Hill Giant": "\U0001f44a", "Stone Giant": "\U0001f5ff",
    "Wyvern": "\U0001f426", "Griffon": "\U0001f985",
    "Beholderkin": "\U0001f441", "Intellect Devourer": "\U0001f9e0",
    "Cloaker": "\U0001f302", "Aboleth Spawn": "\U0001f991",
    "Death Knight": "\U0001f480", "Balor Spawn": "\U0001f525",
    "Elder Wyrm": "\U0001f432", "Void Titan": "\U0001f30c",
}

BOSS_ICONS = {
    "Squeakus": "\U0001f400", "Griznak": "\U0001f47a",
    "Mother Mycelia": "\U0001f344", "Lord Vexmar": "\U0001f480",
    "Cinder Maw": "\U0001f30b", "Vexalyth": "\U0001f578",
    "Sussurax": "\U0001f329", "Vermithrax Pejorative": "\U0001f432",
    "Tharzarr": "\U0001f441", "Drakphage": "\U0001f409",
    "Yxmirax": "\U0001f300", "Balgore": "\U0001f608",
    "Oomzarr": "\U0001f9db", "Kharvex": "\U0001f479",
    "Zulphage": "❤", "Tharquam": "\U0001f987",
    "Mordrex": "\U0001f41d", "Vexmorth": "\U0001f311",
    "Skarlith": "\U0001f525", "Xarzoth": "\U0001f451",
    "Balzoth": "⚰️", "Oomthune": "\U0001f3b5",
    "Yxquath": "\U0001f444", "Tharzoth": "\U0001f30a",
    "Vexmirax": "\U0001f409", "Drakovex": "⛓️",
    "Skardrex": "❄️", "Morgath": "\U0001f50a",
    "Kharzarr": "\U0001f3f0", "Thulzarr": "\U0001f32a",
    "Yxlim": "\U0001f90f", "Drexbal": "⚒️",
    "Vexthune": "\U0001f3bb", "Skalphage": "\U0001f5fa",
    "Oomgore": "\U0001f534", "Balqua": "\U0001f4a7",
    "Zulmorth": "⌛", "Kharqua": "\U0001f6aa",
    "Drextharr": "✨", "Ereboss": "\U0001f30c",
}

TYPE_ICONS = {
    "Aberration": "\U0001f441", "Beast": "\U0001f43e", "Dragon": "\U0001f432",
    "Elemental": "\U0001f300", "Fiend": "\U0001f608", "Giant": "⛰️",
    "Humanoid": "\U0001f464", "Monstrosity": "\U0001f996", "Plant": "\U0001f33f",
    "Undead": "\U0001f480",
}


def foe_icon(foe: Fighter) -> str:
    """Portrait emoji: boss by name, mob by name, else by creature type."""
    if foe.kind == "boss":
        for key, icon in BOSS_ICONS.items():
            if foe.name.startswith(key):
                return icon
    else:
        base = foe.name
        for pre in ("Elder ", "Alpha ", "Dire "):
            if base.startswith(pre):
                base = base[len(pre):]
                break
        if base in MOB_ICONS:
            return MOB_ICONS[base]
    return TYPE_ICONS.get(foe.ctype, "\U0001f479")


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
            Skill("fire", "Fireball", "\U0001f525", "2.0x fire. The classic.", 16, 3, 1, "nuke", 2.0),
            Skill("frost", "Frost Nova", "\u2744\ufe0f", "1.3x + slow foe (-4 SPD 3t).", 18, 5, 3, "slow", 1.3),
            Skill("surge", "Arcane Surge", "\U0001f320", "3.0x cataclysm.", 34, 7, 5, "nuke", 3.0),
        ],
    },
    "Ranger": {
        "icon": "→", "color": "#2dd4bf",
        "flavor": "Eyes of the wild. Fast, precise, never without an arrow.",
        "base": {"max_hp": 102, "max_mp": 40, "atk": 14, "df": 8, "spd": 12, "crit": 20, "dodge": 10},
        "grow": {"max_hp": 16, "max_mp": 5, "atk": 3.4, "df": 1.6, "spd": 0.9},
        "skills": [
            Skill("shot", "Longshot", "→", "A single true arrow.", 0, 0, 1, "basic", 1.0),
            Skill("volley", "Volley", "\U0001f4a8", "2.0x sky-darkening hail.", 14, 4, 1, "nuke", 2.0),
            Skill("serp", "Serpent Arrow", "\U0001f40d", "1.1x + venom burn (3t).", 12, 5, 3, "dot", 1.1),
            Skill("snare", "Entangling Shot", "\U0001f578", "1.3x + root foe (-4 SPD 3t).", 16, 5, 5, "slow", 1.3),
        ],
    },
    "Paladin": {
        "icon": "\U0001f6e1\ufe0f", "color": "#e5e7eb",
        "flavor": "Oathbound bulwark. Holds the line; the Light holds them.",
        "base": {"max_hp": 112, "max_mp": 40, "atk": 13, "df": 9, "spd": 7, "crit": 10, "dodge": 6},
        "grow": {"max_hp": 20, "max_mp": 5, "atk": 3.0, "df": 2.0, "spd": 0.5},
        "skills": [
            Skill("oathblade", "Oathblade", "\U0001f528", "A vow given edge.", 0, 0, 1, "basic", 1.0),
            Skill("judge", "Judgment", "\u2696\ufe0f", "2.0x weighed and found wanting.", 16, 4, 1, "nuke", 2.0),
            Skill("lay", "Lay on Hands", "\U0001f49b", "Restore 32% HP.", 20, 5, 3, "heal", 0.0, 0.32),
            Skill("iron", "Oath of Iron", "\U0001f6e1\ufe0f", "+6 DEF for 3 turns. Unbroken.", 12, 5, 5, "buff", 0.0),
        ],
    },
    "Barbarian": {
        "icon": "\U0001fa93", "color": "#fb923c",
        "flavor": "Rage given legs. Enormous HP, thin patience, thinner mana.",
        "base": {"max_hp": 114, "max_mp": 20, "atk": 16, "df": 7, "spd": 8, "crit": 15, "dodge": 4},
        "grow": {"max_hp": 24, "max_mp": 2, "atk": 3.8, "df": 1.6, "spd": 0.6},
        "skills": [
            Skill("swing", "Greataxe Swing", "\U0001fa93", "Subtlety is for the dead.", 0, 0, 1, "basic", 1.0),
            Skill("cleave", "Reckless Cleave", "\U0001f4a5", "2.0x everything in front.", 18, 5, 1, "nuke", 2.0),
            Skill("rend", "Rend", "❤", "1.2x + bleeding wounds (3t).", 12, 5, 3, "dot", 1.2),
            Skill("wind", "Second Wind", "\U0001f343", "Restore 22% HP. Still standing.", 18, 6, 5, "heal", 0.0, 0.22),
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
    elite: bool = False  # champion mob: tougher, richer
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


def roll_loot(depth: int, boss: bool, hero_cls: str, bonus_drop: float = 0.0) -> Item | None:
    r = random.random()
    if boss:
        roll = random.random()
        rarity = "Legendary" if roll < 0.12 else "Epic" if roll < 0.40 else "Rare"
    else:
        if r > 0.20 + bonus_drop:
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


def scores_table(scores: list, highlight: int = -1, limit: int = 10, expand: bool = True) -> Table:
    t = Table(box=box.ROUNDED, expand=expand, show_lines=False)
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


def boss_roster() -> list[tuple[str, str]]:
    """(full name, first name) of the 40 fixed bosses, depth order."""
    out = [(f"{a} {b}", a) for d in DUNGEONS for a, b in [d["boss"]]]
    out += [(f"{first} {title}", first) for _, first, title in DEEP_BOSSES]
    return out


ROSTER_40 = boss_roster()


def load_codex() -> dict:
    """Codex data: {'slain': [full names], 'kills': {full name: count}}."""
    try:
        with open(CODEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"slain": [], "kills": {}}
            slain = [s for s in data.get("slain", []) if isinstance(s, str)]
            kills = {k: int(v) for k, v in data.get("kills", {}).items()
                     if isinstance(k, str)}
            return {"slain": slain, "kills": kills}
    except (FileNotFoundError, json.JSONDecodeError):
        return {"slain": [], "kills": {}}


def record_boss(full_name: str) -> tuple[bool, int]:
    """Record a boss kill (counting repeats). Returns (is_new, unique total)."""
    roster_fulls = {full for full, _ in ROSTER_40}
    data = load_codex()
    if full_name not in roster_fulls:
        return False, len(data["slain"])
    slain, kills = data["slain"], data["kills"]
    is_new = full_name not in slain
    if is_new:
        slain.append(full_name)
    kills[full_name] = kills.get(full_name, 0) + 1
    with open(CODEX_FILE, "w", encoding="utf-8") as f:
        json.dump({"slain": slain, "kills": kills}, f, indent=2)
    return is_new, len(slain)


def codex_table(data: dict, cols: int = 10) -> Table:
    have = set(data.get("slain", []))
    kills = data.get("kills", {})
    t = Table(box=box.ROUNDED, show_header=False, padding=(0, 1))
    for _ in range(cols):
        t.add_column()
    row: list[str] = []
    # display-length guard: long names abbreviate to share columns
    short = {"Vermithrax Pejorative": "Vermithrax", "Mother Mycelia": "M. Mycelia"}
    for i, (full, first) in enumerate(ROSTER_40, 1):
        shown = short.get(first, first)
        if full in have:
            n = kills.get(full, 1)
            cell = f"[gold1]{shown}[/]" + (f" [dim]×{n}[/]" if n > 1 else "")
        else:
            cell = f"[dim]{i} · ???[/]"
        row.append(cell)
        if len(row) == cols:
            t.add_row(*row)
            row = []
    if row:
        t.add_row(*row)
    return t


def load_legends() -> list:
    try:
        with open(LEGENDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def record_legend(entry: dict) -> list:
    legends = load_legends()
    legends.append(entry)
    legends.sort(key=lambda e: (-e.get("level", 0), -e.get("turns", 0)))
    legends = legends[:50]
    with open(LEGENDS_FILE, "w", encoding="utf-8") as f:
        json.dump(legends, f, indent=2)
    return legends


def legends_table(legends: list, limit: int = 10, expand: bool = True) -> Table:
    t = Table(box=box.ROUNDED, expand=expand, show_lines=False)
    t.add_column("#", width=3, justify="right")
    t.add_column("Name", style="bold gold1")
    t.add_column("Class")
    t.add_column("Level", justify="right")
    t.add_column("Turns", justify="right")
    t.add_column("Date", style="dim")
    for i, e in enumerate(legends[:limit], 1):
        t.add_row(f"\U0001f451{i}", str(e.get("name", "?")), str(e.get("cls", "?")),
                  str(e.get("level", 0)), str(e.get("turns", 0)), str(e.get("date", "?")))
    if not legends:
        t.add_row("", "[dim]No crowned heroes yet. Ereboss waits.[/]", "", "", "", "")
    return t


SAVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "save.json")


def _item_to_json(it: Item | None) -> dict | None:
    if it is None:
        return None
    return {"slot": it.slot, "name": it.name, "rarity": it.rarity,
            "color": it.color, "bonus": it.bonus, "set_name": it.set_name}


def _item_from_json(d: dict | None) -> Item | None:
    if d is None:
        return None
    return Item(slot=d.get("slot", "?"), name=d.get("name", "?"),
                rarity=d.get("rarity", "Common"), color=d.get("color", "white"),
                bonus=d.get("bonus", {}), set_name=d.get("set_name", ""))


def serialize_run(base_tick, speed_idx, hero, depth, room, boss_room, state,
                  rest_left, turn, auto_pots, foe, log) -> dict:
    h = dict(hero)
    h["gear"] = {s: _item_to_json(it) for s, it in hero["gear"].items()}
    f = None
    if foe is not None:
        f = {"name": foe.name, "kind": foe.kind, "level": foe.level,
             "max_hp": foe.max_hp, "hp": foe.hp, "max_mp": foe.max_mp, "mp": foe.mp,
             "atk": foe.atk, "df": foe.df, "spd": foe.spd, "crit": foe.crit,
             "dodge": foe.dodge, "ctype": foe.ctype, "elite": foe.elite,
             "cds": foe.cds, "buffs": foe.buffs, "dots": foe.dots}
    return {"version": 1, "tick": base_tick, "speed_idx": speed_idx,
            "hero": h, "depth": depth, "room": room, "boss_room": boss_room,
            "state": state, "rest_left": rest_left, "turn": turn,
            "auto_pots": auto_pots, "foe": f, "log": list(log)}


def deserialize_hero(d: dict) -> dict:
    h = dict(d)
    h["gear"] = {s: _item_from_json(it) for s, it in d.get("gear", {}).items()}
    for s in ("Weapon", "Armor", "Trinket", "Ring", "Boots"):
        h["gear"].setdefault(s, None)
    h.setdefault("ambush", False)
    return h


def deserialize_foe(d: dict | None) -> Fighter | None:
    if d is None:
        return None
    d = dict(d)
    d.setdefault("ctype", "")
    d.setdefault("elite", False)
    d.setdefault("cds", {})
    return Fighter(**d)


def load_saved_run() -> dict | None:
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    if not isinstance(data.get("hero"), dict):
        return None
    return data


def clear_saved_run() -> None:
    try:
        os.remove(SAVE_FILE)
    except OSError:
        pass


def _median(xs: list):
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def stats_screen(c: Console) -> None:
    """Run statistics from local highscores + codex."""
    scores = load_scores()
    codex = load_codex()
    c.print(Align.center(Text("— \U0001f4ca RUN STATISTICS —", style="bold cyan")))
    if not scores:
        c.print(Align.center(Text("No runs recorded yet. Go die gloriously.", style="dim")))
        return
    depths = [s.get("depth", 0) for s in scores]
    deepest = max(scores, key=lambda s: (s.get("depth", 0), s.get("level", 0)))
    top_killer, top_kills = Counter(s.get("died_to", "?") for s in scores).most_common(1)[0]
    top_killer_txt = str(top_killer)[:34] + (f" ×{top_kills}" if top_kills > 1 else "")
    wide = c.width >= 110
    ov = Table(box=box.ROUNDED, title="Overall", expand=not wide)
    ov.add_column("Measure", style="dim")
    ov.add_column("Value", justify="right", style="bold white")
    ov.add_row("Runs recorded", str(len(scores)))
    ov.add_row("Median depth", str(_median(depths)))
    ov.add_row("Depth-20 rate", f"{sum(1 for d in depths if d >= 20)}/{len(scores)}")
    ov.add_row("Depth-40 rate", f"{sum(1 for d in depths if d >= 40)}/{len(scores)}")
    ov.add_row("Deepest delve", f"{deepest.get('name')} · depth {deepest.get('depth')} ({deepest.get('cls')})")
    ov.add_row("Most common killer", top_killer_txt)
    ov.add_row("Total turns watched", str(sum(s.get("turns", 0) for s in scores)))
    t = Table(box=box.ROUNDED, title="By class", expand=not wide)
    t.add_column("Class", style="bold white")
    t.add_column("Runs", justify="right")
    t.add_column("Med depth", justify="right")
    t.add_column("Best", justify="right")
    t.add_column("D20%", justify="right")
    t.add_column("D40%", justify="right")
    for cn in CLASS_LIST:
        rows = [s for s in scores if s.get("cls") == cn]
        if not rows:
            t.add_row(f"[{CLASSES[cn]['color']}]{cn}[/]", "0", "—", "—", "—", "—")
            continue
        ds = [s.get("depth", 0) for s in rows]
        t.add_row(f"[{CLASSES[cn]['color']}]{cn}[/]", str(len(rows)), str(_median(ds)), str(max(ds)),
                  f"{sum(1 for d in ds if d >= 20) * 100 // len(rows)}%",
                  f"{sum(1 for d in ds if d >= 40) * 100 // len(rows)}%")
    if c.width >= 110:
        c.print(Align.center(Columns([ov, t], equal=False, expand=False)))
    else:
        c.print(Align.center(ov))
        c.print(Align.center(t))


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
    "Ranger":  [("Weapon", "Hunting Bow", {"ATK": 2}),
                ("Armor", "Worn Leathers", {"DEF": 1}),
                ("Trinket", "Feather Charm", {"SPD": 1})],
    "Paladin": [("Weapon", "Oath Sword", {"ATK": 2}),
                ("Armor", "Dented Pauldrons", {"DEF": 2}),
                ("Trinket", "Iron Prayer Beads", {"HP": 6})],
    "Barbarian": [("Weapon", "Notched Greataxe", {"ATK": 3}),
                ("Armor", "Rawhide Wraps", {"DEF": 1}),
                ("Trinket", "Bear Tooth", {"HP": 6})],
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
    gstat = {"atk": "ATK", "df": "DEF", "spd": "SPD"}.get(stat, stat.upper())
    base = hero[key] + gear_bonus(hero, gstat)
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
    # then ~2.7%/level compounded to 25 (x1.17 @10, x1.61 @20), then nearly
    # flat (+0.5%/level) so legendary runs can reach Ereboss; the endless
    # dark beyond still grows forever. Boss ramp mults cap at 25 likewise.
    # (Retuned after armor DEF started working: heroes are sturdier now.)
    # Boss fights stay short (lean HP) but hit harder with depth;
    # attrition, not one-shots, should end runs. Depth 20 = a good run.
    power = 1.027 ** min(max(0, depth - 2), 23) * 1.005 ** max(0, depth - 25)
    tank = power ** 0.5
    elite = False
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
        hp = int((55 + depth * 34 + lvl * 14) * (1.5 + min(depth, 25) * 0.03) * power)
        atk = int((7 + depth * 2.6 + lvl * 1.5) * (1.05 + min(depth, 25) * 0.012) * power)
        df_ = int((4 + depth * 1.8 + lvl * 0.9) * tank)
        spd = int(6 + depth * 0.7 + lvl * 0.3)
        if depth == 40:
            # Ereboss is a hand-tuned capstone, not a formula output: epic
            # but winnable for a well-geared arrival (~15-25 rounds).
            lvl, hp, atk, df_, spd = 42, 12000, 330, 140, 30
        kind = "boss"
    else:
        name = random.choice(d["mobs"])
        ctype = MOB_TYPES.get(name, "Monstrosity")
        lvl = max(1, hero_level + random.randint(-1, 1))
        elite = random.random() < 0.06
        if elite:
            name = f"{random.choice(['Elder ', 'Alpha ', 'Dire '])}{name}"
        hp = int((30 + depth * 20 + lvl * 11 + random.randint(0, 12)) * power * (1.6 if elite else 1.0))
        atk = int((5 + depth * 1.9 + lvl * 1.2 + random.randint(0, 3)) * power * (1.25 if elite else 1.0))
        df_ = int((2 + depth * 1.2 + lvl * 0.7) * tank)
        spd = int(5 + depth * 0.5 + lvl * 0.35 + random.randint(-1, 2))
        kind = "mob"
    # Type traits baked into stats: Beasts are skittish, Monstrosities all teeth.
    base_crit = 8 if not boss else 14
    base_dodge = 5 if not boss else 8
    return Fighter(name=name, kind=kind, level=lvl, max_hp=hp, hp=hp,
                   atk=atk, df=df_, spd=spd, ctype=ctype,
                   elite=elite,
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
        if hero["cls"] in ("Warrior", "Paladin"):
            hero["buffs"]["df"] = [6, 3, skill.name]
            extra = ""
            if hero["cls"] == "Warrior":
                mend = 8 + hero["level"] * 2
                hero["hp"] = min(hero_max_hp(hero), hero["hp"] + mend)
                extra = f", mending {mend} HP"
            msgs(f"[{cname}]{skill.icon} {skill.name}[/] — [cyan]+6 DEF[/] for 3 turns{extra}!")
        else:
            hero["buffs"]["dodge"] = [18, 3, skill.name]
            msgs(f"[{cname}]{skill.icon} {skill.name}[/] — [cyan]+18% dodge[/] for 3 turns!")
        return out
    if skill.kind == "shield":
        hero["buffs"]["ward"] = [40, 3, "Sanctuary"]
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
    "Cinder Maw":     {"art": "Magma Hide", "icon": "\U0001f30b", "chance": 1.0, "cd": 999, "kind": "bulwark", "threshold": 0.5, "amount": 6},
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
    "Beast":      {"art": "Blood Frenzy", "icon": "❤", "chance": 1.0, "cd": 999, "kind": "rage", "threshold": 0.4, "amount": 5},
    "Humanoid":   {"art": "Dirty Trick", "icon": "\U0001f3ad", "chance": 0.15, "cd": 6, "kind": "hex_dodge", "amount": 8, "dur": 2},
}


def boss_art_for(foe: Fighter) -> dict | None:
    """Signature move for a boss: handcrafted by name, else by creature type."""
    for key, candidate in BOSS_ARTS.items():
        if foe.name.startswith(key):
            return candidate
    return TYPE_ARTS.get(foe.ctype)


def boss_ability(foe: Fighter, hero: dict) -> list[str]:
    """One boss signature move, if its cooldown and the dice allow."""
    out: list[str] = []
    art = boss_art_for(foe)
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
        out.append(f"[red]  \U0001f30b Hide hardens like cooling slag (+{art['amount']} DEF).[/]")
    elif kind == "rage":
        foe.buffs["atk"] = [foe.buffs.get("atk", [0, 0])[0] + art["amount"], 999]
        out.append(tag)
        out.append(f"[red]  ❤ Bloodied and beyond pain (+{art['amount']} ATK).[/]")
    elif kind in ("hex_spd", "hex_dodge", "hex_atk"):
        stat = {"hex_spd": "spd", "hex_dodge": "dodge", "hex_atk": "atk"}[kind]
        hero["buffs"][stat] = [hero["buffs"].get(stat, [0, 0])[0] - art["amount"], art["dur"], art["art"]]
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
        for k, v in buffs.items():
            amt, t = v[0], v[1]  # entries may carry a [2] source label; ignore it here
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
    if foe.elite:
        xp = int(xp * 1.5)
    gold = int(random.randint(8, 20) + foe.level * 6 + (60 if boss else 0))
    if foe.elite:
        gold = int(gold * 1.5)
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
    item = roll_loot(max(1, hero.get("depth", 1)), boss, hero["cls"],
                     bonus_drop=0.25 if foe.elite else 0.0)
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
    parts = []
    for k, v in hero["buffs"].items():
        label = v[2] if len(v) > 2 else k
        parts.append(f"[magenta]{label} ({v[0]:+} {k.upper()}) {v[1]}t[/]")
    buff_txt = " ".join(parts) or "[dim]—[/]"
    g = hero["gear"]
    def gear_line(slot: str) -> str:
        it = g[slot]
        if not it:
            return "[dim]empty[/]"
        b = " ".join(f"{v:+}{k}" for k, v in it.bonus.items())
        set_txt = f" [gold1]⟪{it.set_name}⟫[/]" if it.set_name else ""
        return f"[{it.color}]{it.name}[/]{set_txt} [dim]{b}[/]"
    sets = worn_sets(hero)
    set_txt = " ".join(
        f"[gold1]⟪{s}⟫×{n}[/] [dim]({' '.join(f'{v:+}{k}' for k, v in SET_BONUS.get(s, {}).items())})[/]"
        for s, n in sets.items()) or "[dim]—[/]"

    body = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    body.add_column(style="dim", width=5, justify="left")
    body.add_column(justify="left", ratio=1)
    body.add_row("LV", f"[bold yellow]{hero['level']}[/]  [dim]{hero['xp']:>{len(str(need))}}/{need} XP[/] [cyan]{bar(hero['xp'], need, 12)}[/]")
    body.add_row("HP", f"[{hp_color(php)}]{bar(hero['hp'], mxhp, 12)}[/] [bold]{hero['hp']:>{len(str(mxhp))}}/{mxhp}[/]")
    body.add_row("MP", f"[blue]{bar(hero['mp'], mxmp, 12)}[/] [bold]{hero['mp']:>{len(str(mxmp))}}/{mxmp}[/]")
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
                 title_align="left",
                 border_style=c["color"], box=box.ROUNDED)


def foe_panel(foe: Fighter | None, depth: int, room: int, boss_room: bool) -> Panel:
    if foe is None:
        return Panel(Align.center("[dim]…the dark is quiet…[/]"), title="\U0001f47e Encounter",
                     title_align="left", border_style="dim", box=box.ROUNDED)
    p = foe.hp / max(1, foe.max_hp)
    tag = " [red]\U0001f480 BOSS[/]" if foe.kind == "boss" else ""
    body = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    body.add_column(style="dim", width=5, justify="left")
    body.add_column(justify="left", ratio=1)
    body.add_row("LV", f"[bold]{foe.level}[/]{tag}")
    w = len(str(foe.max_hp))
    body.add_row("HP", f"[{hp_color(p)}]{bar(foe.hp, foe.max_hp, 14)}[/] [bold]{foe.hp:>{w}}/{foe.max_hp}[/]")
    # compact + padded: constant width, so wrapping never flip-flops as
    # buffs toggle values across digit counts (SPD 10 <-> 6 etc.)
    body.add_row("DMG", f"[red]ATK{int(foe.eff('atk')):>3} DEF{int(foe.eff('df')):>3} SPD{int(foe.eff('spd')):>3}[/]")
    fx = []
    for _dmg, _turns, _label in foe.dots:
        fx.append(f"[green]{_label}{_turns}[/]")
    if "df" in foe.buffs and foe.buffs["df"][0] < 0:
        fx.append(f"[red]BRKN{foe.buffs['df'][1]}[/]")
    if "spd" in foe.buffs and foe.buffs["spd"][0] < 0:
        fx.append(f"[cyan]SLOW{foe.buffs['spd'][1]}[/]")
    body.add_row("FX", " ".join(fx) if fx else "[dim]—[/]")
    if foe.kind == "boss":
        art = boss_art_for(foe)
    else:
        art = None
    body.add_row("MOVE", f"{art['icon']} {art['art']}" if art else "[dim]none[/]")
    if foe.ctype in TRAIT_BLURB:
        body.add_row("TRAIT", f"[dim]{TRAIT_BLURB[foe.ctype]}[/]")
    else:
        body.add_row("TRAIT", "[dim]none[/]")
    desc = None
    if foe.kind == "boss":
        for key, blurb in BOSS_BLURBS.items():
            if foe.name.startswith(key):
                desc = blurb
                break
    if desc is None:
        desc = TYPE_BLURB.get(foe.ctype, "")
    if desc:
        body.add_row("DESCR", f"[dim italic]{desc}[/]")
    style = "bold red" if foe.kind == "boss" else "red"
    room_txt = "BOSS" if boss_room else f"{room}/{ROOMS_PER_LEVEL}"
    tcolor = CREATURE_TYPES.get(foe.ctype, "white")
    tlabel = f"[{tcolor}]{foe.ctype}[/]" if foe.ctype else ""
    etag = " [bold magenta]\u2b50ELITE[/]" if foe.elite else ""
    return Panel(body, title=f"[{style}]{foe_icon(foe)} {foe.name}[/] [dim]· Lv{foe.level} · {room_txt}[/] {tlabel}{etag}",
                 title_align="left",
                 border_style="red" if foe.kind == "boss" else "#8a7a6a", box=box.ROUNDED)


def arena_panel(depth: int, room: int, boss_room: bool, turn: int, state: str) -> Panel:
    d = dungeon_for_depth(depth)
    # Left-aligned, like every other panel: a centered block would recenter
    # whenever its longest line changes ("Room 3/5" vs "BOSS ROOM — hide!",
    # growing trail numbers), making the whole window drift.
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
    lines.append("\n\n")
    cleared = ROOMS_PER_LEVEL if boss_room else max(0, room - 1)
    cells = []
    for i in range(1, ROOMS_PER_LEVEL + 1):
        if i <= cleared:
            cells.append("[green]✓[/]")
        elif i == room and not boss_room:
            cells.append("[bold yellow]»[/]")
        else:
            cells.append("[dim]·[/]")
    cells.append("[black on yellow] \U0001f479 [/]" if boss_room else "[dim]\U0001f479[/]")
    lines.append_text(Text.from_markup("─".join(cells) + "\n"))
    # depth trail with the goals (position says it all: left is statue row,
    # right is uncharted; the markers would only cost width)
    trail = []
    for dd in range(max(1, depth - 2), depth + 3):
        if dd == depth:
            trail.append(f"[black on yellow] {dd} [/]")
        else:
            trail.append(f"[dim]{dd}[/]")
    if depth < 20:
        goal = "  [gold1]★20[/] [dim]\U0001f45140[/]"
    elif depth == 20:
        goal = "  [bold gold1]★20![/] [dim]\U0001f45140[/]"
    elif depth < 40:
        goal = "  [gold1]★20✓[/] [dim]\U0001f45140[/]"
    elif depth == 40:
        goal = "  [gold1]★20✓[/] [bold gold1]\U0001f45140![/]"
    else:
        goal = "  [gold1]★20✓ \U0001f45140✓[/]"
    lines.append_text(Text.from_markup(" ".join(trail) + goal))
    return Panel(lines, title="\U0001f5fa\ufe0f Dungeon", title_align="left", border_style=d["color"], box=box.ROUNDED)


def skills_panel(hero: dict, paused: bool, speed: float, base_tick: float, auto_pots: bool) -> Panel:
    t = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    t.add_column(width=16)
    t.add_column(ratio=1)
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
    t.add_row("[white]\U0001f9ea potions quaff themselves[/]",
              "[bold yellow][Space][/] pause  [bold yellow][Q][/] quit")
    t.add_row(f"[dim]speed[/] [bold cyan]{speed:g}x ({base_tick / speed:.2f}s)[/] [bold yellow][+][/][dim]/[/][bold yellow][-][/]",
              "[green]AUTO-POTS ON[/] [bold yellow][A][/]" if auto_pots else "[red]AUTO-POTS OFF[/] [bold yellow][A][/]")
    if paused:
        t.add_row("[bold yellow]\u23f8\ufe0f PAUSED[/]", "")
    return Panel(t, title="\u2728 Skills & Keys", title_align="left", border_style="cyan", box=box.ROUNDED)


def log_panel(log: deque) -> Panel:
    if not log:
        txt = "[dim]Your tale begins…[/]"
    else:
        txt = "\n".join(log)
    return Panel(txt, title="\U0001f4dc Chronicle", title_align="left", border_style="#8a7a6a", box=box.ROUNDED)


def build_layout(hero, foe, log, depth, room, boss_room, turn, speed, base_tick, paused, auto_pots, state) -> Layout:
    lay = Layout()
    lay.split_column(
        Layout(name="head", size=3),
        Layout(name="body", ratio=1),
    )
    # One shared right column (monster over skills) so their borders align
    # by construction at every terminal width — no fractional rounding.
    lay["body"].split_row(
        Layout(name="leftarea", ratio=60),
        Layout(name="rightcol", ratio=34),
    )
    lay["leftarea"].split_column(
        Layout(name="toprow", ratio=1),
        Layout(name="log", ratio=1),
    )
    lay["toprow"].split_row(
        Layout(name="left", ratio=34),
        Layout(name="center", ratio=26),
    )
    lay["rightcol"].split_column(
        Layout(name="right", ratio=1),
        Layout(name="sk", ratio=1),
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
    c.print(Align.center(Text("~ a terminal idleRPG ~", style="italic dim")))
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
    if hero.get("crowned"):
        c.print(Align.center(Text("\U0001f451 Crowned in life — a legend either way.", style="bold gold1")))
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
    n_codex = len(load_codex()["slain"])
    c.print(Align.center(Text(f"\U0001f4d6 Boss Codex: {n_codex}/40", style="bold gold1")))
    c.print()
    stats_screen(c)
    c.print()
    c.print(Align.center(Text("Press Enter to return to the tavern…", style="dim")))
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass


def victory_screen(c: Console, hero: dict, legends: list) -> str:
    """Ascension splash after Ereboss falls. Returns 'continue' or 'retire'."""
    c.clear()
    c.print(Align.center(Text("\U0001f451  ASCENSION  \U0001f451", style="bold gold1")))
    c.print(Align.center(Text(f"{hero['name']} the {hero['cls']} has slain Ereboss, the Bottom of Everything!",
                              style="bold white")))
    c.print(Align.center(Text(f"Level {hero['level']} · {hero['turns']} turns · {hero['kills']} kills · {hero['boss_kills']} bosses",
                              style="dim")))
    c.print(Align.center(Text("The Deep Dark has no more names for you.", style="italic dim")))
    c.print()
    c.print(Align.center(Text("— HALL OF LEGENDS —", style="bold gold1")))
    c.print(legends_table(legends, limit=10))
    c.print()
    c.print(Align.center(Text("[Enter] delve on into the endless dark (41+)    [Q] retire a legend", style="dim")))
    try:
        raw = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "continue"
    return "retire" if raw in ("q", "quit") else "continue"


# --------------------------------------------------------------------------- #
# Game loop
# --------------------------------------------------------------------------- #

def run_game(name: str, cls: str, tick: float, demo_ticks: int = 0,
             persist: bool = True, resume: dict | None = None) -> None:
    if resume:
        hero = deserialize_hero(resume["hero"])
        depth = resume.get("depth", 1)
        room = resume.get("room", 1)
        boss_room = resume.get("boss_room", False)
        foe = deserialize_foe(resume.get("foe"))
        state = resume.get("state", "combat")
        rest_left = resume.get("rest_left", 0)
        turn = resume.get("turn", 0)
        auto_pots = resume.get("auto_pots", True)
        base_tick = resume.get("tick", tick)
        speed_idx = resume.get("speed_idx", DEFAULT_SPEED_IDX)
        log: deque = deque(resume.get("log", []), maxlen=MAX_LOG)
        log.append("[dim]\U0001f4be Run resumed. The dark kept your seat warm.[/]")
        hero["hp"] = max(0, min(hero["hp"], hero_max_hp(hero)))
        hero["mp"] = max(0, min(hero["mp"], hero_max_mp(hero)))
        paused = False
        demo_left = demo_ticks
    else:
        hero = make_hero(name, cls)
        hero["depth"] = 1
        log = deque(maxlen=MAX_LOG)
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
            if m.elite:
                log.append(f"[bold magenta]\u2b50 CHAMPION: {m.name}[/] [dim](Lv{m.level}, {m.ctype}) blocks the way![/]")
            else:
                log.append(f"[{dungeon_for_depth(depth)['color']}]— Room {room}: {m.name}[/] [dim](Lv{m.level}) stalks forth…[/]")
        return m

    foe = new_foe() if resume is None else foe

    def save_game(silent: bool = False) -> None:
        if not persist or demo_ticks:
            return
        try:
            with open(SAVE_FILE, "w", encoding="utf-8") as f:
                json.dump(serialize_run(base_tick, speed_idx, hero, depth, room,
                                        boss_room, state, rest_left, turn,
                                        auto_pots, foe, log), f)
        except OSError:
            return
        if not silent:
            log.append("[dim]\U0001f4be progress saved.[/]")

    save_game(silent=True)

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
                save_game(silent=True)
                console.clear()
                console.print("[dim]You slip back to the tavern. The dungeon waits…[/]")
                console.print(f"[dim]{hero['name']} · Lv{hero['level']} · Depth {depth} (saved — --resume to continue · not scored)[/]")
                if hero.get("crowned"):
                    console.print("[gold1]\U0001f451 You leave crowned — the Hall of Legends remembers.[/]")
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
            if turn % 50 == 0:
                save_game()

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
                if persist:
                    scores = save_score(entry)
                    rank = next((i for i, s in enumerate(scores)
                                 if s["name"] == entry["name"] and s["date"] == entry["date"]
                                 and s["died_to"] == killer and s["depth"] == depth
                                 and s["level"] == hero["level"]), 0)
                    clear_saved_run()
                else:
                    scores = load_scores()  # demos watch but never enter the hall
                    rank = len(scores)
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
                    is_new, n = (record_boss(foe.name) if persist else (False, 0))
                    if is_new:
                        log.append(f"[bold gold1]\U0001f4d6 Codex: {foe.name} recorded! ({n}/40)[/]")
                    if depth == 40:
                        # ASCENSION: Ereboss is dead. Legend first, then choose.
                        hero["crowned"] = True
                        legends = record_legend({"name": hero["name"], "cls": hero["cls"],
                                                 "level": hero["level"], "turns": hero["turns"],
                                                 "date": datetime.date.today().isoformat()}) if persist else load_legends()
                        live.stop()
                        if victory_screen(console, hero, legends) == "retire":
                            if persist:
                                save_score({"name": hero["name"], "cls": hero["cls"], "depth": depth,
                                            "level": hero["level"], "kills": hero["kills"],
                                            "boss_kills": hero["boss_kills"], "gold": hero["gold"],
                                            "died_to": "\U0001f451 Crowned, retired", "turns": hero["turns"],
                                            "date": datetime.date.today().isoformat()})
                                clear_saved_run()
                            console.print("[dim]You hang up your sword. The songs will do the rest.[/]")
                            return
                        live.start()
                        log.append("[bold gold1]\U0001f451 Crowned — and still delving. The dark beyond has no names.[/]")
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
    ap = argparse.ArgumentParser(description="IDLEDRAGONS — a DnD terminal idleRPG")
    ap.add_argument("--tick", type=float, default=TICK_DEFAULT, help="seconds per tick (default 1.0)")
    ap.add_argument("--highscores", action="store_true", help="show hall of fallen heroes and exit")
    ap.add_argument("--stats", action="store_true", help="show run statistics and exit")
    ap.add_argument("--resume", action="store_true", help="resume the saved run (Q saves; death/retire clears)")
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
        codex = load_codex()
        total_kills = sum(codex.get("kills", {}).values())
        legends = load_legends()
        console.print(Align.center(Text("— HALL OF FALLEN HEROES —", style="bold gold1")))
        console.print(scores_table(scores, limit=5))
        console.print(Align.center(Text(f"— \U0001f451 HALL OF LEGENDS {len(legends)} —", style="bold gold1")))
        console.print(legends_table(legends, limit=5))
        console.print(Align.center(Text(f"— \U0001f4d6 BOSS CODEX {len(codex['slain'])}/40 · {total_kills} kills —", style="bold gold1")))
        console.print(Align.center(codex_table(codex, cols=10 if console.width >= 120 else 5)))
        stats_screen(console)
        return
    if args.stats:
        stats_screen(console)
        return
    if args.resume:
        data = load_saved_run()
        if data is None:
            print("No saved run found (save.json). Q saves; death and retire clear it.")
            return
        h = data["hero"]
        console.print(f"[dim]\U0001f4be Resuming {h['name']} the {h['cls']} — depth {data.get('depth', 1)}, turn {data.get('turn', 0)}.[/]")
        run_game(h["name"], h["cls"], tick=args.tick, resume=data)
        return

    if args.demo:
        random.seed(7)
        run_game("Demo" + random.choice(["na", "ric"]), random.choice(CLASS_LIST),
                 tick=0.01, demo_ticks=args.demo, persist=False)
        print("demo OK")
        return

    name, cls = creation_screen(args)
    console.clear()
    run_game(name, cls, tick=args.tick)


if __name__ == "__main__":
    main()

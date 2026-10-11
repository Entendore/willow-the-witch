# ======================================================================
#  WILLOW THE WITCH - Potion Ventures  (FINAL - complete project)
#
#  TABLE OF CONTENTS
#    [1] Imports & tuning constants
#    [2] Chiptune audio engine (pure-python synth: SFX bank + 4 themes)
#    [3] Game data ........ quality, ingredients, potions, catalysts,
#                           terrain, biomes, landmarks, monsters,
#                           buildings, layout spots, ui config
#    [4] Narrative ........ villagers, personas, feuds, favors, events,
#                           rumors, story chapters, finale
#    [5] Small helpers .... text, bars, orbs, wrapping, choices
#    [6] Entities ......... Player, Bolt, Pickup, FloatText, Node, Monster
#    [7] Game class
#        7.1  setup & lifecycle        7.9  gameplay systems
#        7.2  audio interface          7.10 input handling
#        7.3  save / load              7.11 update loop
#        7.4  menu framework           7.12 world rendering
#        7.5  inventory/gold/xp/buffs  7.13 HUD rendering
#        7.6  social & feuds           7.14 overlay rendering
#        7.7  story & chronicle        7.15 main loop
#        7.8  world generation
#    [8] Entry point
#
#  Requires: pygame 2.x   (pip install pygame)
# ======================================================================
import os
os.environ.setdefault("SDL_VIDEO_CENTERED", "1")

import pygame
import random
import math
import sys
import json
from array import array

# ======================================================================
#  [1] IMPORTS & TUNING CONSTANTS
# ======================================================================
SCREEN_W, SCREEN_H = 1024, 768
FPS                = 60
ROAD_W             = 26            # road thickness (world & minimap)
SAVE_PATH          = "willow_save.json"

PLAYER_MAX_HP  = 100
MAX_CONTRACTS  = 3                 # orders you can hold at once
BOARD_SIZE     = 3                 # offers shown on the order board
HOTBAR_SLOTS   = 4                 # quick-drink potion slots
SATCHEL_ROWS   = 13                # visible rows in satchel
CHRON_ROWS     = 13                # visible entries in chronicle
MENU_SLIDE_T   = 0.14              # menu open animation seconds
DANGER_MUSIC_R = 230               # monsters nearer than this -> danger theme

CRAFT_KEYS = (pygame.K_e, pygame.K_q, pygame.K_c, pygame.K_x,
              pygame.K_r, pygame.K_v, pygame.K_b, pygame.K_f)

# mixer must be configured BEFORE pygame.init(); 22 kHz mono 16-bit
try:
    pygame.mixer.pre_init(22050, -16, 1, 512)
except pygame.error:
    pass
pygame.init()
try:
    pygame.mixer.init()
except pygame.error:
    pass
AUDIO_OK = pygame.mixer.get_init() is not None
if AUDIO_OK:
    SR, _BITS, MIXCH = pygame.mixer.get_init()
else:
    SR, MIXCH = 22050, 1

screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
pygame.display.set_caption("Willow the Witch - Potion Ventures")
clock = pygame.time.Clock()

FONT_S  = pygame.font.Font(None, 20)
FONT_M  = pygame.font.Font(None, 26)
FONT_L  = pygame.font.Font(None, 40)
FONT_XL = pygame.font.Font(None, 68)

WHITE  = (240, 240, 240)
GREY   = (165, 165, 175)
GOLD   = (250, 205, 80)
GREEN  = (140, 225, 130)
RED    = (245, 95, 95)
PURPLE = (185, 125, 235)

DEFAULT_SETTINGS = {"particles": True, "floats": True, "vignette": True,
                    "fps": False, "autosave": True,
                    "sfx": True, "sfx_vol": 80,
                    "music": True, "music_vol": 65}

# ======================================================================
#  [2] CHIPTUNE AUDIO ENGINE
#      2.1 waveform synthesis   2.2 sound-effect bank
#      2.3 song sequencer       2.4 the four themes
# ======================================================================

# ---- 2.1 waveform synthesis ------------------------------------------
def _tone(dur, f0, f1=None, wave="sq", duty=0.5, vol=0.5, decay=1.6, attack=0.003):
    """Render one note/burst: sweep f0->f1 through a chip waveform."""
    n = max(1, int(dur * SR))
    f1 = f0 if f1 is None else f1
    ph, out = 0.0, []
    for i in range(n):
        t = i / n
        f = f0 + (f1 - f0) * t
        ph = (ph + f / SR) % 1.0
        if wave == "sq":
            v = 1.0 if ph < duty else -1.0
        elif wave == "tri":
            v = 4 * ph - 1 if ph < 0.5 else 3 - 4 * ph
        elif wave == "saw":
            v = 2 * ph - 1
        elif wave == "noise":
            v = random.uniform(-1.0, 1.0)
        else:                                   # sine
            v = math.sin(6.2831853 * ph)
        env = min(1.0, i / (attack * SR)) if attack > 0 else 1.0
        out.append(v * vol * env * (1.0 - t) ** decay)
    return out

def _silence(dur):
    return [0.0] * max(1, int(dur * SR))

def _cat(*parts):
    out = []
    for p in parts:
        out.extend(p)
    return out

def _mix(*parts):
    out = [0.0] * max(len(p) for p in parts)
    for p in parts:
        for i, s in enumerate(p):
            out[i] += s
    return out

def _note(midi, dur, **kw):
    return _tone(dur, 440.0 * 2 ** ((midi - 69) / 12.0), **kw)

def _seq(notes, **kw):
    """notes = [(midi|0 for rest, seconds), ...] rendered back to back."""
    out = []
    for m, d in notes:
        out += _note(m, d, **kw) if m else _silence(d)
    return out

def _snd(samples, vol=1.0):
    """Clip float samples -> 16-bit pygame Sound (handles stereo mixers)."""
    if not AUDIO_OK or not samples:
        return None
    data = array("h")
    for s in samples:
        v = int(clamp(s * vol, -1.0, 1.0) * 32000)
        data.append(v)
        if MIXCH == 2:
            data.append(v)
    try:
        return pygame.mixer.Sound(buffer=data.tobytes())
    except pygame.error:
        return None

# ---- 2.2 sound-effect bank -------------------------------------------
def _build_sfx():
    """Every game sound, synthesized once at startup."""
    S = {}
    # --- UI ---
    S["move"]    = _snd(_tone(.05, 700, 900, vol=.30))
    S["select"]  = _snd(_cat(_tone(.05, 660, vol=.32), _tone(.09, 990, vol=.32)))
    S["back"]    = _snd(_cat(_tone(.06, 440, vol=.28), _tone(.10, 300, vol=.26)))
    S["open"]    = _snd(_tone(.14, 300, 880, vol=.30))
    S["deny"]    = _snd(_tone(.20, 220, 150, vol=.34))
    S["tick"]    = _snd(_tone(.03, 1000, vol=.15))
    # --- economy ---
    S["coin"]    = _snd(_cat(_tone(.06, 988, vol=.30),
                             _tone(.22, 1319, vol=.30, decay=1.2)))
    S["coinbig"] = _snd(_mix(_seq([(76, .1), (79, .1), (84, .28)], vol=.30),
                             _note(96, .55, vol=.10, decay=2.5)))
    S["sell"]    = S["coin"]
    # --- gathering & pickups ---
    S["gather"]  = _snd(_mix(_tone(.05, 0, 0, wave="noise", vol=.12, decay=3),
                             _tone(.09, 520, 660, vol=.25, wave="tri")))
    S["pickup"]  = _snd(_tone(.07, 740, 880, vol=.28))
    S["rare"]    = _snd(_seq([(76, .09), (79, .09), (84, .26)], vol=.32))
    # --- combat ---
    S["bolt"]    = _snd(_tone(.09, 600, 1300, vol=.15, wave="saw"))
    S["hit"]     = _snd(_mix(_tone(.08, 0, 0, wave="noise", vol=.25, decay=3),
                             _tone(.08, 260, 140, vol=.30)))
    S["die"]     = _snd(_cat(_seq([(64, .09), (60, .09), (55, .18)], vol=.30),
                             _tone(.15, 0, 0, wave="noise", vol=.20, decay=2.5)))
    S["hurt"]    = _snd(_mix(_tone(.16, 320, 140, vol=.40),
                             _tone(.05, 0, 0, wave="noise", vol=.20, decay=3)))
    S["down"]    = _snd(_cat(_tone(.5, 420, 60, vol=.38),
                             _tone(.3, 90, 50, vol=.30, decay=1.0)))
    S["heart"]   = _snd(_cat(_tone(.07, 80, 60, vol=.42, wave="sine", decay=1.0),
                             _silence(.05),
                             _tone(.09, 70, 50, vol=.36, wave="sine", decay=1.0)))
    # --- brewing ---
    S["pour"]    = _snd(_tone(.18, 240, 420, vol=.20, wave="tri", decay=1.0))
    S["perfect"] = _snd(_cat(_tone(.05, 1046, vol=.30), _tone(.14, 1568, vol=.30)))
    S["good"]    = _snd(_tone(.10, 700, 950, vol=.30))
    S["ruin"]    = _snd(_tone(.22, 180, 110, vol=.34))
    S["stir"]    = _snd(_tone(.05, 500, 560, vol=.20, wave="tri"))
    S["gulp"]    = _snd(_tone(.13, 340, 170, vol=.30, wave="tri"))
    S["refine"]  = _snd(_seq([(72, .07), (76, .07), (81, .14)], vol=.28))
    # --- brew-result fanfares, richer with quality tier ---
    S["brew0"] = _snd(_seq([(64, .12), (60, .2)], vol=.28))
    S["brew1"] = _snd(_seq([(67, .1), (72, .1), (76, .2)], vol=.30))
    S["brew2"] = _snd(_seq([(72, .09), (76, .09), (79, .09), (84, .24)], vol=.30))
    S["brew3"] = _snd(_mix(_seq([(72, .09), (76, .09), (79, .09), (84, .09), (88, .3)], vol=.30),
                           _note(96, .6, vol=.08, decay=2.5)))
    S["lvl"]     = _snd(_seq([(72, .12), (76, .12), (79, .12), (84, .12), (88, .34)], vol=.30))
    # --- experiments ---
    S["boom"]    = _snd(_mix(_tone(.4, 0, 0, wave="noise", vol=.40, decay=2.0),
                             _tone(.4, 200, 40, vol=.35)))
    S["sparkle"] = _snd(_seq([(84, .06), (88, .06), (91, .06), (96, .06), (100, .2)],
                             vol=.26))
    # --- orders & social ---
    S["accept"]  = _snd(_mix(_tone(.06, 0, 0, wave="noise", vol=.10, decay=3),
                             _tone(.12, 880, 660, vol=.28)))
    S["deliver"] = _snd(_mix(_seq([(72, .1), (76, .1), (79, .1), (84, .3)], vol=.30),
                             _note(96, .5, vol=.10, decay=2.2)))
    S["feud"]    = _snd(_seq([(69, .13), (64, .13), (69, .13), (64, .13),
                              (69, .13), (64, .2)], vol=.30))
    S["warm"]    = _snd(_mix(_note(60, .6, vol=.16, wave="tri", decay=1.2),
                             _note(64, .6, vol=.16, wave="tri", decay=1.2),
                             _note(67, .6, vol=.16, wave="tri", decay=1.2)))
    S["chat"]    = _snd(_tone(.05, 620, 700, vol=.24, wave="tri"))
    # --- world ---
    S["morning"] = _snd(_seq([(60, .18), (67, .18), (72, .35)], vol=.22, wave="tri"))
    S["sleep"]   = _snd(_seq([(72, .18), (67, .18), (60, .35)], vol=.22, wave="tri"))
    S["portal"]  = _snd(_tone(.45, 200, 1500, vol=.22, wave="saw", decay=1.0))
    S["portalback"] = _snd(_tone(.45, 1500, 180, vol=.22, wave="saw", decay=1.0))
    S["chime"]   = _snd(_mix(_tone(.6, 880, vol=.20, decay=2.2),
                             _tone(.6, 1760, vol=.08, decay=3.0)))
    S["mystery"] = _snd(_seq([(69, .16), (72, .16), (76, .16), (81, .4)],
                             vol=.26, wave="tri"))
    knock = _mix(_tone(.05, 0, 0, wave="noise", vol=.30, decay=3),
                 _tone(.05, 140, vol=.30, wave="tri", decay=1.5))
    S["build"]   = _snd(_cat(knock, _silence(.05), knock,
                             _silence(.05), _cat(knock, _tone(.12, 220, 330, vol=.22))))
    return S

# ---- 2.3 song sequencer ----------------------------------------------
def _render_song(bpm, lead, bass, drums, duty=0.25):
    """16th-note step sequencer: square lead + triangle bass + chip drums."""
    step = 60.0 / bpm / 4.0
    total = int(len(lead) * step * SR) + SR // 4
    acc = [0.0] * total

    def put(samples, at):
        end = min(total, at + len(samples))
        for j in range(at, end):
            acc[j] += samples[j - at]

    for i, n in enumerate(lead):
        at = int(i * step * SR)
        if n:
            m, ln = n if isinstance(n, tuple) else (n, 1)
            put(_tone(step * ln * 0.92, 440.0 * 2 ** ((m - 69) / 12.0),
                      vol=.15, duty=duty, decay=1.4), at)
        b = bass[i]
        if b:
            m, ln = b if isinstance(b, tuple) else (b, 1)
            put(_tone(step * ln * 0.92, 440.0 * 2 ** ((m - 69) / 12.0),
                      vol=.19, wave="tri", decay=1.1), at)
        d = drums[i % len(drums)]
        if d == "H":
            put(_tone(.05, 0, 0, wave="noise", vol=.09, decay=3), at)
        elif d == "S":
            put(_mix(_tone(.09, 0, 0, wave="noise", vol=.13, decay=2),
                     _tone(.09, 190, vol=.12, wave="tri", decay=2)), at)
        elif d == "K":
            put(_tone(.11, 120, 45, vol=.22, wave="sine", decay=1.2), at)
    return _snd(acc, vol=0.9)

def _bass_bar(r, hold=8):
    """Root + fifth bass bar."""
    return [(r, hold), 0, 0, 0, 0, 0, 0, 0, (r + 7, 4), 0, (r, 2), 0, 0, 0, 0, 0]

# ---- 2.4 the four themes --------------------------------------------
SONGS = {
    # title: airy, gentle C-pentatonic
    "title": (96,
              [76,0,0,0, 74,0,0,0, 72,0,0,0, 0,0,0,0] +
              [67,0,0,0, 69,0,0,0, 72,0,0,0, 0,0,0,0] +
              [76,0,0,0, 79,0,0,0, 81,0,79,0, 76,0,0,0] +
              [74,0,72,0, 74,0,0,0, (72,4),0,0,0, 0,0,0,0],
              _bass_bar(48) + _bass_bar(45) + _bass_bar(41) + _bass_bar(43),
              "H...H...H...H...", 0.25),
    # home: cozy, bouncy F-C-G-C
    "home": (108,
             [(72,2),0,74,0, 76,0,0,0, 79,0,76,0, 74,0,0,0] +
             [72,0,0,0, 69,0,72,0, 74,0,0,0, 0,0,0,0] +
             [(79,2),0,76,0, 74,0,0,0, 72,0,74,0, 76,0,0,0] +
             [(74,2),0,72,0, 74,0,76,0, (72,4),0,0,0, 0,0,0,0],
             _bass_bar(48) + _bass_bar(41) + _bass_bar(43) + _bass_bar(48),
             "H...H...S...H...", 0.5),
    # wild: driving A-minor adventure
    "wild": (138,
             [76,0,0,0, 79,0,76,0, 74,0,76,0, 0,0,72,0] +
             [69,0,0,0, 72,0,74,0, 76,0,0,0, 0,0,0,0] +
             [81,0,0,0, 79,0,81,0, 84,0,81,0, 79,0,0,0] +
             [76,0,74,0, 76,0,0,0, 72,0,0,0, 0,0,0,0],
             sum([[(r,1),0,(r,1),0,(r,1),0,(r,1),0,(r,1),0,(r,1),0,(r+3,1),0,(r+7,1),0]
                  for r in (45, 45, 41, 43)], []),
             "H..KH..KS..KH..K", 0.25),
    # danger: low, tense, pounding
    "danger": (150,
               [76,0,0,0, 0,0,0,0, 75,0,0,0, 76,0,0,0] +
               [0,0,79,0, 0,0,76,0, 0,0,0,0, 74,0,0,0] +
               [74,0,0,0, 0,0,0,0, 71,0,0,0, 74,0,0,0] +
               [79,0,0,0, 76,0,0,0, (64,4),0,0,0, 0,0,0,0],
               sum([[(r,1),0,(r,1),0,(r,1),0,(r,1),0,(r,1),0,(r,1),0,(r+3,1),0,(r+2,1),0]
                    for r in (40, 40, 38, 43)], []),
               "K.H.S.H.K.H.S.HH", 0.125),
}

# built once, reused across restarts
_AUDIO_CACHE = {}

def ensure_audio():
    if not AUDIO_OK:
        return {}, {}
    if "sfx" not in _AUDIO_CACHE:
        try:
            pygame.mixer.set_reserved(1)
            _AUDIO_CACHE["chan"] = pygame.mixer.Channel(0)
        except pygame.error:
            _AUDIO_CACHE["chan"] = None
        _AUDIO_CACHE["sfx"] = _build_sfx()
        _AUDIO_CACHE["songs"] = {name: _render_song(*spec)
                                 for name, spec in SONGS.items()}
    return _AUDIO_CACHE["sfx"], _AUDIO_CACHE["songs"]

# ======================================================================
#  [3] GAME DATA
#      3.1 quality & buffs   3.2 ingredients   3.3 potions
#      3.4 catalysts         3.5 terrain       3.6 biomes
#      3.7 landmarks         3.8 monsters      3.9 buildings & spots
#      3.10 ui configuration
# ======================================================================

# ---- 3.1 potion quality tiers & buffs --------------------------------
QUALITY = [
    {"name": "Rough",     "short": "R", "mult": 0.75, "color": (170, 170, 180)},
    {"name": "Standard",  "short": "S", "mult": 1.00, "color": (240, 240, 240)},
    {"name": "Fine",      "short": "F", "mult": 1.45, "color": (120, 220, 255)},
    {"name": "Exquisite", "short": "E", "mult": 2.10, "color": (255, 215, 90)},
]

def quality_tier(score):
    """Brew score (incl. level/catalyst bonuses) -> quality tier 0..3."""
    return 3 if score >= 6 else 2 if score >= 4 else 1 if score >= 2 else 0

BUFFS = {
    "swift":     ("Swift",     (255, 170, 220)),
    "fury":      ("Fury",      (120, 200, 255)),
    "stoneskin": ("Stoneskin", (200, 160, 110)),
    "lucky":     ("Lucky",     (255, 205, 80)),
    "clarity":   ("Clarity",   (140, 230, 235)),
}

# ---- 3.2 ingredients (monster-only materials flagged) ----------------
INGREDIENTS = {
    "moonpetal":    {"name": "Moonpetal",      "color": (195, 195, 255)},
    "nightshade":   {"name": "Nightshade",     "color": (130, 70, 170)},
    "ghostmush":    {"name": "Ghost Mushroom", "color": (205, 185, 255)},
    "starbloom":    {"name": "Starbloom",      "color": (255, 230, 120)},
    "goldenclover": {"name": "Golden Clover",  "color": (140, 255, 110)},
    "cactusfruit":  {"name": "Cactus Fruit",   "color": (255, 110, 150)},
    "emberroot":    {"name": "Ember Root",     "color": (255, 130, 50)},
    "frostfern":    {"name": "Frost Fern",     "color": (170, 225, 255)},
    "icecrystal":   {"name": "Ice Crystal",    "color": (120, 190, 255)},
    "bogmyrtle":    {"name": "Bog Myrtle",     "color": (110, 200, 140)},
    "slimejelly":   {"name": "Slime Jelly",      "color": (110, 240, 150), "monster": True},
    "fairydust":    {"name": "Fairy Dust",       "color": (255, 250, 190), "monster": True},
    "scorpvenom":   {"name": "Scorpion Venom",   "color": (200, 120, 255), "monster": True},
    "golemcore":    {"name": "Golem Core",       "color": (160, 220, 255), "monster": True},
    "bogooze":      {"name": "Bog Ooze",         "color": (150, 220, 120), "monster": True},
    "honeycomb":    {"name": "Honeycomb",        "color": (250, 200, 60),  "monster": True},
    "pixiewing":    {"name": "Pixie Wing",       "color": (255, 190, 230), "monster": True},
    "chitin":       {"name": "Chitin Plate",     "color": (190, 140, 90),  "monster": True},
    "frostfang":    {"name": "Frost Fang",       "color": (200, 235, 255), "monster": True},
    "slimecore":    {"name": "Slime Core",       "color": (60, 255, 120),  "monster": True},
    "runeshard":    {"name": "Rune Shard",       "color": (170, 140, 255), "monster": True},
    "murkpearl":    {"name": "Murk Pearl",       "color": (90, 200, 210),  "monster": True},
}

# ---- 3.3 potions (core, secrets, derived tables) ---------------------
POTIONS = {
    "healing":   {"name": "Healing Potion",   "recipe": {"moonpetal": 2, "slimejelly": 1},    "price": 30,  "color": (255, 70, 70)},
    "mana":      {"name": "Mana Potion",      "recipe": {"starbloom": 2, "fairydust": 1},     "price": 35,  "color": (70, 120, 255)},
    "fireward":  {"name": "Fireward Tonic",   "recipe": {"emberroot": 2, "cactusfruit": 1},   "price": 45,  "color": (255, 140, 40)},
    "frostward": {"name": "Frostward Tonic",  "recipe": {"frostfern": 2, "icecrystal": 1},    "price": 45,  "color": (120, 220, 255)},
    "ghostveil": {"name": "Ghost Veil",       "recipe": {"ghostmush": 2, "bogooze": 1},       "price": 60,  "color": (200, 180, 255)},
    "luck":      {"name": "Luck Elixir",      "recipe": {"goldenclover": 1, "fairydust": 2},  "price": 65,  "color": (160, 255, 120)},
    "alphire":   {"name": "Alchemist's Fire", "recipe": {"scorpvenom": 1, "emberroot": 2},    "price": 70,  "color": (255, 90, 30)},
    "might":     {"name": "Elixir of Might",  "recipe": {"golemcore": 1, "goldenclover": 1, "emberroot": 1}, "price": 90, "color": (255, 200, 60)},
    "mead":      {"name": "Meadow Mead",      "recipe": {"honeycomb": 2, "goldenclover": 1},  "price": 55,  "color": (255, 205, 80),
                  "buff": "lucky", "buff_t": 45, "desc": "Gathers yield +1 extra while active."},
    "chitsh":    {"name": "Chitin Shield",    "recipe": {"chitin": 2, "bogmyrtle": 1},        "price": 80,  "color": (200, 160, 110),
                  "buff": "stoneskin", "buff_t": 45, "desc": "Take 40% less damage while active."},
    "glimmer":   {"name": "Glimmerwing Tonic","recipe": {"pixiewing": 2, "moonpetal": 1},     "price": 85,  "color": (255, 170, 220),
                  "buff": "swift", "buff_t": 45, "desc": "+35% movement speed while active."},
    "wolfvig":   {"name": "Wolf's Vigor",     "recipe": {"frostfang": 1, "emberroot": 2},     "price": 90,  "color": (120, 200, 255),
                  "buff": "fury", "buff_t": 45, "desc": "Magic bolts deal +8 damage while active."},
    "pearl":     {"name": "Pearl of Clarity", "recipe": {"murkpearl": 1, "starbloom": 2},     "price": 120, "color": (140, 230, 235),
                  "buff": "clarity", "buff_t": 60, "desc": "Brew needle moves 40% slower while active."},
    "runic":     {"name": "Runic Overload",   "recipe": {"runeshard": 1, "golemcore": 1},     "price": 150, "color": (170, 140, 255),
                  "special": "xp80", "desc": "Drink to gain +80 brewing XP."},
    "concord":   {"name": "Concord Draught",  "recipe": {"honeycomb": 1, "goldenclover": 1, "fairydust": 1},
                  "price": 55, "color": (255, 180, 200),
                  "special": "gift", "desc": "A gift-brew: mends feuds and warms hearts."},
}

SECRET_POTIONS = {
    "philosopher": {"name": "Philosopher's Tonic", "recipe": {"goldenclover": 1, "golemcore": 1},               "price": 120, "color": (255, 230, 140)},
    "shadow":      {"name": "Shadow Elixir",       "recipe": {"nightshade": 2, "ghostmush": 1},                 "price": 95,  "color": (120, 80, 170)},
    "rainbow":     {"name": "Bottled Rainbow",     "recipe": {"starbloom": 1, "icecrystal": 1, "fairydust": 1}, "price": 110, "color": (255, 120, 200)},
    "valeblossom": {"name": "Valeblossom Elixir",  "recipe": {"moonpetal": 1, "starbloom": 1, "cactusfruit": 1,
                                                              "frostfern": 1, "bogmyrtle": 1, "golemcore": 1},
                    "price": 400, "color": (255, 170, 220), "legendary": True},
}

def pot_def(pid):
    return POTIONS.get(pid) or SECRET_POTIONS[pid]

RECIPE_IDS = list(POTIONS.keys()) + list(SECRET_POTIONS.keys())

def _is_beast(d):
    return any(INGREDIENTS[i].get("monster") for i in d["recipe"])

CRAFT_TABS = [
    ("TONICS",     [p for p, d in POTIONS.items() if not _is_beast(d)]),
    ("BEASTCRAFT", [p for p, d in POTIONS.items() if _is_beast(d)]),
    ("SECRETS",    list(SECRET_POTIONS.keys())),
]

INGREDIENT_USES = {}     # ingredient id -> {potion names using it}
for _pid, _d in list(POTIONS.items()) + list(SECRET_POTIONS.items()):
    for _ing in _d["recipe"]:
        INGREDIENT_USES.setdefault(_ing, set()).add(_d["name"])

# ---- 3.4 catalysts (burned during brewing) ---------------------------
CATALYSTS = {
    "fairydust":  {"name": "Pixie Blessing (+1 quality)",  "effect": "quality"},
    "golemcore":  {"name": "Golem Strength (+1 yield)",    "effect": "yield"},
    "starbloom":  {"name": "Sunfire Infusion (calm brew)", "effect": "calm"},
    "slimejelly": {"name": "Slime Stabilizer (no ruin)",   "effect": "safe"},
    "pixiewing":  {"name": "Glimmer Charm (+1 quality)",   "effect": "quality"},
    "runeshard":  {"name": "Rune Might (+1 yield)",        "effect": "yield"},
    "honeycomb":  {"name": "Honeyed Brew (+50% xp)",       "effect": "xp"},
}

# ---- 3.5 terrain zones (movement multipliers) ------------------------
TERRAIN_FX = {
    "pond": {"mult": 0.55}, "oasis": {"mult": 0.60}, "quicksand": {"mult": 0.50},
    "ice": {"mult": 1.30}, "grove": {"mult": 0.90}, "murk": {"mult": 0.80},
    "mist": {"mult": 0.85}, "flowerfield": {"mult": 1.10},
}

# ---- 3.6 biomes ------------------------------------------------------
BIOMES = {
    "forest": {"name": "Whispering Forest", "danger": 1,
               "ground": (36, 82, 46), "accent": (28, 66, 38), "water": (58, 108, 168),
               "road": (146, 110, 72), "road_edge": (104, 78, 50),
               "plants": [("moonpetal", 3), ("nightshade", 3), ("ghostmush", 1)],
               "monsters": ["slime", "slime", "pixie"],
               "decor": ["tree", "tree", "tree", "bush", "stump", "flower"],
               "terrain": [("grove", 3), ("pond", 1), ("mist", 1)],
               "ambient": "leaf", "rare": "ghostmush",
               "scents": ["damp moss and old rain", "wet bark and secret things",
                          "pine sap and far-off thunder"],
               "desc": "Gentle moonlit woods."},
    "meadow": {"name": "Sunny Meadow", "danger": 1,
               "ground": (120, 168, 74), "accent": (104, 150, 62), "water": (70, 130, 190),
               "road": (172, 142, 96), "road_edge": (128, 102, 66),
               "plants": [("starbloom", 3), ("goldenclover", 1)],
               "monsters": ["beeswarm", "beeswarm", "pixie"],
               "decor": ["flower", "flower", "bush", "rock"],
               "terrain": [("flowerfield", 3), ("pond", 1)],
               "ambient": "petal", "rare": "goldenclover",
               "scents": ["warm clover and honey", "sun-baked grass", "pollen and lazy summer"],
               "desc": "Buzzing fields of gold."},
    "desert": {"name": "Scorched Dunes", "danger": 2,
               "ground": (216, 180, 116), "accent": (196, 158, 98), "water": (70, 150, 190),
               "road": (190, 152, 96), "road_edge": (150, 116, 70),
               "plants": [("cactusfruit", 3), ("emberroot", 1)],
               "monsters": ["scorpion", "scorpion", "slime"],
               "decor": ["cactus", "cactus", "rock", "rock"],
               "terrain": [("quicksand", 3), ("oasis", 1)],
               "ambient": "sand", "rare": "cactusfruit",
               "scents": ["hot stone and dry wind", "dust and distant smoke",
                          "cracked clay and mirage"],
               "desc": "Burning sands and venom."},
    "tundra": {"name": "Frozen Peaks", "danger": 3,
               "ground": (205, 222, 235), "accent": (182, 202, 218), "water": (150, 200, 235),
               "road": (176, 192, 210), "road_edge": (140, 158, 178),
               "plants": [("frostfern", 3), ("icecrystal", 1)],
               "monsters": ["icegolem", "frostwolf", "frostwolf"],
               "decor": ["pine", "pine", "snowrock", "rock"],
               "terrain": [("ice", 3), ("pond", 2)],
               "ambient": "snow", "rare": "icecrystal",
               "scents": ["clean cold and pine", "glacier breath", "snow and silence"],
               "desc": "Bitter cold. Living ice."},
    "swamp":  {"name": "Mistmarsh", "danger": 2,
               "ground": (70, 88, 64), "accent": (56, 72, 52), "water": (66, 88, 78),
               "road": (98, 108, 82), "road_edge": (70, 78, 58),
               "plants": [("bogmyrtle", 3), ("ghostmush", 1)],
               "monsters": ["boglurker", "boglurker", "slime"],
               "decor": ["reed", "reed", "stump", "mushroom", "bush"],
               "terrain": [("murk", 3), ("pond", 2), ("mist", 2)],
               "ambient": "firefly", "rare": "bogmyrtle",
               "scents": ["rot and roses", "green water and whispers",
                          "wet earth and old lanterns"],
               "desc": "Foggy mires and lurking shapes."},
}

BIOME_FLAVOR = {   # procedural name parts per biome
    "forest": (["Mossgrove", "Elderwood", "Foxfire", "Oldbark"], ["Hollow", "Glade", "Thicket", "Reach"]),
    "meadow": (["Cloverfield", "Sunbloom", "Windmere", "Golden"], ["Downs", "Vale", "Meadows", "Flats"]),
    "desert": (["Scorched", "Mirage", "Dustveil", "Sunscar"], ["Dunes", "Expanse", "Wastes", "Flats"]),
    "tundra": (["Frostbound", "Palewind", "Whiteout", "Everice"], ["Peaks", "Ridge", "Barrens", "Pass"]),
    "swamp":  (["Blackwater", "Fenwyrd", "Gloomrot", "Deepmist"], ["Mire", "Fens", "Bog", "Marsh"]),
}

ENTRY_OPEN = [
    "You step through the portal into {place}.",
    "The portal spits you out at the edge of {place}.",
    "One whiff of brimstone and you're standing in {place}.",
    "Your broom-less boots find the soil of {place}.",
]
ENTRY_MID = ["The air smells of {scent}.", "Everything smells of {scent} here.",
             "A breath of {scent} greets you."]
ENTRY_TAIL = ["Somewhere, a crow laughs twice.", "The road ahead curls like a question.",
              "Old magic settles over your shoulders like a shawl.",
              "You tighten your hat. Adventure first, tea later.",
              "Grandmother would have loved this place.", "The wilds watch you back."]

# ---- 3.7 landmarks ---------------------------------------------------
LANDMARK_INFO = {
    "leystone": {"label": "Ancient Ley Stone",
                 "flavor": ["The stone remembers your grandmother's handwriting.",
                            "Ley-light crawls up your fingers and hums a note you almost know.",
                            "The rune glows, then dims - as if winking."]},
    "shrine":   {"label": "Mossy Shrine",
                 "flavor": ["Someone left fresh flowers. Someone always does.",
                            "The moss parts to reveal a smiling, worn face.",
                            "You leave a petal. The shrine leaves warmth."]},
    "cache":    {"label": "Buried Cache",
                 "flavor": ["A corner of rope peeks from the dirt like a buried secret.",
                            "Someone buried this in a hurry, long ago.",
                            "The lock is rust. The coin is not."]},
    "spring":   {"label": "Hot Spring",
                 "flavor": ["Steam curls into letters that almost spell your name.",
                            "The water is exactly, impossibly perfect.",
                            "You dangle your boots. The aches pack their bags."]},
    "crystal":  {"label": "Crystal Outcrop",
                 "flavor": ["The crystals ring faintly when the wind leans on them.",
                            "Light pools inside like slow honey.",
                            "One crystal is shaped suspiciously like a hat."]},
    "ruin":     {"label": "Old Ruins",
                 "flavor": ["Arrows carved in the wall point at nothing. Or everything.",
                            "A hearth, still sooty. Someone cooked here once, bravely.",
                            "The stones have opinions about trespassers. Kind ones."]},
    "well":     {"label": "Traveller's Well",
                 "flavor": ["Coins glitter at the bottom like sleeping stars.",
                            "The bucket groans a note of pure E minor.",
                            "Names scratched in the rim: lovers, liars, witches."]},
}
BIOME_LANDMARKS = {
    "forest": ["leystone", "shrine", "ruin"],
    "meadow": ["shrine", "cache", "well"],
    "desert": ["cache", "ruin", "spring"],
    "tundra": ["crystal", "leystone", "ruin"],
    "swamp":  ["leystone", "cache", "shrine"],
}

# ---- 3.8 monsters ----------------------------------------------------
FIRSTKILL = {
    "slime":     "Your first slime bursts like a green thought. You feel oddly proud.",
    "pixie":     "The pixie scatters into glitter that spells 'rude', then fades.",
    "beeswarm":  "The swarm disperses, leaving honey and an apology-shaped hum.",
    "scorpion":  "The scorpion curls one last time, a fist of sand and chitin.",
    "icegolem":  "The golem kneels, cracking into winter's honest arithmetic.",
    "frostwolf": "The wolf's last breath fogs, then becomes the wind's.",
    "boglurker": "The lurker sinks, returning the marsh's borrowed silence.",
}

MONSTERS = {
    "slime":     {"name": "Slime",      "hp": 22, "speed": 45,  "dmg": 6,  "r": 16, "c": (110, 240, 150),
                  "guarantee": "slimejelly", "drops": [], "rare": ("slimecore", 0.12)},
    "pixie":     {"name": "Pixie",      "hp": 14, "speed": 110, "dmg": 4,  "r": 10, "c": (255, 190, 230),
                  "guarantee": "pixiewing", "drops": [("fairydust", 0.55)], "rare": None},
    "beeswarm":  {"name": "Bee Swarm",  "hp": 18, "speed": 85,  "dmg": 5,  "r": 13, "c": (250, 210, 60),
                  "guarantee": "honeycomb", "drops": [("fairydust", 0.5)], "rare": None},
    "scorpion":  {"name": "Scorpion",   "hp": 45, "speed": 65,  "dmg": 10, "r": 17, "c": (190, 140, 90),
                  "guarantee": "chitin", "drops": [("scorpvenom", 0.7)], "rare": None},
    "icegolem":  {"name": "Ice Golem",  "hp": 90, "speed": 30,  "dmg": 14, "r": 22, "c": (150, 200, 235),
                  "guarantee": "golemcore", "drops": [("icecrystal", 0.5)], "rare": ("runeshard", 0.15)},
    "frostwolf": {"name": "Frost Wolf", "hp": 40, "speed": 100, "dmg": 9,  "r": 16, "c": (170, 190, 215),
                  "guarantee": "frostfang", "drops": [("icecrystal", 0.45)], "rare": None},
    "boglurker": {"name": "Bog Lurker", "hp": 55, "speed": 55,  "dmg": 11, "r": 19, "c": (90, 150, 110),
                  "guarantee": "bogooze", "drops": [], "rare": ("murkpearl", 0.18)},
}

SLIME_TINTS = {"forest": (110, 240, 150), "meadow": (210, 230, 90), "desert": (255, 150, 80),
               "tundra": (150, 220, 255), "swamp": (170, 120, 220)}

def _monster_drops(d):
    return ([d["guarantee"]] if d.get("guarantee") else []) \
         + [i for i, _ in d.get("drops", [])] \
         + ([d["rare"][0]] if d.get("rare") else [])

MONSTER_DROPS = {mid: _monster_drops(d) for mid, d in MONSTERS.items()}

def monster_sources(*ings):
    """Which monsters drop any of these ingredients? (display names)"""
    return sorted({MONSTERS[mid]["name"] for mid, drops in MONSTER_DROPS.items()
                   if any(i in drops for i in ings)})

def mastery_level(cnt):
    return 3 if cnt >= 30 else 2 if cnt >= 15 else 1 if cnt >= 5 else 0

# ---- 3.9 buildings & world spots -------------------------------------
BUILDINGS = {
    "garden":     {"name": "Herb Garden",    "cost": 50,  "req": None,     "desc": "Each morning: +2 random common plants."},
    "greenhouse": {"name": "Greenhouse",     "cost": 140, "req": "garden", "desc": "Each morning: +2 random rare plants."},
    "market":     {"name": "Market Stall",   "cost": 120, "req": None,     "desc": "+30% gold from all order rewards."},
    "watchtower": {"name": "Watchtower",     "cost": 110, "req": None,     "desc": "Monsters in biomes have -25% HP and damage."},
    "broomshed":  {"name": "Broom Shed",     "cost": 90,  "req": None,     "desc": "+20% movement speed out in the wilds."},
    "focus":      {"name": "Crystal Focus",  "cost": 150, "req": None,     "desc": "Your magic bolts deal +6 damage."},
    "cauldron2":  {"name": "Grand Cauldron", "cost": 180, "req": None,     "desc": "35% chance a brew minigame yields a double."},
    "cloudbed":   {"name": "Cloud Bed",      "cost": 80,  "req": None,     "desc": "Sleeping restores full HP (otherwise 60%)."},
    "distillery": {"name": "Distillery",     "cost": 220, "req": None,     "desc": "Refine: 1 potion + 1 Bog Myrtle raises its quality one tier."},
}

BASE_SPOTS = [   # interactable locations around the cottage
    {"x": 250, "y": 300, "r": 55, "label": "Order Board",          "act": "orders"},
    {"x": 512, "y": 330, "r": 50, "label": "Cottage Door - Sleep", "act": "door"},
    {"x": 740, "y": 300, "r": 55, "label": "Cauldron - Brew",      "act": "craft"},
    {"x": 512, "y": 630, "r": 50, "label": "Signpost - Travel",    "act": "travel"},
    {"x": 860, "y": 520, "r": 60, "label": "Construction Plot",    "act": "build"},
]

BUILD_SLOTS = [(150, 210), (895, 190), (115, 440), (945, 340),
               (215, 665), (705, 690), (80, 600), (950, 620), (430, 705)]

# ---- 3.10 ui configuration -------------------------------------------
PAUSE_ITEMS = [("Resume", "resume"), ("Controls & Help", "controls"),
               ("Options", "options"), ("Save Game", "save"),
               ("Load Game", "load"), ("Quit to Title", "quit")]

# (settings key, label, kind)  kind: "bool" toggle | "vol" 0..100 step 25
SETTING_ITEMS = [
    ("sfx",       "Sound effects (8-bit)",              "bool"),
    ("sfx_vol",   "SFX volume",                         "vol"),
    ("music",     "Chiptune music",                     "bool"),
    ("music_vol", "Music volume",                       "vol"),
    ("particles", "Ambient particles",                  "bool"),
    ("floats",    "Floating numbers",                   "bool"),
    ("vignette",  "Low-health red vignette",            "bool"),
    ("fps",       "FPS counter",                        "bool"),
    ("autosave",  "Autosave every morning",             "bool"),
]

CONTROLS_COLS = [
    ["MOVEMENT & WORLD",
     "WASD / Arrows ....... move",
     "E ................... interact / gather / chat",
     "SPACE ............... magic bolt (wilds)",
     "ESC ................. pause (base) / flee home",
     "P ................... pause menu (anywhere)",
     "",
     "MENUS",
     "I ................... satchel (S: sort, wheel: scroll)",
     "B ................... bestiary",
     "J ................... chronicle (wheel: scroll)",
     "TAB ................. witch's ledger (stats)",
     "M ................... minimap size   T: tracker"],
    ["CAULDRON",
     "E ................... brew (heat + stir minigame)",
     "Q ................... quick-brew (Standard)",
     "C ................... cycle catalyst",
     "X ................... experiment (secret recipes)",
     "R ................... refine +1 quality tier",
     "V / B ............... sell one / sell all",
     "F ................... drink selected",
     "A / D ............... switch recipe tabs",
     "",
     "ORDERS (at the board)",
     "A / D ............... BOARD / CONTRACTS / VILLAGERS",
     "E ................... accept / deliver / chat",
     "R ................... REJECT an order",
     "G ................... gift Concord Draught",
     "1-4 ................. quick-drink potions",
     "H ................... drink Healing Potion",
     "Mouse: click rows & buttons, wheel scrolls"],
]

# ======================================================================
#  [4] NARRATIVE
#      4.1 villagers & kin  4.2 persona dialogue  4.3 feuds & favors
#      4.4 day events       4.5 rumors            4.6 story & finale
# ======================================================================

# ---- 4.1 villagers, personas, kin ------------------------------------
CUSTOMERS = [("Mira the Farmer", "cheerful"), ("Old Tom", "grumpy"), ("Lady Velvet", "dramatic"),
             ("Captain Bram", "blunt"), ("Pip the Baker", "cheerful"), ("Grandma Rose", "warm"),
             ("Sir Oakley", "dramatic"), ("Wanda the Wise", "mysterious"), ("Bosco the Bard", "dramatic"),
             ("Nessa", "shy")]
PERSONA_OF = dict(CUSTOMERS)

FAMILY_LINKS = {   # kin: relationship changes spill over (+-40%)
    "Grandma Rose": ["Old Tom"], "Old Tom": ["Grandma Rose"],
    "Pip the Baker": ["Nessa"], "Nessa": ["Pip the Baker"],
    "Lady Velvet": ["Captain Bram"], "Captain Bram": ["Lady Velvet"],
}

PERSONA_COLOR = {"cheerful": (255, 200, 90), "grumpy": (150, 150, 150), "dramatic": (200, 80, 120),
                 "blunt": (90, 110, 160), "warm": (230, 150, 110), "mysterious": (140, 90, 180),
                 "shy": (180, 220, 180)}

# ---- 4.2 persona dialogue pools --------------------------------------
PERSONAS = {
    "cheerful":   {"greet": ["Morning, witchling!", "Sun's up and so am I!", "Loveliest day!"],
                   "ask":   ["Could you brew me {qty} {potion}? {reason}",
                             "I need {qty} {potion}, please! {reason}"],
                   "thanks": ["You're a star! Here's {reward}g.", "Wonderful! {reward}g, as promised!"],
                   "reject": ["Aww, okay... maybe next time?", "Oh... alright. Rain check!"],
                   "chat":   ["Beautiful day for brewing!", "I named a chicken after you!",
                              "The bees asked about you. I said you're doing great."],
                   "angry":  ["{name} huffs past your window, definitely not waving."]},
    "grumpy":     {"greet": ["Hmph.", "Make it quick.", "Don't get comfortable."],
                   "ask":   ["{qty} {potion}. {reason} Don't ask questions.",
                             "I'll pay for {qty} {potion}. {reason}"],
                   "thanks": ["Fine work. {reward}g. Don't let it go to your hat.",
                              "Hmph. {reward}g. Good enough."],
                   "reject": ["Figures.", "Waste of a walk.", "Should've known."],
                   "chat":   ["Sky's too blue. Suspicious.", "Everything was better forty years ago.",
                              "The ducks know something. They won't say what."],
                   "angry":  ["{name} nailed a 'NO WITCHES' sign to a tree. It's crooked."]},
    "dramatic":   {"greet": ["WITCH OF THE VALE!", "Oh, fateful day!", "Listen... listen!"],
                   "ask":   ["Fate demands {qty} {potion}! {reason}",
                             "I beg thee: {qty} {potion}. {reason}"],
                   "thanks": ["History will remember this! {reward}g!",
                              "A hero's wage for a hero's brew: {reward}g!"],
                   "reject": ["So the fates decline... I shall endure!", "Betrayed! (I'll be back tomorrow.)"],
                   "chat":   ["I dreamt of a cauldron the size of the moon!",
                              "Somewhere, an adventure yawns and waits for us.",
                              "My autobiography is at chapter nine. It's all true."],
                   "angry":  ["{name} was seen declaiming your name to an unimpressed duck."]},
    "blunt":      {"greet": ["Witch.", "At ease.", "Straight to it."],
                   "ask":   ["Requisition: {qty} {potion}. {reason}",
                             "{qty} {potion}. Deadline matters. {reason}"],
                   "thanks": ["Service rendered. {reward}g. Dismissed... kindly.",
                              "Solid work. {reward}g."],
                   "reject": ["Understood. Request withdrawn.", "Noted. Moving on."],
                   "chat":   ["Weather report: weather.", "Carry on, witch.",
                              "I once wrestled a goose. We don't speak of it."],
                   "angry":  ["{name} filed a formal complaint. It is one word long."]},
    "warm":       {"greet": ["Dearie!", "Come in from the cold, pet.", "There she is."],
                   "ask":   ["Could I trouble you for {qty} {potion}? {reason}",
                             "My joints say yes to {qty} {potion}. {reason}"],
                   "thanks": ["Bless your pointed hat. {reward}g, dear.",
                              "Here, pet: {reward}g. And I knitted the cauldron a cozy once, you know."],
                   "reject": ["That's alright dearie, don't you fret.", "Never mind, pet. Tea another time?"],
                   "chat":   ["You look thin. Take some jam.", "Your grandmother would be proud, dearie.",
                              "I remember when this whole vale was one big sheep field."],
                   "angry":  ["{name} sighs at your door, then leaves jam anyway. No note."]},
    "mysterious": {"greet": ["...", "We meet again.", "The cards said you'd be home."],
                   "ask":   ["The signs ask for {qty} {potion}. {reason}",
                             "{qty} {potion}. The marsh told me to ask you. {reason}"],
                   "thanks": ["As foretold. {reward}g.", "The cards smile. {reward}g."],
                   "reject": ["The cards warned me you'd say no.", "As the mists foretold..."],
                   "chat":   ["The pond told me you'd visit the tundra soon.", "Beware Thursdays.",
                              "Your aura is violet today. Tomorrow, mostly violet."],
                   "angry":  ["{name} is gone. Only a single tarot card remains: The Overdue."]},
    "shy":        {"greet": ["Oh! Hello...", "Um. Hi.", "*waves quietly*"],
                   "ask":   ["S-sorry to bother... {qty} {potion}? {reason}",
                             "If it's not too much... {qty} {potion}? {reason}"],
                   "thanks": ["Th-thank you! {reward}g. *flees*", "You're the best! {reward}g. *scampers off*"],
                   "reject": ["O-oh... okay. Sorry to bother...", "I understand... sorry!"],
                   "chat":   ["I, um... I like your hat...", "*shuffles feet* The bees said hi. For me. To you.",
                              "I pressed a flower for you. It's... it's a flower."],
                   "angry":  ["{name} left a strongly-worded note. It is entirely in lowercase."]},
}

REASONS = [
    "My goat ate my hat and now he won't stop glowing.",
    "The well water's been gossiping about me.",
    "I lost a bet with a goose.",
    "The mine's been humming in B-flat and nobody sleeps.",
    "My neighbour's scarecrow won a medal. I need to believe in something.",
    "Tuesday happened. Twice.",
    "The cats have unionized.",
    "I stepped in something sentimental.",
    "A cloud followed me home. It's still here.",
    "My soup achieved sentience and I respect it too much to eat it.",
    "I promised the mayor. Don't ask what.",
    "It's for a wedding. Possibly mine. Long story.",
]

# ---- 4.3 feuds & favors ----------------------------------------------
FEUD_REASONS = [
    "It started with an unpaid debt of exactly one egg",
    "Both claim the same rooster's loyalty",
    "A fence line has been 'temporarily wrong' for thirty years",
    "They disagree violently about which cloud is the prettiest",
    "A pie at the harvest fair was 'borrowed' and never returned",
    "One of them let a ladder fall on the other's shed. Twice",
    "Their great-grandparents feuded, and they see no reason to stop",
    "They've argued over whose pumpkins won second prize ever since",
]
FEUD_PLEA = [
    "{other} and I are DONE talking. You'll stand with me, won't you?",
    "It's me or {other}, witch. Choose wisely.",
    "Surely YOU see that {other} is in the wrong here?",
    "Everyone in the village will know whose side you took. Choose mine.",
]
GRUMBLE_LINES = [
    "{other} saw you serving {name}. An icy nod is exchanged.",
    "{other} mutters about 'witch favoritism' as they pass your gate.",
    "{other} pointedly buys their potions elsewhere. Loudly.",
]
RECONCILE_LINES = [
    "Time heals: {a} and {b} were seen nodding at each other by the well.",
    "The {a}/{b} feud ends the way all great feuds do - both forgot what it was about.",
    "A shared umbrella in the rain quietly ends the feud between {a} and {b}.",
]
GIFT_LINES = [
    "{name} left a bundle on your doorstep: {gift}.",
    "{name} dropped by with {gift} and gossip about the mayor's goat.",
    "A parcel from {name} sits by the door: {gift}, tied with suspiciously many knots.",
]
SPITE_LINES = [
    "{name} 'accidentally' waters your doorstep. The message is received.",
    "{name} told the baker your potions are 'basically soup'.",
    "{name} organized a boycott of your cottage. Attendance: one goat.",
]
FAVOR_ITEM_LINES = [
    "I need {need} {item} for a project. It's a surprise. Don't ask whose.",
    "If you happen across {need} {item}, I'd be forever in your debt.",
    "The village doctor insists on {need} {item}. Don't question village medicine.",
]
FAVOR_HUNT_LINES = [
    "{need} {monster} have been troubling my garden. Sort them out?",
    "I'd sleep better knowing {need} fewer {monster} lurk about. Name your price.",
]

# ---- 4.4 day events (procedural morning modifiers) -------------------
DAY_EVENTS = [
    {"id": "festival", "title": "Village Festival", "w": 3,
     "desc": "Bunting everywhere! Order rewards +25% today.", "reward": 1.25},
    {"id": "market", "title": "Market Day", "w": 3,
     "desc": "Traders flood in - potion sales pay +30% today.", "sell": 1.30},
    {"id": "restless", "title": "Restless Wilds", "w": 2,
     "desc": "The beasts are stirred up: +1 monster per biome, but drops +25%.", "spawn": 1, "drop": 1.25},
    {"id": "calm", "title": "Quiet Skies", "w": 3,
     "desc": "Not even the bees are busy. Your gathering feels lighter (+1 yield).", "gather": 1},
    {"id": "traveler", "title": "A Lost Traveler", "w": 2,
     "desc": "You pointed a wanderer to the vale. They left a thank-you purse.", "gold": 22},
    {"id": "frost", "title": "Cold Snap", "w": 2,
     "desc": "The cauldron sulks: needle 15% slower, but every brew grants +10 XP.", "needle": 0.85, "brewxp": 10},
    {"id": "letter", "title": "A Feathered Letter", "w": 2,
     "desc": "A goose delivers word from a friend: reputation feels warmer (+1 rep).", "rep": 1},
]

# ---- 4.5 rumors (seed guaranteed landmarks) --------------------------
RUMOR_TPL = [
    "Old Tom swears there's a {landmark} out in the {biome}. He'd know. He fell in it once.",
    "A peddler swears by the {landmark} of the {biome} - 'seen it with me own good eye.'",
    "The geese say a {landmark} waits in the {biome}. The geese are rarely wrong.",
    "Nessa heard humming from the {biome}. Perhaps the {landmark} is waking.",
    "Grandma Rose's tea leaves arranged into a {landmark}, deep in the {biome}.",
]

# ---- 4.6 main story, found family chapter, finale --------------------
STORY = [
    {"title": "Chapter I - The Inherited Hearth",
     "when": lambda g: g.day >= 2,
     "text": ["Daybreak finds a letter on the doormat, sealed with violet wax.",
              "",
              "'Willow - if you're reading this, the cottage is yours now. The",
              "cauldron remembers my hands; it will learn yours. Feed it well,",
              "serve the vale kindly, and mind the wilds after dark.",
              "",
              "There is one recipe I never wrote down. The vale will teach you",
              "when you're ready. It grows in the gaps between everything else.",
              "",
              "- Grandmother Elmira'"]},
    {"title": "Chapter II - Word Gets Around",
     "when": lambda g: g.rep >= 3,
     "text": ["Three satisfied customers in one week. In the village square,",
              "somebody has chalked a little hat next to your name on the",
              "noticeboard. Under it, someone else has written: 'fair prices.'",
              "",
              "The vale is starting to say your name like it belongs here."]},
    {"title": "Chapter III - The Cauldron Speaks",
     "when": lambda g: g.brew_level >= 3,
     "text": ["Your stirring has a rhythm now. The cauldron has begun to answer it -",
              "bubbles rising a half-beat before you even lift the ladle.",
              "",
              "Elmira's margin notes in the old grimoire make sense at last:",
              "'Heat is a question. Stirring is the answer. Timing is everything.'"]},
    {"title": "Chapter IV - Whispers of Old Magic",
     "when": lambda g: len(g.known_secrets) >= 1,
     "text": ["The first secret recipe unfolded under your hands like a moth's wing.",
              "",
              "When you look up from the cauldron, every candle in the cottage is",
              "bending toward you, very slightly, like grass toward wind.",
              "",
              "The vale is teaching you. Elmira said it would."]},
    {"title": "Chapter V - Cartographer's Confession",
     "when": lambda g: len(g.visited) >= 5,
     "text": ["You've walked every corner of the wilds now: forest shade, meadow",
              "gold, desert blaze, tundra silence, marsh murk.",
              "",
              "On your map, five tiny inked hats mark where the portals stand.",
              "The vale is not five places, you realize. It's one place, dreaming",
              "in five voices - and all of them know your name."]},
    {"title": "Chapter VI - The Vale Remembers",
     "when": lambda g: sum(g.kills.values()) >= 20,
     "text": ["Twenty hunts. The monsters have learned your silhouette, and the",
              "monsters talk, in their way - you've heard slime-bubbles pop in",
              "patterns that feel almost like warning each other.",
              "",
              "Deep in the forest, the ley stones have started glowing when you",
              "pass. Not warning-light. Welcoming-light.",
              "",
              "Something is preparing to be given to you."]},
    {"title": "Chapter VII - The Recipe That Wasn't Written",
     "when": lambda g: len(g.known_secrets) >= 3 and sum(g.kills.values()) >= 20 and g.day >= 8,
     "text": ["At midnight the cauldron boils with no fire under it. In the",
              "froth, letters surface and hold their shape:",
              "",
              "  'One bloom from each of my five voices,",
              "   plus a heart of stone from the coldest giant.",
              "   Brew it at your finest and the vale will bloom with you.",
              "   I grew it the day your mother was born. - E.'",
              "",
              "A NEW RECIPE is inscribed in your cauldron's SECRETS tab:",
              "the VALEBLOSSOM ELIXIR."]},
    {"title": "Chapter VIII - The Found Family",
     "when": lambda g: g.family_flag,
     "text": ["Three chairs at your table that used to be empty.",
              "",
              "Rose's jam, Bram's impossible stories, Nessa's quiet company -",
              "the cottage that Elmira left you was never really about the",
              "cauldron. It was a door left open.",
              "",
              "'A witch is not her potions,' Elmira wrote once, in a margin",
              "you only now understand. 'She is the people who knock.'"]},
]

FINALE_TEXT = [
    "You pour the last measure. The cauldron exhales a scent like every",
    "season at once - and outside, impossibly, every plant in the vale",
    "flowers at the same time. Even the cacti. Even the ice.",
    "",
    "The Valeblossom Elixir glows the exact violet of grandmother's wax",
    "seal. On the windowsill, her old watering can is full. It was empty",
    "this morning. It will always be empty when you look, and always full",
    "when you need it.",
    "",
    "The letter's last unspoken line arrives, quiet as snow:",
    "'Well done, Willow. The cottage was never the inheritance. You were.'",
    "",
    "            *  THE WITCH OF THE VALE  *",
    "   (The vale lives on - brew, hunt, and build as long as you like.)",
]

# ======================================================================
#  [5] SMALL HELPERS
# ======================================================================
def text(surf, s, x, y, font=FONT_M, color=WHITE, anchor="topleft"):
    img = font.render(str(s), True, color)
    rect = img.get_rect(**{anchor: (int(x), int(y))})
    surf.blit(img, rect)
    return rect

def bar(surf, x, y, w, h, frac, color, bg=(25, 20, 35), radius=6):
    pygame.draw.rect(surf, bg, (x, y, w, h), border_radius=radius)
    fw = max(2, int(w * max(0.0, min(1.0, frac))))
    pygame.draw.rect(surf, color, (x, y, fw, h), border_radius=radius)

def orb(surf, x, y, r, color):
    pygame.draw.circle(surf, (30, 30, 40), (x, y), r + 2)
    pygame.draw.circle(surf, color, (x, y), r)
    pygame.draw.circle(surf, WHITE, (x - max(1, r // 3), y - max(1, r // 3)), max(1, r // 3))

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def weighted_choice(pairs):
    return random.choices([v for v, _ in pairs], weights=[w for _, w in pairs])[0]

def ang_diff(a, b):
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)

def wrap_text(s, font, width):
    words = str(s).split()
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if font.size(t)[0] <= width:
            cur = t
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines or [""]

def gradient_edge(w, h, horizontal, flip, color=(140, 20, 30)):
    """Pre-rendered alpha gradient strip (used for the low-HP vignette)."""
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    n = 6
    for i in range(n):
        a = int(120 * (1 - i / n))
        if horizontal:
            yy = i * h // n if not flip else h - (i + 1) * h // n
            pygame.draw.rect(s, color + (a,), (0, yy, w, h // n + 1))
        else:
            xx = i * w // n if not flip else w - (i + 1) * w // n
            pygame.draw.rect(s, color + (a,), (xx, 0, w // n + 1, h))
    return s

# ======================================================================
#  [6] ENTITIES
# ======================================================================
class Player:
    def __init__(self):
        self.x, self.y = SCREEN_W // 2, 500
        self.base_speed = 210
        self.hp = PLAYER_MAX_HP
        self.max_hp = PLAYER_MAX_HP
        self.facing = 1
        self.dir_x, self.dir_y = 0, -1
        self.iframes = 0
        self.cool = 0
        self.moving = False
        self.kx = self.ky = 0

    def update(self, dt, keys, game):
        if self.iframes > 0: self.iframes -= dt
        if self.cool > 0: self.cool -= dt
        mx = int(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - int(keys[pygame.K_a] or keys[pygame.K_LEFT])
        my = int(keys[pygame.K_s] or keys[pygame.K_DOWN]) - int(keys[pygame.K_w] or keys[pygame.K_UP])
        if mx and my:
            mx *= 0.7071; my *= 0.7071
        self.moving = bool(mx or my)
        if mx: self.facing = 1 if mx > 0 else -1
        if mx or my:
            n = math.hypot(mx, my) or 1
            self.dir_x, self.dir_y = mx / n, my / n
        spd = self.base_speed
        if game.loc != "base" and "broomshed" in game.buildings: spd *= 1.2
        if game.buffs.get("swift", 0) > 0: spd *= 1.35
        spd *= game.move_mult()
        self.x += (mx * spd + self.kx) * dt
        self.y += (my * spd + self.ky) * dt
        damp = max(0.0, 1 - 7 * dt)
        self.kx *= damp; self.ky *= damp
        self.x = clamp(self.x, 28, SCREEN_W - 28)
        self.y = clamp(self.y, 70, SCREEN_H - 26)

    def draw(self, surf, t):
        x, y = int(self.x), int(self.y)
        pygame.draw.ellipse(surf, (40, 60, 35), (x - 14, y + 6, 28, 10))
        y += int(math.sin(t * 11) * 2) if self.moving else int(math.sin(t * 2.5))
        blink = self.iframes > 0 and int(self.iframes * 12) % 2 == 0
        cloak = (255, 255, 255) if blink else (126, 62, 158)
        skin  = (255, 255, 255) if blink else (255, 221, 190)
        hatc  = (255, 255, 255) if blink else (72, 34, 96)
        pygame.draw.polygon(surf, cloak, [(x - 13, y), (x + 13, y), (x + 6, y - 24), (x - 6, y - 24)])
        pygame.draw.circle(surf, skin, (x, y - 30), 8)
        ex = 3 * self.facing
        pygame.draw.circle(surf, (40, 30, 50), (x + ex - 2, y - 31), 1)
        pygame.draw.circle(surf, (40, 30, 50), (x + ex + 3, y - 31), 1)
        pygame.draw.ellipse(surf, hatc, (x - 14, y - 42, 28, 8))
        pygame.draw.polygon(surf, hatc, [(x - 8, y - 42), (x + 9, y - 42), (x + 3, y - 62)])
        pygame.draw.rect(surf, (255, 255, 255) if blink else GOLD, (x - 8, y - 45, 16, 3))


class Bolt:
    def __init__(self, x, y, dx, dy, dmg):
        self.x, self.y, self.dx, self.dy, self.dmg = x, y, dx, dy, dmg
        self.life = 1.1
        self.t = 0

    def update(self, dt):
        self.x += self.dx * 460 * dt
        self.y += self.dy * 460 * dt
        self.life -= dt
        self.t += dt
        return self.life > 0 and 0 <= self.x <= SCREEN_W and 0 <= self.y <= SCREEN_H

    def draw(self, surf):
        x, y = int(self.x), int(self.y)
        r = 5 + int(math.sin(self.t * 20) * 1.5)
        pygame.draw.circle(surf, (200, 140, 255), (x, y), r + 3)
        pygame.draw.circle(surf, (240, 200, 255), (x, y), r)
        pygame.draw.circle(surf, WHITE, (x, y), 2)


class Pickup:
    def __init__(self, x, y, item, rare=False):
        self.x, self.y, self.item, self.rare = x, y, item, rare
        self.vx = random.uniform(-90, 90)
        self.vy = random.uniform(-90, 90)
        self.t = random.uniform(0, 6)

    def update(self, dt, game):
        self.t += dt
        px, py = game.player.x, game.player.y - 12
        d = math.hypot(px - self.x, py - self.y)
        if d < 100:
            self.x += (px - self.x) / max(d, 1) * 300 * dt
            self.y += (py - self.y) / max(d, 1) * 300 * dt
        else:
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.vx *= max(0.0, 1 - 4 * dt)
            self.vy *= max(0.0, 1 - 4 * dt)
        self.x = clamp(self.x, 16, SCREEN_W - 16)
        self.y = clamp(self.y, 70, SCREEN_H - 16)
        if d < 18:
            game.add_item(self.item, 1)
            game.sfx("rare" if self.rare else "pickup")
            lbl = ("RARE! " if self.rare else "") + "+1 " + INGREDIENTS[self.item]["name"]
            game.add_float(self.x, self.y - 10, lbl,
                           GOLD if self.rare else INGREDIENTS[self.item]["color"])
            return False
        return True

    def draw(self, surf):
        x = int(self.x)
        y = int(self.y + math.sin(self.t * 4) * 2)
        if self.rare:
            pygame.draw.circle(surf, GOLD, (x, y), 12 + int(math.sin(self.t * 8) * 2), 2)
        orb(surf, x, y, 6, INGREDIENTS[self.item]["color"])


class FloatText:
    def __init__(self, x, y, s, color):
        self.x, self.y, self.s, self.color = x, y, s, color
        self.ttl = 1.1

    def update(self, dt):
        self.y -= 34 * dt
        self.ttl -= dt
        return self.ttl > 0

    def draw(self, surf):
        text(surf, self.s, self.x, self.y, FONT_S, self.color, "center")


class Node:
    """Harvestable plant in a biome; regrows after 18s."""
    def __init__(self, x, y, item):
        self.x, self.y, self.item = x, y, item
        self.ready = True
        self.timer = 0
        self.t = random.uniform(0, 6)

    def update(self, dt):
        self.t += dt
        if not self.ready:
            self.timer -= dt
            if self.timer <= 0:
                self.ready = True

    def draw(self, surf):
        x, y = int(self.x), int(self.y)
        c = INGREDIENTS[self.item]["color"]
        sway = math.sin(self.t * 2) * 2
        if self.item == "icecrystal":
            if not self.ready:
                pygame.draw.polygon(surf, (140, 150, 160), [(x - 6, y), (x + 6, y), (x, y - 6)])
                return
            pygame.draw.polygon(surf, c, [(x, y - 24), (x + 8, y - 4), (x + 3, y), (x - 4, y), (x - 8, y - 6)])
            pygame.draw.polygon(surf, (230, 245, 255), [(x - 1, y - 18), (x + 3, y - 6), (x - 3, y - 6)])
            return
        if self.item == "ghostmush":
            if not self.ready:
                pygame.draw.line(surf, (110, 80, 50), (x, y), (x, y - 6), 2)
                return
            pygame.draw.rect(surf, (225, 220, 235), (x - 3, y - 12, 6, 12), border_radius=3)
            pygame.draw.ellipse(surf, c, (x - 11, y - 20, 22, 12))
            pygame.draw.circle(surf, (240, 235, 255), (x - 3, y - 15), 2)
            pygame.draw.circle(surf, (240, 235, 255), (x + 4, y - 17), 2)
            return
        if not self.ready:
            pygame.draw.line(surf, (110, 80, 50), (x, y), (x + sway, y - 8), 2)
            return
        pygame.draw.line(surf, (60, 130, 60), (x, y), (x + sway, y - 16), 3)
        pygame.draw.polygon(surf, (70, 150, 70), [(x, y - 8), (x - 9, y - 13), (x - 2, y - 6)])
        pygame.draw.polygon(surf, (70, 150, 70), [(x, y - 8), (x + 9, y - 13), (x + 2, y - 6)])
        if self.item == "emberroot":
            pygame.draw.polygon(surf, c, [(x + sway, y - 30), (x + sway - 5, y - 16), (x + sway + 5, y - 16)])
        else:
            sx = int(x + sway)
            pygame.draw.circle(surf, c, (sx, y - 20), 5)
            pygame.draw.circle(surf, c, (sx - 5, y - 16), 4)
            pygame.draw.circle(surf, c, (sx + 5, y - 16), 4)
            pygame.draw.circle(surf, (255, 255, 220), (sx, y - 20), 2)


class Monster:
    def __init__(self, mid, x, y, hp_s=1.0, dmg_s=1.0, tint=(110, 240, 150)):
        d = MONSTERS[mid]
        self.mid = mid
        self.x, self.y = x, y
        self.hp = max(1, int(d["hp"] * hp_s))
        self.max_hp = self.hp
        self.dmg = d["dmg"] * dmg_s
        self.speed = d["speed"]
        self.r = d["r"]
        self.tint = tint
        self.wt = 0
        self.wdx = self.wdy = 0
        self.flash = 0
        self.t = random.uniform(0, 10)
        self.kx = self.ky = 0

    def update(self, dt, game):
        self.t += dt
        if self.flash > 0: self.flash -= dt
        p = game.player
        dx, dy = p.x - self.x, p.y - self.y
        dist = math.hypot(dx, dy) or 1
        if dist < 260:                      # chase
            self.x += dx / dist * self.speed * dt
            self.y += dy / dist * self.speed * dt
        else:                               # wander
            self.wt -= dt
            if self.wt <= 0:
                self.wt = random.uniform(0.6, 1.6)
                a = random.uniform(0, math.tau)
                self.wdx, self.wdy = math.cos(a), math.sin(a)
                if random.random() < 0.3:
                    self.wdx = self.wdy = 0
            self.x += self.wdx * self.speed * 0.5 * dt
            self.y += self.wdy * self.speed * 0.5 * dt
        self.x += self.kx * dt
        self.y += self.ky * dt
        self.kx *= max(0.0, 1 - 6 * dt)
        self.ky *= max(0.0, 1 - 6 * dt)
        self.x = clamp(self.x, 30, SCREEN_W - 30)
        self.y = clamp(self.y, 76, SCREEN_H - 30)
        if dist < self.r + 14 and p.iframes <= 0:
            dmg = self.dmg * (0.6 if game.buffs.get("stoneskin", 0) > 0 else 1.0)
            p.hp -= dmg
            p.iframes = 0.9
            p.kx = -dx / dist * 260
            p.ky = -dy / dist * 260
            game.sfx("hurt")
            game.add_float(p.x, p.y - 50, "-" + str(int(dmg)), RED)
            if p.hp <= 0:
                game.on_player_down()

    def draw(self, surf):
        x, y = int(self.x), int(self.y)
        getattr(self, "draw_" + self.mid)(surf, x, y)
        if self.flash > 0:
            pygame.draw.circle(surf, (255, 255, 255), (x, y - self.r // 2), self.r + 4)
        if self.hp < self.max_hp:
            bw = 36
            bx, by = x - bw // 2, y - self.r - 26
            pygame.draw.rect(surf, (25, 25, 35), (bx, by, bw, 5))
            pygame.draw.rect(surf, RED, (bx, by, int(bw * max(0, self.hp) / self.max_hp), 5))

    # ---- per-type bodies ----
    def draw_slime(self, surf, x, y):
        sq = math.sin(self.t * 7) * 3
        w = int(self.r * 2 + sq)
        h = int(self.r * 1.7 - sq)
        pygame.draw.ellipse(surf, self.tint, (x - w // 2, y - h, w, h))
        pygame.draw.ellipse(surf, (255, 255, 255), (x - w // 2 + 5, y - h + 6, max(4, w // 4), max(3, h // 5)))
        pygame.draw.circle(surf, (25, 40, 30), (x - 5, y - h + 14), 2)
        pygame.draw.circle(surf, (25, 40, 30), (x + 5, y - h + 14), 2)

    def draw_pixie(self, surf, x, y):
        flap = math.sin(self.t * 25) * 4
        pygame.draw.ellipse(surf, (220, 240, 255), (x - 14, y - 18 + flap, 9, 6))
        pygame.draw.ellipse(surf, (220, 240, 255), (x + 5, y - 18 - flap, 9, 6))
        pygame.draw.circle(surf, (255, 230, 160), (x, y - 14), 6)
        pygame.draw.circle(surf, PURPLE, (x, y - 6), 4)
        sx = x + math.cos(self.t * 3) * 11
        sy = y - 14 + math.sin(self.t * 3) * 11
        pygame.draw.circle(surf, (255, 255, 200), (int(sx), int(sy)), 2)

    def draw_beeswarm(self, surf, x, y):
        for i in range(4):
            a = self.t * 3 + i * math.tau / 4
            bx = x + math.cos(a) * 12
            by = y - 10 + math.sin(a) * 7
            pygame.draw.ellipse(surf, (250, 210, 60), (bx - 6, by - 4, 12, 8))
            pygame.draw.rect(surf, (40, 30, 20), (bx - 2, by - 4, 3, 8))
            pygame.draw.ellipse(surf, (230, 240, 255), (bx - 4, by - 9, 7, 5))

    def draw_scorpion(self, surf, x, y):
        c = (150, 90, 50)
        pygame.draw.ellipse(surf, c, (x - 16, y - 12, 32, 16))
        pygame.draw.circle(surf, c, (x - 18, y - 6), 6)
        pygame.draw.circle(surf, c, (x - 18, y + 2), 6)
        for i in range(3):
            pygame.draw.line(surf, (110, 65, 35), (x - 8 + i * 8, y - 2), (x - 10 + i * 8, y + 6), 2)
        pygame.draw.circle(surf, c, (x + 10, y - 14), 4)
        pygame.draw.circle(surf, c, (x + 15, y - 20), 4)
        pygame.draw.circle(surf, c, (x + 11, y - 27), 4)
        pygame.draw.polygon(surf, (230, 80, 90), [(x + 11, y - 30), (x + 16, y - 29), (x + 13, y - 36)])
        pygame.draw.circle(surf, (255, 100, 80), (x - 8, y - 8), 2)
        pygame.draw.circle(surf, (255, 100, 80), (x - 3, y - 10), 2)

    def draw_icegolem(self, surf, x, y):
        bob = int(math.sin(self.t * 4) * 2)
        c, d = (150, 200, 235), (110, 160, 200)
        pygame.draw.rect(surf, c, (x - 16, y - 34 + bob, 32, 30), border_radius=6)
        pygame.draw.rect(surf, d, (x - 10, y - 46 + bob, 20, 14), border_radius=4)
        pygame.draw.rect(surf, d, (x - 25, y - 30 + bob, 8, 20), border_radius=3)
        pygame.draw.rect(surf, d, (x + 17, y - 30 + bob, 8, 20), border_radius=3)
        pygame.draw.circle(surf, (140, 220, 255), (x, y - 20 + bob), 5)
        pygame.draw.circle(surf, (60, 90, 120), (x - 4, y - 40 + bob), 2)
        pygame.draw.circle(surf, (60, 90, 120), (x + 4, y - 40 + bob), 2)

    def draw_frostwolf(self, surf, x, y):
        c = (170, 190, 215)
        pygame.draw.ellipse(surf, c, (x - 18, y - 16, 34, 16))
        pygame.draw.circle(surf, c, (x + 16, y - 18), 8)
        pygame.draw.polygon(surf, c, [(x + 11, y - 24), (x + 16, y - 24), (x + 13, y - 31)])
        pygame.draw.polygon(surf, c, [(x + 17, y - 24), (x + 22, y - 24), (x + 20, y - 30)])
        pygame.draw.line(surf, c, (x - 18, y - 12), (x - 26, y - 20), 3)
        for lx in (-12, -4, 6, 14):
            pygame.draw.line(surf, c, (x + lx, y - 6), (x + lx, y + 4), 3)
        pygame.draw.circle(surf, (120, 230, 255), (x + 18, y - 19), 2)

    def draw_boglurker(self, surf, x, y):
        rise = math.sin(self.t * 2) * 3
        pygame.draw.ellipse(surf, (60, 80, 60), (x - 18, y - 20 + rise, 36, 24))
        pygame.draw.ellipse(surf, (80, 105, 80), (x - 10, y - 24 + rise, 20, 12))
        pygame.draw.circle(surf, (255, 230, 90), (x - 6, int(y - 16 + rise)), 3)
        pygame.draw.circle(surf, (255, 230, 90), (x + 6, int(y - 16 + rise)), 3)
        rr = 20 + int(self.t * 10) % 12
        pygame.draw.circle(surf, (100, 130, 110), (x, y), rr, 1)

# ======================================================================
#  [7] GAME
# ======================================================================
class Game:

    # ================================================== 7.1 setup & lifecycle
    def __init__(self):
        self.state = "menu"
        self.loc = "base"
        self.time = 0.0
        self.overlay = None
        self.overlay_idx = 0
        self.menu_open_t = -1.0
        self._restart = False

        self._init_state()
        self._init_hud()
        self._init_narrative()
        self._init_world()
        self._init_intro()

    def _init_state(self):
        """Core run state: player, inventories, progression."""
        self.player = Player()
        self.gold = 40
        self.day = 1
        self.rep = 0
        self.items = {"moonpetal": 2, "slimejelly": 1, "fairydust": 1}
        self.potions = {}                 # pid -> [rough, standard, fine, exquisite]
        self.board, self.orders = [], []
        self.buildings, self.stubs = [], {}
        self.bolts, self.monsters, self.pickups = [], [], []
        self.nodes, self.decor, self.patches = [], [], []
        self.floats, self.messages = [], []
        self.spawn_timer = 10
        self.brew_level, self.brew_xp = 1, 0
        self.known_secrets = []
        self.catalyst = "none"
        self.brew = None
        self.exp = None
        self.craft_tab = 0
        self.order_tab = 0
        self.kills = {}
        self.buffs = {}
        # audio (rendered once, reused across restarts)
        self._sfx_bank, self._songs = ensure_audio()
        self._music_name = None
        # menu system
        self.settings = dict(DEFAULT_SETTINGS)
        self.click_map = []
        self.title_clicks = []
        self.confirm = None
        self.decision = None
        self.pause_sel = 0
        self._menu_back = None
        self.inv_sort = "name"
        self.inv_sel = 0
        self.inv_scroll = 0
        self.save_flash = 0.0
        self.title_note = None

    def _init_hud(self):
        """Ledger stats, HUD pops, HP ghost, vignette surfaces."""
        self.stats = {"gold_earned": 0, "potions": 0, "quality": [0, 0, 0, 0],
                      "deliveries": 0, "rejects": 0, "favors_done": 0,
                      "feuds_resolved": 0, "landmarks": 0, "experiments": 0,
                      "distance": 0.0}
        self.hud_pops = []
        self.hp_ghost = float(PLAYER_MAX_HP)
        self.minimap_big = False
        self.tracker_on = True
        self.buff_max = {}
        self._lpx = self._lpy = None
        self._heart_t = 0.0
        self.vig_top    = gradient_edge(SCREEN_W, 100, True,  False)
        self.vig_bottom = gradient_edge(SCREEN_W, 100, True,  True)
        self.vig_left   = gradient_edge(100, SCREEN_H, False, False)
        self.vig_right  = gradient_edge(100, SCREEN_H, False, True)

    def _init_narrative(self):
        self.rel = {n: 10 for n, _ in CUSTOMERS}
        self.feuds, self.favors, self.chatted = [], [], set()
        self.family_flag = False
        self.chronicle, self.chronicle_sel = [], 0
        self.story_idx = 0
        self.story_view = None
        self.finale = False
        self.visited = set()
        self.first_kills = set()
        self.day_event = None
        self.active_rumor = None
        self.legend_unlocked = False

    def _init_world(self):
        self.roads, self.zones, self.landmarks, self.ambient = [], [], [], []
        self.variant = ""
        self.weather = "clear"
        self.base_roads = [
            self.make_road((250, 300), (512, 630), 50),
            self.make_road((512, 630), (512, 378), 24),
            self.make_road((512, 630), (740, 300), 60),
            self.make_road((512, 630), (860, 520), 50),
        ]
        self.fog = pygame.Surface((256, 256), pygame.SRCALPHA)
        for r in range(128, 0, -3):
            a = int(85 * (1 - r / 128.0) ** 1.5)
            pygame.draw.circle(self.fog, (208, 214, 224, a), (128, 128), r)
        self.fog_full = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        self.fog_full.fill((202, 208, 220, 55))
        self.grass = [(random.randint(20, SCREEN_W - 20), random.randint(90, SCREEN_H - 20)) for _ in range(70)]
        fcols = [(250, 120, 150), (250, 220, 120), (180, 140, 240), (240, 240, 240)]
        self.flowers = [(random.randint(60, SCREEN_W - 60), random.randint(120, SCREEN_H - 40),
                         random.choice(fcols)) for _ in range(26)]
        self.stars = [(random.randint(0, SCREEN_W), random.randint(0, 380), random.uniform(0, 6)) for _ in range(80)]
        self.menu_witch = Player()
        self.menu_witch.x, self.menu_witch.y = 640, 470

    def _init_intro(self):
        self.refresh_board()
        self.chron("Willow inherits her grandmother Elmira's cottage, one cauldron, "
                   "and a letter she hasn't opened yet. Ten villagers already have "
                   "opinions about her.")
        self.msg("Welcome home, Witch Willow!", GOLD, 7)
        self.msg("P = pause menu (save, options, controls). Mouse works in menus!", PURPLE, 8)

    # ================================================== 7.2 audio interface
    def sfx(self, name, vol=1.0):
        """Play a named sound effect (respects settings + master volume)."""
        if not self._sfx_bank or not self.settings.get("sfx", True):
            return
        snd = self._sfx_bank.get(name)
        if snd:
            snd.set_volume(clamp(self.settings.get("sfx_vol", 80) / 100.0 * vol, 0.0, 1.0))
            try:
                snd.play()
            except pygame.error:
                pass

    def theme(self):
        """Which music track should be playing right now?"""
        if self.state == "menu":
            return "title"
        if self.loc == "base":
            return "home"
        p = self.player
        for m in self.monsters:
            if math.hypot(m.x - p.x, m.y - p.y) < DANGER_MUSIC_R:
                return "danger"
        return "wild"

    def update_music(self):
        """Crossfade to the correct theme (reserved channel 0)."""
        if not AUDIO_OK or not self._songs:
            return
        chan = _AUDIO_CACHE.get("chan")
        if chan is None:
            return
        want = self.theme() if (self.settings.get("music", True) and
                                self.settings.get("music_vol", 0) > 0) else None
        if want != self._music_name:
            if self._music_name:
                chan.fadeout(400)
            if want:
                chan.play(self._songs[want], loops=-1, fade_ms=400)
            self._music_name = want
        if want:
            chan.set_volume(self.settings.get("music_vol", 65) / 100.0)

    # ================================================== 7.3 save / load
    def save_game(self):
        data = {
            "version": 1,
            "gold": self.gold, "day": self.day, "rep": self.rep,
            "items": self.items,
            "potions": {k: list(v) for k, v in self.potions.items()},
            "buildings": self.buildings, "kills": self.kills,
            "rel": self.rel, "feuds": self.feuds, "favors": self.favors,
            "known_secrets": self.known_secrets,
            "brew_level": self.brew_level, "brew_xp": self.brew_xp,
            "catalyst": self.catalyst,
            "orders": self.orders, "board": self.board,
            "chronicle": self.chronicle, "story_idx": self.story_idx,
            "visited": sorted(self.visited), "first_kills": sorted(self.first_kills),
            "legend_unlocked": self.legend_unlocked, "family_flag": self.family_flag,
            "finale": self.finale, "stats": self.stats, "settings": self.settings,
            "day_event": self.day_event["id"] if self.day_event else None,
            "rumor": self.active_rumor,
        }
        try:
            with open(SAVE_PATH, "w") as f:
                json.dump(data, f)
            self.save_flash = 1.4
            return True
        except Exception as ex:
            self.msg("Save failed: %s" % ex, RED)
            return False

    def has_save(self):
        return os.path.exists(SAVE_PATH)

    def load_game(self):
        try:
            with open(SAVE_PATH) as f:
                d = json.load(f)
        except Exception as ex:
            self.msg("No valid save found. (%s)" % ex, RED)
            return False
        self.gold = d.get("gold", 40)
        self.day = d.get("day", 1)
        self.rep = d.get("rep", 0)
        self.items = dict(d.get("items", {}))
        self.potions = {k: list(v) for k, v in d.get("potions", {}).items()}
        self.buildings = list(d.get("buildings", []))
        self.kills = dict(d.get("kills", {}))
        self.rel = dict(d.get("rel", {n: 10 for n, _ in CUSTOMERS}))
        self.feuds = list(d.get("feuds", []))
        self.favors = list(d.get("favors", []))
        self.known_secrets = list(d.get("known_secrets", []))
        self.brew_level = d.get("brew_level", 1)
        self.brew_xp = d.get("brew_xp", 0)
        self.catalyst = d.get("catalyst", "none")
        self.orders = list(d.get("orders", []))
        self.board = list(d.get("board", []))
        self.chronicle = list(d.get("chronicle", []))
        self.chronicle_sel = max(0, len(self.chronicle) - 1)
        self.story_idx = d.get("story_idx", 0)
        self.visited = set(d.get("visited", []))
        self.first_kills = set(d.get("first_kills", []))
        self.legend_unlocked = d.get("legend_unlocked", False)
        self.family_flag = d.get("family_flag", False)
        self.finale = d.get("finale", False)
        st = dict(self.stats); st.update(d.get("stats", {})); self.stats = st
        self.settings.update(d.get("settings", {}))
        self.day_event = next((e for e in DAY_EVENTS
                               if e["id"] == d.get("day_event")), None)
        self.active_rumor = d.get("rumor")
        self.stubs = {k: self.gen_road(BUILD_SLOTS[list(BUILDINGS.keys()).index(k)],
                                       (512, 566), 34, step=10)
                      for k in self.buildings if k in BUILDINGS}
        # reset transient state
        self.loc = "base"
        self.bolts, self.pickups, self.monsters = [], [], []
        self.nodes, self.decor, self.patches = [], [], []
        self.zones, self.landmarks, self.roads, self.ambient = [], [], [], []
        self.floats, self.buffs, self.chatted = [], {}, set()
        self.brew = self.exp = self.decision = self.confirm = self.story_view = None
        p = self.player
        p.x, p.y, p.hp = 512, 520, p.max_hp
        self.hp_ghost = p.hp
        self.overlay = None
        self.state = "play"
        self.menu_open_t = self.time
        self.sfx("select")
        self.msg("Save loaded - welcome back, Willow. (Day %d)" % self.day, GOLD, 6)
        return True

    def quit_to_title(self):
        self.overlay = self.confirm = self.decision = self.story_view = None
        self.state = "menu"

    def pause_action(self, key):
        if key == "resume":
            self.sfx("back")
            self.overlay = None
        elif key == "controls":
            self.sfx("select")
            self._menu_back = "pause"
            self.set_overlay("controls")
        elif key == "options":
            self.sfx("select")
            self._menu_back = "pause"
            self.set_overlay("options")
        elif key == "save":
            self.sfx("accept")
            if self.save_game():
                self.msg("Game saved.", GREEN)
        elif key == "load":
            if self.has_save():
                self.ask_confirm("Load Game?",
                                 ["Load your saved village from disk?", "",
                                  "Unsaved progress for today will be lost."],
                                 self.load_game)
            else:
                self.sfx("deny")
                self.msg("No save file found.", RED)
        elif key == "quit":
            self.sfx("select")
            self.ask_confirm("Quit to Title?",
                             ["Return to the title screen?", "",
                              "Save first if you want to keep today!"],
                             self.quit_to_title)

    def try_continue(self):
        if self.has_save():
            self.sfx("select")
            self.load_game()
        else:
            self.sfx("deny")
            self.title_note = ("No save file found yet - start a new "
                               "journey first! (autosaves each morning)")

    def toggle_setting(self, key):
        self.settings[key] = not self.settings.get(key, True)

    # ================================================== 7.4 menu framework
    def set_overlay(self, name):
        self.overlay = name
        self.overlay_idx = 0
        self.menu_open_t = self.time
        if name == "inv":
            self.inv_sel = 0
            self.inv_scroll = 0

    def menu_k(self):
        """0..1 slide/fade progress for the open menu."""
        if self.menu_open_t < 0:
            return 1.0
        return clamp((self.time - self.menu_open_t) / MENU_SLIDE_T, 0.0, 1.0)

    def dim_screen(self, a=170):
        """Dim the world behind menus; returns the slide offset to add to y."""
        k = self.menu_k()
        if a > 0:
            s = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            s.fill((8, 6, 18, int(a * k)))
            screen.blit(s, (0, 0))
        return int((1 - k) * 16)

    def add_click(self, rect, fn):
        self.click_map.append((rect, fn))

    def hovered(self, rect):
        return rect.collidepoint(pygame.mouse.get_pos())

    def handle_click(self, pos):
        if self.state == "menu":
            for rect, fn in self.title_clicks:
                if rect.collidepoint(pos):
                    self.sfx("select")
                    fn(); return
            return
        for rect, fn in reversed(self.click_map):
            if rect.collidepoint(pos):
                self.sfx("tick")
                fn(); return

    def menu_row(self, i, ryi, rx, wu, on_click):
        """Selectable/hoverable row background; click selects or confirms."""
        r = pygame.Rect(rx - 8, ryi - 4, wu + 16, 30)
        self.add_click(r, on_click)
        sel, hov = i == self.overlay_idx, self.hovered(r)
        if sel:
            pygame.draw.rect(screen, (96, 66, 140), r, border_radius=6)
        elif hov:
            pygame.draw.rect(screen, (68, 50, 100), r, border_radius=6)
        return r

    def menu_button(self, label, x, y, fn, color=GREY, enabled=True):
        w = FONT_S.size(label)[0] + 20
        r = pygame.Rect(x, y, w, 22)
        self.add_click(r, fn)
        hov = self.hovered(r) and enabled
        bg = (44, 36, 64) if not enabled else ((64, 50, 94) if hov else (40, 32, 58))
        pygame.draw.rect(screen, bg, r, border_radius=6)
        pygame.draw.rect(screen, color if enabled else (90, 85, 105), r, 1, border_radius=6)
        text(screen, label, r.x + 10, r.y + 4, FONT_S, color if enabled else (90, 85, 105))
        return r.right + 8

    def row_click(self, i, confirm_fn):
        if i == self.overlay_idx:
            confirm_fn()
        else:
            self.overlay_idx = i
            self.sfx("move")

    def ask_confirm(self, title, lines, on_yes):
        self.confirm = {"title": title, "lines": lines, "on_yes": on_yes, "sel": 1}
        self.set_overlay("confirm")

    def _confirm_pick(self, i):
        c = self.confirm
        self.confirm = None
        self.overlay = None
        if i == 0 and c:
            self.sfx("select")
            c["on_yes"]()
        else:
            self.sfx("back")

    def _decision_pick(self, i, cb):
        self.decision = None
        self.overlay = None
        cb()

    # ================================================== 7.5 inventory / gold / xp / buffs
    def add_item(self, item, n=1):
        self.items[item] = self.items.get(item, 0) + n

    def add_float(self, x, y, s, color):
        if self.settings.get("floats", True):
            self.floats.append(FloatText(x, y, s, color))

    def msg(self, s, color=WHITE, ttl=4.5):
        self.messages.append({"s": s, "c": color, "ttl": ttl})
        if len(self.messages) > 5:
            self.messages.pop(0)

    def label(self, s, x, y, color=WHITE):
        img = FONT_S.render(s, True, color)
        r = img.get_rect(midbottom=(int(x), int(y)))
        pygame.draw.rect(screen, (25, 20, 35), (r.x - 6, r.y - 3, r.w + 12, r.h + 6), border_radius=6)
        screen.blit(img, r)

    def earn_gold(self, n):
        self.gold += n
        self.stats["gold_earned"] += n
        self.hud_pops.append({"s": "+%dg" % n, "c": GOLD, "ttl": 1.2, "y": 0})

    def spend_gold(self, n):
        self.gold -= n
        self.hud_pops.append({"s": "-%dg" % n, "c": RED, "ttl": 1.2, "y": 0})

    def set_buff(self, b, dur):
        self.buffs[b] = max(self.buffs.get(b, 0), dur)
        self.buff_max[b] = max(self.buff_max.get(b, 0), dur)

    def rep_tier(self):
        r = self.rep
        if r <= 0: return "Unknown"
        if r < 5:  return "Known"
        if r < 10: return "Trusted"
        if r < 20: return "Renowned"
        return "Legendary"

    # ---- brewing progression ----
    def level_bonus(self):
        return min(3, self.brew_level // 2)

    def xp_next(self):
        return 60 + self.brew_level * 40

    def add_xp(self, n):
        self.brew_xp += n
        while self.brew_xp >= self.xp_next():
            self.brew_xp -= self.xp_next()
            self.brew_level += 1
            self.sfx("lvl")
            self.msg("Brewing level up! Now Lv %d (skill bonus +%d)."
                     % (self.brew_level, self.level_bonus()), PURPLE)
            self.hud_pops.append({"s": "LEVEL UP!", "c": PURPLE, "ttl": 1.6, "y": 0})

    # ---- potion storage (4 quality tiers each) ----
    def potion_total(self, pid):
        return sum(self.potions.get(pid, [0, 0, 0, 0]))

    def pot_count_ge(self, pid, minq):
        arr = self.potions.get(pid)
        return sum(arr[minq:]) if arr else 0

    def add_potion(self, pid, tier, n=1):
        arr = self.potions.setdefault(pid, [0, 0, 0, 0])
        arr[tier] += n
        self.stats["potions"] += n
        self.stats["quality"][tier] += n

    def consume_potion(self, pid):
        """Remove lowest-tier potion of pid; returns tier or None."""
        arr = self.potions.get(pid)
        if not arr or not any(arr):
            return None
        t = next(i for i, v in enumerate(arr) if v > 0)
        arr[t] -= 1
        if sum(arr) == 0:
            del self.potions[pid]
        return t

    def take_potions(self, pid, minq, qty):
        arr = self.potions[pid]
        for t in range(minq, 4):
            take = min(arr[t], qty)
            arr[t] -= take
            qty -= take
            if qty == 0:
                break
        if sum(arr) == 0:
            del self.potions[pid]

    def quick_slots(self):
        """Auto-filled hotbar: Healing first, then most-owned drinkables."""
        out = []
        if self.potion_total("healing") > 0:
            out.append("healing")
        rest = [p for p in self.potions
                if p not in ("healing", "concord") and
                not pot_def(p).get("legendary") and self.potion_total(p) > 0]
        rest.sort(key=lambda p: -self.potion_total(p))
        return (out + rest)[:HOTBAR_SLOTS]

    def drink_potion(self, pid):
        if pid == "concord":
            self.msg("This one is meant for giving, not drinking. (G in the VILLAGERS tab)", PURPLE)
            return
        tier = self.consume_potion(pid)
        if tier is None:
            self.msg("None brewed.", GREY); return
        self.sfx("gulp")
        pd = pot_def(pid)
        if pid == "healing":
            heal = 45 + 15 * tier
            self.player.hp = min(self.player.max_hp, self.player.hp + heal)
            self.add_float(self.player.x, self.player.y - 56, "+%d HP" % heal, GREEN)
            self.msg("You gulp a Healing Potion [%s]. (+%d HP)" % (QUALITY[tier]["name"], heal), GREEN)
        elif pd.get("special") == "xp80":
            self.add_xp(80)
            self.msg("The rune's knowledge floods your mind! (+80 brewing XP)", PURPLE)
        elif pd.get("buff"):
            b = pd["buff"]
            dur = pd["buff_t"] + 10 * tier
            self.set_buff(b, dur)
            self.msg("%s [%s]: %s (%ds)" % (BUFFS[b][0], QUALITY[tier]["name"], pd["desc"], dur),
                     BUFFS[b][1])

    def effect_desc(self, pd):
        if pd.get("buff"):
            nm = BUFFS[pd["buff"]][0]
            return "Drink (F): %s %ds - %s (+10s per quality tier)" % (nm, pd["buff_t"], pd["desc"])
        if pd.get("special") == "xp80":
            return "Drink (F): +80 brewing XP"
        if pd.get("special") == "gift":
            return "GIFT (G in VILLAGERS tab): mends feuds & warms hearts"
        if pd.get("name") == "Healing Potion":
            return "Drink (F/H/1): restores 45 HP (+15 per quality tier)"
        return ""

    # ================================================== 7.6 social: relationships, feuds, favors
    def rel_tier(self, r):
        if r <= -40: return "FEUD (with you)"
        if r < -10:  return "Cold"
        if r < 15:   return "Acquaintance"
        if r < 40:   return "Friend"
        if r < 60:   return "Close Friend"
        return "FOUND FAMILY"

    def add_rel(self, name, n):
        old = self.rel.get(name, 10)
        new = clamp(old + n, -100, 100)
        self.rel[name] = new
        for kin in FAMILY_LINKS.get(name, []):        # kin share standing
            self.rel[kin] = clamp(self.rel.get(kin, 10) + int(n * 0.4), -100, 100)
        if old > -40 and new <= -40:
            s = "%s has declared a personal FEUD against you! (Gift a Concord Draught to mend it.)" % name
            self.msg(s, RED); self.chron(s)
        if old < 60 and new >= 60:
            s = "%s now considers you FOUND FAMILY! They may visit your cottage." % name
            self.msg(s, GOLD); self.chron(s)
        if len([k for k, v in self.rel.items() if v >= 60]) >= 3:
            self.family_flag = True

    def feud_involving(self, name):
        for f in self.feuds:
            if not f["done"] and name in (f["a"], f["b"]):
                return f
        return None

    def sulking(self, name):
        f = self.feud_involving(name)
        return bool(f and f["sided"] is None and f["age"] >= 2)

    def family_names(self):
        return [n for n, v in sorted(self.rel.items(), key=lambda kv: -kv[1]) if v >= 60]

    def villager_list(self):
        return [n for n, _ in sorted(self.rel.items(), key=lambda kv: (-kv[1], kv[0]))]

    # ---- feuds ----
    def maybe_start_feud(self):
        if self.day < 3 or len([f for f in self.feuds if not f["done"]]) >= 2:
            return False
        free = [n for n, _ in CUSTOMERS if not self.feud_involving(n)]
        if len(free) < 2:
            return False
        a, b = random.sample(free, 2)
        reason = random.choice(FEUD_REASONS)
        f = {"a": a, "b": b, "reason": reason, "age": 0, "sided": None, "done": False}
        self.feuds.append(f)
        plea_a = random.choice(PERSONAS[PERSONA_OF[a]]["greet"]) + " " + \
                 random.choice(FEUD_PLEA).format(other=b)
        plea_b = random.choice(PERSONAS[PERSONA_OF[b]]["greet"]) + " " + \
                 random.choice(FEUD_PLEA).format(other=a)
        lines = ["%s and %s are no longer speaking.", "%s.", "",
                 "Both turn up at your cottage the same evening,",
                 "each demanding you take a side.", "",
                 '%s: "%s"' % (a, plea_a), '%s: "%s"' % (b, plea_b)]
        self.decision = {"title": "A FEUD ERUPTS!", "lines": lines, "sel": 0,
                         "options": [("Side with %s" % a, lambda: self.side_feud(f, a, b)),
                                     ("Side with %s" % b, lambda: self.side_feud(f, b, a)),
                                     ("Refuse to take sides", lambda: self.neutral_feud(f))]}
        self.sfx("feud")
        self.set_overlay("decision")
        self.chron("A feud began: %s vs %s. %s." % (a, b, reason))
        return True

    def side_feud(self, f, ally, foe):
        f["sided"] = ally
        self.add_rel(ally, 15)
        self.add_rel(foe, -20)
        self.sfx("select")
        self.msg("You sided with %s. %s is furious - and %s's kin take note!"
                 % (ally, foe, foe), GOLD)
        self.chron("Willow sided with %s against %s. The village holds its breath."
                   % (ally, foe))

    def neutral_feud(self, f):
        f["sided"] = "neutral"
        self.add_rel(f["a"], -4)
        self.add_rel(f["b"], -4)
        self.sfx("back")
        self.msg("You refuse to pick a side. Neither is thrilled, but both respect it... mostly.", GREY)
        self.chron("Willow stayed neutral in the %s/%s feud." % (f["a"], f["b"]))

    def resolve_feud(self, f, via):
        f["done"] = True
        self.stats["feuds_resolved"] += 1
        self.sfx("warm")
        if via == "gift":
            line = ("%s accepts the Concord Draught - the feud with %s ends "
                    "in hugs and slight stickiness!" % (via, f["b"] if via == f["a"] else f["a"]))
        else:
            line = random.choice(RECONCILE_LINES).format(a=f["a"], b=f["b"])
        self.msg(line, GREEN)
        self.chron(line + " (feud ended)")
        self.add_rel(f["a"], 5)
        self.add_rel(f["b"], 5)

    # ---- favors ----
    def maybe_start_favor(self):
        names = [n for n, _ in CUSTOMERS
                 if not any(v["who"] == n for v in self.favors) and not self.sulking(n)]
        if not names:
            return
        who = random.choice(names)
        greet = random.choice(PERSONAS[PERSONA_OF[who]]["greet"])
        if random.random() < 0.5:                       # fetch favor
            item = random.choice(list(INGREDIENTS.keys()))
            need = random.randint(1, 3)
            line = greet + " " + random.choice(FAVOR_ITEM_LINES).format(
                need=need, item=INGREDIENTS[item]["name"])
            fav = {"who": who, "kind": "item", "target": item, "need": need, "have": 0,
                   "reward": 12 + need * 9, "due": self.day + 4, "line": line}
            what = "fetch %dx %s" % (need, INGREDIENTS[item]["name"])
        else:                                           # hunt favor
            mid = random.choice(list(MONSTERS.keys()))
            need = random.randint(2, 4)
            line = greet + " " + random.choice(FAVOR_HUNT_LINES).format(
                need=need, monster=MONSTERS[mid]["name"])
            fav = {"who": who, "kind": "hunt", "target": mid, "need": need, "have": 0,
                   "reward": 15 + need * 11, "due": self.day + 4, "line": line}
            what = "hunt %dx %s" % (need, MONSTERS[mid]["name"])
        self.decision = {"title": "A PERSONAL REQUEST", "sel": 0,
                         "lines": ["%s knocks at your door:" % who, "", '"%s"' % line],
                         "options": [("Accept %s's favor" % who, lambda: self.accept_favor(fav, what)),
                                     ("Turn it down", lambda: self.reject_favor(fav))]}
        self.sfx("chat")
        self.set_overlay("decision")

    def accept_favor(self, fav, what):
        self.favors.append(fav)
        self.add_rel(fav["who"], 3)
        self.sfx("accept")
        self.msg("Favor accepted - see your CONTRACTS tab.", GOLD)
        self.chron("Willow agreed to help %s: %s." % (fav["who"], what))

    def reject_favor(self, fav):
        self.add_rel(fav["who"], -6)
        self.sfx("deny")
        self.msg('%s: "%s"' % (fav["who"],
                 random.choice(PERSONAS[PERSONA_OF[fav["who"]]]["reject"])), GREY)

    def complete_favor(self, fav):
        self.earn_gold(fav["reward"])
        self.stats["favors_done"] += 1
        self.add_rel(fav["who"], 16)
        self.sfx("deliver")
        self.msg('%s: "%s"' % (fav["who"],
                 random.choice(PERSONAS[PERSONA_OF[fav["who"]]]["thanks"]).format(reward=fav["reward"])), GOLD)
        if fav["kind"] == "item":
            self.chron("Favor for %s completed: delivered %dx %s. Friendship deepened."
                       % (fav["who"], fav["need"], INGREDIENTS[fav["target"]]["name"]))
        else:
            self.chron("Favor for %s completed: %dx %s hunted. Friendship deepened."
                       % (fav["who"], fav["need"], MONSTERS[fav["target"]]["name"]))
        if fav in self.favors:
            self.favors.remove(fav)

    def deliver_favor(self, fav):
        if fav["kind"] == "hunt":
            self.msg("%d/%d %s hunted so far - keep at it!"
                     % (fav["have"], fav["need"], MONSTERS[fav["target"]]["name"]), GREY)
            return
        if self.items.get(fav["target"], 0) < fav["need"]:
            self.msg("You need %dx %s." % (fav["need"], INGREDIENTS[fav["target"]]["name"]), RED)
            return
        for _ in range(fav["need"]):
            self.items[fav["target"]] -= 1
            if self.items[fav["target"]] <= 0:
                del self.items[fav["target"]]
        self.complete_favor(fav)
        self.check_story()

    # ---- chat & gifts ----
    def chat_npc(self, name):
        if name in self.chatted:
            self.msg("%s has already said their piece today." % name, GREY)
            return
        self.chatted.add(name)
        self.add_rel(name, 1)
        self.sfx("chat")
        f = self.feud_involving(name)
        if f:
            other = f["b"] if name == f["a"] else f["a"]
            line = "They only want to talk about %s. It is always %s's fault." % (other, other)
        elif self.rel[name] <= -40:
            line = "They glare at their shoes. The shoes are also glaring."
        else:
            line = random.choice(PERSONAS[PERSONA_OF[name]]["chat"])
        self.msg('%s: "%s"' % (name, line), (220, 210, 235))

    def gift_npc(self, name):
        if self.consume_potion("concord") is None:
            self.sfx("deny")
            self.msg("You need a Concord Draught to gift (brew it at the cauldron).", RED)
            return
        f = self.feud_involving(name)
        if f:
            other = f["b"] if name == f["a"] else f["a"]
            self.add_rel(name, 14)
            self.add_rel(other, 8)
            self.resolve_feud(f, via="gift")
        else:
            self.sfx("warm")
            amt = 22 if self.rel.get(name, 10) <= -40 else 12
            self.add_rel(name, amt)
            self.msg('%s: "%s" (+%d rel)' % (name,
                     random.choice(PERSONAS[PERSONA_OF[name]]["thanks"]).format(reward="a lovely draught"),
                     amt), GOLD)
        self.check_story()

    def social_morning(self):
        """Family gifts & enemy spite - the human weather report."""
        for name, v in self.rel.items():
            if v >= 60 and random.random() < 0.35:
                self.sfx("chime", 0.6)
                if random.random() < 0.5:
                    gift = "%dg and a hugged jar of something" % random.randint(8, 16)
                    self.earn_gold(10)
                else:
                    it = random.choice(list(INGREDIENTS.keys()))
                    gift = "%s x%d" % (INGREDIENTS[it]["name"], 2)
                    self.add_item(it, 2)
                self.msg(random.choice(GIFT_LINES).format(name=name, gift=gift), GOLD, 7)
            elif v <= -40 and random.random() < 0.4:
                self.msg(random.choice(SPITE_LINES).format(name=name), RED, 6)

    # ================================================== 7.7 story & chronicle
    def chron(self, s):
        self.chronicle.append({"day": self.day, "text": s})
        self.chronicle_sel = max(0, len(self.chronicle) - 1)

    def show_story(self, title, lines):
        self.story_view = {"title": title, "lines": lines}
        self.set_overlay("story")

    def open_chronicle(self):
        self.set_overlay("chronicle")
        self.chronicle_sel = max(0, len(self.chronicle) - 1)

    def check_story(self):
        while self.story_idx < len(STORY):
            ch = STORY[self.story_idx]
            if not ch["when"](self):
                break
            self.story_idx += 1
            self.sfx("mystery")
            self.show_story(ch["title"], ch["text"])
            self.chron("%s - %s" % (ch["title"],
                                    " ".join(l for l in ch["text"] if l)[:110] + "..."))
            if ch["title"].startswith("Chapter VII "):
                self.legend_unlocked = True

    # ================================================== 7.8 world generation
    def gen_road(self, a, b, wobble=90, step=12):
        """Waypoints + Chaikin smoothing -> curvy path point list."""
        pts = [a]
        for i in range(1, random.randint(2, 4) + 1):
            t = i / 4.0
            bx = a[0] + (b[0] - a[0]) * t
            by = a[1] + (b[1] - a[1]) * t
            L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
            px, py = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
            off = random.uniform(-wobble, wobble)
            pts.append((bx + px * off, by + py * off))
        pts.append(b)
        for _ in range(2):                       # chaikin corners
            out = [pts[0]]
            for i in range(len(pts) - 1):
                p, q = pts[i], pts[i + 1]
                out.append((p[0] * .75 + q[0] * .25, p[1] * .75 + q[1] * .25))
                out.append((p[0] * .25 + q[0] * .75, p[1] * .25 + q[1] * .75))
            out.append(pts[-1])
            pts = out
        res = [pts[0]]
        for p in pts[1:]:
            if math.hypot(p[0] - res[-1][0], p[1] - res[-1][1]) >= step:
                res.append(p)
        return res

    def make_road(self, a, b, wobble=90, w=ROAD_W):
        pts = self.gen_road(a, b, wobble)
        stones = []
        for i, p in enumerate(pts):
            if i % 5:
                continue
            if i + 1 < len(pts):
                dx, dy = pts[i + 1][0] - p[0], pts[i + 1][1] - p[1]
            else:
                dx, dy = 1, 0
            L = math.hypot(dx, dy) or 1
            sx, sy = -dy / L, dx / L
            side = random.choice([-1, 1])
            off = w / 2 + random.uniform(2, 6)
            stones.append((p[0] + sx * side * off, p[1] + sy * side * off,
                           random.uniform(1.5, 3)))
        return (pts, stones)

    def on_road(self, x, y):
        for pts, _ in (self.base_roads if self.loc == "base" else self.roads):
            for p in pts[::2]:
                if abs(p[0] - x) < ROAD_W and abs(p[1] - y) < ROAD_W and \
                   math.hypot(p[0] - x, p[1] - y) < ROAD_W / 2 + 5:
                    return True
        return False

    def terrain_at(self, x, y):
        for z in self.zones:
            dx = (x - z["x"]) / z["r"]
            dy = (y - z["y"]) / (z["r"] * 0.5)
            if dx * dx + dy * dy <= 1:
                return z
        return None

    def move_mult(self):
        if self.loc == "base":
            return 1.0
        m = 1.0
        if self.on_road(self.player.x, self.player.y):
            m *= 1.28
        z = self.terrain_at(self.player.x, self.player.y)
        if z:
            m *= TERRAIN_FX[z["kind"]]["mult"]
        if self.weather == "misty":
            m *= 0.92
        return min(m, 1.8)

    # ================================================== 7.9 gameplay systems
    # ---- orders ----
    def make_order(self):
        pool = ["healing", "mana", "fireward", "frostward", "luck"]
        if self.day >= 4:
            pool = list(POTIONS.keys())
        pid = weighted_choice([(p, 1.0) for p in pool] +
                              [(s, 0.6) for s in self.known_secrets])
        price = pot_def(pid)["price"]
        qty = random.choice([1, 1, 2]) if price >= 60 else random.choice([1, 2, 2, 3])
        mult = random.uniform(1.25, 1.6) * (1 + 0.04 * max(self.rep, 0))
        minq = 2 if (self.day >= 3 and random.random() < 0.28) else 1
        if minq == 2:
            mult *= 1.35
        if "market" in self.buildings:
            mult *= 1.3
        due = self.day + random.randint(3, 6)
        avail = [(n, p) for n, p in CUSTOMERS if not self.sulking(n)] or list(CUSTOMERS)
        who, _persona = random.choice(avail)
        r = self.rel.get(who, 10)
        mult *= 1.0 + max(0, r) / 300.0          # friends pay more
        rival_note = ""
        f = self.feud_involving(who)
        if f:                                     # feuding orders pay a tithe more
            mult *= 1.10
            other = f["b"] if who == f["a"] else f["a"]
            rival_note = " (P.S. %s is a scoundrel.)" % other
        if r <= -40:
            mult *= 0.75                          # personal feud discount
        per = PERSONAS[PERSONA_OF[who]]
        reason = random.choice(REASONS)
        line = random.choice(per["greet"]) + " " + \
            random.choice(per["ask"]).format(qty=qty, potion=pot_def(pid)["name"],
                                             reason=reason, due=due) + rival_note
        return {"pid": pid, "qty": qty, "reward": int(price * qty * mult),
                "due": due, "who": who, "minq": minq, "line": line}

    def refresh_board(self):
        self.board = [self.make_order() for _ in range(BOARD_SIZE)]

    def accept_order(self):
        if len(self.orders) >= MAX_CONTRACTS:
            self.sfx("deny")
            self.msg("You can only hold %d contracts at once." % MAX_CONTRACTS, RED); return
        o = self.board.pop(self.overlay_idx)
        self.orders.append(o)
        self.overlay_idx = min(self.overlay_idx, len(self.board) - 1) if self.board else 0
        self.sfx("accept")
        self.msg("Accepted: %dx %s for %s." % (o["qty"], pot_def(o["pid"])["name"], o["who"]), GOLD)

    def reject_order(self):
        if not self.board:
            return
        o = self.board.pop(self.overlay_idx)
        self.stats["rejects"] += 1
        self.add_rel(o["who"], -6)
        self.sfx("deny")
        self.msg('%s: "%s"' % (o["who"],
                 random.choice(PERSONAS[PERSONA_OF[o["who"]]]["reject"])), GREY)
        self.overlay_idx = min(self.overlay_idx, len(self.board) - 1) if self.board else 0

    def deliver_order(self):
        o = self.orders[self.overlay_idx]
        have = self.pot_count_ge(o["pid"], o["minq"])
        if have < o["qty"]:
            self.sfx("deny")
            need = "Standard+" if o["minq"] == 1 else "Fine or better"
            self.msg("You need %dx %s (%s). Brewed: %d." %
                     (o["qty"], pot_def(o["pid"])["name"], need, have), RED)
            return
        self.take_potions(o["pid"], o["minq"], o["qty"])
        self.earn_gold(o["reward"])
        self.stats["deliveries"] += 1
        self.rep += 1
        self.orders.pop(self.overlay_idx)
        self.overlay_idx = min(self.overlay_idx, len(self.orders) - 1) if self.orders else 0
        self.sfx("deliver")
        thanks = random.choice(PERSONAS[PERSONA_OF[o["who"]]]["thanks"]).format(reward=o["reward"])
        self.msg('%s: "%s"' % (o["who"], thanks), GOLD)
        self.chron('Delivered to %s: %dx %s for %dg. "%s"' %
                   (o["who"], o["qty"], pot_def(o["pid"])["name"], o["reward"], thanks))
        self.add_rel(o["who"], 7)
        f = self.feud_involving(o["who"])
        if f:                                     # feud fallout
            other = f["b"] if o["who"] == f["a"] else f["a"]
            if f["sided"] == o["who"]:
                self.add_rel(o["who"], 2)
            else:
                self.add_rel(other, -4 if f["sided"] == other else -2)
                self.msg(random.choice(GRUMBLE_LINES).format(other=other, name=o["who"]), GREY)
        self.add_float(self.player.x, self.player.y - 60, "+%dg" % o["reward"], GOLD)
        self.check_story()

    # ---- brewing ----
    def start_brew(self, pid):
        if pid in SECRET_POTIONS and pid not in self.known_secrets:
            if SECRET_POTIONS[pid].get("legendary") and self.legend_unlocked:
                self.known_secrets.append(pid)
            else:
                self.sfx("deny")
                self.msg("Sealed recipe - the story must unfold first (J).", RED); return
        rec = pot_def(pid)["recipe"]
        for ing, n in rec.items():
            if self.items.get(ing, 0) < n:
                self.sfx("deny")
                self.msg("Missing ingredients!", RED); return
        cat = self.catalyst if (self.catalyst != "none" and self.items.get(self.catalyst, 0) > 0) else "none"
        for ing, n in rec.items():
            self.items[ing] -= n
            if self.items[ing] <= 0:
                del self.items[ing]
        if cat != "none":
            self.items[cat] -= 1
            if self.items[cat] <= 0:
                del self.items[cat]
        self.catalyst = "none"
        self.brew = {"pid": pid, "phase": "heat", "t": 0.0, "score": 0, "stirs": 0,
                     "needle": 0.0, "ang": random.uniform(0, math.tau),
                     "target": random.uniform(0, math.tau), "cat": cat}
        self.sfx("pour")
        self.set_overlay("brew")

    def cancel_brew(self):
        b = self.brew
        if b:
            for ing, n in pot_def(b["pid"])["recipe"].items():
                self.add_item(ing, n)
            if b["cat"] != "none":
                self.add_item(b["cat"], 1)
        self.brew = None
        self.sfx("back")
        self.set_overlay("craft")
        self.msg("Brew cancelled - ingredients returned.", GREY)

    def update_brew(self, dt):
        b = self.brew
        if not b:
            return
        b["t"] += dt
        if b["phase"] == "heat":
            spd = 2.6 if (b["cat"] != "none" and CATALYSTS[b["cat"]]["effect"] == "calm") else 4.2
            if self.buffs.get("clarity", 0) > 0:
                spd *= 0.6
            if self.day_event and self.day_event.get("needle"):
                spd *= self.day_event["needle"]
            b["needle"] = (math.sin(b["t"] * spd) + 1) / 2
        else:
            b["ang"] = (b["ang"] + dt * (3.0 + 0.5 * b["stirs"])) % math.tau

    def lock_brew(self):
        b = self.brew
        if not b:
            return
        if b["phase"] == "heat":
            n = b["needle"]
            pts = 2 if 0.42 <= n <= 0.58 else 1 if 0.24 <= n <= 0.76 else 0
            if pts == 0 and b["cat"] != "none" and CATALYSTS[b["cat"]]["effect"] == "safe":
                pts = 1
            self.sfx("perfect" if pts == 2 else "good" if pts == 1 else "ruin")
            b["score"] += pts
            b["phase"] = "stir"
            b["target"] = random.uniform(0, math.tau)
        else:
            hit = ang_diff(b["ang"], b["target"]) <= math.radians(30)
            self.sfx("stir" if hit else "tick")
            if hit:
                b["score"] += 1
            b["stirs"] += 1
            if b["stirs"] >= 3:
                self.resolve_brew()
            else:
                b["target"] = random.uniform(0, math.tau)

    def resolve_brew(self):
        b = self.brew
        pid = b["pid"]
        pd = pot_def(pid)
        score = b["score"] + self.level_bonus()
        eff = CATALYSTS[b["cat"]]["effect"] if b["cat"] != "none" else None
        if eff == "quality":
            score += 1
        tier = quality_tier(score)
        amt = 1
        if "cauldron2" in self.buildings and random.random() < 0.35:
            amt += 1
        if eff == "yield":
            amt += 1
        self.add_potion(pid, tier, amt)
        xp = 8 + 4 * score + 5 * tier
        if eff == "xp":
            xp = int(xp * 1.5)
        if self.day_event and self.day_event.get("brewxp"):
            xp += self.day_event["brewxp"]
        self.add_xp(xp)
        self.sfx("brew%d" % tier)
        q = QUALITY[tier]
        self.msg("Brewed %dx %s [%s]! (+%d xp)" % (amt, pd["name"], q["name"], xp), q["color"])
        self.add_float(self.player.x, self.player.y - 60,
                       "+%d %s %s" % (amt, q["name"], pd["name"]), q["color"])
        if tier == 3:
            for i in range(3):
                self.add_float(self.player.x + random.randint(-40, 40),
                               self.player.y - 40 - random.randint(0, 30), "*", GOLD)
        self.brew = None
        self.set_overlay("craft")
        if pid == "valeblossom" and not self.finale:
            self.finale = True
            self.earn_gold(500)
            self.chron("BREWED THE VALEBLOSSOM ELIXIR. Every plant in the vale "
                       "flowered at once. Grandmother's letter was finally complete. (+500g)")
            self.show_story("Finale - The Vale Blooms", FINALE_TEXT)
        else:
            self.check_story()

    def quick_brew(self, pid):
        if pid in SECRET_POTIONS and pid not in self.known_secrets:
            self.sfx("deny")
            self.msg("Undiscovered recipe!", RED); return
        rec = pot_def(pid)["recipe"]
        for ing, n in rec.items():
            if self.items.get(ing, 0) < n:
                self.sfx("deny")
                self.msg("Missing ingredients!", RED); return
        for ing, n in rec.items():
            self.items[ing] -= n
            if self.items[ing] <= 0:
                del self.items[ing]
        self.add_potion(pid, 1, 1)
        self.add_xp(6)
        self.sfx("good")
        self.msg("Quick-brewed 1 %s [Standard]. (+6 xp)" % pot_def(pid)["name"], WHITE)
        self.add_float(self.player.x, self.player.y - 60,
                       "+1 Standard %s" % pot_def(pid)["name"], WHITE)

    def refine(self, pid):
        if pid in SECRET_POTIONS and pid not in self.known_secrets:
            return
        if "distillery" not in self.buildings:
            self.sfx("deny")
            self.msg("You need the Distillery to refine potions.", RED); return
        arr = self.potions.get(pid)
        if not arr or not any(arr):
            self.msg("Nothing of that potion to refine.", GREY); return
        t = next(i for i, v in enumerate(arr) if v > 0)
        if t >= 3:
            self.msg("Already Exquisite - perfection!", GOLD); return
        if self.items.get("bogmyrtle", 0) < 1:
            self.sfx("deny")
            self.msg("Refining needs 1 Bog Myrtle (Mistmarsh).", RED); return
        self.items["bogmyrtle"] -= 1
        if self.items["bogmyrtle"] <= 0:
            del self.items["bogmyrtle"]
        arr[t] -= 1
        arr[t + 1] += 1
        self.add_xp(6)
        self.sfx("refine")
        self.msg("Refined %s: %s -> %s!" % (pot_def(pid)["name"],
                 QUALITY[t]["name"], QUALITY[t + 1]["name"]), QUALITY[t + 1]["color"])

    def sale_mult(self):
        return self.day_event.get("sell", 1.0) if self.day_event else 1.0

    def sell_potion(self, pid):
        t = self.consume_potion(pid)
        if t is None:
            self.msg("None brewed to sell.", GREY); return
        g = int(pot_def(pid)["price"] * QUALITY[t]["mult"] * self.sale_mult())
        self.earn_gold(g)
        self.sfx("coin")
        self.msg("Sold 1 %s [%s] for %dg." % (pot_def(pid)["name"], QUALITY[t]["name"], g), GOLD)

    def sell_all(self, pid):
        total, n = 0, 0
        while True:
            t = self.consume_potion(pid)
            if t is None:
                break
            total += int(pot_def(pid)["price"] * QUALITY[t]["mult"] * self.sale_mult())
            n += 1
        if n:
            self.earn_gold(total)
            self.sfx("coinbig")
            self.msg("Sold %dx %s for %dg total." % (n, pot_def(pid)["name"], total), GOLD)
        else:
            self.msg("Nothing of that potion to sell.", GREY)

    def craft_action(self, k):
        cur = CRAFT_TABS[self.craft_tab][1]
        if not cur:
            return
        pid = cur[min(self.overlay_idx, len(cur) - 1)]
        if k == pygame.K_e:   self.start_brew(pid)
        elif k == pygame.K_q: self.quick_brew(pid)
        elif k == pygame.K_c: self.cycle_catalyst()
        elif k == pygame.K_x: self.open_experiment()
        elif k == pygame.K_r: self.refine(pid)
        elif k == pygame.K_v: self.sell_potion(pid)
        elif k == pygame.K_b: self.sell_all(pid)
        elif k == pygame.K_f: self.drink_potion(pid)

    def cycle_catalyst(self):
        owned = [c for c in CATALYSTS if self.items.get(c, 0) > 0]
        order = ["none"] + owned
        cur = self.catalyst if self.catalyst in order else "none"
        self.catalyst = order[(order.index(cur) + 1) % len(order)]
        name = CATALYSTS[self.catalyst]["name"] if self.catalyst != "none" else "none"
        self.sfx("move")
        self.msg("Catalyst set: %s." % name, PURPLE)

    # ---- experiments ----
    def open_experiment(self):
        self.set_overlay("exp")
        self.exp = {"sel": 0, "slots": [None, None],
                    "last": ("Combine any two ingredients... who knows what happens?", GREY)}

    def do_experiment(self):
        a, b = self.exp["slots"]
        if self.items.get(a, 0) < 1 or self.items.get(b, 0) < 1 or \
           (a == b and self.items.get(a, 0) < 2):
            self.exp["last"] = ("Not enough of those ingredients.", RED)
            return
        self.stats["experiments"] += 1
        for it in (a, b):
            self.items[it] -= 1
            if self.items[it] <= 0:
                del self.items[it]
        self.exp["slots"] = [None, None]
        self.add_xp(10)
        r = random.random()
        locked = [s for s in SECRET_POTIONS if s not in self.known_secrets and
                  not SECRET_POTIONS[s].get("legendary")]
        if locked and r < 0.18:
            disc = random.choice(locked)
            self.known_secrets.append(disc)
            self.sfx("sparkle")
            s = "DISCOVERY! You devised the recipe for %s! (+45 xp)" % SECRET_POTIONS[disc]["name"]
            self.exp["last"] = (s, GOLD)
            self.msg(s, GOLD)
            self.chron("Experimenting at the cauldron, Willow unlocked a secret: "
                       "the %s." % SECRET_POTIONS[disc]["name"])
            self.add_xp(45)
            self.check_story()
        elif r < 0.48:
            pid = random.choice(RECIPE_IDS[:len(POTIONS)] + self.known_secrets)
            self.add_potion(pid, 1, 1)
            self.sfx("good")
            self.exp["last"] = ("Success! The swirl settles into a Standard %s."
                                % pot_def(pid)["name"], GREEN)
        elif r < 0.60:
            back = random.choice([a, b])
            self.add_item(back, 1)
            self.sfx("gather")
            self.exp["last"] = ("The mixture separates... you recover 1 %s."
                                % INGREDIENTS[back]["name"], GREY)
        elif r < 0.66:
            self.player.hp = max(1, self.player.hp - 4)
            self.sfx("boom")
            self.exp["last"] = ("PFOOSH! A minor explosion singes your eyebrows. (-4 HP)", RED)
        else:
            g = random.randint(6, 14)
            self.earn_gold(g)
            self.sfx("coin")
            self.exp["last"] = ("Murky sludge... but a passing collector pays %dg for it." % g,
                                (200, 160, 120))

    # ---- building ----
    def build_request(self, key):
        b = BUILDINGS[key]
        if key in self.buildings:
            self.msg("Already built.", GREY); return
        if b["req"] and b["req"] not in self.buildings:
            self.sfx("deny")
            self.msg("Requires %s first." % BUILDINGS[b["req"]]["name"], RED); return
        if self.gold < b["cost"]:
            self.sfx("deny")
            self.msg("Not enough gold!", RED); return
        self.ask_confirm("Construct %s?" % b["name"],
                         ["Spend %dg on the %s?" % (b["cost"], b["name"]), "", b["desc"]],
                         lambda k=key: self.build(k))

    def build(self, key):
        b = BUILDINGS[key]
        if key in self.buildings or self.gold < b["cost"]:
            return
        if b["req"] and b["req"] not in self.buildings:
            return
        self.spend_gold(b["cost"])
        self.buildings.append(key)
        slot = BUILD_SLOTS[list(BUILDINGS.keys()).index(key)]
        self.stubs[key] = self.gen_road(slot, (512, 566), 34, step=10)
        self.sfx("build")
        self.msg("Built the %s! A path now connects it to the road." % b["name"], GOLD)
        self.chron("Willow raised the %s. The cottage grounds grow more like a village "
                   "every day." % b["name"])

    # ---- sleeping, events, rumors ----
    def roll_day_event(self):
        ev = weighted_choice([(e, e["w"]) for e in DAY_EVENTS])
        self.day_event = ev
        self.sfx("chime")
        self.msg("TODAY: %s - %s" % (ev["title"], ev["desc"]), (255, 200, 120), 8)
        self.chron("Day %d: %s. %s" % (self.day, ev["title"], ev["desc"]))
        if ev.get("gold"):
            self.earn_gold(ev["gold"])
        if ev.get("rep"):
            self.rep += ev["rep"]

    def roll_rumor(self):
        bid = random.choice(list(BIOMES.keys()))
        kind = random.choice(BIOME_LANDMARKS[bid])
        t = random.choice(RUMOR_TPL).format(
            landmark=LANDMARK_INFO[kind]["label"].lower(), biome=BIOMES[bid]["name"])
        self.active_rumor = {"biome": bid, "kind": kind, "text": t}
        self.sfx("mystery")
        self.msg("RUMOR: %s" % t, PURPLE, 8)
        self.chron("Rumor around the stove: %s" % t)

    def sleep(self):
        self.sfx("sleep")
        self.player.hp = self.player.max_hp if "cloudbed" in self.buildings else \
            max(self.player.hp, int(self.player.max_hp * 0.6))
        self.day += 1
        produced = []
        if "garden" in self.buildings:
            for _ in range(2):
                it = random.choice(["moonpetal", "nightshade", "starbloom",
                                    "cactusfruit", "frostfern", "bogmyrtle"])
                self.add_item(it); produced.append(it)
        if "greenhouse" in self.buildings:
            for _ in range(2):
                it = random.choice(["ghostmush", "goldenclover", "emberroot", "icecrystal"])
                self.add_item(it); produced.append(it)
        for o in self.orders[:]:                       # expired contracts
            if self.day > o["due"]:
                angry = random.choice(PERSONAS[PERSONA_OF[o["who"]]]["angry"]).format(name=o["who"])
                self.orders.remove(o)
                self.rep -= 1
                self.add_rel(o["who"], -10)
                self.msg(angry, RED)
                self.chron("Missed %s's deadline. %s (-1 rep)" % (o["who"], angry))
        for fav in self.favors[:]:                     # expired favors
            if self.day > fav["due"]:
                self.favors.remove(fav)
                self.add_rel(fav["who"], -8)
                self.msg("%s's favor went unfinished. They noticed. (-8 rel)" % fav["who"], RED)
                self.chron("Willow let %s's favor lapse." % fav["who"])
        for f in self.feuds:                           # feuds cool off
            if f["done"]:
                continue
            f["age"] += 1
            if f["age"] >= 4 or (f["sided"] is not None and f["age"] >= 6):
                self.resolve_feud(f, via="time")
        self.refresh_board()
        self.chatted = set()
        self.check_story()
        if self.overlay is None:                       # social decisions
            if not self.maybe_start_feud() and random.random() < 0.25:
                self.maybe_start_favor()
        self.social_morning()
        if random.random() < 0.75:
            self.roll_day_event()
        else:
            self.day_event = None
        if random.random() < 0.6:
            self.roll_rumor()
        if self.settings.get("autosave", True):
            self.save_game()
        self.sfx("morning")
        if produced:
            self.msg("Day %d. Your garden produced: %s."
                     % (self.day, ", ".join(INGREDIENTS[i]["name"] for i in produced)), GREEN)
        else:
            self.msg("Day %d. New orders wait on the board." % self.day, GOLD)
        self.add_float(self.player.x, self.player.y - 60, "Day %d" % self.day, GOLD)

    # ---- travel & biome generation ----
    def enter_biome(self, bid):
        b = BIOMES[bid]
        self.loc = bid
        self.overlay = None
        self.bolts, self.pickups, self.floats = [], [], []
        self.nodes, self.monsters, self.decor = [], [], []
        self.ambient = []
        p = self.player
        p.x, p.y, p.kx, p.ky = 512, 630, 0, 0
        p.iframes = 1.0
        first_visit = bid not in self.visited
        self.visited.add(bid)
        adjs, nouns = BIOME_FLAVOR[bid]
        self.variant = random.choice(adjs) + " " + random.choice(nouns)
        self.weather = weighted_choice([("clear", 5), ("breezy", 3), ("misty", 2)])
        # narrative entry line
        place = "%s - the %s" % (b["name"], self.variant)
        line = random.choice(ENTRY_OPEN).format(place=place) + " " + \
               random.choice(ENTRY_MID).format(scent=random.choice(b["scents"])) + " " + \
               random.choice(ENTRY_TAIL)
        if first_visit:
            line += "  (First visit! The vale takes note.)"
            self.chron("First steps into the %s. %s" % (b["name"], line))
        self.sfx("portal")
        self.msg(line, (200, 230, 255), 7)
        # roads
        self.roads = [self.make_road((512, 700),
                                     (random.randint(200, 820), random.randint(130, 190)), 140)]
        if random.random() < 0.55:
            mid = self.roads[0][0][len(self.roads[0][0]) // 2]
            side = random.choice([(90, mid[1] + random.randint(-60, 60)),
                                  (SCREEN_W - 90, mid[1] + random.randint(-60, 60))])
            self.roads.append(self.make_road(mid, side, 90))
        self._gen_zones(b)
        self._gen_landmarks(bid)
        self._gen_plants(b, p)
        for _ in range(18):
            self.decor.append((random.choice(b["decor"]),
                               random.uniform(50, SCREEN_W - 50),
                               random.uniform(95, SCREEN_H - 45)))
        self._gen_monsters(b, p)
        self.spawn_timer = random.uniform(8, 12)
        self.msg("(%s)" % {"clear": "clear skies", "breezy": "a stiff breeze",
                           "misty": "rolling mist"}[self.weather], GREY, 4)

    def _free_zone_spot(self, r):
        for _try in range(40):
            x = random.uniform(r + 40, SCREEN_W - r - 40)
            y = random.uniform(r + 80, SCREEN_H - r - 50)
            if math.hypot(x - 512, y - 700) < r + 110:
                continue
            if any(math.hypot(x - q[0], y - q[1]) < r + ROAD_W + 8
                   for road, _ in self.roads for q in road[::4]):
                continue
            if any(math.hypot(x - z["x"], y - z["y"]) < r + z["r"] for z in self.zones):
                continue
            return x, y
        return None

    def _gen_zones(self, b):
        self.zones = []
        for _ in range(random.randint(4, 6)):
            kind = weighted_choice(b["terrain"])
            r = random.uniform(45, 90)
            spot = self._free_zone_spot(r)
            if not spot:
                continue
            x, y = spot
            z = {"kind": kind, "x": x, "y": y, "r": r, "t": random.uniform(0, 9)}
            if kind == "quicksand":
                z["dots"] = [(random.uniform(-r * .7, r * .7), random.uniform(-r * .35, r * .35))
                             for _ in range(14)]
            elif kind == "ice":
                z["cracks"] = [(random.uniform(-r * .6, r * .6), random.uniform(-r * .3, r * .3),
                                random.uniform(-r * .5, r * .5), random.uniform(-r * .25, r * .25))
                               for _ in range(4)]
            elif kind == "flowerfield":
                z["fl"] = [(random.uniform(-r * .8, r * .8), random.uniform(-r * .4, r * .4),
                            random.choice([(255, 120, 150), (255, 220, 120),
                                           (240, 240, 255), (180, 140, 240)]))
                           for _ in range(16)]
            self.zones.append(z)

    def _gen_landmarks(self, bid):
        self.landmarks = []
        pool = BIOME_LANDMARKS[bid][:]
        rumored = self.active_rumor and self.active_rumor["biome"] == bid
        if rumored:                                     # rumor guarantees the find
            kind = self.active_rumor["kind"]
            if kind in pool:
                pool.remove(kind)
            pool.insert(0, kind)
        random.shuffle(pool)
        for kind in pool[:random.randint(1, 2) + (1 if rumored else 0)]:
            for _try in range(60):
                x = random.uniform(90, SCREEN_W - 90)
                y = random.uniform(130, SCREEN_H - 110)
                if math.hypot(x - 512, y - 700) < 150:
                    continue
                if any(math.hypot(x - q[0], y - q[1]) < ROAD_W + 34
                       for road, _ in self.roads for q in road[::4]):
                    continue
                if any(math.hypot(x - z["x"], y - z["y"]) < z["r"] + 40 for z in self.zones):
                    continue
                self.landmarks.append({"kind": kind, "x": x, "y": y, "used": False,
                                       "t": random.uniform(0, 9)})
                break
        if rumored:
            self.msg("The rumor led true - somewhere here lies a %s!"
                     % LANDMARK_INFO[self.active_rumor["kind"]]["label"], GOLD, 7)

    def _gen_plants(self, b, p):
        self.patches = [(random.uniform(60, SCREEN_W - 60), random.uniform(100, SCREEN_H - 60),
                         random.uniform(35, 85)) for _ in range(8)]
        tries = 0
        while len(self.nodes) < 11 and tries < 500:
            tries += 1
            if random.random() < 0.6 and self.roads:    # cluster near roads
                q = random.choice(random.choice(self.roads)[0])
                x, y = q[0] + random.uniform(-70, 70), q[1] + random.uniform(-70, 70)
            else:
                x, y = random.uniform(70, SCREEN_W - 70), random.uniform(120, SCREEN_H - 90)
            x, y = clamp(x, 70, SCREEN_W - 70), clamp(y, 120, SCREEN_H - 90)
            if math.hypot(x - 512, y - 700) < 130: continue
            if math.hypot(x - p.x, y - p.y) < 80: continue
            if any(math.hypot(x - l["x"], y - l["y"]) < 60 for l in self.landmarks): continue
            if any(math.hypot(x - n.x, y - n.y) < 55 for n in self.nodes): continue
            self.nodes.append(Node(x, y, weighted_choice(b["plants"])))

    def _gen_monsters(self, b, p):
        ds = 1 + (self.day - 1) * 0.03
        scale = (0.75 if "watchtower" in self.buildings else 1.0) * ds
        count = 2 + b["danger"] + (self.day_event.get("spawn", 0) if self.day_event else 0)
        for _ in range(count):
            for _try in range(50):
                x = random.uniform(60, SCREEN_W - 60)
                y = random.uniform(110, SCREEN_H - 60)
                if math.hypot(x - p.x, y - p.y) < 280:
                    continue
                self.monsters.append(Monster(random.choice(b["monsters"]), x, y,
                                             scale, scale,
                                             SLIME_TINTS.get(self.loc, (110, 240, 150))))
                break

    def go_home(self):
        self.loc = "base"
        self.overlay = None
        self.player.x, self.player.y = 512, 520
        self.player.iframes = 1.0
        self.bolts, self.pickups, self.monsters = [], [], []
        self.nodes, self.decor, self.patches = [], [], []
        self.zones, self.landmarks, self.roads, self.ambient = [], [], [], []
        self.floats = []
        self.sfx("portalback")
        self.msg("You return to your cottage.", (180, 220, 255))

    def on_player_down(self):
        lost = int(self.gold * 0.25)
        self.spend_gold(lost)
        self.player.hp = int(self.player.max_hp * 0.6)
        self.player.iframes = 2.0
        self.buffs.clear()
        self.sfx("down")
        self.msg("You black out... a villager carries you home. Lost %dg!" % lost, RED)
        self.chron("The wilds claimed Willow for a night. A villager carried her home; "
                   "%dg went to the healer." % lost)
        self.go_home()

    def spawn_monster(self, hp_s=1.0, dmg_s=1.0):
        b = BIOMES[self.loc]
        if len(self.monsters) >= 3 + b["danger"] * 2:
            return
        for _ in range(50):
            side = random.choice(["top", "bottom", "left", "right"])
            if side == "top":      x, y = random.uniform(50, SCREEN_W - 50), 95
            elif side == "bottom": x, y = random.uniform(50, SCREEN_W - 50), SCREEN_H - 45
            elif side == "left":   x, y = 45, random.uniform(110, SCREEN_H - 45)
            else:                  x, y = SCREEN_W - 45, random.uniform(110, SCREEN_H - 45)
            if math.hypot(x - self.player.x, y - self.player.y) < 220:
                continue
            self.monsters.append(Monster(random.choice(b["monsters"]), x, y, hp_s, dmg_s,
                                         SLIME_TINTS.get(self.loc, (110, 240, 150))))
            return

    def kill_monster(self, m):
        cnt = self.kills.get(m.mid, 0) + 1
        self.kills[m.mid] = cnt
        d = MONSTERS[m.mid]
        lvl = mastery_level(cnt)
        dm = self.day_event.get("drop", 1.0) if self.day_event else 1.0
        self.sfx("die")
        if d.get("guarantee"):                       # mastery adds +1 per level
            for _ in range(1 + lvl):
                self.pickups.append(Pickup(m.x + random.uniform(-16, 16),
                                           m.y - 10 + random.uniform(-10, 6), d["guarantee"]))
        for item, ch in d.get("drops", []):
            if random.random() < ch * dm:
                self.pickups.append(Pickup(m.x + random.uniform(-14, 14), m.y - 10, item))
        if d.get("rare") and random.random() < d["rare"][1] * dm:
            self.pickups.append(Pickup(m.x, m.y - 14, d["rare"][0], rare=True))
            self.sfx("rare")
            self.add_float(m.x, m.y - 44, "RARE DROP!", GOLD)
        if cnt in (5, 15, 30) and d.get("guarantee"):
            self.sfx("lvl", 0.7)
            self.msg("%s mastery Lv%d! Now drops +%d %s per kill."
                     % (d["name"], lvl, lvl, INGREDIENTS[d["guarantee"]]["name"]), GOLD)
        if m.mid not in self.first_kills:
            self.first_kills.add(m.mid)
            self.msg(FIRSTKILL[m.mid], (255, 210, 130), 7)
            self.chron("First %s felled. %s" % (d["name"], FIRSTKILL[m.mid]))
        self.add_float(m.x, m.y - 20, "%s defeated!" % d["name"], (255, 210, 130))
        for fav in self.favors[:]:                   # hunt favors auto-track
            if fav["kind"] == "hunt" and fav["target"] == m.mid:
                fav["have"] += 1
                self.msg("Favor for %s: %d/%d %s." %
                         (fav["who"], fav["have"], fav["need"], MONSTERS[m.mid]["name"]),
                         (230, 210, 160), 3)
                if fav["have"] >= fav["need"]:
                    self.complete_favor(fav)
        self.check_story()

    # ---- landmarks ----
    def touch_landmark(self, l):
        l["used"] = True
        self.stats["landmarks"] += 1
        k = l["kind"]
        name = LANDMARK_INFO[k]["label"]
        self.add_xp(6)
        self.sfx("mystery")
        if self.active_rumor and self.active_rumor["biome"] == self.loc and \
           self.active_rumor["kind"] == k:
            self.sfx("chime")
            self.msg("The rumor was true! Word of your find will reach the village.", GOLD)
            self.chron("The rumor proved true: a %s in the %s."
                       % (name, BIOMES[self.loc]["name"]))
            self.active_rumor = None
            self.rep += 1
        if k == "leystone":
            mats = [i for i, d in INGREDIENTS.items() if d.get("monster")]
            got = random.sample(mats, 2)
            for g in got:
                self.add_item(g, 2)
            self.msg("%s hums - parts coalesce! +2 %s, +2 %s."
                     % (name, INGREDIENTS[got[0]]["name"], INGREDIENTS[got[1]]["name"]), PURPLE)
            self.add_float(l["x"], l["y"] - 50, "+4 materials", PURPLE)
        elif k == "shrine":
            self.player.hp = min(self.player.max_hp, self.player.hp + 40)
            self.set_buff("lucky", 60)
            self.msg("%s blesses you! +40 HP, Lucky for 60s." % name, GOLD)
            self.add_float(l["x"], l["y"] - 50, "BLESSED!", GOLD)
        elif k == "cache":
            g = random.randint(15, 35)
            self.earn_gold(g)
            self.msg("%s unearthed: %dg!" % (name, g), GOLD)
            self.add_float(l["x"], l["y"] - 50, "+%dg" % g, GOLD)
        elif k == "spring":
            self.player.hp = self.player.max_hp
            self.msg("%s soothes every ache. Fully healed!" % name, GREEN)
            self.add_float(l["x"], l["y"] - 50, "FULL HP", GREEN)
        elif k == "crystal":
            it = BIOMES[self.loc]["rare"]
            self.add_item(it, 2)
            self.msg("%s shatters gently: +2 %s." % (name, INGREDIENTS[it]["name"]),
                     INGREDIENTS[it]["color"])
            self.add_float(l["x"], l["y"] - 50, "+2 %s" % INGREDIENTS[it]["name"],
                           INGREDIENTS[it]["color"])
        elif k == "ruin":
            got = [weighted_choice(BIOMES[self.loc]["plants"]) for _ in range(3)]
            for g in got:
                self.add_item(g, 1)
            self.msg("%s searched: found %s." %
                     (name, ", ".join(INGREDIENTS[g]["name"] for g in got)), (230, 210, 160))
            self.add_float(l["x"], l["y"] - 50, "+3 plants", (230, 210, 160))
        elif k == "well":
            self.player.hp = min(self.player.max_hp, self.player.hp + 25)
            self.earn_gold(12)
            self.msg("%s: cool water (+25 HP) and a dropped coin pouch (+12g)!" % name, GOLD)
            self.add_float(l["x"], l["y"] - 50, "+25 HP +12g", GOLD)
        self.msg(random.choice(LANDMARK_INFO[k]["flavor"]), (190, 175, 215), 6)

    # ---- interaction ----
    def interact(self):
        if self.loc == "base":
            for s in BASE_SPOTS:
                if math.hypot(self.player.x - s["x"], self.player.y - s["y"]) < s["r"]:
                    if s["act"] == "door":
                        self.sleep()
                    else:
                        self.set_overlay(s["act"])
                        self.order_tab = 0
                    return
            self.msg("Nothing to interact with here.", GREY)
        else:
            cand = [nd for nd in self.nodes if nd.ready and
                    math.hypot(self.player.x - nd.x, self.player.y - nd.y) < 46]
            if cand:
                nd = min(cand, key=lambda n: math.hypot(self.player.x - n.x, self.player.y - n.y))
                n = 1
                if random.random() < 0.3: n += 1
                if self.buffs.get("lucky", 0) > 0: n += 1
                if self.day_event and self.day_event.get("gather"): n += self.day_event["gather"]
                self.add_item(nd.item, n)
                self.sfx("gather")
                self.add_float(nd.x, nd.y - 26, "+%d %s" % (n, INGREDIENTS[nd.item]["name"]),
                               INGREDIENTS[nd.item]["color"])
                nd.ready = False
                nd.timer = 18
                return
            for l in self.landmarks:
                if not l["used"] and math.hypot(self.player.x - l["x"], self.player.y - l["y"]) < 46:
                    self.touch_landmark(l); return
            if math.hypot(self.player.x - 512, self.player.y - 700) < 60:
                self.go_home(); return
            self.msg("Nothing nearby. Try the glowing plants or landmarks!", GREY)

    # ================================================== 7.10 input handling
    def overlay_len(self):
        if self.overlay == "craft":    return len(CRAFT_TABS[self.craft_tab][1])
        if self.overlay == "build":    return len(BUILDINGS)
        if self.overlay == "travel":   return len(BIOMES)
        if self.overlay == "bestiary": return len(MONSTERS)
        if self.overlay == "orders":
            if self.order_tab == 0:   return max(1, len(self.board))
            if self.order_tab == 1:   return max(1, len(self.orders) + len(self.favors))
            return len(CUSTOMERS)
        return 1

    def overlay_confirm(self):
        if self.overlay == "craft":
            cur = CRAFT_TABS[self.craft_tab][1]
            if cur:
                self.start_brew(cur[min(self.overlay_idx, len(cur) - 1)])
        elif self.overlay == "build":
            keys = list(BUILDINGS.keys())
            self.build_request(keys[min(self.overlay_idx, len(keys) - 1)])
        elif self.overlay == "travel":
            self.enter_biome(list(BIOMES.keys())[self.overlay_idx])
        elif self.overlay == "orders":
            if self.order_tab == 0:
                if self.board: self.accept_order()
            elif self.order_tab == 1:
                if self.overlay_idx < len(self.orders):
                    if self.orders: self.deliver_order()
                elif self.favors:
                    self.deliver_favor(self.favors[self.overlay_idx - len(self.orders)])
            else:
                names = self.villager_list()
                if names and self.overlay_idx < len(names):
                    self.chat_npc(names[self.overlay_idx])
        self.overlay_idx = min(self.overlay_idx, self.overlay_len() - 1)

    def orders_action(self, k):
        if self.order_tab == 0:
            if k == pygame.K_e and self.board:
                self.accept_order()
            elif k == pygame.K_r:
                self.reject_order()
        elif self.order_tab == 1:
            if k == pygame.K_e:
                self.overlay_confirm()
        else:
            names = self.villager_list()
            if not names:
                return
            name = names[min(self.overlay_idx, len(names) - 1)]
            if k == pygame.K_e:
                self.chat_npc(name)
            elif k == pygame.K_g:
                self.gift_npc(name)

    def handle_event(self, e):
        if e.type == pygame.QUIT:
            pygame.quit(); sys.exit()
        if e.type == pygame.MOUSEWHEEL:
            self._on_wheel(e); return
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self.handle_click(e.pos); return
        if e.type != pygame.KEYDOWN:
            return
        k = e.key
        if self.state == "menu":
            self._key_title(k); return
        # one small handler per screen
        if self.overlay == "brew":       self._key_brew(k)
        elif self.overlay == "pause":    self._key_pause(k)
        elif self.overlay == "confirm":  self._key_confirm(k)
        elif self.overlay == "decision": self._key_decision(k)
        elif self.overlay == "story":    self._key_story(k)
        elif self.overlay == "chronicle":self._key_chronicle(k)
        elif self.overlay == "exp":      self._key_exp(k)
        elif self.overlay == "inv":      self._key_inv(k)
        elif self.overlay == "stats":    self._key_stats(k)
        elif self.overlay in ("controls", "options"): self._key_options(k)
        elif self.overlay:               self._key_menu(k)
        else:                            self._key_world(k)

    def _on_wheel(self, e):
        if self.state != "play":
            return
        if self.overlay == "chronicle" and self.chronicle:
            self.chronicle_sel = clamp(self.chronicle_sel - e.y, 0, len(self.chronicle) - 1)
            self.sfx("tick")
        elif self.overlay == "inv":
            self.inv_scroll = max(0, self.inv_scroll - e.y)
        elif self.overlay in ("craft", "orders", "build", "travel", "bestiary") \
                and self.overlay_len() > 1:
            self.overlay_idx = (self.overlay_idx - e.y) % self.overlay_len()
            self.sfx("move")

    def _key_title(self, k):
        if self.overlay == "controls":
            self.overlay = None
        elif k in (pygame.K_RETURN, pygame.K_SPACE):
            self.sfx("select")
            self._restart = True
        elif k == pygame.K_c:
            self.try_continue()
        elif k == pygame.K_h:
            self.sfx("open")
            self._menu_back = None
            self.set_overlay("controls")

    def _key_brew(self, k):
        if k == pygame.K_ESCAPE:
            self.cancel_brew()
        elif k in (pygame.K_SPACE, pygame.K_e, pygame.K_RETURN):
            self.lock_brew()

    def _key_pause(self, k):
        if k in (pygame.K_UP, pygame.K_w):
            self.pause_sel = (self.pause_sel - 1) % len(PAUSE_ITEMS)
            self.sfx("move")
        elif k in (pygame.K_DOWN, pygame.K_s):
            self.pause_sel = (self.pause_sel + 1) % len(PAUSE_ITEMS)
            self.sfx("move")
        elif k in (pygame.K_e, pygame.K_RETURN):
            self.sfx("select")
            self.pause_action(PAUSE_ITEMS[self.pause_sel][1])
        elif k in (pygame.K_ESCAPE, pygame.K_p):
            self.sfx("back")
            self.overlay = None

    def _key_confirm(self, k):
        c = self.confirm
        if k in (pygame.K_UP, pygame.K_w, pygame.K_LEFT, pygame.K_a):
            c["sel"] = (c["sel"] - 1) % 2
            self.sfx("move")
        elif k in (pygame.K_DOWN, pygame.K_s, pygame.K_RIGHT, pygame.K_d):
            c["sel"] = (c["sel"] + 1) % 2
            self.sfx("move")
        elif k in (pygame.K_e, pygame.K_RETURN):
            self._confirm_pick(c["sel"])
        elif k == pygame.K_ESCAPE:
            self.sfx("back")
            self.confirm = None
            self.overlay = None

    def _key_decision(self, k):
        d = self.decision
        if k in (pygame.K_UP, pygame.K_w):
            d["sel"] = (d["sel"] - 1) % len(d["options"])
            self.sfx("move")
        elif k in (pygame.K_DOWN, pygame.K_s):
            d["sel"] = (d["sel"] + 1) % len(d["options"])
            self.sfx("move")
        elif k in (pygame.K_e, pygame.K_RETURN):
            _, cb = d["options"][d["sel"]]
            self._decision_pick(d["sel"], cb)
        elif k == pygame.K_ESCAPE:
            self.sfx("back")
            self.decision = None
            self.overlay = None
            self.msg("You slip away without answering.", GREY)

    def _key_story(self, k):
        if k in (pygame.K_ESCAPE, pygame.K_e, pygame.K_RETURN, pygame.K_SPACE):
            self.sfx("select")
            self.overlay = None

    def _key_chronicle(self, k):
        if k in (pygame.K_ESCAPE, pygame.K_j):
            self.sfx("back")
            self.overlay = None
        elif k in (pygame.K_UP, pygame.K_w):
            self.chronicle_sel = max(0, self.chronicle_sel - 1)
            self.sfx("tick")
        elif k in (pygame.K_DOWN, pygame.K_s):
            self.chronicle_sel = min(len(self.chronicle) - 1, self.chronicle_sel + 1)
            self.sfx("tick")

    def _key_exp(self, k):
        its = sorted(self.items, key=lambda n: INGREDIENTS[n]["name"])
        if k in (pygame.K_ESCAPE, pygame.K_x):
            self.sfx("back")
            self.overlay = "craft"
            self.menu_open_t = self.time
        elif k in (pygame.K_UP, pygame.K_w) and its:
            self.exp["sel"] = (self.exp["sel"] - 1) % len(its)
            self.sfx("move")
        elif k in (pygame.K_DOWN, pygame.K_s) and its:
            self.exp["sel"] = (self.exp["sel"] + 1) % len(its)
            self.sfx("move")
        elif k == pygame.K_c:
            self.sfx("back")
            self.exp["slots"] = [None, None]
        elif k in (pygame.K_e, pygame.K_RETURN) and its:
            it = its[min(self.exp["sel"], len(its) - 1)]
            slots = self.exp["slots"]
            if slots[0] is not None and slots[1] is not None:
                self.do_experiment()
            else:
                need = 2 if it in slots else 1
                if self.items.get(it, 0) < need:
                    self.exp["last"] = ("Not enough %s (need %d)."
                                        % (INGREDIENTS[it]["name"], need), RED)
                else:
                    self.sfx("select")
                    slots[0 if slots[0] is None else 1] = it

    def _key_inv(self, k):
        plist = list(self.potions)
        if k in (pygame.K_ESCAPE, pygame.K_i):
            self.sfx("back")
            self.overlay = None
        elif k in (pygame.K_UP, pygame.K_w) and plist:
            self.inv_sel = (self.inv_sel - 1) % len(plist)
            self.sfx("move")
        elif k in (pygame.K_DOWN, pygame.K_s) and plist:
            self.inv_sel = (self.inv_sel + 1) % len(plist)
            self.sfx("move")
        elif k == pygame.K_s:
            self.cycle_inv_sort()
        elif k in (pygame.K_e, pygame.K_RETURN) and plist:
            self.drink_potion(plist[min(self.inv_sel, len(plist) - 1)])

    def _key_stats(self, k):
        if k in (pygame.K_TAB, pygame.K_ESCAPE, pygame.K_e, pygame.K_RETURN):
            self.sfx("back")
            self.overlay = None

    def _key_options(self, k):
        if k in (pygame.K_ESCAPE, pygame.K_e, pygame.K_RETURN):
            self.sfx("back")
            self.overlay = self._menu_back
            self.menu_open_t = self.time
        elif self.overlay == "options" and k in (pygame.K_UP, pygame.K_w):
            self.overlay_idx = (self.overlay_idx - 1) % len(SETTING_ITEMS)
            self.sfx("move")
        elif self.overlay == "options" and k in (pygame.K_DOWN, pygame.K_s):
            self.overlay_idx = (self.overlay_idx + 1) % len(SETTING_ITEMS)
            self.sfx("move")
        elif self.overlay == "options" and k == pygame.K_SPACE:
            self._options_toggle(self.overlay_idx)
        elif self.overlay == "options" and k in (pygame.K_LEFT, pygame.K_RIGHT):
            key, _, kind = SETTING_ITEMS[self.overlay_idx]
            if kind == "vol":
                step = 25 if k == pygame.K_RIGHT else -25
                self.settings[key] = clamp(self.settings.get(key, 65) + step, 0, 100)
                self.sfx("tick")

    def _options_toggle(self, i):
        key, _, kind = SETTING_ITEMS[i]
        if kind == "bool":
            self.toggle_setting(key)
        else:
            self.settings[key] = (self.settings.get(key, 65) + 25) % 125
        self.sfx("tick")

    def _key_menu(self, k):
        """Generic in-overlay keys (craft / orders / build / travel / bestiary)."""
        if k in (pygame.K_ESCAPE, pygame.K_i):
            self.sfx("back")
            self.overlay = None; return
        if self.overlay == "bestiary" and k == pygame.K_b:
            self.sfx("back")
            self.overlay = None; return
        if k in (pygame.K_UP, pygame.K_w):
            self.overlay_idx = (self.overlay_idx - 1) % self.overlay_len()
            self.sfx("move"); return
        if k in (pygame.K_DOWN, pygame.K_s):
            self.overlay_idx = (self.overlay_idx + 1) % self.overlay_len()
            self.sfx("move"); return
        if self.overlay == "orders" and k in (pygame.K_LEFT, pygame.K_a):
            self.order_tab = (self.order_tab - 1) % 3
            self.overlay_idx = 0
            self.sfx("move"); return
        if self.overlay == "orders" and k in (pygame.K_RIGHT, pygame.K_d):
            self.order_tab = (self.order_tab + 1) % 3
            self.overlay_idx = 0
            self.sfx("move"); return
        if self.overlay == "orders" and k in (pygame.K_e, pygame.K_r, pygame.K_g):
            self.orders_action(k); return
        if self.overlay == "craft" and k in (pygame.K_LEFT, pygame.K_a):
            self.craft_tab = (self.craft_tab - 1) % 3
            self.overlay_idx = min(self.overlay_idx, self.overlay_len() - 1)
            self.sfx("move"); return
        if self.overlay == "craft" and k in (pygame.K_RIGHT, pygame.K_d):
            self.craft_tab = (self.craft_tab + 1) % 3
            self.overlay_idx = min(self.overlay_idx, self.overlay_len() - 1)
            self.sfx("move"); return
        if self.overlay == "craft" and k in CRAFT_KEYS:
            self.craft_action(k); return
        if self.overlay in ("build", "travel", "bestiary") and k in (pygame.K_e, pygame.K_RETURN):
            self.overlay_confirm(); return
        if k == pygame.K_RETURN:
            self.overlay_confirm()

    def _key_world(self, k):
        """Keys with no overlay open (world / HUD)."""
        if k == pygame.K_p or (k == pygame.K_ESCAPE and self.loc == "base"):
            self.sfx("open")
            self.pause_sel = 0
            self.set_overlay("pause")
        elif k == pygame.K_TAB:
            self.sfx("open")
            self.set_overlay("stats")
        elif k == pygame.K_m:
            self.minimap_big = not self.minimap_big
            self.sfx("tick")
        elif k == pygame.K_t:
            self.tracker_on = not self.tracker_on
            self.sfx("tick")
            self.msg("Tracker %s." % ("on" if self.tracker_on else "off"), GREY, 2)
        elif k in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
            slots = self.quick_slots()
            i = k - pygame.K_1
            if i < len(slots):
                self.drink_potion(slots[i])
            else:
                self.msg("Empty slot.", GREY, 1.5)
        elif k == pygame.K_i:
            self.sfx("open")
            self.set_overlay("inv")
        elif k == pygame.K_b:
            self.sfx("open")
            self.set_overlay("bestiary")
        elif k == pygame.K_j:
            self.sfx("open")
            self.open_chronicle()
        elif k == pygame.K_e:
            self.interact()
        elif k == pygame.K_h:
            self.drink_potion("healing")
        elif k == pygame.K_ESCAPE and self.loc != "base":
            self.go_home()

    # ================================================== 7.11 update loop
    def update(self, dt):
        self.time += dt
        self.update_music()
        if self.save_flash > 0:
            self.save_flash -= dt
        self.floats = [f for f in self.floats if f.update(dt)]
        for m in self.messages[:]:
            m["ttl"] -= dt
            if m["ttl"] <= 0:
                self.messages.remove(m)
        for pop in self.hud_pops[:]:
            pop["ttl"] -= dt
            pop["y"] += 30 * dt
            if pop["ttl"] <= 0:
                self.hud_pops.remove(pop)
        if self.hp_ghost < self.player.hp:
            self.hp_ghost = self.player.hp
        else:
            self.hp_ghost = max(self.player.hp, self.hp_ghost - 40 * dt)
        if self.state != "play":
            return
        # low-health heartbeat
        frac = self.player.hp / self.player.max_hp
        self._heart_t -= dt
        if frac < 0.3 and self._heart_t <= 0:
            self.sfx("heart")
            self._heart_t = max(0.55, frac * 2.4)
        for b in list(self.buffs):
            self.buffs[b] -= dt
            if self.buffs[b] <= 0:
                del self.buffs[b]
                self.msg("%s wore off." % BUFFS[b][0], GREY, 2.5)
        if self.overlay == "brew":
            self.update_brew(dt); return
        if self.overlay:
            return
        keys = pygame.key.get_pressed()
        self.player.update(dt, keys, self)
        p = self.player
        if self._lpx is None:
            self._lpx, self._lpy = p.x, p.y
        else:
            self.stats["distance"] += math.hypot(p.x - self._lpx, p.y - self._lpy)
            self._lpx, self._lpy = p.x, p.y
        if self.loc != "base":
            self.update_biome(dt, keys)

    def update_ambient(self, dt):
        if not self.settings.get("particles", True):
            self.ambient = []
            return
        kind = BIOMES[self.loc]["ambient"]
        target = 55 if self.weather == "breezy" else 30
        if len(self.ambient) < target and random.random() < 0.6:
            if kind in ("leaf", "petal", "snow"):
                self.ambient.append({"k": kind, "x": random.uniform(0, SCREEN_W),
                                     "y": random.uniform(40, 90), "ph": random.uniform(0, 6),
                                     "c": random.choice([(110, 190, 90), (220, 150, 70)])
                                     if kind == "leaf" else (255, 170, 200)})
            elif kind == "sand":
                self.ambient.append({"k": "sand", "x": -12,
                                     "y": random.uniform(80, SCREEN_H - 40),
                                     "v": random.uniform(180, 300)})
            else:
                self.ambient.append({"k": "firefly", "x": random.uniform(40, SCREEN_W - 40),
                                     "y": random.uniform(90, SCREEN_H - 50),
                                     "a": random.uniform(0, 6.28),
                                     "life": random.uniform(4, 8)})
        wind = 60 if self.weather == "breezy" else 15
        keep = []
        for p in self.ambient:
            p["ph"] = p.get("ph", 0) + dt
            k = p["k"]
            if k in ("leaf", "petal"):
                p["x"] += math.sin(p["ph"] * 2) * 20 * dt + wind * 0.4 * dt
                p["y"] += (28 if k == "leaf" else 22) * dt
                if p["y"] < SCREEN_H + 10 and p["x"] < SCREEN_W + 10:
                    keep.append(p)
            elif k == "snow":
                p["x"] += math.sin(p["ph"]) * 12 * dt + wind * 0.2 * dt
                p["y"] += 38 * dt
                if p["y"] < SCREEN_H + 6:
                    keep.append(p)
            elif k == "sand":
                p["x"] += p["v"] * dt
                if p["x"] < SCREEN_W + 14:
                    keep.append(p)
            else:                                    # firefly
                p["a"] += random.uniform(-2, 2) * dt * 3
                p["x"] = clamp(p["x"] + math.cos(p["a"]) * 26 * dt, 20, SCREEN_W - 20)
                p["y"] = clamp(p["y"] + math.sin(p["a"]) * 26 * dt, 80, SCREEN_H - 40)
                p["life"] -= dt
                if p["life"] > 0:
                    keep.append(p)
        self.ambient = keep

    def update_biome(self, dt, keys):
        p = self.player
        if keys[pygame.K_SPACE] and p.cool <= 0:     # homing magic bolt
            p.cool = 0.3
            dmg = (16 if "focus" in self.buildings else 10) + \
                  (8 if self.buffs.get("fury", 0) > 0 else 0)
            tx, ty = p.dir_x, p.dir_y
            best, bd = None, 430
            for m in self.monsters:
                d = math.hypot(m.x - p.x, m.y - m.r * 0.5 - (p.y - 24))
                if d < bd:
                    bd, best = d, m
            if best:
                ax, ay = best.x - p.x, best.y - best.r * 0.5 - (p.y - 24)
                n = math.hypot(ax, ay) or 1
                tx, ty = ax / n, ay / n
            self.sfx("bolt")
            self.bolts.append(Bolt(p.x, p.y - 24, tx, ty, dmg))
        self.spawn_timer -= dt
        if self.spawn_timer <= 0:
            self.spawn_timer = random.uniform(8, 13)
            if "watchtower" in self.buildings:
                self.spawn_monster(0.75, 0.75)
            else:
                self.spawn_monster()
        for nd in self.nodes:
            nd.update(dt)
        for z in self.zones:
            z["t"] += dt
        self.update_ambient(dt)
        for m in self.monsters:
            m.update(dt, self)
        if self.loc == "base":                       # player was knocked out
            return
        self.bolts = [bl for bl in self.bolts if bl.update(dt)]
        for bl in self.bolts:
            for m in self.monsters:
                if m.hp > 0 and math.hypot(m.x - bl.x, m.y - m.r * 0.5 - bl.y) < m.r + 7:
                    m.hp -= bl.dmg
                    m.flash = 0.12
                    m.kx += bl.dx * 150
                    m.ky += bl.dy * 150
                    self.sfx("hit")
                    self.add_float(m.x, m.y - m.r - 16, str(bl.dmg), (255, 235, 140))
                    bl.life = 0
                    break
        for m in self.monsters:
            if m.hp <= 0:
                self.kill_monster(m)
        self.monsters = [m for m in self.monsters if m.hp > 0]
        self.pickups = [pk for pk in self.pickups if pk.update(dt, self)]

    # ================================================== 7.12 world rendering
    def draw(self):
        self.click_map = []
        if self.state == "menu":
            self.draw_menu()
            if self.overlay == "controls":
                self.draw_controls()
            pygame.display.flip()
            return
        if self.loc == "base":
            self.draw_base()
        else:
            self.draw_biome()
        self.draw_hud()
        self.draw_buff_icons()
        if self.overlay is None:
            self.draw_vignette()
            if self.tracker_on:
                self.draw_tracker()
            self.draw_danger()
            self.draw_hotbar()
            self.draw_minimap()
            self.draw_hints()
        else:
            getattr(self, "draw_" + self.overlay)()   # draw_<overlay> convention
        self.draw_messages()
        if self.settings.get("fps"):
            text(screen, "%d FPS" % clock.get_fps(), 12, SCREEN_H - 52, FONT_S, GREY)
        if self.save_flash > 0:
            img = FONT_S.render("SAVED", True, GREEN)
            img.set_alpha(clamp(int(self.save_flash * 255), 0, 255))
            screen.blit(img, (SCREEN_W - 60, SCREEN_H - 56))
        pygame.display.flip()

    # ---- prop drawing shared by base & biomes ----
    def draw_tree(self, x, y):
        pygame.draw.rect(screen, (110, 80, 50), (x - 6, y - 10, 12, 26))
        pygame.draw.circle(screen, (50, 110, 55), (x, y - 34), 26)
        pygame.draw.circle(screen, (62, 126, 67), (x - 12, y - 22), 16)
        pygame.draw.circle(screen, (62, 126, 67), (x + 12, y - 22), 16)

    def draw_villager(self, x, y, color, t, ph=0):
        bob = int(math.sin(t * 2 + ph) * 2)
        pygame.draw.ellipse(screen, (40, 60, 35), (x - 10, y + 4, 20, 6))
        pygame.draw.ellipse(screen, color, (x - 8, y - 16 + bob, 16, 22))
        pygame.draw.circle(screen, (255, 221, 190), (x, y - 22 + bob), 6)
        pygame.draw.circle(screen, (40, 30, 50), (x - 2, y - 23 + bob), 1)
        pygame.draw.circle(screen, (40, 30, 50), (x + 2, y - 23 + bob), 1)

    def draw_hut(self, t):
        pygame.draw.rect(screen, (168, 126, 88), (412, 195, 200, 110), border_radius=4)
        pygame.draw.line(screen, (120, 88, 60), (412, 230), (612, 230), 3)
        pygame.draw.rect(screen, (94, 58, 36), (490, 250, 44, 55))
        pygame.draw.circle(screen, (94, 58, 36), (512, 250), 22)
        pygame.draw.circle(screen, GOLD, (524, 280), 3)
        pygame.draw.circle(screen, (255, 231, 150), (452, 240), 15)
        pygame.draw.circle(screen, (94, 58, 36), (452, 240), 15, 3)
        pygame.draw.line(screen, (94, 58, 36), (452, 225), (452, 255), 2)
        pygame.draw.line(screen, (94, 58, 36), (437, 240), (467, 240), 2)
        pygame.draw.rect(screen, (110, 80, 60), (584, 112, 22, 48))
        pygame.draw.rect(screen, (90, 62, 44), (580, 106, 30, 10), border_radius=3)
        pygame.draw.polygon(screen, (96, 52, 112), [(388, 200), (636, 200), (512, 100)])
        if self.finale:
            pygame.draw.circle(screen, (255, 170, 220), (470, 108), 5)
            pygame.draw.circle(screen, (255, 170, 220), (556, 104), 4)
        for i in range(3):
            ph = (t * 0.5 + i * 0.33) % 1
            pygame.draw.circle(screen, (200, 200, 210),
                               (int(595 + math.sin(t + i) * 8), int(100 - ph * 46)),
                               int(4 + ph * 6))

    def draw_cauldron(self, x, y, t, liquid=(90, 200, 110), fren=1.0):
        for i in range(5):
            pygame.draw.circle(screen, (100, 95, 105), (x - 24 + i * 12, y + 22), 7)
        fl = max(2, int(2 + fren))
        for i in range(fl):
            fx = x - 14 + i * (28 // max(1, fl - 1)) if fl > 1 else x
            fh = int((8 + (math.sin(t * 9 + i * 2) + 1) * 4) * (0.7 + 0.3 * min(fren, 2.0)))
            pygame.draw.polygon(screen, (255, 140, 50),
                                [(fx - 5, y + 20), (fx + 5, y + 20), (fx, y + 20 - fh)])
            pygame.draw.polygon(screen, (255, 220, 90),
                                [(fx - 2, y + 20), (fx + 2, y + 20), (fx, y + 20 - fh * 0.6)])
        pygame.draw.ellipse(screen, (35, 32, 45), (x - 36, y - 22, 72, 46))
        pygame.draw.ellipse(screen, (55, 52, 68), (x - 40, y - 30, 80, 18))
        pygame.draw.ellipse(screen, liquid, (x - 32, y - 28, 64, 12))
        for i in range(int(2 + 2 * min(fren, 2.5))):
            ph = (t * (0.6 + 0.35 * fren) + i * 0.37) % 1
            pygame.draw.circle(screen, (150, 240, 160),
                               (int(x + math.sin(t * 1.3 + i * 2.1) * 16),
                                int(y - 30 - ph * 26)), int(2 + ph * 3), 1)

    def draw_board_sign(self, x, y):
        pygame.draw.rect(screen, (110, 75, 45), (x - 4, y - 30, 8, 46))
        pygame.draw.rect(screen, (150, 105, 60), (x - 34, y - 52, 68, 44), border_radius=4)
        pygame.draw.rect(screen, (95, 62, 35), (x - 34, y - 52, 68, 44), 3, border_radius=4)
        for i in range(4):
            px, py = x - 26 + (i % 2) * 26, y - 46 + (i // 2) * 20
            pygame.draw.rect(screen, (235, 225, 200), (px, py, 20, 14))
            pygame.draw.line(screen, (150, 140, 120), (px + 2, py + 4), (px + 17, py + 4), 1)
            pygame.draw.line(screen, (150, 140, 120), (px + 2, py + 8), (px + 13, py + 8), 1)

    def draw_signpost(self, x, y):
        pygame.draw.rect(screen, (120, 85, 50), (x - 5, y - 46, 10, 62))
        pygame.draw.polygon(screen, (170, 120, 70),
                            [(x - 48, y - 46), (x + 48, y - 46), (x + 40, y - 30), (x - 40, y - 30)])
        text(screen, "TRAVEL", x, y - 45, FONT_S, (70, 45, 25), "center")

    def draw_plot(self, x, y):
        pygame.draw.rect(screen, (140, 105, 65), (x - 45, y - 20, 90, 44), 3, border_radius=6)
        for cx, cy in [(x - 45, y - 20), (x + 45, y - 20), (x - 45, y + 24), (x + 45, y + 24)]:
            pygame.draw.rect(screen, (110, 80, 50), (cx - 3, cy - 3, 6, 6))
        pygame.draw.line(screen, (150, 110, 70), (x - 6, y + 6), (x + 8, y - 10), 4)
        pygame.draw.rect(screen, (160, 160, 170), (x + 4, y - 18, 14, 9), border_radius=2)

    def draw_road(self, pts, stones, col, edge, w=ROAD_W):
        wear = tuple(min(255, c + 20) for c in col)
        for p in pts:
            pygame.draw.circle(screen, col, (int(p[0]), int(p[1])), w // 2)
        for p in pts[::3]:
            pygame.draw.circle(screen, wear, (int(p[0]), int(p[1])), max(2, w // 5))
        for sx, sy, sr in stones:
            pygame.draw.circle(screen, edge, (int(sx), int(sy)), int(sr))

    def draw_building_icon(self, k, x, y, t):
        if k == "garden":
            pygame.draw.rect(screen, (120, 85, 55), (x - 22, y - 8, 44, 16), border_radius=4)
            for i in range(3):
                sx = x - 12 + i * 12
                pygame.draw.line(screen, (70, 160, 70), (sx, y - 6), (sx, y - 18), 2)
                pygame.draw.circle(screen, (110, 220, 110), (sx, y - 20), 4)
        elif k == "greenhouse":
            pygame.draw.rect(screen, (180, 225, 240), (x - 22, y - 20, 44, 26), border_radius=8)
            pygame.draw.rect(screen, (110, 150, 170), (x - 22, y - 20, 44, 26), 2, border_radius=8)
            pygame.draw.line(screen, (110, 150, 170), (x, y - 20), (x, y + 6), 2)
        elif k == "market":
            for i in range(4):
                pygame.draw.rect(screen, (220, 70, 70) if i % 2 == 0 else (240, 240, 240),
                                 (x - 24 + i * 12, y - 18, 12, 10))
            pygame.draw.rect(screen, (140, 100, 60), (x - 24, y - 8, 48, 14))
        elif k == "watchtower":
            pygame.draw.rect(screen, (130, 120, 130), (x - 8, y - 30, 16, 34))
            pygame.draw.rect(screen, (90, 80, 95), (x - 14, y - 36, 28, 8), border_radius=3)
        elif k == "broomshed":
            pygame.draw.polygon(screen, (140, 100, 60), [(x - 20, y + 4), (x + 20, y + 4), (x, y - 16)])
            pygame.draw.line(screen, (160, 120, 70), (x + 14, y - 20), (x + 26, y + 6), 3)
            pygame.draw.polygon(screen, (220, 180, 90), [(x + 24, y + 4), (x + 32, y + 8), (x + 26, y + 12)])
        elif k == "focus":
            pygame.draw.rect(screen, (120, 110, 130), (x - 10, y - 4, 20, 10))
            pygame.draw.polygon(screen, (150, 220, 255), [(x, y - 26), (x + 8, y - 6), (x - 8, y - 6)])
        elif k == "cauldron2":
            pygame.draw.ellipse(screen, (60, 55, 75), (x - 16, y - 12, 32, 20))
            pygame.draw.ellipse(screen, (220, 180, 60), (x - 18, y - 16, 36, 8), 2)
            pygame.draw.circle(screen, (150, 255, 150), (x, y - 18 + int(math.sin(t * 4) * 2)), 3)
        elif k == "cloudbed":
            pygame.draw.ellipse(screen, (240, 240, 250), (x - 22, y - 10, 44, 18))
            pygame.draw.ellipse(screen, (240, 240, 250), (x - 12, y - 16, 20, 14))
            pygame.draw.rect(screen, (150, 100, 60), (x - 24, y + 6, 48, 4))
        elif k == "distillery":
            pygame.draw.rect(screen, (170, 115, 65), (x - 16, y - 12, 30, 20), border_radius=5)
            pygame.draw.ellipse(screen, (200, 145, 90), (x - 18, y - 16, 34, 9))
            pygame.draw.line(screen, (170, 115, 65), (x + 13, y - 8), (x + 24, y - 16), 3)
            pygame.draw.circle(screen, (140, 220, 255),
                               (x + 25, y - 18 + int(math.sin(t * 5) * 2)), 3)
            pygame.draw.polygon(screen, (255, 140, 50), [(x - 8, y + 10), (x + 4, y + 10), (x - 2, y + 2)])

    def draw_base(self):
        t = self.time
        screen.fill((98, 150, 72))
        for gx, gy in self.grass:
            pygame.draw.line(screen, (84, 134, 62), (gx, gy), (gx + 2, gy - 5), 1)
        for fx, fy, fc in self.flowers:
            pygame.draw.circle(screen, fc, (fx, fy), 3)
        for pts, stones in self.base_roads:
            self.draw_road(pts, stones, (170, 140, 95), (122, 94, 62))
        for key in self.buildings:
            if key in self.stubs:
                pts, _ = self.stubs[key]
                self.draw_road(pts, [], (160, 132, 90), (122, 94, 62), w=16)
        self.draw_tree(70, 160); self.draw_tree(955, 175)
        self.draw_tree(60, 690); self.draw_tree(975, 670)
        for slot, k in zip(BUILD_SLOTS, BUILDINGS.keys()):
            if k in self.buildings:
                self.draw_building_icon(k, slot[0], slot[1], t)
                text(screen, BUILDINGS[k]["name"], slot[0], slot[1] + 16, FONT_S, (235, 220, 185), "center")
        self.draw_hut(t)
        self.draw_board_sign(250, 300)
        self.draw_cauldron(740, 300, t)
        self.draw_signpost(512, 630)
        self.draw_plot(860, 520)
        for i, name in enumerate(self.family_names()[:4]):   # found family visiting
            x, y = [(430, 500), (600, 495), (668, 522), (368, 532)][i]
            self.draw_villager(x, y, PERSONA_COLOR[PERSONA_OF[name]], t, i * 1.3)
            text(screen, name.split()[0], x, y + 14, FONT_S, (245, 238, 210), "center")
        near = next((s for s in BASE_SPOTS
                     if math.hypot(self.player.x - s["x"], self.player.y - s["y"]) < s["r"]), None)
        if near:
            pygame.draw.ellipse(screen, (255, 245, 160),
                                (near["x"] - 26, near["y"] - 8, 52, 18), 2)
            self.label(near["label"] + "  [E]", near["x"], near["y"] - 62)
        self.draw_aura()
        self.player.draw(screen, t)
        for f in self.floats:
            f.draw(screen)

    def draw_portal(self, x, y, t):
        pygame.draw.ellipse(screen, (52, 26, 84), (x - 28, y - 62, 56, 66))
        pygame.draw.ellipse(screen, (110, 55, 170), (x - 22, y - 56, 44, 54))
        pygame.draw.ellipse(screen, (170, 110, 230), (x - 15, y - 49, 30, 40))
        for i in range(5):
            ph = (t * 1.2 + i * 0.2) % 1
            wob = math.sin(ph * 9 + i * 2) * 8 * (1 - ph)
            pygame.draw.circle(screen, (235, 205, 255),
                               (int(x + wob), int(y - 52 + ph * 44)), 2)
        text(screen, "HOME", x, y + 8, FONT_S, (225, 190, 255), "center")

    def draw_decor(self, k, x, y):
        if k == "tree":
            pygame.draw.rect(screen, (95, 70, 45), (x - 6, y - 14, 12, 22))
            pygame.draw.circle(screen, (40, 95, 45), (x, y - 30), 22)
            pygame.draw.circle(screen, (52, 112, 52), (x - 12, y - 18), 14)
            pygame.draw.circle(screen, (52, 112, 52), (x + 12, y - 18), 14)
        elif k == "pine":
            pygame.draw.rect(screen, (90, 70, 50), (x - 5, y - 8, 10, 16))
            pygame.draw.polygon(screen, (60, 100, 85), [(x - 18, y - 8), (x + 18, y - 8), (x, y - 44)])
            pygame.draw.polygon(screen, (75, 115, 95), [(x - 14, y - 30), (x + 14, y - 30), (x, y - 58)])
            pygame.draw.polygon(screen, (235, 240, 250), [(x - 7, y - 48), (x + 7, y - 48), (x, y - 58)])
        elif k == "cactus":
            pygame.draw.rect(screen, (70, 140, 70), (x - 7, y - 34, 14, 40), border_radius=7)
            pygame.draw.rect(screen, (70, 140, 70), (x - 20, y - 26, 13, 9), border_radius=4)
            pygame.draw.rect(screen, (70, 140, 70), (x - 20, y - 34, 9, 16), border_radius=4)
            pygame.draw.rect(screen, (70, 140, 70), (x + 7, y - 20, 13, 9), border_radius=4)
            pygame.draw.rect(screen, (70, 140, 70), (x + 11, y - 30, 9, 18), border_radius=4)
            pygame.draw.circle(screen, (255, 110, 150), (x, y - 36), 4)
        elif k == "rock":
            pygame.draw.ellipse(screen, (130, 130, 140), (x - 14, y - 10, 28, 16))
            pygame.draw.ellipse(screen, (160, 160, 170), (x - 8, y - 12, 14, 10))
        elif k == "snowrock":
            pygame.draw.ellipse(screen, (150, 160, 175), (x - 16, y - 12, 32, 18))
            pygame.draw.ellipse(screen, (240, 245, 252), (x - 12, y - 16, 24, 10))
        elif k == "bush":
            pygame.draw.ellipse(screen, (60, 110, 55), (x - 14, y - 14, 28, 18))
            pygame.draw.circle(screen, (220, 80, 90), (x - 5, y - 8), 2)
            pygame.draw.circle(screen, (220, 80, 90), (x + 6, y - 10), 2)
        elif k == "reed":
            sway = math.sin(self.time * 2 + x) * 3
            for i in range(3):
                rx = x - 8 + i * 8
                pygame.draw.line(screen, (110, 150, 90), (rx, y), (rx + sway, y - 26), 2)
                pygame.draw.ellipse(screen, (140, 120, 70), (rx - 2 + sway, y - 34, 4, 10))
        elif k == "mushroom":
            pygame.draw.rect(screen, (200, 190, 180), (x - 3, y - 10, 6, 10))
            pygame.draw.ellipse(screen, (180, 90, 110), (x - 9, y - 16, 18, 10))
            pygame.draw.circle(screen, (240, 220, 230), (x - 2, y - 13), 1)
        elif k == "stump":
            pygame.draw.rect(screen, (110, 80, 50), (x - 9, y - 12, 18, 14), border_radius=3)
            pygame.draw.ellipse(screen, (150, 115, 70), (x - 9, y - 16, 18, 8))
        elif k == "flower":
            pygame.draw.line(screen, (70, 130, 60), (x, y), (x, y - 8), 2)
            pygame.draw.circle(screen, (250, 210, 120), (x, y - 11), 3)

    def draw_zone(self, z, b):
        x, y, r = int(z["x"]), int(z["y"]), z["r"]
        w, h = int(r * 2), int(r)
        k = z["kind"]
        if k == "pond":
            pygame.draw.ellipse(screen, b["water"], (x - w // 2, y - h // 2, w, h))
            pygame.draw.ellipse(screen, tuple(min(255, c + 30) for c in b["water"]),
                                (x - w // 3, y - h // 3, w * 2 // 3, h * 2 // 3))
            for i in range(2):
                ph = (z["t"] * 0.8 + i * 0.5) % 1
                lx = x - w // 3 + int(ph * w * 2 / 3)
                pygame.draw.line(screen, (230, 240, 255), (lx - 8, y - 4 + i * 6), (lx + 8, y - 4 + i * 6), 1)
        elif k == "oasis":
            pygame.draw.ellipse(screen, b["water"], (x - w // 2, y - h // 2, w, h))
            pygame.draw.ellipse(screen, (90, 170, 210), (x - w // 3, y - h // 3, w * 2 // 3, h * 2 // 3))
            pygame.draw.line(screen, (110, 80, 50), (x + r // 2, y - 4), (x + r // 2 + 6, y - 34), 4)
            for a in (-1.9, -1.4, -0.9, -2.4):
                pygame.draw.line(screen, (60, 150, 70), (x + r // 2 + 6, y - 34),
                                 (x + r // 2 + 6 + int(math.cos(a) * 14),
                                  y - 34 + int(math.sin(a) * 10)), 3)
        elif k == "quicksand":
            pygame.draw.ellipse(screen, (150, 118, 80), (x - w // 2, y - h // 2, w, h))
            for dx, dy in z["dots"]:
                pygame.draw.circle(screen, (128, 98, 64), (int(x + dx), int(y + dy)), 2)
        elif k == "grove":
            pygame.draw.ellipse(screen, tuple(max(0, c - 14) for c in b["ground"]),
                                (x - w // 2, y - h // 2, w, h))
        elif k == "murk":
            pygame.draw.ellipse(screen, (56, 66, 58), (x - w // 2, y - h // 2, w, h))
            pygame.draw.ellipse(screen, (70, 84, 74), (x - w // 3, y - h // 3, w * 2 // 3, h * 2 // 3))
        elif k == "ice":
            pygame.draw.ellipse(screen, (188, 222, 245), (x - w // 2, y - h // 2, w, h))
            pygame.draw.ellipse(screen, (240, 250, 255), (x - w // 2, y - h // 2, w, h), 2)
            for x1, y1, x2, y2 in z["cracks"]:
                pygame.draw.line(screen, (255, 255, 255),
                                 (int(x + x1), int(y + y1)), (int(x + x2), int(y + y2)), 1)
        elif k == "flowerfield":
            pygame.draw.ellipse(screen, tuple(min(255, c + 16) for c in b["ground"]),
                                (x - w // 2, y - h // 2, w, h))
            for fx, fy, fc in z["fl"]:
                pygame.draw.circle(screen, fc, (int(x + fx), int(y + fy)), 2)

    def draw_landmark(self, l, t):
        x, y = int(l["x"]), int(l["y"])
        used, k = l["used"], l["kind"]
        if k == "leystone":
            glow = 0 if used else int(6 + math.sin(t * 3 + l["t"]) * 3)
            if glow:
                pygame.draw.circle(screen, (170, 140, 255), (x, y - 16), 30 + glow, 2)
            pygame.draw.polygon(screen, (130, 130, 145) if used else (150, 140, 175),
                                [(x - 10, y + 6), (x + 10, y + 6), (x + 7, y - 30), (x - 7, y - 30)])
            rc = (100, 100, 115) if used else PURPLE
            for ry in (-24, -16, -8):
                pygame.draw.line(screen, rc, (x - 3, y + ry), (x + 4, y + ry + 2), 2)
        elif k == "shrine":
            pygame.draw.rect(screen, (140, 140, 130), (x - 14, y - 22, 6, 28))
            pygame.draw.rect(screen, (140, 140, 130), (x + 8, y - 22, 6, 28))
            pygame.draw.rect(screen, (150, 150, 140), (x - 18, y - 28, 36, 8), border_radius=3)
            if not used:
                fh = 5 + int((math.sin(t * 9) + 1) * 2)
                pygame.draw.polygon(screen, (255, 170, 60),
                                    [(x - 1, y - 2), (x + 1, y - 2), (x, y - 2 - fh)])
                pygame.draw.circle(screen, (200, 190, 170), (x, y), 3)
        elif k == "cache":
            pygame.draw.ellipse(screen, (140, 112, 76), (x - 20, y - 8, 40, 16))
            pygame.draw.rect(screen, (150, 110, 60) if not used else (120, 88, 48),
                             (x - 12, y - 16, 24, 14), border_radius=3)
            if used:
                pygame.draw.rect(screen, (100, 74, 40), (x - 12, y - 26, 24, 6), border_radius=3)
                pygame.draw.line(screen, (100, 74, 40), (x - 12, y - 22), (x - 22, y - 34), 2)
            else:
                pygame.draw.rect(screen, (190, 150, 90), (x - 12, y - 20, 24, 6), border_radius=3)
                pygame.draw.rect(screen, GOLD, (x - 2, y - 14, 4, 6))
        elif k == "spring":
            pygame.draw.ellipse(screen, (90, 170, 200), (x - 22, y - 10, 44, 20))
            pygame.draw.ellipse(screen, (140, 210, 235), (x - 14, y - 6, 28, 10))
            for i in range(2):
                ph = (t * 0.9 + i * 0.5) % 1
                pygame.draw.circle(screen, (235, 245, 250),
                                   (x + int(math.sin(ph * 6 + i) * 8), y - 12 - int(ph * 18)),
                                   int(2 + ph * 3), 1)
        elif k == "crystal":
            base = (150, 150, 160) if used else (150, 220, 255)
            hi = (170, 170, 180) if used else (230, 245, 255)
            pygame.draw.polygon(screen, base, [(x - 10, y + 4), (x - 2, y + 4), (x - 6, y - 22)])
            pygame.draw.polygon(screen, base, [(x + 1, y + 4), (x + 11, y + 4), (x + 7, y - 16)])
            pygame.draw.polygon(screen, base, [(x - 4, y + 4), (x + 4, y + 4), (x, y - 30)])
            pygame.draw.polygon(screen, hi, [(x - 1, y - 24), (x + 1, y - 14), (x - 3, y - 14)])
            if not used and int(t * 3) % 3 == 0:
                pygame.draw.circle(screen, WHITE, (x + 8, y - 18), 1)
        elif k == "ruin":
            pygame.draw.rect(screen, (150, 145, 135), (x - 22, y - 18, 12, 22))
            pygame.draw.rect(screen, (150, 145, 135), (x + 8, y - 12, 14, 16))
            pygame.draw.rect(screen, (140, 135, 125), (x - 10, y - 26, 22, 6))
            for i in range(4):
                pygame.draw.circle(screen, (135, 130, 120),
                                   (x - 18 + i * 12, y + 4 + (i % 2) * 2), 3)
        elif k == "well":
            pygame.draw.circle(screen, (130, 125, 120), (x, y), 14)
            pygame.draw.circle(screen, (60, 70, 80), (x, y), 9)
            pygame.draw.line(screen, (110, 80, 50), (x - 12, y - 2), (x - 12, y - 26), 3)
            pygame.draw.line(screen, (110, 80, 50), (x + 12, y - 2), (x + 12, y - 26), 3)
            pygame.draw.polygon(screen, (150, 90, 60), [(x - 18, y - 24), (x + 18, y - 24), (x, y - 38)])
            pygame.draw.line(screen, (90, 90, 90), (x, y - 26), (x, y - 12), 1)
            pygame.draw.rect(screen, (110, 80, 50), (x - 4, y - 12, 8, 6))

    def draw_ambient(self):
        if not self.settings.get("particles", True):
            return
        for p in self.ambient:
            x, y = int(p["x"]), int(p["y"])
            k = p["k"]
            if k == "leaf":
                pygame.draw.ellipse(screen, p["c"], (x - 3, y - 2, 6, 4))
            elif k == "petal":
                pygame.draw.ellipse(screen, p["c"], (x - 2, y - 2, 5, 3))
            elif k == "snow":
                pygame.draw.circle(screen, (250, 250, 255), (x, y), 2)
            elif k == "sand":
                pygame.draw.rect(screen, (226, 200, 148), (x - 6, y, 12, 2))
            elif math.sin(p["ph"] * 4) > 0:          # firefly pulse
                pygame.draw.circle(screen, (255, 255, 170), (x, y), 2)
                pygame.draw.circle(screen, (255, 255, 120), (x, y), 4, 1)

    def draw_biome(self):
        t = self.time
        b = BIOMES[self.loc]
        screen.fill(b["ground"])
        for i, f in enumerate((0.82, 0.9, 0.96)):    # depth bands
            pygame.draw.rect(screen, tuple(int(c * f) for c in b["ground"]),
                             (0, 54 + i * 22, SCREEN_W, 22))
        for px, py, pr in self.patches:
            pygame.draw.ellipse(screen, b["accent"], (px - pr, py - pr * 0.4, pr * 2, pr * 0.8))
        for z in self.zones:
            if z["kind"] != "mist":
                self.draw_zone(z, b)
        for pts, stones in self.roads:
            self.draw_road(pts, stones, b["road"], b["road_edge"])
        for k, dx, dy in self.decor:
            self.draw_decor(k, dx, dy)
        self.draw_portal(512, 700, t)
        for l in self.landmarks:
            self.draw_landmark(l, t)
        for nd in self.nodes:
            nd.draw(screen)
        for m in self.monsters:
            m.draw(screen)
        for pk in self.pickups:
            pk.draw(screen)
        self.draw_aura()
        self.player.draw(screen, t)
        for bl in self.bolts:
            bl.draw(screen)
        for f in self.floats:
            f.draw(screen)
        for z in self.zones:                          # mist on top
            if z["kind"] == "mist":
                sz = int(z["r"] * 2.8)
                img = pygame.transform.smoothscale(self.fog, (sz, int(sz * 0.7)))
                screen.blit(img, (z["x"] - sz // 2, z["y"] - int(sz * 0.35)))
        if self.weather == "misty":
            screen.blit(self.fog_full, (0, 0))
        self.draw_ambient()
        for nd in self.nodes:
            if nd.ready and math.hypot(self.player.x - nd.x, self.player.y - nd.y) < 46:
                self.label("Gather %s  [E]" % INGREDIENTS[nd.item]["name"], nd.x, nd.y - 34)
                break
        for l in self.landmarks:
            if not l["used"] and math.hypot(self.player.x - l["x"], self.player.y - l["y"]) < 46:
                self.label(LANDMARK_INFO[l["kind"]]["label"] + "  [E]", l["x"], l["y"] - 40, GOLD)
                break
        if math.hypot(self.player.x - 512, self.player.y - 700) < 60:
            self.label("Step into the portal  [E]", 512, 622)

    def draw_aura(self):
        for b, (nm, c) in BUFFS.items():
            if self.buffs.get(b, 0) > 0:
                r = 30 + int(math.sin(self.time * 6) * 3)
                pygame.draw.circle(screen, c, (int(self.player.x), int(self.player.y - 18)), r, 2)
                break

    # ================================================== 7.13 HUD rendering
    def draw_moon(self, x, y, phase):
        if phase == 0:
            pygame.draw.circle(screen, (90, 90, 110), (x, y), 7)
            return
        pygame.draw.circle(screen, (230, 230, 210), (x, y), 7)
        d = (4 - phase) * 2.6
        if -8 < d < 8:
            pygame.draw.circle(screen, (20, 15, 32), (x + int(d), y), 7)

    def draw_weather(self, cx, cy):
        pygame.draw.circle(screen, (30, 24, 46), (cx, cy), 9)
        if self.weather == "clear":
            pygame.draw.circle(screen, (250, 210, 90), (cx, cy), 5)
            for a in range(8):
                aa = a * math.tau / 8
                pygame.draw.line(screen, (250, 210, 90),
                                 (cx + math.cos(aa) * 6, cy + math.sin(aa) * 6),
                                 (cx + math.cos(aa) * 8, cy + math.sin(aa) * 8), 1)
        elif self.weather == "breezy":
            for i in range(3):
                pygame.draw.line(screen, (200, 220, 240), (cx - 6, cy - 4 + i * 4),
                                 (cx + 5 - (i % 2) * 3, cy - 4 + i * 4), 1)
        else:
            for i in range(3):
                for xx in range(-5, 6, 3):
                    pygame.draw.line(screen, (190, 195, 210), (cx + xx, cy - 4 + i * 4),
                                     (cx + xx + 2, cy - 4 + i * 4), 1)

    def draw_hud(self):
        pygame.draw.rect(screen, (20, 15, 32), (0, 0, SCREEN_W, 54))
        pygame.draw.line(screen, (80, 60, 110), (0, 54), (SCREEN_W, 54), 2)
        # gold + pops
        pygame.draw.circle(screen, GOLD, (26, 27), 9)
        pygame.draw.circle(screen, (170, 130, 40), (26, 27), 9, 2)
        pygame.draw.circle(screen, (255, 245, 200), (23, 24), 2)
        text(screen, "%dg" % self.gold, 42, 14, FONT_M, GOLD)
        for pop in self.hud_pops:
            img = FONT_S.render(pop["s"], True, pop["c"])
            img.set_alpha(clamp(int(pop["ttl"] * 220), 0, 255))
            screen.blit(img, (108, 40 - int(pop["y"])))
        # day + moon phase
        self.draw_moon(152, 27, self.day % 8)
        text(screen, "Day %d" % self.day, 168, 14, FONT_M, WHITE)
        # HP: heart, ghost trail, fill, quarters, low-pulse
        hp, mx = max(0, self.player.hp), self.player.max_hp
        frac = hp / mx
        bx, by, bw, bh = 250, 16, 170, 20
        hx, hy = 236, 24
        pygame.draw.circle(screen, (225, 80, 90), (hx - 4, hy - 3), 5)
        pygame.draw.circle(screen, (225, 80, 90), (hx + 4, hy - 3), 5)
        pygame.draw.polygon(screen, (225, 80, 90), [(hx - 9, hy - 1), (hx + 9, hy - 1), (hx, hy + 9)])
        pygame.draw.rect(screen, (70, 25, 30), (bx, by, bw, bh), border_radius=7)
        pygame.draw.rect(screen, (200, 200, 210),
                         (bx, by, int(bw * clamp(self.hp_ghost / mx, 0, 1)), bh), border_radius=7)
        fcol = GREEN if frac > 0.5 else ((250, 200, 90) if frac > 0.25 else RED)
        pygame.draw.rect(screen, fcol, (bx, by, int(bw * frac), bh), border_radius=7)
        for i in range(1, 4):
            pygame.draw.line(screen, (20, 15, 32), (bx + i * bw // 4, by),
                             (bx + i * bw // 4, by + bh), 1)
        if frac < 0.3 and int(self.time * 4) % 2 == 0:
            pygame.draw.rect(screen, RED, (bx - 2, by - 2, bw + 4, bh + 4), 2, border_radius=9)
        text(screen, "%d/%d" % (int(hp), mx), bx + bw // 2, by + 2, FONT_S, WHITE, "center")
        # reputation + tier
        text(screen, "Rep %+d" % self.rep, 440, 6, FONT_S, (200, 170, 240))
        text(screen, self.rep_tier(), 440, 24, FONT_S, GOLD if self.rep >= 10 else GREY)
        # contracts: ready count + blinking deadline
        ready = sum(1 for o in self.orders if self.pot_count_ge(o["pid"], o["minq"]) >= o["qty"])
        s, c = "Contracts %d/3" % len(self.orders), GREY
        if ready:
            s += "  [%d ready]" % ready
            c = GREEN
        soon = min((o["due"] for o in self.orders), default=None)
        if soon is not None:
            left = max(0, soon - self.day)
            s += "  due %dd" % left
            if left <= 1:
                c = RED if int(self.time * 3) % 2 == 0 else (255, 150, 150)
            elif c == GREY:
                c = WHITE
        text(screen, s, 560, 14, FONT_M, c)
        # brewing xp strip
        bar(screen, 0, 51, SCREEN_W, 3, self.brew_xp / self.xp_next(), PURPLE, radius=1)
        text(screen, "Lv%d" % self.brew_level, 8, 40, FONT_S, PURPLE)
        # right block
        if self.loc == "base":
            text(screen, "Your Cottage   [P pause]", SCREEN_W - 16, 8, FONT_M, GOLD, "topright")
            text(screen, "Brew Lv %d  |  %d family here" % (self.brew_level, len(self.family_names())),
                 SCREEN_W - 16, 30, FONT_S, (220, 200, 240), "topright")
        else:
            b = BIOMES[self.loc]
            text(screen, "%s - %s" % (b["name"], self.variant), SCREEN_W - 16, 6, FONT_M, WHITE, "topright")
            line2 = "danger %d  |  %s" % (b["danger"], self.weather)
            self.draw_weather(SCREEN_W - 16 - FONT_S.size(line2)[0] - 14, 38)
            text(screen, line2, SCREEN_W - 16, 28, FONT_S, RED, "topright")
        if self.active_rumor:
            text(screen, "Rumor: %s in the %s" %
                 (LANDMARK_INFO[self.active_rumor["kind"]]["label"],
                  BIOMES[self.active_rumor["biome"]]["name"]),
                 SCREEN_W - 16, 46, FONT_S, PURPLE, "topright")

    def draw_buff_icons(self):
        if not self.buffs:
            return
        x = SCREEN_W // 2 - (len(self.buffs) * 38 - 8) // 2
        for b, v in self.buffs.items():
            nm, c = BUFFS[b]
            frac = v / max(1.0, self.buff_max.get(b, v))
            cx, cy = x + 15, 66
            pygame.draw.circle(screen, (25, 20, 35), (cx, cy), 14)
            if frac > 0:
                pygame.draw.arc(screen, c, pygame.Rect(cx - 14, cy - 14, 28, 28),
                                -math.pi / 2, -math.pi / 2 + clamp(frac, 0, 1) * math.tau, 3)
            text(screen, nm[:2].upper(), cx, cy - 6, FONT_S, c, "center")
            text(screen, "%d" % int(math.ceil(v)), cx, cy + 2, FONT_S, WHITE, "center")
            x += 38

    def draw_tracker(self):
        lines = []
        for o in self.orders:
            have = self.pot_count_ge(o["pid"], o["minq"])
            left = o["due"] - self.day
            col = RED if left <= 1 else (GREEN if have >= o["qty"] else GREY)
            lines.append(("%dx %s  %d/%d  %dd" % (o["qty"], pot_def(o["pid"])["name"],
                                                  have, o["qty"], max(0, left)), col))
        for fav in self.favors:
            left = max(0, fav["due"] - self.day)
            nm = (INGREDIENTS[fav["target"]]["name"] if fav["kind"] == "item"
                  else MONSTERS[fav["target"]]["name"])
            prog = fav["have"] if fav["kind"] == "hunt" else \
                min(fav["need"], self.items.get(fav["target"], 0))
            lines.append(("[favor] %s %d/%d  %dd" % (nm, prog, fav["need"], left),
                          RED if left <= 1 else (255, 200, 140)))
        for f in [f for f in self.feuds if not f["done"]][:1]:
            side = f["sided"] if f["sided"] else "unpicked"
            lines.append(("feud: %s/%s (%s)" % (f["a"].split()[0], f["b"].split()[0], side),
                          (255, 120, 120)))
        if not lines:
            return
        w = 330
        pygame.draw.rect(screen, (15, 12, 24), (12, 62, w, 24 + len(lines) * 18), border_radius=8)
        pygame.draw.rect(screen, (70, 55, 100), (12, 62, w, 24 + len(lines) * 18), 1, border_radius=8)
        self.add_click(pygame.Rect(12, 62, w, 20), lambda: setattr(self, "tracker_on", False))
        text(screen, "TRACKER  [T]", 22, 66, FONT_S, (200, 180, 230))
        for i, (s, c) in enumerate(lines):
            text(screen, "| " + s, 22, 84 + i * 18, FONT_S, c)

    def draw_danger(self):
        if self.loc == "base" or not self.monsters:
            return
        p = self.player
        near = [(math.hypot(m.x - p.x, m.y - p.y), m)
                for m in self.monsters
                if math.hypot(m.x - p.x, m.y - p.y) < 300]
        if not near:
            return
        d, m = min(near)
        a = math.atan2(m.y - p.y, m.x - p.x)
        cx = p.x + math.cos(a) * 36
        cy = p.y - 14 + math.sin(a) * 36
        col = RED if d < 160 else (255, 170, 90)
        if int(self.time * (6 if d < 160 else 3)) % 2 == 0:
            pygame.draw.polygon(screen, col,
                                [(cx + math.cos(a) * 8, cy + math.sin(a) * 8),
                                 (cx + math.cos(a + 2.5) * 7, cy + math.sin(a + 2.5) * 7),
                                 (cx + math.cos(a - 2.5) * 7, cy + math.sin(a - 2.5) * 7)])
        if d < 160:
            text(screen, "!! %d NEAR" % len(near), SCREEN_W - 16, 66, FONT_S, RED, "topright")

    def draw_hotbar(self):
        slots = self.quick_slots()
        box, gap = 46, 6
        x0 = SCREEN_W // 2 - (HOTBAR_SLOTS * box + (HOTBAR_SLOTS - 1) * gap) // 2
        y0 = SCREEN_H - 88
        for i in range(HOTBAR_SLOTS):
            bx = x0 + i * (box + gap)
            pid = slots[i] if i < len(slots) else None
            col = pot_def(pid)["color"] if pid else (60, 55, 75)
            pygame.draw.rect(screen, (20, 16, 30), (bx, y0, box, box), border_radius=9)
            pygame.draw.rect(screen, col if pid else (55, 50, 70), (bx, y0, box, box), 2, border_radius=9)
            if pid:
                orb(screen, bx + box // 2, y0 + box // 2 - 3, 9, col)
                text(screen, "x%d" % self.potion_total(pid), bx + box - 4, y0 + box - 16,
                     FONT_S, WHITE, "topright")
                self.add_click(pygame.Rect(bx, y0, box, box), lambda pp=pid: self.drink_potion(pp))
                if pid == "healing" and self.player.hp < self.player.max_hp * 0.5 \
                        and int(self.time * 4) % 2 == 0:
                    pygame.draw.rect(screen, GREEN, (bx, y0, box, box), 2, border_radius=9)
            text(screen, str(i + 1), bx + 4, y0 + 2, FONT_S, GREY)
        text(screen, "quick potions", SCREEN_W // 2, y0 - 16, FONT_S, (120, 110, 140), "center")

    def draw_minimap(self):
        big = self.minimap_big
        W, H = (500, 360) if big else (190, 132)
        x0 = (SCREEN_W - W) // 2 if big else SCREEN_W - W - 14
        y0 = 140 if big else SCREEN_H - H - 44
        mm = pygame.Surface((W, H), pygame.SRCALPHA)
        mm.fill((14, 11, 24, 215))
        sx, sy = W / SCREEN_W, H / SCREEN_H
        P = lambda x, y: (x * sx, y * sy)
        if self.loc == "base":
            for pts, _ in self.base_roads:
                if len(pts) > 1:
                    pygame.draw.lines(mm, (120, 100, 70), False, [P(*q) for q in pts[::2]], 2)
            for key in self.buildings:
                bx, by = BUILD_SLOTS[list(BUILDINGS.keys()).index(key)]
                px, py = P(bx, by)
                pygame.draw.rect(mm, GOLD, (px - 2, py - 2, 4, 4))
            for s in BASE_SPOTS:
                px, py = P(s["x"], s["y"])
                pygame.draw.circle(mm, (250, 220, 120), (int(px), int(py)), 3)
        else:
            b = BIOMES[self.loc]
            ZC = {"pond": (60, 110, 180), "oasis": (80, 160, 200), "quicksand": (150, 115, 75),
                  "ice": (200, 230, 250), "grove": (22, 56, 30), "murk": (38, 50, 42),
                  "mist": (170, 175, 190), "flowerfield": (150, 190, 90)}
            for z in self.zones:
                px, py = P(z["x"], z["y"])
                pygame.draw.ellipse(mm, ZC.get(z["kind"], (90, 90, 90)),
                                    (px - z["r"] * sx, py - z["r"] * 0.5 * sy,
                                     z["r"] * sx * 2, z["r"] * sy))
            for pts, _ in self.roads:
                if len(pts) > 1:
                    pygame.draw.lines(mm, b["road"], False, [P(*q) for q in pts[::2]], 2)
            px, py = P(512, 700)
            pygame.draw.rect(mm, PURPLE, (px - 3, py - 4, 6, 8))
            for nd in self.nodes:
                if nd.ready:
                    nx, ny = P(nd.x, nd.y)
                    pygame.draw.circle(mm, INGREDIENTS[nd.item]["color"], (int(nx), int(ny)), 2)
            for l in self.landmarks:
                lx, ly = P(l["x"], l["y"])
                pygame.draw.polygon(mm, GOLD if not l["used"] else (110, 110, 120),
                                    [(lx, ly - 4), (lx + 3, ly), (lx, ly + 4), (lx - 3, ly)])
                if not l["used"] and self.active_rumor and \
                        self.active_rumor["biome"] == self.loc:
                    pygame.draw.circle(mm, GOLD, (int(lx), int(ly)), 6, 1)
            for m in self.monsters:
                mx, my = P(m.x, m.y)
                pygame.draw.circle(mm, RED, (int(mx), int(my)), 2)
        p = self.player
        px, py = P(p.x, p.y)
        pygame.draw.circle(mm, WHITE, (int(px), int(py)), 3)
        pygame.draw.line(mm, WHITE, (px, py), (px + p.dir_x * 8, py + p.dir_y * 8), 1)
        screen.blit(mm, (x0, y0))
        pygame.draw.rect(screen, GOLD if big else PURPLE, (x0, y0, W, H), 2, border_radius=6)
        self.add_click(pygame.Rect(x0, y0, W, H),
                       lambda: setattr(self, "minimap_big", not self.minimap_big))
        if big:
            text(screen, "FIELD MAP", x0 + W // 2, y0 + 8, FONT_L, GOLD, "midtop")
            text(screen, "gold diamond = landmark | red = monster | dots = plants | click / M: shrink",
                 x0 + W // 2, y0 + H - 22, FONT_S, GREY, "center")
        else:
            text(screen, "M", x0 + W - 14, y0 + 4, FONT_S, GREY)

    def draw_vignette(self):
        if not self.settings.get("vignette", True):
            return
        frac = self.player.hp / self.player.max_hp
        if frac >= 0.3:
            return
        sev = (0.3 - frac) / 0.3
        k = int(255 * sev * (0.6 + 0.4 * math.sin(self.time * 6)))
        for img, pos in ((self.vig_top, (0, 54)), (self.vig_bottom, (0, SCREEN_H - 100)),
                         (self.vig_left, (0, 54)), (self.vig_right, (SCREEN_W - 100, 54))):
            img.set_alpha(k)
            screen.blit(img, pos)

    def draw_messages(self):
        y = SCREEN_H - 84
        for m in self.messages[-4:]:
            box = pygame.Rect(12, y - 3, FONT_S.size(m["s"])[0] + 24, 22)
            pygame.draw.rect(screen, (14, 11, 22), box, border_radius=6)
            pygame.draw.rect(screen, m["c"], (12, y - 3, 4, 22), border_radius=2)
            screen.blit(FONT_S.render(m["s"], True, (0, 0, 0)), (23, y + 1))
            screen.blit(FONT_S.render(m["s"], True, m["c"]), (22, y))
            y -= 26

    def draw_hints(self):
        s = ("WASD move | E interact | I satchel | 1-4 potion | B bestiary | "
             "J chronicle | TAB stats | P pause" if self.loc == "base" else
             "WASD move | SPACE bolt | E gather | 1-4 potion | H heal | "
             "B bestiary | TAB stats | P pause")
        w = FONT_S.size(s)[0]
        pygame.draw.rect(screen, (20, 15, 30),
                         (SCREEN_W // 2 - w // 2 - 10, SCREEN_H - 30, w + 20, 24), border_radius=8)
        text(screen, s, SCREEN_W // 2, SCREEN_H - 27, FONT_S, GREY, "center")

    # ================================================== 7.14 overlay rendering
    def panel(self, title, n_rows, extra=80, w=700):
        h = 84 + n_rows * 34 + extra
        x0 = (SCREEN_W - w) // 2
        y0 = 90 + self.dim_screen(170)
        pygame.draw.rect(screen, (46, 34, 68), (x0, y0, w, h), border_radius=12)
        pygame.draw.rect(screen, PURPLE, (x0, y0, w, h), 3, border_radius=12)
        text(screen, title, SCREEN_W // 2, y0 + 12, FONT_L, GOLD, "midtop")
        return x0 + 16, y0 + 66, w - 32

    # ---- title screen ----
    def draw_menu(self):
        t = self.time
        self.title_clicks = []
        screen.fill((22, 14, 38))
        for sx, sy, sp in self.stars:
            pygame.draw.circle(screen, (220, 220, 255), (sx, sy),
                               1 + int((math.sin(t * 2 + sp) + 1) * 1.2))
        pygame.draw.circle(screen, (240, 235, 200), (860, 120), 46)
        pygame.draw.circle(screen, (22, 14, 38), (842, 106), 40)
        text(screen, "WILLOW THE WITCH", SCREEN_W // 2, 60, FONT_XL, GOLD, "midtop")
        text(screen, "friendship, feuds, favors, and one inherited cauldron",
             SCREEN_W // 2, 138, FONT_M, (200, 180, 230), "midtop")
        self.draw_cauldron(SCREEN_W // 2 - 60, 400, t)
        self.menu_witch.draw(screen, t)
        if not AUDIO_OK:
            text(screen, "(no audio device found - running silent)",
                 SCREEN_W // 2, 170, FONT_S, (150, 140, 170), "center")
        bx = SCREEN_W // 2
        r1 = pygame.Rect(bx - 150, 620, 300, 36)
        pygame.draw.rect(screen, (70, 50, 110) if self.hovered(r1) else (50, 36, 84),
                         r1, border_radius=9)
        pygame.draw.rect(screen, GOLD, r1, 2, border_radius=9)
        text(screen, "NEW JOURNEY  (Enter)", bx, 629, FONT_M, GOLD, "center")
        self.title_clicks.append((r1, lambda: setattr(self, "_restart", True)))
        for rect, label, col, fn in (
                (pygame.Rect(bx + 165, 622, 150, 30), "Continue (C)",
                 GREEN if self.has_save() else (110, 105, 125), self.try_continue),
                (pygame.Rect(bx - 315, 622, 150, 30), "Controls (H)",
                 PURPLE, lambda: self.set_overlay("controls"))):
            pygame.draw.rect(screen, (58, 46, 88) if self.hovered(rect) else (40, 32, 58),
                             rect, border_radius=8)
            pygame.draw.rect(screen, col, rect, 1, border_radius=8)
            text(screen, label, rect.centerx, rect.y + 6, FONT_M, col, "center")
            self.title_clicks.append((rect, fn))
        if self.title_note:
            text(screen, self.title_note, SCREEN_W // 2, 596, FONT_S, (255, 200, 150), "center")
        text(screen, "8-bit sound on! Mouse works everywhere. P pauses in game.",
             SCREEN_W // 2, 680, FONT_S, (170, 160, 190), "center")

    # ---- pause / options / controls / confirm ----
    def draw_pause(self):
        self.dim_screen(190)
        y0 = 170 + self.dim_screen(0)
        w, h = 420, 80 + len(PAUSE_ITEMS) * 38 + 20
        x0 = (SCREEN_W - w) // 2
        pygame.draw.rect(screen, (40, 30, 60), (x0, y0, w, h), border_radius=14)
        pygame.draw.rect(screen, GOLD, (x0, y0, w, h), 3, border_radius=14)
        text(screen, "PAUSED", SCREEN_W // 2, y0 + 16, FONT_L, GOLD, "midtop")
        for i, (label, key) in enumerate(PAUSE_ITEMS):
            ryi = y0 + 70 + i * 38
            r = pygame.Rect(x0 + 40, ryi - 4, w - 80, 32)
            self.add_click(r, lambda kk=key: self.pause_action(kk))
            sel, hov = i == self.pause_sel, self.hovered(r)
            if sel or hov:
                pygame.draw.rect(screen, (80, 60, 120) if sel else (64, 50, 96), r, border_radius=7)
            text(screen, ("> " if sel else "   ") + label, x0 + 56, ryi, FONT_M,
                 GOLD if sel else (215, 205, 230))
        text(screen, "UP/DOWN + E, or click.  ESC resumes.  Save autosaves each morning.",
             SCREEN_W // 2, y0 + h - 24, FONT_S, GREY, "center")

    def draw_options(self):
        rx, ry, wu = self.panel("OPTIONS", len(SETTING_ITEMS), extra=80, w=780)
        for i, (key, label, kind) in enumerate(SETTING_ITEMS):
            ryi = ry + i * 34
            self.menu_row(i, ryi, rx, wu - 150,
                          lambda ii=i: self._options_toggle(ii))
            text(screen, label, rx + 8, ryi, FONT_M, WHITE)
            if kind == "bool":
                on = self.settings.get(key, True)
                vr = pygame.Rect(rx + wu - 120, ryi - 2, 100, 26)
                pygame.draw.rect(screen, (30, 24, 44), vr, border_radius=6)
                pygame.draw.rect(screen, GREEN if on else GREY, vr, 2, border_radius=6)
                text(screen, "ON " if on else "OFF", vr.centerx, ryi + 2, FONT_S,
                     GREEN if on else GREY, "center")
                self.add_click(vr, lambda ii=i: self._options_toggle(ii))
            else:
                v = self.settings.get(key, 65)
                vr = pygame.Rect(rx + wu - 120, ryi - 2, 100, 26)
                pygame.draw.rect(screen, (30, 24, 44), vr, border_radius=6)
                bar(screen, vr.x + 3, ryi + 1, 66, 22, v / 100.0, GOLD, bg=(30, 24, 44), radius=5)
                text(screen, "%d%%" % v, rx + wu - 46, ryi + 2, FONT_S, GOLD)
                self.add_click(vr, lambda ii=i: self._options_toggle(ii))
        text(screen, "E / SPACE / click: toggle & cycle   |   LEFT/RIGHT: adjust volumes",
             rx + wu // 2, ry + len(SETTING_ITEMS) * 34 + 16, FONT_S, GREY, "center")
        text(screen, "ESC: back", rx + wu // 2, ry + len(SETTING_ITEMS) * 34 + 40,
             FONT_S, GREY, "center")

    def draw_controls(self):
        w, h = 860, 560
        x0 = (SCREEN_W - w) // 2
        y0 = 100 + self.dim_screen(185)
        pygame.draw.rect(screen, (40, 30, 60), (x0, y0, w, h), border_radius=14)
        pygame.draw.rect(screen, PURPLE, (x0, y0, w, h), 3, border_radius=14)
        text(screen, "CONTROLS & HELP", SCREEN_W // 2, y0 + 14, FONT_L, GOLD, "midtop")
        for c, col in enumerate(CONTROLS_COLS):
            xx, yy = x0 + 40 + c * (w // 2), y0 + 70
            for ln in col:
                is_head = bool(ln) and not ln.startswith(" ") and ln.isupper()
                text(screen, ln, xx, yy, FONT_S, (200, 170, 240) if is_head else (215, 210, 230))
                yy += 21
        text(screen, "Tips: brew quality pays x2.1 | gift Concord to end feuds | rumors reveal landmarks",
             SCREEN_W // 2, y0 + h - 50, FONT_S, (180, 170, 200), "center")
        if int(self.time * 2) % 2 == 0:
            text(screen, "any key / click to go back", SCREEN_W // 2, y0 + h - 26, FONT_S, GREY, "center")
        self.add_click(pygame.Rect(x0, y0, w, h),
                       lambda: setattr(self, "overlay", self._menu_back))

    def draw_confirm(self):
        c = self.confirm
        lines = []
        for ln in c["lines"]:
            lines += wrap_text(ln, FONT_M, 560) if ln else [""]
        w, h = 640, 150 + len(lines) * 26
        x0 = (SCREEN_W - w) // 2
        y0 = 230 + self.dim_screen(205)
        pygame.draw.rect(screen, (40, 28, 62), (x0, y0, w, h), border_radius=14)
        pygame.draw.rect(screen, GOLD, (x0, y0, w, h), 3, border_radius=14)
        text(screen, c["title"], SCREEN_W // 2, y0 + 16, FONT_L, GOLD, "midtop")
        yy = y0 + 66
        for ln in lines:
            text(screen, ln, SCREEN_W // 2, yy, FONT_M, (225, 218, 235), "center")
            yy += 26
        for i, lbl in enumerate(["Yes, do it", "No, cancel"]):
            r = pygame.Rect(SCREEN_W // 2 - 180 + i * 190, yy + 8, 170, 34)
            self.add_click(r, lambda ii=i: self._confirm_pick(ii))
            pygame.draw.rect(screen, (86, 60, 130) if (i == c["sel"] or self.hovered(r))
                             else (44, 34, 66), r, border_radius=8)
            pygame.draw.rect(screen, GREEN if i == 0 else GREY, r, 2, border_radius=8)
            text(screen, lbl, r.centerx, yy + 16, FONT_M,
                 WHITE if i == c["sel"] else (200, 195, 215), "center")

    # ---- story / decision / chronicle ----
    def draw_story(self):
        sv = self.story_view
        lines = []
        for ln in sv["lines"]:
            lines += wrap_text(ln, FONT_M, 760) if ln else [""]
        w, h = 860, 150 + len(lines) * 26
        x0 = (SCREEN_W - w) // 2
        y0 = max(60, (SCREEN_H - h) // 2) + self.dim_screen(200)
        pygame.draw.rect(screen, (40, 28, 62), (x0, y0, w, h), border_radius=14)
        pygame.draw.rect(screen, GOLD, (x0, y0, w, h), 3, border_radius=14)
        text(screen, sv["title"], SCREEN_W // 2, y0 + 18, FONT_L, GOLD, "midtop")
        pygame.draw.line(screen, PURPLE, (x0 + 60, y0 + 58), (x0 + w - 60, y0 + 58), 2)
        yy = y0 + 76
        for ln in lines:
            text(screen, ln, SCREEN_W // 2, yy, FONT_M, (225, 218, 235), "center")
            yy += 26
        r = pygame.Rect(SCREEN_W // 2 - 110, y0 + h - 44, 220, 30)
        self.add_click(r, lambda: setattr(self, "overlay", None))
        pygame.draw.rect(screen, (60, 46, 92) if self.hovered(r) else (44, 34, 66),
                         r, border_radius=8)
        if int(self.time * 2) % 2 == 0:
            text(screen, "E / ENTER to continue", SCREEN_W // 2, y0 + h - 38, FONT_S, GREY, "center")

    def draw_decision(self):
        d = self.decision
        lines = []
        for ln in d["lines"]:
            lines += wrap_text(ln, FONT_M, 720) if ln else [""]
        w = 820
        h = 160 + len(lines) * 26 + len(d["options"]) * 36
        x0 = (SCREEN_W - w) // 2
        y0 = max(50, (SCREEN_H - h) // 2) + self.dim_screen(205)
        pygame.draw.rect(screen, (40, 28, 62), (x0, y0, w, h), border_radius=14)
        pygame.draw.rect(screen, GOLD, (x0, y0, w, h), 3, border_radius=14)
        text(screen, d["title"], SCREEN_W // 2, y0 + 18, FONT_L, GOLD, "midtop")
        pygame.draw.line(screen, PURPLE, (x0 + 60, y0 + 58), (x0 + w - 60, y0 + 58), 2)
        yy = y0 + 74
        for ln in lines:
            text(screen, ln, SCREEN_W // 2, yy, FONT_M, (225, 218, 235), "center")
            yy += 26
        yy += 10
        for i, (label, cb) in enumerate(d["options"]):
            r = pygame.Rect(x0 + 120, yy - 5, w - 240, 30)
            self.add_click(r, lambda ii=i, f=cb: self._decision_pick(ii, f))
            sel, hov = i == d["sel"], self.hovered(r)
            if sel or hov:
                pygame.draw.rect(screen, (80, 56, 118) if sel else (66, 48, 98), r, border_radius=7)
            text(screen, ("> " if sel else "   ") + label, SCREEN_W // 2, yy, FONT_M,
                 GOLD if sel else (210, 200, 230), "center")
            yy += 36
        text(screen, "UP/DOWN: choose   E: decide   ESC: walk away",
             SCREEN_W // 2, y0 + h - 28, FONT_S, GREY, "center")

    def draw_chronicle(self):
        w, h = 780, 560
        x0 = (SCREEN_W - w) // 2
        y0 = 100 + self.dim_screen(185)
        pygame.draw.rect(screen, (52, 38, 40), (x0, y0, w, h), border_radius=12)
        pygame.draw.rect(screen, (205, 165, 100), (x0, y0, w, h), 3, border_radius=12)
        text(screen, "THE CHRONICLE OF WILLOW", SCREEN_W // 2, y0 + 12, FONT_L, GOLD, "midtop")
        text(screen, "as the vale remembers it", SCREEN_W // 2, y0 + 46, FONT_S, GREY, "center")
        n = len(self.chronicle)
        if not n:
            text(screen, "(blank pages await)", SCREEN_W // 2, y0 + 120, FONT_M, GREY, "center")
        start = max(0, min(self.chronicle_sel - CHRON_ROWS // 2, max(0, n - CHRON_ROWS)))
        yy = y0 + 76
        for i in range(start, min(n, start + CHRON_ROWS)):
            e = self.chronicle[i]
            r = pygame.Rect(x0 + 14, yy - 4, w - 28, 34)
            self.add_click(r, lambda ii=i: setattr(self, "chronicle_sel", ii))
            if i == self.chronicle_sel or self.hovered(r):
                pygame.draw.rect(screen, (80, 56, 50) if i == self.chronicle_sel else (66, 48, 44),
                                 r, border_radius=5)
            text(screen, "Day %d" % e["day"], x0 + 26, yy, FONT_S, (200, 160, 100))
            for j, ln in enumerate(wrap_text(e["text"], FONT_S, w - 130)[:2]):
                text(screen, ln, x0 + 96, yy + j * 19, FONT_S, WHITE)
            yy += 38
        if start > 0:
            r = pygame.Rect(x0 + w - 60, y0 + 62, 40, 26)
            self.add_click(r, lambda: setattr(self, "chronicle_sel",
                                              max(0, self.chronicle_sel - CHRON_ROWS)))
            text(screen, "^ more", r.x, r.y + 5, FONT_S, GOLD)
        if start + CHRON_ROWS < n:
            r = pygame.Rect(x0 + w - 60, y0 + h - 60, 40, 26)
            self.add_click(r, lambda: setattr(self, "chronicle_sel",
                                              min(n - 1, self.chronicle_sel + CHRON_ROWS)))
            text(screen, "v more", r.x, r.y + 5, FONT_S, GOLD)
        text(screen, "Day %d  |  entry %d/%d  |  UP/DOWN or wheel: scroll  |  J/ESC: close"
             % (self.day, self.chronicle_sel + 1, max(1, n)),
             SCREEN_W // 2, y0 + h - 28, FONT_S, GREY, "center")

    # ---- cauldron & brewing ----
    def draw_craft(self):
        tabs = CRAFT_TABS
        cur = tabs[self.craft_tab][1]
        rx, ry, wu = self.panel("THE CAULDRON  -  Brewing Lv %d" % self.brew_level,
                                len(cur), extra=160, w=1000)
        lw = 555
        dx, dw = rx + lw + 24, wu - lw - 24
        # tabs
        tx = rx
        for i, (tn, _) in enumerate(tabs):
            lbl = ("[ %s ]" % tn) if i == self.craft_tab else tn
            r = pygame.Rect(tx - 4, ry - 32, FONT_M.size(lbl)[0] + 12, 26)
            self.add_click(r, lambda ii=i: (setattr(self, "craft_tab", ii),
                                            setattr(self, "overlay_idx", 0)))
            if i == self.craft_tab:
                pygame.draw.rect(screen, (60, 44, 92), r, border_radius=6)
            elif self.hovered(r):
                pygame.draw.rect(screen, (48, 36, 72), r, border_radius=6)
            text(screen, lbl, tx, ry - 30, FONT_M, GOLD if i == self.craft_tab else GREY)
            tx = r.right + 14
        text(screen, "A/D: tabs  |  wheel: scroll", rx + wu, ry - 30, FONT_S, GREY, "topright")
        # xp
        bar(screen, rx + wu - 200, 96, 190, 12, self.brew_xp / self.xp_next(), PURPLE)
        text(screen, "%d/%d xp to Lv %d" % (self.brew_xp, self.xp_next(), self.brew_level + 1),
             rx + wu - 105, 110, FONT_S, GREY, "midtop")
        # rows
        for i, pid in enumerate(cur):
            pd = pot_def(pid)
            known = pid not in SECRET_POTIONS or pid in self.known_secrets
            ryi = ry + i * 34
            self.menu_row(i, ryi, rx, lw,
                          lambda ii=i: self.row_click(ii, self.overlay_confirm))
            if not known:
                text(screen, "? ? ?" + ("  (story-sealed)" if pd.get("legendary")
                                        else "  (undiscovered)"),
                     rx + 24, ryi, FONT_M, PURPLE if pd.get("legendary") else (115, 105, 135))
                continue
            text(screen, ("* " if pid in SECRET_POTIONS else "") + pd["name"],
                 rx + 24, ryi, FONT_M,
                 (255, 170, 220) if pd.get("legendary") else
                 (GOLD if pid in SECRET_POTIONS else WHITE))
            arr = self.potions.get(pid, [0, 0, 0, 0])
            text(screen, "x%d" % sum(arr), rx + 310, ryi + 3, FONT_S, GREY)
            for t in range(4):
                if arr[t]:
                    sx = rx + lw - 150 + t * 34
                    pygame.draw.rect(screen, QUALITY[t]["color"], (sx, ryi + 4, 11, 11), border_radius=2)
                    text(screen, str(arr[t]), sx + 14, ryi + 2, FONT_S, QUALITY[t]["color"])
            craftable = all(self.items.get(ing, 0) >= nd for ing, nd in pd["recipe"].items())
            text(screen, "OK" if craftable else "missing", rx + lw - 8, ryi + 3, FONT_S,
                 GREEN if craftable else (200, 90, 90), "topright")
        # detail panel
        pygame.draw.line(screen, (90, 70, 120), (dx - 14, ry - 8), (dx - 14, ry + len(cur) * 34), 1)
        spid = cur[min(self.overlay_idx, len(cur) - 1)]
        pd = pot_def(spid)
        known = spid not in SECRET_POTIONS or spid in self.known_secrets
        yy = ry
        if not known:
            pygame.draw.circle(screen, (80, 70, 100), (dx + 14, yy + 10), 12)
            text(screen, "??? " + ("(story-sealed)" if pd.get("legendary") else "(secret)"),
                 dx + 34, yy, FONT_M, PURPLE if pd.get("legendary") else GREY)
            yy += 34
            if pd.get("legendary"):
                hints = ["This legend will be revealed",
                         "as the story unfolds - see the Chronicle (J)."]
            else:
                hints = ["Undiscovered recipes are found by",
                         "experimenting at the cauldron (X)."]
            for h in hints:
                text(screen, h, dx, yy, FONT_S, GREY); yy += 20
        else:
            orb(screen, dx + 14, yy + 10, 12, pd["color"])
            text(screen, pd["name"], dx + 34, yy, FONT_M,
                 (255, 170, 220) if pd.get("legendary") else WHITE)
            yy += 32
            text(screen, "Sell price (today):", dx, yy, FONT_S, (200, 170, 240)); yy += 20
            for t in range(4):
                pygame.draw.rect(screen, QUALITY[t]["color"], (dx, yy + 3, 10, 10), border_radius=2)
                text(screen, "%s  %dg" % (QUALITY[t]["name"],
                     int(pd["price"] * QUALITY[t]["mult"] * self.sale_mult())),
                     dx + 18, yy, FONT_S, QUALITY[t]["color"])
                yy += 19
            yy += 6
            text(screen, "Recipe:", dx, yy, FONT_S, (200, 170, 240)); yy += 20
            for ing, need in pd["recipe"].items():
                have = self.items.get(ing, 0)
                orb(screen, dx + 5, yy + 8, 5, INGREDIENTS[ing]["color"])
                text(screen, "%dx %s  (have %d)" % (need, INGREDIENTS[ing]["name"], have),
                     dx + 18, yy, FONT_S, GREEN if have >= need else RED)
                yy += 19
            beast_ings = [i for i in pd["recipe"] if INGREDIENTS[i].get("monster")]
            if beast_ings:
                srcs = monster_sources(*beast_ings)
                if srcs:
                    text(screen, "Source: hunt " + ", ".join(srcs), dx, yy, FONT_S, (255, 210, 130))
                    yy += 20
            yy += 2
            for key, colr in ((pd.get("desc"), (220, 215, 235)),
                              (self.effect_desc(pd), (180, 220, 190))):
                if key:
                    for ln in wrap_text(key, FONT_S, dw)[:2]:
                        text(screen, ln, dx, yy, FONT_S, colr); yy += 18
            if pd.get("special") == "gift":
                text(screen, "Concord in stock: %d" % self.potion_total("concord"),
                     dx, yy, FONT_S, (255, 180, 200)); yy += 18
        # footer buttons
        fy = ry + len(cur) * 34 + 10
        cat = CATALYSTS[self.catalyst]["name"] if self.catalyst != "none" else "None"
        if self.catalyst != "none":
            cat += " x%d" % self.items.get(self.catalyst, 0)
        x = rx
        for lbl, key in (("E Brew", pygame.K_e), ("Q Quick", pygame.K_q), ("F Drink", pygame.K_f),
                         ("V Sell 1", pygame.K_v), ("B Sell ALL", pygame.K_b),
                         ("C Catalyst: %s" % cat, pygame.K_c),
                         ("X Experiment", pygame.K_x), ("R Refine", pygame.K_r)):
            x = self.menu_button(lbl, x, fy, lambda kk=key: self.craft_action(kk), GOLD)
            if x > rx + wu - 160:
                x, fy = rx, fy + 26
        fy += 30
        gc = "Grand Cauldron: 35% double brews" if "cauldron2" in self.buildings \
            else "Grand Cauldron inactive"
        text(screen, "%s  |  squares = stock by quality (R/S/F/E)  |  * = secret / legend  |  "
             "click a row twice to brew" % gc, rx + wu // 2, fy, FONT_S, (120, 110, 140), "center")
        text(screen, "ESC: close", rx + wu // 2, fy + 20, FONT_S, GREY, "center")

    def draw_brew(self):
        b = self.brew
        if not b:
            return
        pd = pot_def(b["pid"])
        self.dim_screen(185)
        text(screen, "BREWING: %s" % pd["name"], SCREEN_W // 2, 96, FONT_L, pd["color"], "midtop")
        fren = (0.5 + b["needle"] * 2.2) if b["phase"] == "heat" else 1.8
        self.draw_cauldron(512, 400, self.time, liquid=pd["color"], fren=fren)
        cat = CATALYSTS[b["cat"]]["name"] if b["cat"] != "none" else "none"
        clar = "   [Clarity: needle slowed]" if self.buffs.get("clarity", 0) > 0 else ""
        text(screen, "Skill: %d    Lv bonus +%d    Catalyst: %s%s"
             % (b["score"], self.level_bonus(), cat, clar),
             SCREEN_W // 2, 460, FONT_M, (220, 210, 240), "center")
        if b["phase"] == "heat":
            gx, gy, gw, gh = 312, 520, 400, 24
            pygame.draw.rect(screen, (120, 45, 40), (gx, gy, gw, gh), border_radius=8)
            pygame.draw.rect(screen, (200, 170, 60), (gx + int(gw * 0.24), gy, int(gw * 0.18), gh))
            pygame.draw.rect(screen, (200, 170, 60), (gx + int(gw * 0.58), gy, int(gw * 0.18), gh))
            pygame.draw.rect(screen, (90, 200, 90), (gx + int(gw * 0.42), gy, int(gw * 0.16), gh),
                             border_radius=4)
            nx = gx + int(b["needle"] * gw)
            pygame.draw.polygon(screen, WHITE, [(nx - 8, gy - 10), (nx + 8, gy - 10), (nx, gy - 1)])
            text(screen, "cold", gx, gy + gh + 6, FONT_S, (150, 190, 230))
            text(screen, "PERFECT", gx + gw // 2, gy + gh + 6, FONT_S, GREEN, "center")
            text(screen, "ruin", gx + gw, gy + gh + 6, FONT_S, RED, "topright")
            text(screen, "HEAT THE CAULDRON - press SPACE when the needle hits the green zone!",
                 SCREEN_W // 2, 580, FONT_M, WHITE, "center")
        else:
            cx, cy, cr = 512, 630, 58
            pygame.draw.circle(screen, (40, 32, 56), (cx, cy), cr + 6)
            pygame.draw.circle(screen, (70, 58, 96), (cx, cy), cr + 6, 3)
            s, e = b["target"] - 0.55, b["target"] + 0.55
            if s < 0:
                s += math.tau; e += math.tau
            pygame.draw.arc(screen, GOLD, pygame.Rect(cx - cr, cy - cr, cr * 2, cr * 2), s, e, 8)
            px, py = cx + math.cos(b["ang"]) * (cr - 4), cy + math.sin(b["ang"]) * (cr - 4)
            pygame.draw.circle(screen, WHITE, (int(px), int(py)), 6)
            pygame.draw.line(screen, (150, 130, 180), (cx, cy), (px, py), 1)
            text(screen, "STIR! Press SPACE when the spark crosses the golden arc  (%d/3)" % b["stirs"],
                 SCREEN_W // 2, 705, FONT_M, WHITE, "center")
        text(screen, "SPACE/E: lock in      ESC: cancel (ingredients refunded)",
             SCREEN_W // 2, 738, FONT_S, GREY, "center")

    def draw_exp(self):
        its = sorted(self.items, key=lambda n: INGREDIENTS[n]["name"])
        self.exp["sel"] = min(self.exp["sel"], max(0, len(its) - 1))
        rows = 2 + max(len(its), 4)
        rx, ry, wu = self.panel("EXPERIMENT CAULDRON", rows, extra=112, w=680)
        locked = [s for s in SECRET_POTIONS if s not in self.known_secrets and
                  not SECRET_POTIONS[s].get("legendary")]
        text(screen, "%d secret recipe(s) still undiscovered - every experiment has a chance!"
             % len(locked), rx + wu // 2, ry - 26, FONT_M, PURPLE, "center")
        for si in range(2):
            sxx = rx + 40 + si * 190
            pygame.draw.rect(screen, (30, 24, 44), (sxx, ry, 170, 30), border_radius=6)
            pygame.draw.rect(screen, PURPLE, (sxx, ry, 170, 30), 2, border_radius=6)
            v = self.exp["slots"][si]
            text(screen, INGREDIENTS[v]["name"] if v else "? ? ?", sxx + 85, ry + 7, FONT_M,
                 INGREDIENTS[v]["color"] if v else GREY, "center")
        text(screen, "+", rx + 222, ry + 4, FONT_L, GREY)
        text(screen, "INGREDIENTS - pick two (monster parts work too!):",
             rx + 8, ry + 40, FONT_S, (200, 170, 240))
        ly = ry + 64
        if not its:
            text(screen, "(you have no ingredients - go gathering or hunting!)", rx + 24, ly, FONT_M, GREY)
        for i, it in enumerate(its):
            yy = ly + i * 26
            if i == self.exp["sel"]:
                pygame.draw.rect(screen, (80, 56, 118), (rx, yy - 3, wu, 24), border_radius=5)
            pygame.draw.circle(screen, INGREDIENTS[it]["color"], (rx + 14, yy + 8), 6)
            tag = " [monster]" if INGREDIENTS[it].get("monster") else ""
            text(screen, "%s  x%d%s" % (INGREDIENTS[it]["name"], self.items[it], tag),
                 rx + 30, yy, FONT_M, WHITE)
        y = ry + rows * 34 - 20
        text(screen, "UP/DOWN: select   E: add to slot / run   C: clear   X/ESC: back",
             rx + wu // 2, y, FONT_S, GREY, "center")
        last, lc = self.exp["last"]
        text(screen, last, rx + wu // 2, y + 24, FONT_M, lc, "center")

    # ---- bestiary ----
    def draw_bestiary(self):
        rx, ry, wu = self.panel("BESTIARY - MONSTER MATERIALS", len(MONSTERS), extra=96, w=920)
        lw = wu - 250
        text(screen, "Every kill drops parts. Mastery Lv1@5, Lv2@15, Lv3@30 kills: "
             "+1 guaranteed drop per level.", rx, ry - 28, FONT_S, (255, 210, 130))
        mids = list(MONSTERS.keys())
        for i, mid in enumerate(mids):
            d = MONSTERS[mid]
            ryi = ry + i * 34
            self.menu_row(i, ryi, rx, lw, lambda ii=i: setattr(self, "overlay_idx", ii))
            cnt = self.kills.get(mid, 0)
            lvl = mastery_level(cnt)
            pygame.draw.circle(screen, d["c"], (rx + 10, ryi + 10), 7)
            text(screen, d["name"], rx + 24, ryi, FONT_M, WHITE)
            text(screen, "kills %d" % cnt, rx + 160, ryi + 3, FONT_S, GREY)
            text(screen, "mastery %s" % ("I" * lvl if lvl else "-"),
                 rx + 225, ryi + 3, FONT_S, GOLD if lvl else GREY)
            drops = "Always: %s" % INGREDIENTS[d["guarantee"]]["name"] if d.get("guarantee") else ""
            for it, ch in d.get("drops", []):
                drops += " | %d%% %s" % (int(ch * 100), INGREDIENTS[it]["name"])
            if d.get("rare"):
                drops += " | RARE %d%% %s" % (int(d["rare"][1] * 100),
                                              INGREDIENTS[d["rare"][0]]["name"])
            text(screen, drops, rx + 310, ryi + 3, FONT_S, (215, 235, 190))
        # portrait (render the real monster body, upscaled 3x)
        px0 = rx + lw + 20
        sel_mid = mids[min(self.overlay_idx, len(mids) - 1)]
        d = MONSTERS[sel_mid]
        tmp = pygame.Surface((80, 90), pygame.SRCALPHA)
        m = Monster(sel_mid, 40, 62)
        getattr(m, "draw_" + sel_mid)(tmp, 40, 62)
        img = pygame.transform.smoothscale(tmp, (200, 225))
        pygame.draw.rect(screen, (30, 24, 44), (px0, ry, 200, 225), border_radius=10)
        screen.blit(img, (px0, ry))
        pygame.draw.rect(screen, d["c"], (px0, ry, 200, 225), 2, border_radius=10)
        text(screen, d["name"], px0 + 100, ry + 232, FONT_M, WHITE, "center")
        names = sorted({n for p in MONSTER_DROPS[sel_mid] for n in INGREDIENT_USES.get(p, [])})
        yy = ry + 258
        for ln in wrap_text("Used in: " + (", ".join(names) if names else "(none yet)"),
                            FONT_S, wu - lw - 20)[:3]:
            text(screen, ln, px0, yy, FONT_S, (200, 170, 240)); yy += 18
        text(screen, "UP/DOWN: browse   B/ESC: close",
             rx + lw // 2, ry + len(mids) * 34 + 12, FONT_S, GREY, "center")

    # ---- orders / villagers ----
    def draw_orders(self):
        if self.order_tab == 0:
            n, extra, title = max(len(self.board), 1), 170, "ORDER BOARD"
        elif self.order_tab == 1:
            n, extra, title = max(len(self.orders) + len(self.favors), 1), 170, "MY CONTRACTS"
        else:
            n, extra, title = len(CUSTOMERS), 90, "THE VILLAGERS"
        rx, ry, wu = self.panel(title, n, extra=extra, w=860)
        counts = ["(%d)" % len(self.board), "(%d+%d)" % (len(self.orders), len(self.favors)),
                  "(%d fam)" % len(self.family_names())]
        tx = rx
        for i, lbl in enumerate(["BOARD", "CONTRACTS", "VILLAGERS"]):
            lbl2 = ("[ %s %s ]" % (lbl, counts[i])) if i == self.order_tab \
                else "%s %s" % (lbl, counts[i])
            r = pygame.Rect(tx - 4, ry - 32, FONT_M.size(lbl2)[0] + 12, 26)
            self.add_click(r, lambda ii=i: (setattr(self, "order_tab", ii),
                                            setattr(self, "overlay_idx", 0)))
            if i == self.order_tab:
                pygame.draw.rect(screen, (60, 44, 92), r, border_radius=6)
            elif self.hovered(r):
                pygame.draw.rect(screen, (48, 36, 72), r, border_radius=6)
            text(screen, lbl2, tx, ry - 30, FONT_M, GOLD if i == self.order_tab else GREY)
            tx = r.right + 12
        text(screen, "A/D: tabs", rx + wu, ry - 30, FONT_S, GREY, "topright")
        if self.order_tab == 0:
            self._orders_board(rx, ry, wu, n)
        elif self.order_tab == 1:
            self._orders_contracts(rx, ry, wu, n)
        else:
            self._orders_villagers(rx, ry, wu, n)

    def _orders_board(self, rx, ry, wu, n):
        if not self.board:
            text(screen, "The board is empty - sleep in your cottage for new orders.",
                 rx + wu // 2, ry + 24, FONT_M, GREY, "center")
        for i, o in enumerate(self.board):
            p = pot_def(o["pid"])
            ryi = ry + i * 34
            self.menu_row(i, ryi, rx, wu,
                          lambda ii=i: self.row_click(ii, self.accept_order))
            pygame.draw.circle(screen, p["color"], (rx + 8, ryi + 11), 7)
            rel = self.rel.get(o["who"], 10)
            text(screen, "%s:  %dx %s" % (o["who"], o["qty"], p["name"]), rx + 24, ryi, FONT_M, WHITE)
            text(screen, self.rel_tier(rel), rx + 360, ryi + 3, FONT_S,
                 GOLD if rel >= 60 else (GREEN if rel >= 40 else (RED if rel <= -40 else GREY)))
            text(screen, "Standard+" if o["minq"] == 1 else "FINE ONLY", rx + 500, ryi + 3, FONT_S,
                 GREY if o["minq"] == 1 else (120, 220, 255))
            text(screen, "%dg  due day %d" % (o["reward"], o["due"]), rx + wu - 4, ryi + 2,
                 FONT_S, RED if o["due"] - self.day <= 1 else (230, 210, 160), "topright")
        if self.board and self.overlay_idx < len(self.board):
            o = self.board[self.overlay_idx]
            yy = ry + n * 34 + 8
            pygame.draw.line(screen, (90, 70, 120), (rx, yy - 6), (rx + wu, yy - 6), 1)
            for j, ln in enumerate(wrap_text(o["line"], FONT_S, wu - 20)[:3]):
                text(screen, ln, rx, yy + j * 20, FONT_S, (225, 215, 235))
            self.menu_button("E Accept", rx, yy + 66, self.accept_order, GOLD)
            self.menu_button("R Reject (%s won't like it)" % o["who"], rx + 110, yy + 66,
                             self.reject_order, RED)

    def _orders_contracts(self, rx, ry, wu, n):
        entries = [("order", o) for o in self.orders] + [("favor", f) for f in self.favors]
        if not entries:
            text(screen, "Nothing yet - accept orders from the BOARD tab.",
                 rx + wu // 2, ry + 24, FONT_M, GREY, "center")
        for i, (kind, e) in enumerate(entries):
            ryi = ry + i * 34
            self.menu_row(i, ryi, rx, wu,
                          lambda ii=i: self.row_click(ii, self.overlay_confirm))
            if kind == "order":
                p = pot_def(e["pid"])
                pygame.draw.circle(screen, p["color"], (rx + 8, ryi + 11), 7)
                have = self.pot_count_ge(e["pid"], e["minq"])
                text(screen, "%s:  %dx %s" % (e["who"], e["qty"], p["name"]), rx + 24, ryi, FONT_M, WHITE)
                text(screen, "brewed %d/%d" % (have, e["qty"]), rx + 400, ryi + 2, FONT_S,
                     GREEN if have >= e["qty"] else RED)
            else:
                pygame.draw.circle(screen, (255, 180, 120), (rx + 8, ryi + 11), 7)
                nm = (INGREDIENTS[e["target"]]["name"] if e["kind"] == "item"
                      else MONSTERS[e["target"]]["name"])
                prog = e["have"] if e["kind"] == "hunt" else \
                    min(e["need"], self.items.get(e["target"], 0))
                text(screen, "[FAVOR] %s: %s" % (e["who"],
                     ("fetch %dx %s" if e["kind"] == "item" else "hunt %dx %s") % (e["need"], nm)),
                     rx + 24, ryi, FONT_M, (255, 210, 160))
                text(screen, "ready %d/%d" % (prog, e["need"]), rx + 400, ryi + 2, FONT_S,
                     GREEN if prog >= e["need"] else GREY)
            text(screen, "%dg  due day %d" % (e["reward"], e["due"]), rx + wu - 4, ryi + 2,
                 FONT_S, RED if e["due"] - self.day <= 1 else (230, 210, 160), "topright")
        if entries and self.overlay_idx < len(entries):
            _, e = entries[self.overlay_idx]
            yy = ry + n * 34 + 8
            pygame.draw.line(screen, (90, 70, 120), (rx, yy - 6), (rx + wu, yy - 6), 1)
            for j, ln in enumerate(wrap_text(e["line"], FONT_S, wu - 20)[:2]):
                text(screen, ln, rx, yy + j * 20, FONT_S, (225, 215, 235))
            self.menu_button("E Deliver / Hand in", rx, yy + 44, self.overlay_confirm, GOLD)

    def _orders_villagers(self, rx, ry, wu, n):
        names = self.villager_list()
        text(screen, "Found family: %d   |   Active feuds: %d   |   sorted by closeness"
             % (len(self.family_names()),
                len([f for f in self.feuds if not f["done"]])),
             rx + wu // 2, ry - 28, FONT_S, (230, 200, 240), "center")
        bar_w = 120
        for i, name in enumerate(names):
            rel = self.rel[name]
            ryi = ry + i * 34
            self.menu_row(i, ryi, rx, wu,
                          lambda ii=i: self.row_click(
                              ii, lambda: self.chat_npc(
                                  names[min(self.overlay_idx, len(names) - 1)])))
            pygame.draw.circle(screen, PERSONA_COLOR[PERSONA_OF[name]], (rx + 10, ryi + 10), 7)
            text(screen, name, rx + 24, ryi, FONT_M, WHITE)
            bx = rx + 240
            bar(screen, bx, ryi + 3, bar_w, 12, (rel + 100) / 200.0,
                GOLD if rel >= 60 else (GREEN if rel >= 40 else (RED if rel <= -40 else PURPLE)))
            text(screen, self.rel_tier(rel), bx + bar_w + 10, ryi + 2, FONT_S,
                 GOLD if rel >= 60 else (RED if rel <= -40 else GREY))
            tags = ""
            if FAMILY_LINKS.get(name):
                tags = "kin: " + "/".join(FAMILY_LINKS[name])
            f = self.feud_involving(name)
            if f:
                tags += "   FEUDING with %s" % (f["b"] if name == f["a"] else f["a"])
            if tags:
                text(screen, tags, bx + bar_w + 165, ryi + 3, FONT_S,
                     RED if f else (170, 150, 190))
        yy = ry + n * 34 + 6
        pygame.draw.line(screen, (90, 70, 120), (rx, yy - 4), (rx + wu, yy - 4), 1)
        x = self.menu_button("E Chat (+1, once/day)", rx, yy,
                             lambda: self.orders_action(pygame.K_e), GREEN)
        self.menu_button("G Gift Concord (x%d) - mends feuds" % self.potion_total("concord"),
                         x, yy, lambda: self.orders_action(pygame.K_g), (255, 180, 200))
        text(screen, "Family visits your cottage | kin share your standing (+-40%)",
             rx, yy + 28, FONT_S, (170, 150, 190))

    # ---- build / travel / satchel / ledger ----
    def draw_build(self):
        keys = list(BUILDINGS.keys())
        rx, ry, wu = self.panel("CONSTRUCTION PLOT", len(keys), extra=140, w=780)
        lw = wu - 140
        for i, k in enumerate(keys):
            b = BUILDINGS[k]
            ryi = ry + i * 34
            self.menu_row(i, ryi, rx, lw,
                          lambda ii=i: self.row_click(
                              ii, lambda: self.build_request(
                                  keys[min(self.overlay_idx, len(keys) - 1)])))
            built = k in self.buildings
            locked = b["req"] is not None and b["req"] not in self.buildings
            suffix = "  - BUILT" if built else \
                ("  (needs %s)" % BUILDINGS[b["req"]]["name"] if locked else "")
            text(screen, b["name"] + suffix, rx + 8, ryi, FONT_M,
                 GOLD if built else (GREY if locked else WHITE))
            if built:
                text(screen, "DONE", rx + lw - 4, ryi + 2, FONT_S, GREEN, "topright")
            else:
                text(screen, "%dg" % b["cost"], rx + lw - 4, ryi + 2, FONT_S,
                     GREEN if self.gold >= b["cost"] and not locked else RED, "topright")
        sel_k = keys[min(self.overlay_idx, len(keys) - 1)]
        sel = BUILDINGS[sel_k]
        px = rx + lw + 24
        pygame.draw.rect(screen, (30, 24, 44), (px - 8, ry - 4, 120, 90), border_radius=10)
        self.draw_building_icon(sel_k, px + 50, ry + 38, self.time)
        yy = ry + len(keys) * 34 + 8
        for ln in wrap_text(sel["desc"], FONT_M, wu - 20)[:2]:
            text(screen, ln, rx + wu // 2, yy, FONT_M, (210, 200, 230), "center")
            yy += 24
        self.menu_button("E Build (asks to confirm)", rx, yy + 6,
                         lambda: self.build_request(sel_k), GOLD)
        text(screen, "Gold: %dg   |   ESC: close   |   built paths connect automatically" % self.gold,
             rx, yy + 40, FONT_S, GREY)

    def draw_travel(self):
        keys = list(BIOMES.keys())
        rx, ry, wu = self.panel("SIGNPOST - CHOOSE A DESTINATION", len(keys), extra=130, w=820)
        lw = wu - 190
        for i, bid in enumerate(keys):
            b = BIOMES[bid]
            ryi = ry + i * 34
            self.menu_row(i, ryi, rx, lw,
                          lambda ii=i: self.row_click(
                              ii, lambda: self.enter_biome(
                                  list(BIOMES.keys())[min(self.overlay_idx, len(BIOMES) - 1)])))
            text(screen, b["name"] + ("  (new!)" if bid not in self.visited else ""),
                 rx + 8, ryi, FONT_M, WHITE if bid not in self.visited else (215, 215, 225))
            text(screen, "!" * b["danger"], rx + 250, ryi + 2, FONT_M, RED)
            text(screen, ", ".join(INGREDIENTS[p]["name"] for p, _ in b["plants"]),
                 rx + 300, ryi + 3, FONT_S, (215, 235, 190))
        sel_bid = keys[self.overlay_idx]
        b = BIOMES[sel_bid]
        px = rx + lw + 20
        pygame.draw.rect(screen, b["ground"], (px - 6, ry - 6, 170, 120), border_radius=10)
        pygame.draw.rect(screen, b["road"], (px + 10, ry + 70, 140, 10), border_radius=5)
        pygame.draw.ellipse(screen, b["accent"], (px + 14, ry + 16, 60, 24))
        pygame.draw.circle(screen, b["water"], (px + 120, ry + 34), 16)
        self.draw_tree(px + 100, ry + 92)
        mons = ", ".join(MONSTERS[m]["name"] for m in dict.fromkeys(b["monsters"]))
        feats = ", ".join(sorted({k for k, _ in b["terrain"]}))
        yy = ry + len(keys) * 34 + 8
        text(screen, "%s    Monsters: %s" % (b["desc"], mons),
             rx + wu // 2, yy, FONT_S, (210, 200, 230), "center")
        rumor_note = ""
        if self.active_rumor and self.active_rumor["biome"] == sel_bid:
            rumor_note = "   <-- YOUR RUMOR POINTS HERE!"
        text(screen, "Terrain: %s  |  landmarks inside%s" % (feats, rumor_note),
             rx + wu // 2, yy + 22, FONT_S, GOLD if rumor_note else (160, 190, 210), "center")
        self.menu_button("E Set off", rx, yy + 48, lambda: self.enter_biome(sel_bid), GOLD)
        text(screen, "ESC: close", rx + 150, yy + 53, FONT_S, GREY)

    def inv_items_sorted(self):
        if self.inv_sort == "count":
            return sorted(self.items, key=lambda i: -self.items[i])
        if self.inv_sort == "type":
            return sorted(self.items, key=lambda i: (0 if INGREDIENTS[i].get("monster") else 1, i))
        return sorted(self.items, key=lambda i: INGREDIENTS[i]["name"])

    def cycle_inv_sort(self):
        order = ["name", "count", "type"]
        self.inv_sort = order[(order.index(self.inv_sort) + 1) % 3]
        self.sfx("move")

    def _inv_pick(self, idx):
        plist = list(self.potions)
        if idx == self.inv_sel and plist and idx < len(plist):
            self.drink_potion(plist[idx])
        else:
            self.inv_sel = idx
            self.sfx("move")

    def draw_inv(self):
        w = 680
        its = self.inv_items_sorted()
        plist = list(self.potions)
        total = max(len(its), len(plist), 1)
        self.inv_scroll = clamp(self.inv_scroll, 0, max(0, total - SATCHEL_ROWS))
        h = 130 + SATCHEL_ROWS * 28 + 90
        x0 = (SCREEN_W - w) // 2
        y0 = 90 + self.dim_screen(170)
        pygame.draw.rect(screen, (46, 34, 68), (x0, y0, w, h), border_radius=12)
        pygame.draw.rect(screen, PURPLE, (x0, y0, w, h), 3, border_radius=12)
        text(screen, "SATCHEL", SCREEN_W // 2, y0 + 12, FONT_L, GOLD, "midtop")
        self.menu_button("Sort [S]: %s" % {"name": "Name", "count": "Count",
                                           "type": "Type"}[self.inv_sort],
                         x0 + 24, y0 + 48, self.cycle_inv_sort, PURPLE)
        text(screen, "wheel scrolls", x0 + 220, y0 + 53, FONT_S, GREY)
        text(screen, "INGREDIENTS", x0 + 40, y0 + 78, FONT_M, (200, 170, 240))
        text(screen, "POTIONS  [E drinks selected]", x0 + 390, y0 + 78, FONT_M, (200, 170, 240))
        y = y0 + 104
        for idx in range(self.inv_scroll, min(total, self.inv_scroll + SATCHEL_ROWS)):
            yy = y + (idx - self.inv_scroll) * 28
            if idx < len(its):
                item = its[idx]
                r = pygame.Rect(x0 + 24, yy - 3, 330, 26)
                self.add_click(r, lambda: None)
                if self.hovered(r):
                    pygame.draw.rect(screen, (60, 46, 92), r, border_radius=5)
                pygame.draw.circle(screen, INGREDIENTS[item]["color"], (x0 + 46, yy + 8), 6)
                tag = " [monster]" if INGREDIENTS[item].get("monster") else ""
                text(screen, "%s x%d%s" % (INGREDIENTS[item]["name"], self.items[item], tag),
                     x0 + 60, yy, FONT_M, WHITE)
            if idx < len(plist):
                pid = plist[idx]
                arr = self.potions[pid]
                parts = " ".join("%s%d" % (QUALITY[t]["short"], arr[t]) for t in range(4) if arr[t])
                r = pygame.Rect(x0 + 374, yy - 3, w - 400, 26)
                self.add_click(r, lambda pp=idx: self._inv_pick(pp))
                sel = idx == self.inv_sel
                if sel or self.hovered(r):
                    pygame.draw.rect(screen, (96, 66, 140) if sel else (64, 50, 96),
                                     r, border_radius=5)
                if sel:
                    self.inv_sel = idx
                pygame.draw.circle(screen, pot_def(pid)["color"], (x0 + 390, yy + 8), 6)
                text(screen, "%s x%d (%s)" % (pot_def(pid)["name"], sum(arr), parts),
                     x0 + 404, yy, FONT_M, WHITE)
        if total > SATCHEL_ROWS:
            text(screen, "^ more", x0 + w - 84, y0 + 100, FONT_S,
                 GOLD if self.inv_scroll > 0 else (90, 85, 105))
            text(screen, "v more", x0 + w - 84, y0 + h - 66, FONT_S,
                 GOLD if self.inv_scroll + SATCHEL_ROWS < total else (90, 85, 105))
            text(screen, "%d-%d / %d" % (self.inv_scroll + 1,
                 min(total, self.inv_scroll + SATCHEL_ROWS), total),
                 x0 + w - 84, y0 + h - 44, FONT_S, GREY)
        text(screen, "Quality: R=Rough  S=Standard  F=Fine  E=Exquisite",
             x0 + 390, y0 + h - 64, FONT_S, GREY)
        text(screen, "Brewing Lv %d (%d/%d xp)   Gold: %dg   Rep: %+d   Day %d"
             % (self.brew_level, self.brew_xp, self.xp_next(), self.gold, self.rep, self.day),
             SCREEN_W // 2, y0 + h - 34, FONT_M, GOLD, "center")

    def draw_stats(self):
        rx, ry, wu = self.panel("WITCH'S LEDGER  (TAB to close)", 10, extra=170, w=860)
        st = self.stats
        col2 = rx + wu // 2 + 20
        text(screen, "CAREER", rx, ry - 26, FONT_M, (200, 170, 240))
        rows1 = [("Days in the vale", self.day),
                 ("Deliveries completed", st["deliveries"]),
                 ("Orders rejected", st["rejects"]),
                 ("Favors completed", st["favors_done"]),
                 ("Gold earned (total)", "%dg" % st["gold_earned"]),
                 ("Distance wandered", "%d steps" % int(st["distance"]))]
        for i, (k, v) in enumerate(rows1):
            text(screen, k, rx, ry + i * 26, FONT_S, GREY)
            text(screen, str(v), rx + 220, ry + i * 26, FONT_S, WHITE, "topright")
        text(screen, "BREWING & WILDS", col2, ry - 26, FONT_M, (200, 170, 240))
        rows2 = [("Brewing level", "%d  (%d/%d xp)" % (self.brew_level, self.brew_xp, self.xp_next())),
                 ("Potions obtained", st["potions"]),
                 ("Monsters slain", sum(self.kills.values())),
                 ("Landmarks found", st["landmarks"]),
                 ("Feuds resolved", st["feuds_resolved"]),
                 ("Experiments run", st["experiments"]),
                 ("Biomes visited", "%d/5" % len(self.visited))]
        for i, (k, v) in enumerate(rows2):
            text(screen, k, col2, ry + i * 26, FONT_S, GREY)
            text(screen, str(v), col2 + 240, ry + i * 26, FONT_S, WHITE, "topright")
        y = ry + max(len(rows1), len(rows2)) * 26 + 12
        text(screen, "POTION QUALITY MIX", rx, y, FONT_S, (200, 170, 240))
        totalq = max(1, sum(st["quality"]))
        for t in range(4):
            bx = rx + t * 165
            bar(screen, bx, y + 20, 145, 12, st["quality"][t] / totalq, QUALITY[t]["color"])
            text(screen, "%s %d" % (QUALITY[t]["name"], st["quality"][t]),
                 bx + 72, y + 36, FONT_S, QUALITY[t]["color"], "center")
        y2 = y + 62
        text(screen, "SOCIAL", rx, y2, FONT_S, (200, 170, 240))
        fams = self.family_names()
        text(screen, "Found family: %s" % (", ".join(fams) if fams else "-"), rx, y2 + 22, FONT_S, GOLD)
        text(screen, "Reputation: %+d (%s)" % (self.rep, self.rep_tier()),
             rx + 330, y2 + 22, FONT_S, (200, 170, 240))
        text(screen, "Secret recipes known: %d" % len(self.known_secrets),
             rx + 330, y2, FONT_S, (200, 170, 240))

    # ================================================== 7.15 main loop
    def run(self):
        while True:
            dt = min(clock.tick(FPS) / 1000.0, 0.05)
            for e in pygame.event.get():
                self.handle_event(e)
            self.update(dt)
            self.draw()
            if self._restart:
                self.__init__()          # fresh run (keeps the same object alive)
                self._restart = False
                self.state = "play"      # a fresh journey starts immediately

# ======================================================================
#  [8] ENTRY POINT
# ======================================================================
if __name__ == "__main__":
    Game().run()

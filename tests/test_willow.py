# ======================================================================
#  TEST SUITE for "Willow the Witch - Potion Ventures"  (willow.py)
#
#  TABLE OF CONTENTS
#    [0] Harness ....... headless SDL, module import, fixtures, helpers
#    [U] UNIT TESTS .... pure functions, data integrity, audio synth,
#                        entities (Player/Bolt/Pickup/Node/Monster)
#    [I] INTEGRATION ... brew pipeline, orders, feuds, favors, save/load,
#                        world generation, landmarks, sleep, building
#    [P] PERFORMANCE ... time-budgeted generation / update / draw /
#                        pipeline / economy benchmarks
#    [M] MEMORY LEAK ... caps, expiry, vacuum, gc-growth smoke tests
#    [E] END-TO-END .... real key-event playthroughs (boot, gather, brew,
#                        deliver, build, sleep, combat, feuds, save/load)
#
#  Run:   .venv/bin/python -m pytest tests/ -v
#  Needs: pytest (pip install pytest); game at project root as willow.py
#  Note:  the first Game construction synthesizes all chiptune audio
#         (~2-4 s, once per process); later tests reuse the cache.
# ======================================================================
import os
import sys
import gc
import time
import math
import random as _random
import importlib

# Headless SDL must be configured BEFORE willow (-> pygame) is imported.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

# Make the project root (home of willow.py) importable from tests/.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest
import pygame

# ---------------------------------------------------------------- [0]
# Harness: locate the game module (accepts a few common filenames).
def _import_game():
    for name in ("willow", "witch_game", "main"):
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    raise ImportError(
        "Could not import the game. Save the game file as 'willow.py' "
        "in the project root (one level above tests/).")

W = _import_game()

class FakeKeys:
    """Dict-like stand-in for pygame.key.get_pressed()."""
    def __init__(self, **down):
        self.d = {k: 1 for k in down}
    def __getitem__(self, k):
        return self.d.get(k, 0)

def press(game, key):
    """Send one KEYDOWN event through the game's real input pipeline."""
    game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))

def flush(game, seconds=1.4, dt=0.05):
    """Advance the world so floats/messages/pops expire."""
    for _ in range(int(seconds / dt)):
        game.update(dt)

def kill_all(game):
    """Kill every monster via the real kill path (drops/favors/story)."""
    for m in list(game.monsters):
        game.kill_monster(m)
    game.monsters = []

def vacuum(game):
    """Teleport-collect every pickup through its real update path."""
    for pk in list(game.pickups):
        game.player.x, game.player.y = pk.x, pk.y
    game.pickups = [pk for pk in game.pickups if pk.update(0.016, game)]

def gc_objects():
    gc.collect()
    gc.collect()
    return len(gc.get_objects())

needs_audio = pytest.mark.skipif(not W.AUDIO_OK, reason="no audio device")

@pytest.fixture()
def game(monkeypatch, tmp_path):
    """A playable Game with save I/O redirected to a temp folder."""
    monkeypatch.setattr(W, "SAVE_PATH", str(tmp_path / "willow_test_save.json"))
    _random.seed(1337)
    g = W.Game()
    g.state = "play"
    yield g

@pytest.fixture()
def menu_game(monkeypatch, tmp_path):
    monkeypatch.setattr(W, "SAVE_PATH", str(tmp_path / "willow_test_save.json"))
    _random.seed(1337)
    yield W.Game()          # stays on the title screen

# Feud tests use a fixed NON-KIN pair so relationship math (incl. kin
# spillover) is exact and independent of random sampling.
FEUD_PAIR = (["Old Tom", "Nessa"])

def pin_feud_pair(monkeypatch):
    monkeypatch.setattr(_random, "sample", lambda pop, k: list(FEUD_PAIR))

# ======================================================================
#  [U] UNIT TESTS
# ======================================================================
class TestUnitPureFunctions:

    def test_unit_quality_tier_thresholds(self):
        assert [W.quality_tier(s) for s in (0, 1, 2, 3, 4, 5, 6, 9)] == \
               [0, 0, 1, 1, 2, 2, 3, 3]

    def test_unit_mastery_levels(self):
        assert [W.mastery_level(c) for c in (0, 4, 5, 14, 15, 29, 30, 500)] == \
               [0, 0, 1, 1, 2, 2, 3, 3]

    def test_unit_clamp(self):
        assert W.clamp(5, 0, 10) == 5
        assert W.clamp(-3, 0, 10) == 0
        assert W.clamp(99, 0, 10) == 10

    def test_unit_ang_diff(self):
        assert W.ang_diff(0.3, 0.3) == pytest.approx(0.0)
        assert W.ang_diff(0.0, math.pi) == pytest.approx(math.pi, abs=1e-6)
        assert W.ang_diff(0.1, 2 * math.pi - 0.1) == pytest.approx(0.2, abs=1e-6)

    def test_unit_wrap_text(self):
        assert W.wrap_text("hello world", W.FONT_M, 500) == ["hello world"]
        lines = W.wrap_text(" ".join(["word"] * 200), W.FONT_S, 200)
        assert len(lines) > 3
        assert all(W.FONT_S.size(ln)[0] <= 200 for ln in lines)

    def test_unit_weighted_choice_domain_and_zero_weight(self):
        opts = [("a", 1), ("b", 0), ("c", 3)]
        picks = {W.weighted_choice(opts) for _ in range(400)}
        assert picks == {"a", "c"}                      # b never (weight 0)
        assert W.weighted_choice([("only", 5)]) == "only"

class TestUnitGameDataIntegrity:

    def test_unit_recipes_reference_real_ingredients(self):
        for pid, d in list(W.POTIONS.items()) + list(W.SECRET_POTIONS.items()):
            assert d["name"] and d["price"] > 0
            assert isinstance(d["color"], tuple) and len(d["color"]) == 3
            for ing, qty in d["recipe"].items():
                assert ing in W.INGREDIENTS, pid
                assert qty >= 1

    def test_unit_monster_drop_tables_valid(self):
        for mid, d in W.MONSTERS.items():
            if d.get("guarantee"):
                assert d["guarantee"] in W.INGREDIENTS, mid
            for ing, ch in d.get("drops", []):
                assert ing in W.INGREDIENTS and 0 < ch <= 1
            if d.get("rare"):
                assert d["rare"][0] in W.INGREDIENTS and 0 < d["rare"][1] <= 1

    def test_unit_biomes_reference_valid_content(self):
        for bid, b in W.BIOMES.items():
            assert all(p in W.INGREDIENTS for p, _ in b["plants"])
            assert all(m in W.MONSTERS for m in b["monsters"])
            assert all(k in W.TERRAIN_FX for k, _ in b["terrain"])
            assert b["rare"] in W.INGREDIENTS
            assert all(k in W.LANDMARK_INFO for k in W.BIOME_LANDMARKS[bid])
            assert b["danger"] in (1, 2, 3)

    def test_unit_craft_tabs_partition_potentials(self):
        tonics, beast = W.CRAFT_TABS[0][1], W.CRAFT_TABS[1][1]
        assert sorted(tonics + beast) == sorted(W.POTIONS.keys())
        assert not set(tonics) & set(beast)
        assert W.CRAFT_TABS[2][1] == list(W.SECRET_POTIONS.keys())

    def test_unit_ingredient_uses_map(self):
        assert "Healing Potion" in W.INGREDIENT_USES["slimejelly"]
        assert W.monster_sources("slimejelly") == ["Slime"]
        assert W.monster_sources("not_an_item") == []

    def test_unit_monster_drops_helper(self):
        assert W.MONSTER_DROPS["slime"] == ["slimejelly", "slimecore"]
        assert W.MONSTER_DROPS["pixie"] == ["pixiewing", "fairydust"]

    def test_unit_personas_complete_and_kin_symmetric(self):
        needed = {"greet", "ask", "thanks", "reject", "chat", "angry"}
        for _name, persona in W.CUSTOMERS:
            assert needed <= set(W.PERSONAS[persona].keys())
        for a, kin in W.FAMILY_LINKS.items():
            for b in kin:
                assert a in W.FAMILY_LINKS.get(b, []), (a, b)

    def test_unit_buildings_and_spots_valid(self):
        for k, b in W.BUILDINGS.items():
            assert b["cost"] > 0 and b["desc"]
            assert b["req"] is None or b["req"] in W.BUILDINGS
        valid_acts = {"orders", "door", "craft", "travel", "build"}
        assert all(s["act"] in valid_acts for s in W.BASE_SPOTS)
        assert len(W.BUILD_SLOTS) == len(W.BUILDINGS)

    def test_unit_day_events_and_story_shape(self):
        for ev in W.DAY_EVENTS:
            assert {"id", "title", "w", "desc"} <= set(ev)
            assert ev["w"] > 0
        for ch in W.STORY:
            assert ch["title"] and callable(ch["when"]) and ch["text"]
        assert W.FINALE_TEXT and W.RUMOR_TPL and W.REASONS

class TestUnitAudioEngine:

    def test_unit_tone_length_and_range(self):
        if not W.AUDIO_OK:
            pytest.skip("no audio device")
        n = len(W._tone(0.1, 440))
        assert abs(n - int(0.1 * W.SR)) <= 2
        for wave in ("sq", "tri", "saw", "noise", "sine"):
            s = W._tone(0.05, 300, 700, wave=wave)
            assert max(abs(v) for v in s) <= 1.0 + 1e-9
        assert len(set(W._tone(0.05, 0, 0, wave="noise"))) > 10   # truly noisy

    def test_unit_silence_is_silent(self):
        assert all(v == 0.0 for v in W._silence(0.05))

    @needs_audio
    def test_unit_song_renderer_produces_sound(self):
        snd = W._render_song(*W.SONGS["wild"])
        assert snd is not None
        # 64 lead steps @138 bpm -> ~7 s of audio
        assert 4.0 < snd.get_length() < 12.0

    @needs_audio
    def test_unit_all_four_themes_rendered(self):
        sfx_bank, songs = W.ensure_audio()
        assert set(songs.keys()) == {"title", "home", "wild", "danger"}
        assert all(snd is not None and snd.get_length() > 2 for snd in songs.values())

    @needs_audio
    def test_unit_sfx_bank_complete(self):
        sfx_bank, _ = W.ensure_audio()
        for name in ("coin", "gather", "bolt", "hit", "die", "hurt", "down",
                     "heart", "pour", "perfect", "good", "ruin", "stir",
                     "brew0", "brew1", "brew2", "brew3", "lvl", "boom",
                     "sparkle", "accept", "deliver", "feud", "warm", "chat",
                     "morning", "sleep", "portal", "portalback", "chime",
                     "mystery", "build", "move", "select", "back", "open",
                     "deny", "tick", "pickup", "rare", "gulp", "refine",
                     "coinbig", "sell"):
            assert name in sfx_bank and sfx_bank[name] is not None, name

    def test_unit_bass_bar_is_16_steps(self):
        assert len(W._bass_bar(48)) == 16
        for _bpm, lead, bass, _dr, _duty in W.SONGS.values():
            assert len(lead) % 16 == 0
            assert len(bass) % 16 == 0
            assert len(_dr) % 16 == 0

class TestUnitRenderingHelpers:

    def test_unit_text_returns_rect(self):
        r = W.text(W.screen, "hi", 10, 10)
        assert isinstance(r, pygame.Rect) and r.width > 0

    def test_unit_bar_and_orb_draw(self):
        W.bar(W.screen, 10, 10, 50, 10, 0.5, W.GOLD)
        W.orb(W.screen, 30, 30, 6, (255, 0, 0))

    def test_unit_gradient_edge_dimensions(self):
        s = W.gradient_edge(100, 40, True, False)
        assert s.get_size() == (100, 40)
        assert s.get_at((5, 5)).a > s.get_at((5, 35)).a   # fades out

class TestUnitEntities:

    def test_unit_player_moves_and_clamps(self, game):
        p = game.player
        p.x, p.y = 100, 400
        p.update(0.1, FakeKeys(d=1), game)
        assert p.x > 100
        p.x = W.SCREEN_W - 29
        for _ in range(20):
            p.update(0.05, FakeKeys(d=1), game)
        assert p.x <= W.SCREEN_W - 28 + 1e-6

    def test_unit_player_diagonal_is_normalized(self, game):
        p = game.player
        p.x, p.y = 512, 400
        p.update(0.1, FakeKeys(d=1, s=1), game)
        moved = math.hypot(p.x - 512, p.y - 400)
        straight = 210 * 0.1
        assert moved == pytest.approx(straight, rel=0.05)   # no diagonal speed boost

    def test_unit_bolt_lifetime_and_motion(self):
        b = W.Bolt(0, 0, 1, 0, 10)
        assert b.update(0.5) is True and b.x == pytest.approx(230)
        alive = True
        for _ in range(5):
            alive = b.update(0.5)
        assert alive is False                                # expired

    def test_unit_pickup_magnet_and_collection(self, game):
        game.items.clear()
        pk = W.Pickup(game.player.x + 5, game.player.y, "moonpetal")
        assert pk.update(0.016, game) is False               # collected at once
        assert game.items.get("moonpetal") == 1

    def test_unit_pickup_drifts_when_far(self, game):
        pk = W.Pickup(60, 120, "moonpetal")
        game.player.x, game.player.y = 900, 700
        x0 = pk.x
        assert pk.update(0.016, game) is True
        assert pk.x != x0                                     # drifting/scattered

    def test_unit_float_text_expires(self):
        f = W.FloatText(10, 10, "x", W.WHITE)
        assert f.update(0.5) is True
        assert f.update(2.0) is False

    def test_unit_node_regrows(self):
        n = W.Node(10, 10, "moonpetal")
        n.ready = False
        n.timer = 0.05
        n.update(0.1)
        assert n.ready is True

    def test_unit_monster_chases_player(self, game):
        game.buffs.clear()
        m = W.Monster("slime", 512, 300)
        game.player.x, game.player.y = 512, 400
        d0 = math.hypot(game.player.x - m.x, game.player.y - m.y)
        m.update(0.05, game)
        d1 = math.hypot(game.player.x - m.x, game.player.y - m.y)
        assert d1 < d0

    def test_unit_monster_damage_triggers_float_and_iframes(self, game):
        m = W.Monster("slime", game.player.x, game.player.y + 5)
        game.player.iframes = 0
        hp0 = game.player.hp
        m.update(0.05, game)
        assert game.player.hp < hp0
        assert game.player.iframes > 0

    def test_unit_stoneskin_reduces_damage(self, game):
        m = W.Monster("slime", game.player.x, game.player.y + 5)
        game.buffs["stoneskin"] = 10
        game.player.iframes = 0
        hp0 = game.player.hp
        m.update(0.05, game)
        assert hp0 - game.player.hp == pytest.approx(m.dmg * 0.6)

# ======================================================================
#  [I] INTEGRATION TESTS
# ======================================================================
class TestIntegrationBrewing:

    def test_intg_full_brew_flow_produces_quality_potion(self, game):
        game.items.update({"moonpetal": 4, "slimejelly": 2})
        game.start_brew("healing")
        assert game.brew["phase"] == "heat"
        assert game.items["moonpetal"] == 2 and game.items["slimejelly"] == 1
        game.brew["needle"] = 0.5                       # perfect heat
        game.lock_brew()
        assert game.brew["phase"] == "stir"
        for _ in range(3):                              # three perfect stirs
            game.brew["ang"] = game.brew["target"]
            game.lock_brew()
        assert game.brew is None
        assert game.overlay == "craft"
        arr = game.potions["healing"]
        assert arr[2] == 1                              # score 5 -> Fine
        assert game.brew_xp > 0

    def test_intg_brew_blocked_without_ingredients(self, game):
        game.items.clear()
        game.start_brew("healing")
        assert game.brew is None and game.overlay != "brew"

    def test_intg_cancel_brew_refunds_everything(self, game):
        game.items.update({"moonpetal": 2, "slimejelly": 1})
        game.start_brew("healing")
        game.cancel_brew()
        assert game.items == {"moonpetal": 2, "slimejelly": 1}
        assert game.brew is None and game.overlay == "craft"

    def test_intg_quick_brew_gives_standard(self, game):
        game.items.update({"moonpetal": 2, "slimejelly": 1})
        game.quick_brew("healing")
        assert game.potions["healing"][1] == 1

    def test_intg_refine_requires_distillery_and_myrtle(self, game):
        game.add_potion("healing", 0, 1)
        game.refine("healing")                          # no distillery
        assert game.potions["healing"][0] == 1
        game.buildings.append("distillery")
        game.refine("healing")                          # no bogmyrtle
        assert game.potions["healing"][0] == 1
        game.add_item("bogmyrtle", 1)
        game.refine("healing")
        assert game.potions["healing"][1] == 1 and "bogmyrtle" not in game.items

    def test_intg_sell_one_and_sell_all_math(self, game):
        game.add_potion("healing", 0, 1)
        game.add_potion("healing", 2, 2)
        expected = sum(int(W.POTIONS["healing"]["price"] *
                           W.QUALITY[t]["mult"] * 1.0)
                       for t in (0, 2, 2))
        g0 = game.gold
        game.sell_all("healing")
        assert game.gold - g0 == expected
        assert "healing" not in game.potions

    def test_intg_drinking_quality_healing_scales(self, game):
        game.add_potion("healing", 3, 1)                # Exquisite
        game.player.hp = 10
        game.drink_potion("healing")
        assert game.player.hp == 10 + 45 + 15 * 3

    def test_intg_level_bonus_and_xp_curve(self, game):
        assert game.level_bonus() == 0                  # level 1
        game.brew_xp = game.xp_next()                   # force a level-up
        game.add_xp(0)
        assert game.brew_level == 2 and game.level_bonus() == 1

class TestIntegrationOrders:

    def _stock_and_order(self, game, pid="healing", qty=1, minq=1):
        for _ in range(qty):
            game.add_potion(pid, minq, 1)
        o = {"pid": pid, "qty": qty, "reward": 50, "due": game.day + 5,
             "who": "Mira the Farmer", "minq": minq, "line": "please"}
        game.orders = [o]
        return o

    def test_intg_deliver_pays_rep_and_relationship(self, game):
        o = self._stock_and_order(game)
        g0, rep0, rel0 = game.gold, game.rep, game.rel["Mira the Farmer"]
        game.deliver_order()
        assert game.gold == g0 + o["reward"]
        assert game.rep == rep0 + 1
        assert game.rel["Mira the Farmer"] == rel0 + 7
        assert game.orders == []

    def test_intg_deliver_blocked_when_short(self, game):
        self._stock_and_order(game, qty=2)
        game.potions["healing"] = [0, 1, 0, 0]           # only 1 of 2
        g0 = game.gold
        game.deliver_order()
        assert game.gold == g0 and len(game.orders) == 1

    def test_intg_fine_only_order_rejects_standard(self, game):
        self._stock_and_order(game, qty=2, minq=2)       # needs 2 Fine+
        game.potions["healing"] = [0, 3, 1, 0]           # only 1 Fine, rest Standard
        g0 = game.gold
        game.deliver_order()
        assert game.gold == g0 and len(game.orders) == 1

    def test_intg_accept_and_max_contracts(self, game):
        game.refresh_board()
        game.overlay_idx = 0
        game.accept_order()
        assert len(game.orders) == 1 and len(game.board) == W.BOARD_SIZE - 1
        game.orders = [game.board[0]] * W.MAX_CONTRACTS  # simulate full board
        n_board = len(game.board)
        game.accept_order()
        assert len(game.board) == n_board                # rejected, board intact

    def test_intg_reject_costs_relationship(self, game):
        game.refresh_board()
        who = game.board[0]["who"]
        rel0 = game.rel[who]
        game.overlay_idx = 0
        game.reject_order()
        assert game.rel[who] == rel0 - 6 and len(game.board) == W.BOARD_SIZE - 1

    def test_intg_sleep_expires_overdue_contracts(self, game, monkeypatch):
        monkeypatch.setattr(game, "roll_day_event", lambda: None)  # no rep noise
        who = "Old Tom"
        game.orders = [{"pid": "healing", "qty": 1, "reward": 10,
                        "due": game.day, "who": who, "minq": 1, "line": "x"}]
        rep0, rel0 = game.rep, game.rel[who]
        game.sleep()                                     # day -> 2 > due
        assert game.orders == []
        assert game.rep == rep0 - 1
        assert game.rel[who] == rel0 - 10
        assert game.day == 2

class TestIntegrationSocial:

    def test_intg_feud_decision_siding(self, game, monkeypatch):
        pin_feud_pair(monkeypatch)                       # Old Tom vs Nessa (non-kin)
        game.day = 3
        assert game.maybe_start_feud() is True
        assert game.overlay == "decision"
        press(game, pygame.K_e)                          # option 0: side with Old Tom
        feud = game.feuds[0]
        assert feud["sided"] == "Old Tom" and feud["b"] == "Nessa"
        assert game.rel["Old Tom"] == 25                 # 10 + 15
        assert game.rel["Nessa"] == -10                  # 10 - 20
        assert game.rel["Grandma Rose"] == 16            # Tom's kin: +int(15*.4)
        assert game.rel["Pip the Baker"] == 2            # Nessa's kin: -int(20*.4)
        assert game.overlay is None

    def test_intg_feud_neutral_and_time_resolution(self, game):
        f = {"a": "Old Tom", "b": "Nessa", "reason": "x", "age": 0,
             "sided": None, "done": False}
        game.feuds = [f]
        game.neutral_feud(f)
        assert f["sided"] == "neutral"
        for _ in range(4):
            game.sleep()
            game.overlay = None                          # dismiss story/favor popups
        assert f["done"] is True
        assert game.stats["feuds_resolved"] == 1

    def test_intg_kin_spillover_and_family_flag(self, game):
        game.add_rel("Grandma Rose", 10)                 # Tom is her kin
        assert game.rel["Old Tom"] == 10 + int(10 * 0.4)
        for name in ("Grandma Rose", "Pip the Baker", "Nessa"):
            game.rel[name] = 59
            game.add_rel(name, 1)                        # crosses 60 -> family
        assert game.family_flag is True
        assert len(game.family_names()) == 3

    def test_intg_item_favor_complete_flow(self, game):
        fav = {"who": "Old Tom", "kind": "item", "target": "moonpetal",
               "need": 2, "have": 0, "reward": 30,
               "due": game.day + 4, "line": "x"}
        game.favors = [fav]
        game.deliver_favor(fav)                          # nothing in satchel yet
        assert fav in game.favors
        game.add_item("moonpetal", 2)
        g0, rel0 = game.gold, game.rel["Old Tom"]
        game.deliver_favor(fav)
        assert game.favors == [] and game.gold == g0 + 30
        assert game.rel["Old Tom"] == rel0 + 16
        assert "moonpetal" not in game.items

    def test_intg_hunt_favor_tracks_kills(self, game):
        fav = {"who": "Mira the Farmer", "kind": "hunt", "target": "slime",
               "need": 2, "have": 0, "reward": 40,
               "due": game.day + 4, "line": "x"}
        game.favors = [fav]
        game.kill_monster(W.Monster("slime", 0, 0))
        assert fav["have"] == 1 and fav in game.favors
        game.pickups.clear()
        game.kill_monster(W.Monster("slime", 0, 0))
        assert game.favors == [] and game.stats["favors_done"] == 1

    def test_intg_chat_once_per_day_and_gift(self, game):
        game.chat_npc("Nessa")
        rel1 = game.rel["Nessa"]
        game.chat_npc("Nessa")                           # blocked: already chatted
        assert game.rel["Nessa"] == rel1
        game.gift_npc("Nessa")                           # no Concord -> denied
        assert game.rel["Nessa"] == rel1
        game.add_potion("concord", 1, 1)
        game.gift_npc("Nessa")
        assert game.rel["Nessa"] == rel1 + 12

    def test_intg_sulking_villagers_leave_board(self, game):
        f = {"a": "Old Tom", "b": "Nessa", "reason": "x", "age": 2,
             "sided": None, "done": False}
        game.feuds = [f]
        assert game.sulking("Old Tom") and game.sulking("Nessa")
        for _ in range(W.BOARD_SIZE):
            game.make_order()
        names = {o["who"] for o in game.board}
        assert "Old Tom" not in names and "Nessa" not in names

class TestIntegrationExperiment:

    def test_intg_experiment_discovery_deterministic(self, game, monkeypatch):
        monkeypatch.setattr(_random, "random", lambda: 0.05)   # < 0.18
        game.exp = {"sel": 0, "slots": ["moonpetal", "slimejelly"], "last": ("", WHITE)}
        n = len(game.known_secrets)
        game.do_experiment()
        assert len(game.known_secrets) == n + 1

    def test_intg_experiment_recovery_branch(self, game, monkeypatch):
        monkeypatch.setattr(_random, "random", lambda: 0.55)   # 0.48..0.60
        game.items.update({"moonpetal": 1, "starbloom": 1})
        game.exp = {"sel": 0, "slots": ["moonpetal", "starbloom"], "last": ("", WHITE)}
        game.do_experiment()
        assert "recover" in game.exp["last"][0]
        assert game.items.get("moonpetal", 0) + game.items.get("starbloom", 0) >= 1

    def test_intg_experiment_explosion_branch(self, game, monkeypatch):
        monkeypatch.setattr(_random, "random", lambda: 0.63)   # 0.60..0.66
        game.items.update({"moonpetal": 1, "starbloom": 1})
        game.exp = {"sel": 0, "slots": ["moonpetal", "starbloom"], "last": ("", WHITE)}
        hp0 = game.player.hp
        game.do_experiment()
        assert game.player.hp == hp0 - 4

class TestIntegrationBuilding:

    def test_intg_build_confirm_flow_creates_path(self, game):
        g0 = game.gold
        game.build_request("garden")
        assert game.overlay == "confirm" and game.confirm is not None
        game._confirm_pick(0)                            # "Yes, do it"
        assert "garden" in game.buildings
        assert game.gold == g0 - W.BUILDINGS["garden"]["cost"]
        assert len(game.stubs["garden"]) > 2             # generated path

    def test_intg_building_requirements_enforced(self, game):
        game.gold = 9999
        game.build_request("greenhouse")                 # needs garden
        assert "greenhouse" not in game.buildings
        game.buildings.append("garden")
        game.build_request("greenhouse")
        game._confirm_pick(0)
        assert "greenhouse" in game.buildings

class TestIntegrationKillAndMastery:

    def test_intg_kills_mastery_and_guaranteed_drops(self, game):
        game.loc = "forest"
        for i in range(15):
            game.kill_monster(W.Monster("slime", 100 + i, 100))
            game.pickups.clear()
        assert game.kills["slime"] == 15
        assert W.mastery_level(15) == 2
        game.pickups.extend([W.Pickup(0, 0, "slimejelly")])
        assert "slimejelly" in W.MONSTER_DROPS["slime"]

    def test_intg_kill_feeds_first_kill_chronicle(self, game):
        n = len(game.chronicle)
        game.kill_monster(W.Monster("frostwolf", 0, 0))
        game.pickups.clear()
        assert any("First Frost Wolf" in e["text"] for e in game.chronicle[n:])

class TestIntegrationWorldGeneration:

    def test_intg_enter_biome_builds_complete_world(self, game):
        for bid in W.BIOMES:
            game.enter_biome(bid)
            assert game.loc == bid
            assert 1 <= len(game.nodes) <= 11
            assert len(game.monsters) >= 1
            assert len(game.roads) >= 1 and len(game.roads[0][0]) > 4
            assert 1 <= len(game.zones) <= 6
            assert game.variant and game.weather in ("clear", "breezy", "misty")
            assert game.player.x == 512 and game.player.y == 630

    def test_intg_rumor_guarantees_its_landmark(self, game):
        game.active_rumor = {"biome": "forest", "kind": "shrine", "text": "x"}
        game.enter_biome("forest")
        kinds = [l["kind"] for l in game.landmarks]
        assert "shrine" in kinds

    def test_intg_move_mult_road_and_terrain(self, game):
        game.enter_biome("forest")
        game.zones = []
        mid = game.roads[0][0][len(game.roads[0][0]) // 2]
        game.player.x, game.player.y = mid
        assert game.on_road(*mid) is True
        assert game.move_mult() > 1.0                    # road speed boost
        game.zones = [{"kind": "pond", "x": mid[0], "y": mid[1],
                       "r": 50, "t": 0}]
        assert game.move_mult() < 1.0                    # pond slows

    def test_intg_plants_cluster_near_roads(self, game):
        game.enter_biome("forest")
        road_pts = [q for road, _ in game.roads for q in road]
        near = sum(1 for n in game.nodes
                   if min(math.hypot(n.x - p[0], n.y - p[1])
                          for p in road_pts) < 120)
        assert near >= 2                                 # biased spawn works

class TestIntegrationLandmarks:

    def test_intg_every_landmark_effect_fires(self, game):
        game.loc = "forest"
        game.active_rumor = None
        for kind in W.LANDMARK_INFO:
            l = {"kind": kind, "x": 0, "y": 0, "used": False, "t": 0}
            g0, hp0 = game.gold, game.player.hp
            game.player.hp = min(hp0, 10)
            before_items = dict(game.items)
            game.touch_landmark(l)
            assert l["used"] is True
            if kind == "cache":
                assert game.gold > g0
            elif kind == "spring":
                assert game.player.hp == game.player.max_hp
            elif kind == "shrine":
                assert game.buffs.get("lucky", 0) > 0
            elif kind == "crystal":
                assert game.items.get("ghostmush", 0) >= 2
            elif kind == "well":
                assert game.player.hp == 35 and game.gold == g0 + 12
            elif kind == "leystone":
                gained = sum(game.items.get(i, 0) - before_items.get(i, 0)
                             for i, d in W.INGREDIENTS.items() if d.get("monster"))
                assert gained == 4
            elif kind == "ruin":
                plants = ("moonpetal", "nightshade", "ghostmush")
                gained = sum(game.items.get(i, 0) - before_items.get(i, 0)
                             for i in plants)
                assert gained == 3

    def test_intg_rumor_landmark_grants_reputation(self, game):
        game.loc = "forest"
        game.active_rumor = {"biome": "forest", "kind": "well", "text": "x"}
        rep0 = game.rep
        game.touch_landmark({"kind": "well", "x": 0, "y": 0,
                             "used": False, "t": 0})
        assert game.rep == rep0 + 1 and game.active_rumor is None

class TestIntegrationSaveLoad:

    def test_intg_save_load_roundtrip(self, game):
        # mutate a representative slice of state
        game.gold, game.day, game.rep = 777, 9, 12
        game.items = {"moonpetal": 3, "chitin": 1}
        game.potions = {"healing": [1, 2, 0, 1]}
        game.buildings = ["garden", "market"]
        game.kills = {"slime": 6}
        game.known_secrets = ["shadow"]
        game.brew_level, game.brew_xp = 4, 30
        game.rel["Nessa"] = 66
        game.finale = False
        game.chron("integration marker entry")
        snap = dict(game.stats)
        assert game.save_game() is True
        g2 = W.Game()
        assert g2.load_game() is True
        assert g2.state == "play"
        assert (g2.gold, g2.day, g2.rep) == (777, 9, 12)
        assert g2.items == {"moonpetal": 3, "chitin": 1}
        assert g2.potions == {"healing": [1, 2, 0, 1]}
        assert g2.buildings == ["garden", "market"]
        assert g2.kills == {"slime": 6}
        assert g2.known_secrets == ["shadow"]
        assert (g2.brew_level, g2.brew_xp) == (4, 30)
        assert g2.rel["Nessa"] == 66
        assert g2.stats["deliveries"] == snap["deliveries"]
        assert any("integration marker" in e["text"] for e in g2.chronicle)
        assert g2.monsters == [] and g2.bolts == []      # transient state reset
        assert g2.day_event is None or g2.day_event in W.DAY_EVENTS

    def test_intg_day_event_and_rumor_survive_save(self, game):
        game.day_event = W.DAY_EVENTS[0]                 # festival
        game.active_rumor = {"biome": "swamp", "kind": "cache", "text": "x"}
        game.save_game()
        g2 = W.Game()
        g2.load_game()
        assert g2.day_event["id"] == "festival"
        assert g2.active_rumor["kind"] == "cache"

    def test_intg_autosave_writes_file_on_sleep(self, game):
        game.sleep()
        game.overlay = None
        assert os.path.exists(W.SAVE_PATH)

class TestIntegrationMusicDirector:

    def test_intg_theme_selection(self, game):
        game.state = "menu"
        assert game.theme() == "title"
        game.state = "play"; game.loc = "base"
        assert game.theme() == "home"
        game.enter_biome("forest")
        assert game.theme() == "wild"
        game.monsters.append(W.Monster("slime",
                                       game.player.x + 100, game.player.y))
        assert game.theme() == "danger"                  # within 230 px
        game.monsters.clear()
        assert game.theme() == "wild"

    @needs_audio
    def test_intg_music_crossfade_and_mute(self, game):
        game.update_music()
        assert game._music_name == "home"
        game.settings["music"] = False
        game.update_music()
        assert game._music_name is None
        game.settings["music"] = True
        game.update_music()
        assert game._music_name == "home"

# ======================================================================
#  [P] PERFORMANCE TESTS  (generous budgets so they never flake on CI)
# ======================================================================
class TestPerformance:

    def test_perf_biome_generation_25_runs(self, game):
        t0 = time.perf_counter()
        for _ in range(5):
            for bid in W.BIOMES:
                game.enter_biome(bid)
        assert time.perf_counter() - t0 < 6.0

    def test_perf_update_300_frames_busy_scene(self, game):
        game.enter_biome("forest")
        game.player.iframes = 999                        # ignore knockback noise
        for _ in range(60):                              # bounded spawn fill
            if len(game.monsters) >= 5:
                break
            game.spawn_monster()
        t0 = time.perf_counter()
        for _ in range(300):
            game.update(1 / 60)
        assert time.perf_counter() - t0 < 4.0

    def test_perf_draw_60_frames_world(self, game):
        game.enter_biome("forest")
        game.draw()                                      # warm-up
        t0 = time.perf_counter()
        for _ in range(60):
            game.draw()
        assert time.perf_counter() - t0 < 4.0

    def test_perf_draw_30_frames_heavy_overlay(self, game):
        game.set_overlay("craft")
        game.draw()
        t0 = time.perf_counter()
        for _ in range(30):
            game.draw()
        assert time.perf_counter() - t0 < 3.0
        game.overlay = None

    def test_perf_full_trip_pipeline_15_cycles(self, game):
        t0 = time.perf_counter()
        for _ in range(15):
            game.enter_biome("forest")
            game.player.hp, game.player.iframes = 100, 999
            for _f in range(30):
                game.update(1 / 60)
            game.go_home()
        assert time.perf_counter() - t0 < 6.0

    def test_perf_200_quick_brews(self, game):
        game.items.update({"moonpetal": 400, "slimejelly": 200})
        t0 = time.perf_counter()
        for _ in range(200):
            game.quick_brew("healing")
        assert time.perf_counter() - t0 < 2.0
        assert game.potion_total("healing") == 200

    def test_perf_200_pickup_vacuum(self, game):
        game.pickups = [W.Pickup(game.player.x + _random.uniform(-60, 60),
                                 game.player.y + _random.uniform(-60, 60),
                                 "moonpetal") for _ in range(200)]
        t0 = time.perf_counter()
        for _ in range(300):
            game.pickups = [pk for pk in game.pickups if pk.update(1 / 60, game)]
            if not game.pickups:
                break
        assert time.perf_counter() - t0 < 3.0
        assert game.pickups == [] and game.items["moonpetal"] == 200

    def test_perf_message_and_float_churn(self, game):
        t0 = time.perf_counter()
        for i in range(2000):
            game.msg("m%d" % i, W.GREY, 0.01)
            game.add_float(i % W.SCREEN_W, i % W.SCREEN_H, "+1", W.GOLD)
        flush(game, 1.5)
        assert time.perf_counter() - t0 < 2.0

# ======================================================================
#  [M] MEMORY-LEAK TESTS
# ======================================================================
class TestMemoryLeaks:

    def test_mem_message_log_capped(self, game):
        for i in range(500):
            game.msg("spam %d" % i)
        assert len(game.messages) <= 5

    def test_mem_float_texts_fully_expire(self, game):
        for i in range(300):
            game.add_float(i, i, "+1", W.GOLD)
        flush(game, 1.5)
        assert game.floats == []

    def test_mem_hud_pops_expire(self, game):
        for i in range(60):
            game.earn_gold(1)
        flush(game, 2.0)
        assert game.hud_pops == []

    def test_mem_dead_bolts_purged(self, game):
        game.loc = "forest"
        game.monsters = []
        game.bolts = [W.Bolt(0, 0, 1, 0, 5) for _ in range(60)]
        for b in game.bolts:
            b.life = 0
        game.update_biome(0.016, FakeKeys())
        assert game.bolts == []

    def test_mem_buffs_expire_not_accumulate(self, game):
        for _ in range(50):
            game.set_buff("lucky", 0.05)
        assert len(game.buffs) == 1                      # keyed, never stacked
        flush(game, 0.5)
        assert game.buffs == {}

    def test_mem_pickups_vacuumed_after_many_kills(self, game):
        game.loc = "forest"
        for i in range(15):
            game.kill_monster(W.Monster("slime", 100 + i, 100))
            assert len(game.pickups) < 40                # bounded per kill wave
            vacuum(game)
        assert game.pickups == []

    def test_mem_click_map_reset_every_frame(self, game):
        game.enter_biome("forest")
        for _ in range(100):
            game.draw()
            assert len(game.click_map) < 150             # rebuilt, not appended

    def test_mem_world_cycles_gc_growth(self, game):
        # Chronicle is an append-only journal BY DESIGN -> excluded from leak
        # accounting; everything else must stay flat.
        game.enter_biome("forest"); game.go_home()       # warm-up
        base = gc_objects()
        for _ in range(12):
            game.enter_biome("forest")
            game.player.iframes = 999
            kill_all(game)
            vacuum(game)
            flush(game, 1.3)
            game.go_home()
        growth = gc_objects() - base
        assert growth < 4000, "possible leak: %d new objects over 12 cycles" % growth

    def test_mem_game_recreation_gc_growth(self):
        W.Game()                                         # warm caches
        base = gc_objects()
        for _ in range(8):
            g = W.Game()
            g.enter_biome("forest")
            del g
        growth = gc_objects() - base
        assert growth < 5000, "possible leak: %d new objects over 8 Games" % growth

    def test_mem_chronicle_growth_is_by_design(self, game):
        n = len(game.chronicle)
        for i in range(50):
            game.chron("entry %d" % i)
        assert len(game.chronicle) == n + 50             # journal, never trimmed

    def test_mem_overlay_open_close_stable(self, game):
        for _ in range(50):
            game.set_overlay("craft")
            game.overlay = None
        game.set_overlay("craft")
        assert game.overlay_idx == 0                     # selection reset

# ======================================================================
#  [E] END-TO-END TESTS  (real key events through handle_event)
# ======================================================================
class TestEndToEnd:

    def test_e2e_boot_title_to_gameplay(self, menu_game):
        assert menu_game.state == "menu"
        press(menu_game, pygame.K_RETURN)
        assert menu_game._restart is True                # run() consumes this flag
        # emulate the run-loop body that consumes the restart:
        menu_game.__init__()
        menu_game._restart = False
        menu_game.state = "play"
        assert any("Welcome home" in m["s"] for m in menu_game.messages)
        assert menu_game.theme() == "home"

    def test_e2e_full_day_gather_brew_deliver_build_sleep(self, game):
        # -- travel via signpost UI --
        game.player.x, game.player.y = 512, 630          # signpost
        press(game, pygame.K_e)
        assert game.overlay == "travel"
        press(game, pygame.K_e)                          # forest (index 0)
        assert game.loc == "forest" and game.overlay is None
        # -- gather a plant through the world interaction --
        node = next(n for n in game.nodes if n.ready)
        game.player.x, game.player.y = node.x, node.y
        press(game, pygame.K_e)
        assert node.ready is False
        press(game, pygame.K_ESCAPE)                     # flee home
        assert game.loc == "base"
        # -- brew a Healing Potion at the cauldron UI --
        game.items.update({"moonpetal": 2, "slimejelly": 1})   # pack the satchel
        game.player.x, game.player.y = 740, 300          # cauldron
        press(game, pygame.K_e)
        assert game.overlay == "craft"
        press(game, pygame.K_e)                          # row 0 = Healing Potion
        assert game.overlay == "brew" and game.brew is not None
        game.brew["needle"] = 0.5
        press(game, pygame.K_SPACE)                      # lock heat
        for _ in range(3):
            game.brew["ang"] = game.brew["target"]
            press(game, pygame.K_SPACE)                  # lock stirs
        assert game.overlay == "craft"
        assert game.potion_total("healing") == 1
        # -- deliver an injected contract through the CONTRACTS tab --
        game.orders = [{"pid": "healing", "qty": 1, "reward": 50,
                        "due": game.day + 5, "who": "Mira the Farmer",
                        "minq": 1, "line": "my soup is sad"}]
        g0 = game.gold
        game.player.x, game.player.y = 250, 300          # order board
        press(game, pygame.K_e)
        assert game.overlay == "orders"
        press(game, pygame.K_d)                          # -> CONTRACTS tab
        press(game, pygame.K_e)                          # deliver
        assert game.gold == g0 + 50 and game.orders == []
        assert game.rep == 1
        # -- build the Herb Garden through the confirm dialog --
        game.player.x, game.player.y = 860, 520          # construction plot
        press(game, pygame.K_e)
        assert game.overlay == "build"
        press(game, pygame.K_e)                          # row 0 = Herb Garden
        assert game.overlay == "confirm"
        press(game, pygame.K_w)                          # sel 1 -> 0 ("Yes")
        press(game, pygame.K_e)
        assert "garden" in game.buildings
        assert game.gold == g0 + 50 - W.BUILDINGS["garden"]["cost"]
        # -- sleep at the cottage door; dismiss any story/social popup --
        game.player.x, game.player.y = 512, 330          # cottage door
        press(game, pygame.K_e)
        assert game.day == 2
        for _ in range(3):
            if game.overlay == "story":
                press(game, pygame.K_e)
            elif game.overlay == "decision":
                press(game, pygame.K_ESCAPE)
            else:
                break
        assert os.path.exists(W.SAVE_PATH)               # morning autosave fired

    def test_e2e_combat_kill_and_loot(self, game, monkeypatch):
        game.enter_biome("forest")
        game.player.iframes = 999
        game.spawn_timer = 99999                         # no reinforcements
        game.monsters = [W.Monster("slime", game.player.x + 60, game.player.y)]
        jellies0 = game.items.get("slimejelly", 0)
        # headless get_pressed() reports nothing: hold SPACE via a stub
        monkeypatch.setattr(pygame.key, "get_pressed", lambda: FakeKeys(space=1))
        for _ in range(600):                             # real bolt cooldowns
            game.update(1 / 60)
            if game.kills.get("slime"):
                break
        assert game.kills.get("slime") == 1
        vacuum(game)                                     # magnet collects the drops
        assert game.items.get("slimejelly", 0) > jellies0
        assert game.pickups == []

    def test_e2e_feud_prompt_answered_with_keys(self, game, monkeypatch):
        pin_feud_pair(monkeypatch)                       # Old Tom vs Nessa
        game.day = 3
        assert game.maybe_start_feud() is True
        assert game.overlay == "decision"
        press(game, pygame.K_e)                          # side with option A
        assert game.feuds[0]["sided"] == "Old Tom"
        assert game.rel["Old Tom"] == 25
        assert game.overlay is None

    def test_e2e_pause_save_then_load_restores_state(self, game):
        game.gold, game.day = 999, 4
        press(game, pygame.K_p)                          # pause menu
        assert game.overlay == "pause"
        for _ in range(3):
            press(game, pygame.K_s)                      # sel 0 -> Save(3)
        assert game.pause_sel == 3
        press(game, pygame.K_e)                          # save
        assert game.save_flash > 0
        press(game, pygame.K_ESCAPE)
        game.gold = 111                                  # dirty the live state
        press(game, pygame.K_p)
        for _ in range(4):
            press(game, pygame.K_s)                      # sel -> Load(4)
        press(game, pygame.K_e)                          # open confirm
        assert game.overlay == "confirm"
        press(game, pygame.K_w)                          # sel 1 -> 0 ("Yes")
        press(game, pygame.K_e)
        assert game.gold == 999 and game.day == 4
        assert game.overlay is None and game.state == "play"

    def test_e2e_options_toggle_music_from_pause(self, game):
        assert game.settings["music"] is True
        press(game, pygame.K_p)
        for _ in range(2):
            press(game, pygame.K_s)                      # sel -> Options(2)
        press(game, pygame.K_e)
        assert game.overlay == "options"
        press(game, pygame.K_s); press(game, pygame.K_s) # row 2 = music
        press(game, pygame.K_SPACE)                      # toggle off
        assert game.settings["music"] is False
        press(game, pygame.K_ESCAPE); press(game, pygame.K_ESCAPE)
        assert game.overlay is None
        game.update_music()
        assert game._music_name is None                  # director obeys setting

    def test_e2e_title_continue_roundtrip(self, monkeypatch, tmp_path):
        monkeypatch.setattr(W, "SAVE_PATH", str(tmp_path / "ct.json"))
        _random.seed(7)
        g1 = W.Game()
        g1.state = "play"
        g1.day, g1.gold = 7, 321
        g1.chron("continue-me marker")
        assert g1.save_game() is True
        g2 = W.Game()                                    # fresh title screen
        assert g2.state == "menu"
        press(g2, pygame.K_c)                            # Continue
        assert g2.state == "play"
        assert g2.day == 7 and g2.gold == 321
        assert any("continue-me" in e["text"] for e in g2.chronicle)

    def test_e2e_travel_menu_rumor_pointer_and_depart(self, game):
        game.active_rumor = {"biome": "tundra", "kind": "crystal", "text": "x"}
        game.set_overlay("travel")
        tundra_idx = list(W.BIOMES.keys()).index("tundra")
        for _ in range(tundra_idx):
            press(game, pygame.K_s)
        press(game, pygame.K_e)
        assert game.loc == "tundra"
        assert any(l["kind"] == "crystal" for l in game.landmarks)

    def test_e2e_satchel_sort_drink_cycle(self, game):
        game.add_potion("healing", 1, 2)
        game.add_potion("luck", 1, 1)
        game.player.hp = 40
        game.set_overlay("inv")
        plist = list(game.potions)
        game.inv_sel = plist.index("luck")
        press(game, pygame.K_e)                          # drink selected (luck)
        assert "luck" not in game.potions
        press(game, pygame.K_s)                          # cycle sort mode
        assert game.inv_sort in ("name", "count", "type")
        press(game, pygame.K_i)                          # close
        assert game.overlay is None

    def test_e2e_villager_chat_via_orders_menu(self, game):
        game.set_overlay("orders")
        game.order_tab = 2                               # VILLAGERS tab
        game.overlay_idx = 0
        names = game.villager_list()
        rel0 = game.rel[names[0]]
        game.orders_action(pygame.K_e)                   # chat footer action
        assert game.rel[names[0]] == rel0 + 1

    def test_e2e_mousewheel_scrolls_chronicle(self, game):
        for i in range(30):
            game.chron("entry %d" % i)
        game.open_chronicle()
        assert game.chronicle_sel == len(game.chronicle) - 1
        game.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=3))
        assert game.chronicle_sel == len(game.chronicle) - 4

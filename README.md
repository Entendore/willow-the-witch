# Willow the Witch - Potion Ventures

A cozy witch-shop game in a single Python file. Take orders from ten
villagers with big personalities, gather ingredients across five
procedurally generated biomes, fight monsters for rare crafting parts,
brew potions with a skill minigame, build up your cottage - and uncover
Grandmother Elmira's last recipe.

## Quick start

    ./run.sh            # Linux / macOS
    run.bat             # Windows

## Controls

| Key              | Action                                  |
|------------------|-----------------------------------------|
| WASD / Arrows    | Move                                    |
| E                | Interact / gather / chat / confirm      |
| SPACE            | Magic bolt (wilds) / lock brew minigame |
| 1-4 / H          | Quick-drink potions / Healing Potion    |
| I / B / J / TAB  | Satchel / Bestiary / Chronicle / Ledger |
| M / T            | Minimap size / Quest tracker            |
| P or ESC         | Pause menu (save, options, controls)    |
| Mouse            | Click rows, tabs and buttons everywhere |

## Features

- Orders: persona customers, quality demands (FINE ONLY!), deadlines,
  accept/reject with relationship consequences, personal favor quests
- Crafting: heat+stir brew minigame, 4 quality tiers, catalysts,
  brewing XP/levels, experiment cauldron, 3 secret recipes + 1 sealed
  legendary, refine, quick-brew, sell one/all, Beastcraft tab
- Monsters: 7 types, guaranteed + rare material drops, kill mastery,
  danger-theme music, 5 drinkable buff potions
- World: procedural biome names/weather, terrain zones, winding roads
  (+speed bonus), one-time landmarks, ambient particles, rumor-seeded
  finds
- Village: relationships -> Found Family (visits & gifts), procedural
  feuds with pick-a-side choices, kin spillover, daily events
- Story: 8 chapters + finale (Valeblossom Elixir), auto-writing journal
- Base: 9 buildings with real effects + generated connecting paths
- HUD: minimap, tracker, hotbar, buff rings, danger chevron, ledger
- Audio: fully procedural 8-bit SFX (~40) + 4 looping chiptune themes

## Project layout

    willow.py            the entire game (sections [1]..[8], see TOC)
    tests/test_willow.py unit / integration / perf / memory / e2e suite
    run.sh, run.bat      launchers
    willow_save.json     created at runtime (autosave each morning)

## Testing

    .venv/bin/python -m pytest tests/ -v        # full suite
    .venv/bin/python -m pytest tests/ -v -k unit
    .venv/bin/python -m pytest tests/ -v -k "perf or mem" -s

## Architecture (see TOC inside willow.py)

    [1] constants      [2] chiptune audio engine   [3] game data
    [4] narrative      [5] helpers                 [6] entities
    [7] Game class     [8] entry point

## Troubleshooting

- No sound? Options menu -> toggle music/SFX; the game also runs
  silently if no audio device is present.
- Headless servers: export SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy

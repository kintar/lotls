# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A knowledge base for "The Lantern of the Laughless Saint", an old-school CRPG in the style of Morrowind, Daggerfall, and Skyrim. It's meant to collect game information such as quests, geography, and crafting recipes. A save-game editor is planned later. There's no build or tests yet.

`alchemy_combinations.md` is generated; don't edit it by hand. Rerun the generator after changing `alchemy_ingredients.md`:

```
python3 scripts/generate_combinations.py
```

The script only uses the Python standard library. The combination sizes it covers are set in `SIZES`.

`scripts/gvas.py` is a read-only parser for the game's save files (uncompressed UE 5.8 GVAS, Narrative Pro save system). It prints the property tree with absolute file offsets:

```
python3 scripts/gvas.py <path/to/Save.sav>
```

Player gold, stats and XP are under `PlayerData` near the end of the file. Offsets shift between saves, so locate fields by path, not fixed offsets.

`scripts/gvas_edit.py` builds on it to show and edit values by path or alias (`gold`, `xp`, `attr:<Name>`, `skill:<Name>.<Field>`, `skillpoints`, `perkpoints`):

```
python3 scripts/gvas_edit.py show <save> gold skill:Alchemy
python3 scripts/gvas_edit.py set <save> gold=5000 skill:Alchemy.Level=25
```

It only patches fixed-size values (int, float, bool) in place. Strings, names and anything that changes length would require rewriting every enclosing size field, which isn't implemented.

## Data conventions

`alchemy_ingredients.md` holds ingredient data:
- One `# Ingredient Name` heading per ingredient, sorted alphabetically.
- Each ingredient lists exactly four effects as a bullet list, in the order the game shows them.
- An effect that hasn't been discovered yet is written as `- ???`. Keep the placeholder in that slot so the other effects stay in their positions.
- Bullets use `- Effect` with a space after the dash. A few older entries are missing the space (`-Effect`); normalize them when you edit nearby.
- Effect names are written the way the game spells them (e.g. "Fortify Two-Handed", "Damage Health (Over Time)", "Boost Stamina Regen"). Reuse an existing spelling instead of creating a variant, since the data may later be parsed by tooling such as the planned save editor.

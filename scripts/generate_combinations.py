#!/usr/bin/env python3
"""Regenerate alchemy_combinations.md from alchemy_ingredients.md."""
import itertools
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "alchemy_ingredients.md"
OUTPUT = ROOT / "alchemy_combinations.md"
SIZES = ((2, "Two"), (3, "Three"))


def load_ingredients():
    ingredients = {}
    current = None
    for line in SOURCE.read_text().splitlines():
        line = line.strip()
        if line.startswith("# "):
            current = line[2:].strip()
            ingredients[current] = []
        elif line.startswith("-") and current:
            effect = line[1:].strip()
            if effect != "???":
                ingredients[current].append(effect)
    return ingredients


def potion(ingredients, combo):
    """Effects shared by at least two ingredients, or None if any ingredient adds nothing."""
    counts = Counter(e for name in combo for e in set(ingredients[name]))
    effects = {e for e, n in counts.items() if n >= 2}
    if not effects or any(not (set(ingredients[name]) & effects) for name in combo):
        return None
    return sorted(effects)


def main():
    ingredients = load_ingredients()
    names = sorted(ingredients)
    out = [
        "Combinations generated from `alchemy_ingredients.md` by `scripts/generate_combinations.py`. "
        "A potion gets every effect that at least two of its ingredients share, and a combination counts "
        "only if every ingredient adds at least one of those effects. Unknown (`???`) effects are not "
        "included, so this list will change as they are discovered.",
        "",
    ]
    for size, label in SIZES:
        out += [f"# {label}-Ingredient Potions", ""]
        for combo in itertools.combinations(names, size):
            effects = potion(ingredients, combo)
            if effects:
                out.append(f"## {' + '.join(combo)}")
                out += [f"- {e}" for e in effects]
                out.append("")
    OUTPUT.write_text("\n".join(out).rstrip() + "\n")


if __name__ == "__main__":
    main()

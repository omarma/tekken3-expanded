#!/usr/bin/env python3
"""Add GTE library seeds to the phase2 seed file."""
import json

SEED_FILE = "recompiler/seeds/phase2_ghidra_seeds.json"

NEW_SEEDS = [
    "0xBFC34E00", "0xBFC3586C", "0xBFC359B4", "0xBFC35AD8",
    "0xBFC35B08", "0xBFC35B38", "0xBFC35B68",
    "0xBFC36000", "0xBFC36024", "0xBFC36068", "0xBFC36094",
    "0xBFC360E0", "0xBFC36104", "0xBFC3614C", "0xBFC36178",
    "0xBFC361A0", "0xBFC361CC", "0xBFC361F4", "0xBFC3621C",
    "0xBFC36244", "0xBFC3625C", "0xBFC36280", "0xBFC36294",
    "0xBFC362BC", "0xBFC362D0", "0xBFC3632C", "0xBFC36388",
    "0xBFC363A0", "0xBFC363F0", "0xBFC36458", "0xBFC364DC",
    "0xBFC3653C", "0xBFC365C4", "0xBFC365F8", "0xBFC36684",
    "0xBFC36740", "0xBFC367D4", "0xBFC36880", "0xBFC36940",
    "0xBFC36998", "0xBFC36A3C", "0xBFC36B14", "0xBFC36BEC",
    "0xBFC36C60", "0xBFC36CA4", "0xBFC36FF0",
]

with open(SEED_FILE) as f:
    data = json.load(f)

existing = {s["address"] for s in data["seeds"]}
added = 0
for addr in NEW_SEEDS:
    if addr not in existing:
        data["seeds"].append({"address": addr, "name": f"gte_lib_{addr[2:]}"})
        added += 1

data["seed_count"] = len(data["seeds"])
data["source"] += " + gte_lib_seeds"

with open(SEED_FILE, "w") as f:
    json.dump(data, f, indent=2)

print(f"Added {added} new seeds. Total: {data['seed_count']}")

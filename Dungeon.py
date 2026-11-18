#!/usr/bin/env python3
"""
Dungeon Mode for Havenus Elite
"""
import json
import random
import sys
import time
from copy import deepcopy
from typing import Callable, List, Dict, Any, Iterator, Optional
from main import (
    MIST_OF_TRUTH,
    SWORD_OF_THE_FORGOTTEN,
    Combatant,
    load_combatants_from_file,
    run_interactive_battle,
)

# File paths
ENEMY_FILE = "enemy.json"
FLOOR_DATA_FILE = "Floor_Data.json"
REALIGEAR_FILE = "RealiGear.json"
SHOP_FILE = "Shop.json"
BATTLE_HANDLER_FILE = "Battle_Handler.json"
OCCURANCE_HANDLER_FILE = "Occurance_Handler.json"
ONRUSH_HANDLER_FILE = "Onrush_handler.json"
STORY_FILE = "story.json"
LIMBURST_FILE = "LIMBurst.json"
EXTRA_UNITS_FILE = "extra_units.json"
PLAYER_SAVE_FILE = "player_save.json"
STARTING_COMBATANTS = [
    "Macduff",
    "Racheal",
    "The Monster",
    "Goole",
    "Antonia",
    "Romeo",
    "Snowball",
    "Sherlock",
    "Kyla",
    "George",
    "Linda",
    "Tia",
    "A Sector Assassin Antonia",
]
CHARACTERS = [
    "Macduff", "Racheal", "The Monster", "Goole", "Antonia", "Romeo",
    "Snowball", "Sherlock", "Kyla", "George", "Linda", "Tia",
]
STARTING_LIMBURSTS = [
    {"Character": "Macduff", "Name": "Sinner's Sword"},
    {"Character": "Racheal", "Name": "Lost One's Spear"},
    {"Character": "The Monster", "Name": "Cataclysmic Slam"},
    {"Character": "Goole", "Name": "Silence Of Solidarity"},
    {"Character": "Antonia", "Name": "Golden Barter"},
    {"Character": "Romeo", "Name": "Frost Mist Waltz"},
    {"Character": "Snowball", "Name": "Withered Spirit"},
    {"Character": "Sherlock", "Name": "Bullet of Expertise"},
    {"Character": "George", "Name": "Hammer Of Gloom"},
    {"Character": "Kyla", "Name": "Mental Distress"},
    {"Character": "Linda", "Name": "Delusional Dreams"},
    {"Character": "Tia", "Name": "Rewriting"},
]
STORY_CHAPTERS = [
    "Story Mode 1",
    "Story Branch 1.1",
    "Story Branch 1.2",
    "Story Mode 2",
    "Story Branch 2.1",
]
CHAPTER_DISPLAY_NAMES = {
    "Story Branch 2.1": "Chapter Branch 2.1",
}
DUNGEON_FLOORS = [
    "Level 1 Floor",
    "Level 2 Floor",
    "Level 3 Floor",
    "Level 4 Floor",
    "Samurai Dojo",
    "Samurai Commandment",
    "Pyric Offence",
    "Extinguishment",
    "Battle Blood",
    "The Castle Of Flames",
    "Boss Rush 1",
    "Boss Rush 2",
]
DUNGEON_ADVERSITIES = {
    "10% more HP": "hp",
    "Deal 10% more damage": "damage",
    "+10 Defense": "defense",
    "+1 min and max speed": "speed",
    "Base Power +1": "base_power",
}


def chapter_display_name(chapter: str) -> str:
    return CHAPTER_DISPLAY_NAMES.get(chapter, chapter)


EVERCHANGING_COMBATANTS = [
    "Infernal Over-xtinguisher Macduff"
]
CLASS_PORTRAIT_CLASSES = [
    "A Sector",
    "E Sector",
    "F Sector",
    "L Sector",
    "Illumina Samurai",
    "Way Of The Blade",
    "Quantum Corp.",
]
REMEMBRANCE_COMBATANTS = [
    "Divinus LB Suit :: For Correct Justice Macduff",
    "Divinus LB Tool :: Blazing Blade George",
    "Guillevien Branch N Commander Snowball",
    "Guillevien Branch N Commander Linda",
    "Den Dwellers Romeo",
    "Oni Crawlers The Monster",
]
REMEMBRANCE_LIMBURSTS = [
    {"Character": "Snowball", "Name": "Land Master"},
    {"Character": "The Monster", "Name": "Of Past"},
    {"Character": "Macduff", "Name": "For Correct Justice"},
]
REMEMBRANCE_BURST_CONVERSION_CHANCE = 0.45
REMEMBRANCE_PORTRAIT_ENABLED = False

def load_json(file_path: str) -> Dict[str, Any]:
    with open(file_path, 'r') as f:
        return json.load(f)


def parse_speed_range(speed_range: str) -> Optional[tuple[int, int]]:
    try:
        lo, hi = map(int, speed_range.split("-"))
        return lo, hi
    except Exception:
        return None


def increase_speed_range(speed_range: str, amount: int) -> str:
    parsed = parse_speed_range(speed_range)
    if not parsed:
        return speed_range
    lo, hi = parsed
    lo = max(0, lo + amount)
    hi = max(lo, hi + amount)
    return f"{lo}-{hi}"


def get_reali_gear_cost(name: str, reali_gear: Dict[str, Any], owned_gear: set[str]) -> int:
    base_cost = int(reali_gear["RealiGear"][name]["Tier"] * 50)
    if "Lucky Charm" in owned_gear:
        discounted = int(base_cost * 0.9)
        return max(1, discounted)
    return base_cost


def draw_reali_gear_stock(
    shop_data: Dict[str, Any],
    reali_gear: Dict[str, Any],
    owned_gear: set[str],
) -> List[str]:
    gear_catalog = reali_gear["RealiGear"]
    shop_gear = shop_data.get("realiGear", [])
    missing_gear = [name for name in shop_gear if name not in gear_catalog]
    if missing_gear:
        raise KeyError(f"Shop references unknown RealiGear: {missing_gear}")

    stock = []
    for tier, amount in ((1, 3), (2, 2), (3, 1)):
        available = [
            name for name in shop_gear
            if name not in owned_gear and gear_catalog[name]["Tier"] == tier
        ]
        stock.extend(random.sample(available, min(amount, len(available))))
    return stock


def choose_element_for_cloak() -> str:
    elements = ["Fire", "Water", "Wind", "Earth", "Lightning", "Void", "Charm"]
    print("Choose an element to resist:")
    for idx, elem in enumerate(elements, 1):
        print(f"  {idx}. {elem}")
    while True:
        choice = input("Select element (number): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(elements):
                return elements[idx]
        except ValueError:
            pass
        print("Invalid selection. Please choose a valid element.")


def apply_reali_gear_effect(player_team: List[Combatant], reali_gear: Dict[str, Any], name: str, owned_gear: set[str]) -> None:
    if name == "Lucky Charm":
        owned_gear.add("Lucky Charm")
        print("🎲 Lucky Charm purchased: shop prices are now 10% cheaper.")
        return

    if name == "Health Amulet":
        for c in player_team:
            c.max_hp += 50
            c.hp += 50
        print("❤️ Health Amulet equipped: max HP increased by 50 for all team members.")
        return

    if name == "Speed Boots":
        for c in player_team:
            c.speed_range = increase_speed_range(c.speed_range, 1)
        print("⚡ Speed Boots equipped: speed range increased by 1 for all team members.")
        return

    if name == "Power Ring":
        for c in player_team:
            c.gear_bonuses["Power Ring"] = c.gear_bonuses.get("Power Ring", 0) + 20
        print("💪 Power Ring equipped: attack power increased by 20% for all team members.")
        return

    if name == "Defense Shield":
        for c in player_team:
            c.defense += 10
        print("🛡️ Defense Shield equipped: defense increased by 10 for all team members.")
        return

    if name == "Elemental Cloak":
        element = choose_element_for_cloak()
        for c in player_team:
            c.resistances[element] = "Ineff"
        print(f"🧥 Elemental Cloak equipped: all team members gain Ineff resistance to {element}.")
        return

    team_wide_gear = {
        "Claws Of Wood",
        "Umbrella To Wash Away Guilt",
        "Lone Clouds",
        "Breifcase Full Of Bullets",
        "The Cape of the Flame Conqueror",
    }
    if name in team_wide_gear:
        for c in player_team:
            c.gear_bonuses[name] = 1
        print(f"✨ {name} equipped for all team members.")
        return

    if name == "Trunk Body":
        if player_team:
            player_team[0].gear_bonuses[name] = 1
        print("🌳 Trunk Body equipped by the first unit in the team order.")
        return

    raise ValueError(f"No effect handler for RealiGear {name!r}.")


def select_starting_team(
    combatants: Dict[str, Any],
    excluded_names: Optional[List[str]] = None,
    unlocked_combatants: Optional[List[str]] = None,
    unlocked_limbursts: Optional[List[Dict[str, str]]] = None,
) -> List[Combatant]:
    from main import load_json_file, LIMBURST_FILE
    from copy import deepcopy

    # Load Limit Bursts
    lb_data = {}
    try:
        lb_data = load_json_file(LIMBURST_FILE).get("LimitBursts", {})
    except Exception as e:
        print(f"Warning: Could not load {LIMBURST_FILE}: {e}")

    excluded_names = [name.strip() for name in (excluded_names or []) if name and name.strip()]
    normalized_exclusions = {name.lower() for name in excluded_names}

    def is_excluded(name: str) -> bool:
        normalized_name = name.lower()
        return any(
            banned in normalized_name
            for banned in normalized_exclusions
        )

    available_combatants = (
        set(unlocked_combatants) if unlocked_combatants is not None
        else set(STARTING_COMBATANTS)
    )
    roster = sorted(
        name for name in combatants
        if name in available_combatants and not is_excluded(name)
    )
    if not roster:
        print("No combatants found.")
        sys.exit(1)
    if len(roster) < 2:
        raise ValueError(
            "At least two eligible combatants are required to select a team."
        )
    print("Available Combatants:")
    for i, name in enumerate(roster, 1):
        print(f"{i}. {name}")
    selected = []
    while len(selected) < 4:
        try:
            choice = int(input(f"Select Combatant {len(selected)+1} (number): ")) - 1
            if 0 <= choice < len(roster):
                name = roster[choice]
                base_c = deepcopy(Combatant(combatants[name], name))
                if base_c.name not in [c.name for c in selected]:

                    # Handle Limit Burst Selection
                    available_lbs = [
                        burst for burst in lb_data.get(base_c.name, [])
                        if unlocked_limbursts is None
                        or is_limburst_unlocked(
                            unlocked_limbursts, base_c.name, burst.get("Name", "")
                        )
                    ]
                    if available_lbs:
                        print(f"\n✨ Select Limit Burst for {base_c.name}:")
                        for j, lb in enumerate(available_lbs):
                            print(f"  [{j}] {lb['Name']} ({lb['Type']}) - Cost: {lb['Cost']}")

                        lb_choice = input(f"Choice (0-{len(available_lbs)-1}, default 0): ").strip()
                        try:
                            lb_idx = int(lb_choice) if lb_choice else 0
                            if 0 <= lb_idx < len(available_lbs):
                                base_c.selected_limit_burst = available_lbs[lb_idx]
                            else:
                                base_c.selected_limit_burst = available_lbs[0]
                        except ValueError:
                            print("Invalid choice. Using default.")
                            base_c.selected_limit_burst = available_lbs[0]

                    selected.append(base_c)
                else:
                    print(f"{base_c.name} is already selected.")
            else:
                print("Invalid choice.")
        except ValueError:
            print("Invalid input.")
    return selected


def create_special_boss_team(
    combatants: Dict[str, Any],
    names: List[str],
    skill_slots: Optional[int] = None,
) -> List[Combatant]:
    from copy import deepcopy

    team = []
    for name in names:
        raw = combatants.get(name)
        if raw is None:
            raise KeyError(f"Special boss combatant not found: {name}")
        if raw.get("Class") != "Havenus Elite":
            raise ValueError(f"Special boss combatant is not Havenus Elite: {name}")
        combatant = deepcopy(Combatant(raw, name))
        combatant.skill_slots = skill_slots if skill_slots is not None else 5
        if skill_slots is not None:
            combatant._fixed_skill_slots = skill_slots
        team.append(combatant)
    return team


def configure_special_boss(boss: Combatant, section: Dict[str, Any], limburst_data: Dict[str, Any]) -> None:
    skill_slots = section.get("skill_slots")
    boss.skill_slots = skill_slots if skill_slots is not None else 5
    if skill_slots is not None:
        boss._fixed_skill_slots = skill_slots
    boss.forced_skill_sequences = section.get("skill_sequences", {})
    boss.forced_skill_sequence_index = 0
    boss.forced_limit_burst_cost = section.get("limit_burst_cost", {})
    boss.selected_limit_burst = None

    limit_burst_name = section.get("limit_burst")
    if not limit_burst_name:
        return

    limit_bursts = (limburst_data or {}).get("LimitBursts", {})
    boss.selected_limit_burst = next(
        (
            burst
            for bursts in limit_bursts.values()
            for burst in bursts
            if burst.get("Name") == limit_burst_name
        ),
        None,
    )
    if boss.selected_limit_burst is None:
        raise KeyError(f"Special boss Limit Burst not found: {limit_burst_name}")

def choose_floor() -> str:
    floors = ["Floor 1", "Floor 2", "Floor 3", "Floor 4", "Samurai Dojo", "Pyric Offence", "The Castle Of Flames", "Story Mode 1", "Boss Rush 1", "VS Vin", "VS Macbeth", "Story Branch 1.1", "Story Branch 1.2", "Boss Onrush", "Story Mode 2", "Boss Rush 2", "VS The Lord of the Flies", "Spectral Truth Test"]
    print("Choose a floor:")
    for i, floor in enumerate(floors, 1):
        print(f"{i}. {floor}")
    choice = int(input("Select floor (number): ")) - 1
    return floors[choice]


def iter_floor_sections(
    floor_data: Dict[str, Any],
) -> Iterator[tuple[str, Dict[str, Any], bool]]:
    while True:
        floor = choose_floor()
        for index, section in enumerate(floor_data["Floors"][floor]["sections"]):
            yield floor, section, index == 0

        print("Floor completed! Congratulations.")
        while True:
            choice = input("1. Try another floor\n2. End here\nChoose: ").strip()
            if choice == "1":
                break
            if choice == "2":
                return
            print("Invalid selection. Please choose 1 or 2.")


def get_enemies_from_pool(pool_name: str, battle_handler: Dict[str, Any], enemy_data: Dict[str, Any]) -> List[Combatant]:
    pool = battle_handler["Pools"].get(pool_name, [])
    enemies = []
    for item in pool:
        enemy_name = item["enemy"]
        amount = item["amount"]
        for _ in range(amount):
            if enemy_name in enemy_data["Enemies"]:
                raw = enemy_data["Enemies"][enemy_name]
                # Handle deformality
                if raw.get("deformality") == "yes":
                    parts = raw.get("parts", [])
                    for part in parts:
                        part_raw = dict(raw)  # copy
                        part_raw.update(part)
                        part_raw["Name"] = part["Name"]
                        enemies.append(Combatant(part_raw, part["Name"]))
                else:
                    enemies.append(Combatant(raw, enemy_name))
    return enemies


def get_enemies_for_section(section: Dict[str, Any], battle_handler: Dict[str, Any], enemy_data: Dict[str, Any]) -> List[Combatant]:
    if "pool" in section:
        return get_enemies_from_pool(section["pool"], battle_handler, enemy_data)

    if "enemy" in section:
        enemy_key = section["enemy"]
        if enemy_key in battle_handler["Pools"]:
            return get_enemies_from_pool(enemy_key, battle_handler, enemy_data)
        if enemy_key in enemy_data["Enemies"]:
            raw = enemy_data["Enemies"][enemy_key]
            if raw.get("deformality") == "yes":
                enemies = []
                for part in raw.get("parts", []):
                    part_raw = dict(raw)
                    part_raw.update(part)
                    part_raw["Name"] = part["Name"]
                    enemies.append(Combatant(part_raw, part["Name"]))
                return enemies
            return [Combatant(raw, enemy_key)]
        print(f"Unknown enemy or pool: {enemy_key}")
    return []


def get_onrush_teams(section: Dict[str, Any], onrush_handler: Dict[str, Any],
                     battle_handler: Dict[str, Any], enemy_data: Dict[str, Any]) -> tuple[List[Combatant], List[Combatant]]:
    onrush = onrush_handler["Onrushes"].get(section["pool"])
    if not onrush:
        print(f"Unknown onrush: {section['pool']}")
        return [], []

    enemies = []
    for enemy_name in onrush.get("enemies", []):
        enemies.extend(get_enemies_for_section({"enemy": enemy_name}, battle_handler, enemy_data))

    starting_amount = int(onrush.get("starting_enemies", 0))
    if starting_amount < 1 or starting_amount > len(enemies):
        print(f"Invalid starting enemy amount for onrush: {section['pool']}")
        return [], []
    return enemies[:starting_amount], enemies[starting_amount:]


def add_extra_unit_to_team(
    player_team: List[Combatant],
    section: Dict[str, Any],
    extra_units_data: Dict[str, Any],
) -> List[Combatant]:
    extra_unit_name = section.get("extra unit")
    if not extra_unit_name:
        return player_team
    extra_raw = extra_units_data.get(extra_unit_name)
    if extra_raw is None:
        raise KeyError(f"Extra unit not found: {extra_unit_name}")
    extra_unit = Combatant(extra_raw, extra_unit_name)
    extra_unit.is_extra_unit = True
    battle_team = player_team + [extra_unit]
    for unit in battle_team:
        unit.team_members = battle_team
    return battle_team


def handle_occurrence(occurrence_name: str, occurance_handler: Dict[str, Any], player_team: List[Combatant]) -> bool:
    occ = occurance_handler["Occurrences"].get(occurrence_name)
    if not occ:
        print(f"Unknown occurrence: {occurrence_name}")
        return True
    print(f"Occurrence: {occ['description']}")
    effect = occ["effect"]
    if effect == "damage":
        dmg = occ["value"]
        for c in player_team:
            if c.is_alive():
                c.take_damage(dmg)
                print(f"{c.name} takes {dmg} damage. HP: {c.hp}/{c.max_hp}")
    elif effect == "status":
        status = occ["status"]
        potency = occ["potency"]
        count = occ["count"]
        for c in player_team:
            if c.is_alive():
                c.apply_status(status, potency, count)
                print(f"{c.name} gains {status} ({potency}, {count})")
    elif effect == "check":
        element = occ["element"]
        threshold = occ["threshold"]
        # Assume player has element matching, roll d20 + morale/10
        for c in player_team:
            if c.is_alive():
                roll = random.randint(1, 20) + c.morale // 10
                if roll >= threshold:
                    print(f"{c.name} passes the {element} check (roll: {roll} >= {threshold})")
                else:
                    print(f"{c.name} fails the {element} check (roll: {roll} < {threshold})")
                    # Fail: take damage or something
                    c.take_damage(50)
                    print(f"{c.name} takes 50 damage from failure.")
    elif effect == "deformality":
        enemy = occ["enemy"]
        print(f"Deformality triggered: {enemy}")
        # This will lead to boss battle
        return enemy
    return True


def handle_story(pool_name: str, story_handler: Dict[str, Any]) -> None:
    story_pool = story_handler.get("Pools", {}).get(pool_name, [])
    if not story_pool:
        print(f"Unknown or empty story pool: {pool_name}")
        return

    for entry in story_pool:
        speaker = entry.get("speaker", "Narrator")
        dialogue = entry.get("dialogue", "")
        print(f"{speaker}: ", end="", flush=True)
        for character in dialogue:
            print(character, end="", flush=True)
            time.sleep(0.03)
        print()

def clear_statuses_and_heal(player_team: List[Combatant]):
    for c in player_team:
        c.statuses.clear()
        if c.is_alive():
            heal_amount = max(1, int(c.max_hp * 0.25))
            c.heal(heal_amount)
            c.morale = min(100, c.morale + 30)
            print(f"{c.name} is restored: cleared statuses, healed {heal_amount} HP, and recovered 30 morale (now {c.hp}/{c.max_hp}, morale {c.morale}).")
        else:
            c.morale = min(100, c.morale + 30)
            print(f"{c.name} was dead; cleared all lingering statuses and recovered 30 morale without reviving them.")


def should_continue_story_after_boss_loss(floor_name: str, boss_name: str) -> bool:
    return floor_name == "Story Branch 1.1" and boss_name == "Vin - The Diamond Commander"


def revive_dead_allies(player_team: List[Combatant]) -> int:
    dead_allies = [c for c in player_team if not c.is_alive()]
    for c in dead_allies:
        c.statuses.clear()
        c.hp = c.max_hp
        c.alive = True
        c.subdued = False
    return len(dead_allies)


def shop_interface(player_team: List[Combatant], shop_data: Dict[str, Any], reali_gear: Dict[str, Any], cash: int, owned_gear: set[str]) -> int:
    stock = draw_reali_gear_stock(shop_data, reali_gear, owned_gear)
    print(f"Welcome to the shop! You have {cash} cash.")
    while True:
        print("\nShop options:")
        print("1. Realigear")
        print("2. Heals and Revivals")
        print("3. Leave")
        choice = input("Choose: ").strip()

        if choice == "1":
            if not stock:
                print("No RealiGear remains available in this shop.")
                continue
            print("Available RealiGear:")
            for index, name in enumerate(stock, 1):
                item = reali_gear["RealiGear"][name]
                cost = get_reali_gear_cost(name, reali_gear, owned_gear)
                print(
                    f"{index}. {name} (Tier {item['Tier']}, {cost} cash): "
                    f"{item['Description']}"
                )
            print("0. Back to shop options")
            try:
                gear_choice = int(input("Select RealiGear: ").strip())
            except ValueError:
                print("Invalid selection.")
                continue
            if gear_choice == 0:
                continue
            if not 1 <= gear_choice <= len(stock):
                print("Invalid selection.")
                continue

            name = stock[gear_choice - 1]
            cost = get_reali_gear_cost(name, reali_gear, owned_gear)
            if cash < cost:
                print(f"Not enough cash to buy {name}.")
                continue
            apply_reali_gear_effect(player_team, reali_gear, name, owned_gear)
            cash -= cost
            owned_gear.add(name)
            stock.remove(name)
            print(f"Bought {name} for {cost} cash. You have {cash} cash remaining.")
        elif choice == "2":
            needs_recovery = any(
                not c.is_alive() or c.hp < c.max_hp for c in player_team
            )
            if not needs_recovery:
                print("All units are already fully healed and alive.")
                continue
            if cash < 200:
                print("Not enough cash. Healing and revivals cost 200 cash.")
                continue
            while True:
                confirm = input(
                    "Spend 200 cash to fully heal and revive all units? (y/n): "
                ).strip().lower()
                if confirm in {"y", "yes"}:
                    cash -= 200
                    revived_count = revive_dead_allies(player_team)
                    for unit in player_team:
                        unit.hp = unit.max_hp
                    print(
                        f"Spent 200 cash. Fully healed the team and revived "
                        f"{revived_count} unit(s)."
                    )
                    break
                if confirm in {"n", "no"}:
                    print("No healing or revivals purchased.")
                    break
                print("Please answer y or n.")
        elif choice == "3":
            print("Leaving the shop.")
            return cash
        else:
            print("Invalid selection.")


def new_player_state(combatants: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "keys": 3000,
        "cash": 500,
        "owned_gear": [],
        "unlocked_combatants": [
            name for name in STARTING_COMBATANTS if name in combatants
        ],
        "unlocked_limbursts": [dict(burst) for burst in STARTING_LIMBURSTS],
        "planes": {character: 0 for character in CHARACTERS},
        "unlocked_chapters": [STORY_CHAPTERS[0]],
        "completed_chapters": [],
        "active_story": None,
        "portrait_counters": {"everchanging": 0, "class": 0, "remembrance": 0},
        "portraits": {},
    }


def all_limburst_skills(limburst_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"Character": character, **burst}
        for character, bursts in limburst_data.get("LimitBursts", {}).items()
        for burst in bursts
    ]


def is_limburst_unlocked(
    unlocked_limbursts: List[Dict[str, str]], character: str, name: str
) -> bool:
    return any(
        burst.get("Character") == character and burst.get("Name") == name
        for burst in unlocked_limbursts
        if isinstance(burst, dict)
    )


def load_player_state(
    combatants: Dict[str, Any], limburst_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    try:
        with open(PLAYER_SAVE_FILE, "r", encoding="utf-8") as save_file:
            saved_state = json.load(save_file)
    except FileNotFoundError:
        return new_player_state(combatants)

    if not isinstance(saved_state, dict):
        raise ValueError(f"{PLAYER_SAVE_FILE} must contain a JSON object.")

    if limburst_data is None:
        limburst_data = load_json(LIMBURST_FILE)
    state = new_player_state(combatants)
    state.update(saved_state)
    state["unlocked_combatants"] = list(dict.fromkeys(
        name for name in state.get("unlocked_combatants", [])
        if name in combatants
    ))
    for name in STARTING_COMBATANTS:
        if name in combatants and name not in state["unlocked_combatants"]:
            state["unlocked_combatants"].append(name)
    all_bursts = all_limburst_skills(limburst_data)
    all_burst_keys = {
        (burst["Character"], burst["Name"]) for burst in all_bursts
    }
    unlocked_bursts: List[Dict[str, str]] = []
    unlocked_burst_keys = set()
    for saved_burst in state.get("unlocked_limbursts", []):
        if isinstance(saved_burst, str):
            # Old saves stored only names, which unlocked every same-name variant.
            matching_bursts = [
                (burst["Character"], burst["Name"])
                for burst in all_bursts
                if burst["Name"] == saved_burst
            ]
        elif isinstance(saved_burst, dict):
            matching_bursts = [(
                saved_burst.get("Character"),
                saved_burst.get("Name"),
            )]
        else:
            continue
        for character, name in matching_bursts:
            burst_key = (character, name)
            if burst_key in all_burst_keys and burst_key not in unlocked_burst_keys:
                unlocked_bursts.append({"Character": character, "Name": name})
                unlocked_burst_keys.add(burst_key)
    for burst in STARTING_LIMBURSTS:
        burst_key = (burst["Character"], burst["Name"])
        if burst_key in all_burst_keys and burst_key not in unlocked_burst_keys:
            unlocked_bursts.append(dict(burst))
            unlocked_burst_keys.add(burst_key)
    state["unlocked_limbursts"] = unlocked_bursts
    saved_planes = state.get("planes", {})
    state["planes"] = {
        character: max(0, int(saved_planes.get(character, 0)))
        for character in CHARACTERS
    }

    state["unlocked_chapters"] = [
        chapter for chapter in STORY_CHAPTERS
        if chapter in state.get("unlocked_chapters", [])
    ] or [STORY_CHAPTERS[0]]
    state["completed_chapters"] = [
        chapter for chapter in STORY_CHAPTERS
        if chapter in state.get("completed_chapters", [])
    ]
    if ("Story Mode 2" in state["completed_chapters"]
            and "Story Branch 2.1" not in state["unlocked_chapters"]):
        state["unlocked_chapters"].append("Story Branch 2.1")
    state.pop("unlocked_challenges", None)
    counters = state.get("portrait_counters", {})
    state["portrait_counters"] = {
        "everchanging": max(
            0, int(counters.get("everchanging", counters.get("status", 0)))
        ),
        "class": max(0, int(counters.get("class", counters.get("combatant", 0)))),
        "remembrance": max(0, int(counters.get("remembrance", 0))),
    }
    state["keys"] = max(0, int(state.get("keys", 3000)))
    state["cash"] = max(0, int(state.get("cash", 500)))
    state["owned_gear"] = list(dict.fromkeys(state.get("owned_gear", [])))
    return state


def save_player_state(state: Dict[str, Any]) -> None:
    temporary_path = f"{PLAYER_SAVE_FILE}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as save_file:
        json.dump(state, save_file, indent=2)
    import os
    os.replace(temporary_path, PLAYER_SAVE_FILE)


def refresh_portraits(
    state: Dict[str, Any], combatants: Dict[str, Any]
) -> None:
    selected_class = random.choice(CLASS_PORTRAIT_CLASSES)
    class_rate_up = [
        name for name, raw in combatants.items()
        if (not REMEMBRANCE_PORTRAIT_ENABLED
            or name not in REMEMBRANCE_COMBATANTS)
        and raw.get("Class") == selected_class
    ]
    if not class_rate_up:
        raise ValueError(f"Class Portrait has no combatants for {selected_class!r}.")
    portraits = {
        "everchanging": {
            "label": "Everchanging",
            "rate_up": [
                name for name in EVERCHANGING_COMBATANTS if name in combatants
            ],
        },
        "class": {"label": selected_class, "rate_up": class_rate_up},
    }
    if REMEMBRANCE_PORTRAIT_ENABLED:
        portraits["remembrance"] = {
            "label": "Remembrance",
            "rate_up": [
                name for name in REMEMBRANCE_COMBATANTS if name in combatants
            ],
        }
    state["portraits"] = portraits


def portrait_combatant_pools(
    portrait_key: str,
    portrait: Dict[str, Any],
    combatants: Dict[str, Any],
) -> tuple[List[str], List[str]]:
    allowed = [
        name for name in combatants
        if (not REMEMBRANCE_PORTRAIT_ENABLED
            or portrait_key == "remembrance"
            or name not in REMEMBRANCE_COMBATANTS)
    ]
    allowed_set = set(allowed)
    rate_up = [
        name for name in portrait.get("rate_up", [])
        if name in allowed_set
    ]
    rate_up_set = set(rate_up)
    natural = [name for name in allowed if name not in rate_up_set]
    return rate_up, natural


def serialize_team(team: List[Combatant]) -> List[Dict[str, Any]]:
    return [
        {
            "key": combatant.key,
            "hp": combatant.hp,
            "max_hp": combatant.max_hp,
            "morale": combatant.morale,
            "alive": combatant.alive,
            "defense": combatant.defense,
            "speed_range": combatant.speed_range,
            "resistances": dict(combatant.resistances),
            "gear_bonuses": dict(combatant.gear_bonuses),
            "statuses": combatant.statuses,
            "skill_slots": combatant.skill_slots,
            "limit_burst": (
                combatant.selected_limit_burst.get("Name")
                if combatant.selected_limit_burst else None
            ),
        }
        for combatant in team
    ]


def reset_team_for_retry(team: List[Combatant]) -> None:
    for unit in team:
        unit.hp = unit.max_hp
        unit.morale = 50
        unit.alive = True
        unit.statuses.clear()
        unit._was_alive = True
        unit.prepare_for_battle()


def run_battle_with_retry(
    state: Dict[str, Any],
    player_team: List[Combatant],
    run_battle: Callable[[], tuple[List[Combatant], List[Combatant], List[str]]],
) -> bool:
    while True:
        battle_team, enemies, transcript = run_battle()
        battle_result = transcript[-1].strip() if transcript else None
        if (battle_result == "TEAM A WINS!"
                or (any(unit.is_alive() for unit in battle_team)
                    and not any(enemy.is_alive() for enemy in enemies))):
            state["keys"] += 300
            save_player_state(state)
            print(f"Victory! Gained 300 Keys. Total: {state['keys']}")
            return True

        print("Battle lost.")
        reset_team_for_retry(player_team)
        while True:
            choice = input("1. Retry battle\n2. Return to menu\nChoose: ").strip()
            if choice == "1":
                break
            if choice == "2":
                return False
            print("Invalid selection.")


def restore_team(
    saved_team: List[Dict[str, Any]], combatants: Dict[str, Any]
) -> List[Combatant]:
    from main import load_json_file

    bursts_by_character_and_name = {
        (character, burst.get("Name")): burst
        for character, bursts in load_json_file(LIMBURST_FILE).get("LimitBursts", {}).items()
        for burst in bursts
    }
    team = []
    for saved in saved_team:
        key = saved.get("key")
        if key not in combatants:
            raise ValueError(f"Saved team contains unknown combatant: {key}")
        unit = Combatant(combatants[key], key)
        unit.max_hp = max(1, int(saved.get("max_hp", unit.max_hp)))
        unit.hp = max(0, min(unit.max_hp, int(saved.get("hp", unit.max_hp))))
        unit.morale = max(0, min(100, int(saved.get("morale", 50))))
        unit.alive = bool(saved.get("alive", unit.hp > 0))
        unit.defense = int(saved.get("defense", unit.defense))
        unit.speed_range = saved.get("speed_range", unit.speed_range)
        unit.resistances = dict(saved.get("resistances", unit.resistances))
        unit.gear_bonuses = {
            name: int(value)
            for name, value in saved.get("gear_bonuses", {}).items()
        }
        unit.statuses = saved.get("statuses", {})
        unit.skill_slots = max(1, int(saved.get("skill_slots", 1)))
        burst_name = saved.get("limit_burst")
        unit.selected_limit_burst = bursts_by_character_and_name.get(
            (unit.name, burst_name)
        )
        team.append(unit)
    for unit in team:
        unit.team_members = team
    return team


def choose_unlocked_combatant(
    state: Dict[str, Any], combatants: Dict[str, Any], rate_up: List[str]
) -> str:
    locked = [
        name for name in rate_up
        if name in combatants and name not in state["unlocked_combatants"]
    ]
    if not locked:
        print("All rate-up combatants are already unlocked.")
        return ""
    print("Choose a combatant to unlock:")
    for index, name in enumerate(locked, 1):
        print(f"{index}. {name} (Tier {combatants[name].get('Tier', '?')})")
    while True:
        choice = input("Unlock combatant (number): ").strip()
        try:
            index = int(choice) - 1
            if 0 <= index < len(locked):
                selected = locked[index]
                state["unlocked_combatants"].append(selected)
                print(f"{selected} is now unlocked!")
                return selected
        except ValueError:
            pass
        print("Invalid selection.")


def perform_pull(
    state: Dict[str, Any],
    combatants: Dict[str, Any],
    portrait_key: str,
    ten_pull: bool,
    limburst_data: Optional[Dict[str, Any]] = None,
) -> None:
    if portrait_key == "remembrance" and not REMEMBRANCE_PORTRAIT_ENABLED:
        raise ValueError("Remembrance Portrait is disabled.")
    cost = 3000 if ten_pull else 300
    if state["keys"] < cost:
        print(f"Not enough Keys. You need {cost} Keys.")
        return
    state["keys"] -= cost
    if limburst_data is None:
        limburst_data = load_json(LIMBURST_FILE)
    all_bursts = all_limburst_skills(limburst_data)
    portrait = state["portraits"][portrait_key]
    rate_up, natural = portrait_combatant_pools(
        portrait_key, portrait, combatants
    )
    allowed_combatants = set(rate_up) | set(natural)
    if portrait_key == "remembrance":
        burst_conversion_chance = REMEMBRANCE_BURST_CONVERSION_CHANCE
        excluded_bursts = set()
    else:
        burst_conversion_chance = 0.35
        excluded_bursts = {
            (burst["Character"], burst["Name"])
            for burst in REMEMBRANCE_LIMBURSTS
        }
    pulls = 10 if ten_pull else 1

    for pull_index in range(pulls):
        if ten_pull and pull_index == 9:
            tier = random.choices([2], weights=[100], k=1)[0]
        else:
            tier = random.choices([1, 2, 3], weights=[85, 14, 1], k=1)[0]
        available_bursts = [
            burst for burst in all_bursts
            if (
                (burst["Character"], burst["Name"]) not in excluded_bursts
                and not is_limburst_unlocked(
                    state["unlocked_limbursts"],
                    burst["Character"],
                    burst["Name"],
                )
            )
        ]
        if (
            tier == 3
            and available_bursts
            and random.random() < burst_conversion_chance
        ):
            if portrait_key == "remembrance":
                rate_up_bursts = [
                    burst for burst in available_bursts
                    if any(
                        burst["Character"] == featured["Character"]
                        and burst["Name"] == featured["Name"]
                        for featured in REMEMBRANCE_LIMBURSTS
                    )
                ]
                natural_bursts = [
                    burst for burst in available_bursts
                    if not any(
                        burst["Character"] == featured["Character"]
                        and burst["Name"] == featured["Name"]
                        for featured in REMEMBRANCE_LIMBURSTS
                    )
                ]
                if rate_up_bursts and natural_bursts:
                    burst_candidates = (
                        rate_up_bursts
                        if random.random() < 0.5
                        else natural_bursts
                    )
                else:
                    burst_candidates = rate_up_bursts or natural_bursts
            else:
                burst_candidates = available_bursts
            selected_burst = random.choice(burst_candidates)
            state["unlocked_limbursts"].append({
                "Character": selected_burst["Character"],
                "Name": selected_burst["Name"],
            })
            print(
                f"Roll {pull_index + 1}: Tier 3 LIMBurst - "
                f"{selected_burst['Character']}: "
                f"{selected_burst['Name']} (unlocked!)"
            )
        else:
            rate_up_locked = [
                name for name in rate_up
                if name in combatants
                and combatants[name].get("Tier") == tier
                and name not in state["unlocked_combatants"]
            ]
            use_rate_up = bool(rate_up_locked) and random.random() < 0.5
            if use_rate_up:
                candidates = rate_up_locked
            else:
                candidates = [
                    name for name in natural
                    if combatants[name].get("Tier") == tier
                ]
                if not candidates:
                    candidates = [
                        name for name in combatants
                        if combatants[name].get("Tier") == tier
                        and name in allowed_combatants
                    ]
            if not candidates:
                candidates = [
                    name for name in combatants
                    if combatants[name].get("Tier") == tier
                    and name in allowed_combatants
                ]
            if not candidates:
                raise ValueError(f"No combatants found for tier {tier}.")

            selected = random.choice(candidates)
            newly_unlocked = selected not in state["unlocked_combatants"]
            if newly_unlocked:
                state["unlocked_combatants"].append(selected)
                print(f"Roll {pull_index + 1}: Tier {tier} - {selected} (unlocked!)")
            else:
                character = combatants[selected].get("Name")
                if character not in state["planes"]:
                    raise ValueError(
                        f"Combatant {selected} has unknown character {character!r}."
                    )
                plane_range = {1: (1, 5), 2: (10, 30), 3: (40, 60)}[tier]
                planes_gained = random.randint(*plane_range)
                state["planes"][character] += planes_gained
                print(
                    f"Roll {pull_index + 1}: Tier {tier} - {selected} "
                    f"(duplicate: +{planes_gained} {character} planes)"
                )

        state["portrait_counters"][portrait_key] += 1
        if state["portrait_counters"][portrait_key] >= 200:
            locked_rate_up = [
                name for name in portrait["rate_up"]
                if name in combatants and name not in state["unlocked_combatants"]
            ]
            if locked_rate_up:
                state["portrait_counters"][portrait_key] -= 200
                choose_unlocked_combatant(
                    state, combatants, portrait["rate_up"]
                )
            else:
                state["portrait_counters"][portrait_key] = 200
                print("All rate-up combatants are already unlocked; counter remains at 200.")
    save_player_state(state)
    print(f"Remaining Keys: {state['keys']}")


def combatants_menu(
    state: Dict[str, Any],
    combatants: Dict[str, Any],
    limburst_data: Optional[Dict[str, Any]] = None,
) -> None:
    if limburst_data is None:
        limburst_data = load_json(LIMBURST_FILE)
    portrait_titles = {
        "everchanging": "Everchanging Portrait",
        "class": "Class Portrait",
        "remembrance": "Remembrance Portrait",
    }
    while True:
        print(f"\nKeys: {state['keys']}")
        print("Portraits:")
        available_portraits = [
            (key, title) for key, title in portrait_titles.items()
            if key in state.get("portraits", {})
        ]
        for key, title in available_portraits:
            portrait = state.get("portraits", {}).get(key, {})
            label = portrait.get("label", "Not available")
            print(
                f"  {title}: {label} | Counter "
                f"{state['portrait_counters'][key]}/200"
            )
        portrait_choices = {
            str(index): key
            for index, (key, _) in enumerate(available_portraits, 1)
        }
        view_choice_start = len(available_portraits) + 1
        print(f"{view_choice_start}. View Unlocked Combatants")
        print(f"{view_choice_start + 1}. View All Combatants")
        print(f"{view_choice_start + 2}. View Unlocked LIMBursts")
        print(f"{view_choice_start + 3}. View All LIMBursts")
        print(f"{view_choice_start + 4}. Back")
        choice = input("Choose: ").strip()
        if choice in portrait_choices:
            portrait_key = portrait_choices[choice]
            portrait = state["portraits"][portrait_key]
            rate_up, natural = portrait_combatant_pools(
                portrait_key, portrait, combatants
            )
            print(f"Rate up: {', '.join(rate_up)}")
            print(f"Natural pool: {', '.join(natural)}")
            roll_choice = input("1. Single roll (300 Keys)\n2. Ten roll (3000 Keys)\n3. Back\nChoose: ").strip()
            if roll_choice in {"1", "2"}:
                perform_pull(
                    state, combatants, portrait_key, roll_choice == "2",
                    limburst_data,
                )
        elif choice == str(view_choice_start):
            print("Unlocked Combatants:")
            for name in state["unlocked_combatants"]:
                print(f"  {name} (Tier {combatants[name].get('Tier', '?')})")
        elif choice == str(view_choice_start + 1):
            print("All Combatants:")
            for name, raw in combatants.items():
                marker = " [Unlocked]" if name in state["unlocked_combatants"] else ""
                print(f"  {name} (Tier {raw.get('Tier', '?')}){marker}")
        elif choice == str(view_choice_start + 2):
            print("Unlocked LIMBursts:")
            for burst in state["unlocked_limbursts"]:
                print(f"  {burst['Character']}: {burst['Name']}")
        elif choice == str(view_choice_start + 3):
            print("All LIMBursts:")
            for burst in all_limburst_skills(limburst_data):
                marker = (
                    " [Unlocked]"
                    if is_limburst_unlocked(
                        state["unlocked_limbursts"],
                        burst["Character"],
                        burst["Name"],
                    ) else ""
                )
                print(f"  {burst['Character']}: {burst['Name']}{marker}")
        elif choice == str(view_choice_start + 4):
            return
        else:
            print("Invalid selection.")


def combatants_and_limbursts_menu(
    state: Dict[str, Any],
    combatants: Dict[str, Any],
    limburst_data: Dict[str, Any],
) -> None:
    limit_bursts = limburst_data.get("LimitBursts", {})
    while True:
        print("\nCharacters and planes:")
        for index, character in enumerate(CHARACTERS, 1):
            print(f"{index}. {character} ({state['planes'][character]} planes)")
        print(f"{len(CHARACTERS) + 1}. Back")
        try:
            character_index = int(input("Select character: ").strip()) - 1
        except ValueError:
            print("Invalid selection.")
            continue
        if character_index == len(CHARACTERS):
            return
        if not 0 <= character_index < len(CHARACTERS):
            print("Invalid selection.")
            continue

        character = CHARACTERS[character_index]
        while True:
            locked_combatants = [
                (name, raw)
                for name, raw in combatants.items()
                if raw.get("Name") == character
                and name not in state["unlocked_combatants"]
                and raw.get("Tier") in (2, 3)
            ]
            locked_bursts = [
                burst for burst in limit_bursts.get(character, [])
                if not is_limburst_unlocked(
                    state["unlocked_limbursts"], character, burst.get("Name", "")
                )
            ]
            items: List[tuple[str, str, int]] = []
            print(f"\n{character}: {state['planes'][character]} planes")
            for name, raw in locked_combatants:
                cost = 150 if raw["Tier"] == 2 else 400
                items.append(("combatant", name, cost))
                print(f"{len(items)}. Combatant: {name} (Tier {raw['Tier']}, {cost} planes)")
            for burst in locked_bursts:
                name = burst["Name"]
                items.append(("limburst", name, 400))
                print(f"{len(items)}. LIMBurst: {name} (400 planes)")
            if not items:
                print("All combatants and LIMBursts for this character are unlocked.")
            print(f"{len(items) + 1}. Back")
            try:
                item_index = int(input("Select item to unlock: ").strip()) - 1
            except ValueError:
                print("Invalid selection.")
                continue
            if item_index == len(items):
                break
            if not 0 <= item_index < len(items):
                print("Invalid selection.")
                continue
            kind, name, cost = items[item_index]
            if state["planes"][character] < cost:
                print(f"Not enough planes. {cost} planes required.")
                continue
            state["planes"][character] -= cost
            if kind == "combatant":
                state["unlocked_combatants"].append(name)
            else:
                state["unlocked_limbursts"].append({
                    "Character": character,
                    "Name": name,
                })
            save_player_state(state)
            print(f"Unlocked {name} for {cost} planes.")


def apply_dungeon_adversities(
    enemies: List[Combatant], selected_adversities: List[str]
) -> None:
    unknown_adversities = [
        adversity for adversity in selected_adversities
        if adversity not in DUNGEON_ADVERSITIES
    ]
    if unknown_adversities:
        raise ValueError(f"Unknown dungeon adversities: {unknown_adversities}")
    counts = {
        kind: selected_adversities.count(adversity)
        for adversity, kind in DUNGEON_ADVERSITIES.items()
    }
    if not selected_adversities:
        return

    for enemy in enemies:
        hp_percent = 10 * counts["hp"]
        if hp_percent:
            enemy.max_hp = max(1, enemy.max_hp * (100 + hp_percent) // 100)
            if enemy.hp > 0:
                enemy.hp = max(1, enemy.hp * (100 + hp_percent) // 100)
        enemy._dungeon_adversity_damage_pct = 10 * counts["damage"]
        enemy.defense += 10 * counts["defense"]
        if counts["speed"]:
            enemy.speed_range = increase_speed_range(
                enemy.speed_range, counts["speed"],
            )
        enemy._dungeon_adversity_base_power = counts["base_power"]
        enemy.apply_status("Adversity", potency=0, count=len(selected_adversities))


def run_dungeon_battle(
    section: Dict[str, Any],
    player_team: List[Combatant],
    state: Dict[str, Any],
    data: Dict[str, Any],
    selected_adversities: List[str],
    is_onrush: bool = False,
) -> bool:
    def run_attempt() -> tuple[List[Combatant], List[Combatant], List[str]]:
        if is_onrush:
            enemies, reinforcements = get_onrush_teams(
                section,
                data["onrush_handler"],
                data["battle_handler"],
                data["enemy_data"],
            )
            all_enemies = enemies + list(reinforcements)
        else:
            enemies = get_enemies_for_section(
                section, data["battle_handler"], data["enemy_data"],
            )
            reinforcements = []
            all_enemies = enemies
        if not enemies:
            raise ValueError(f"No enemies found for dungeon section: {section}")

        apply_dungeon_adversities(all_enemies, selected_adversities)
        battle_player_team = add_extra_unit_to_team(
            player_team, section, data["extra_units_data"],
        )
        try:
            transcript = run_interactive_battle(
                battle_player_team,
                enemies,
                enemy_replacement_queue=list(reinforcements),
            )
        finally:
            for unit in player_team:
                unit.team_members = player_team
        return battle_player_team, all_enemies, transcript

    completed = run_battle_with_retry(state, player_team, run_attempt)
    if completed:
        data["cash"] += 100
        state["cash"] = data["cash"]
        save_player_state(state)
        print(f"Victory! Gained 100 cash. Total: {data['cash']}")
        clear_statuses_and_heal(player_team)
        for unit in player_team:
            unit.skill_slots = 1
    return completed


def run_dungeon_floor(
    floor_name: str,
    player_team: List[Combatant],
    state: Dict[str, Any],
    data: Dict[str, Any],
    selected_adversities: List[str],
) -> bool:
    sections = data["floor_data"]["Floors"][floor_name]["sections"]
    for index, section in enumerate(sections, 1):
        kind = section["type"]
        print(f"\n{floor_name} — section {index}/{len(sections)}: {kind}")
        if kind == "shop":
            data["cash"] = shop_interface(
                player_team,
                data["shop_data"],
                data["reali_gear"],
                data["cash"],
                data["owned_gear"],
            )
            state["cash"] = data["cash"]
            state["owned_gear"] = sorted(data["owned_gear"])
            save_player_state(state)
        elif kind in {"encounters", "boss"}:
            if not run_dungeon_battle(
                section, player_team, state, data, selected_adversities,
            ):
                return False
        elif kind == "onrush":
            if not run_dungeon_battle(
                section, player_team, state, data, selected_adversities,
                is_onrush=True,
            ):
                return False
        elif kind == "occurrences":
            occurrences = data["occurance_handler"]["Pools"].get(
                section["pool"], [],
            )
            for occurrence in occurrences:
                result = handle_occurrence(
                    occurrence["occurrence"],
                    data["occurance_handler"],
                    player_team,
                )
                if isinstance(result, str) and not run_dungeon_battle(
                    {"type": "boss", "enemy": result},
                    player_team,
                    state,
                    data,
                    selected_adversities,
                ):
                    return False
        else:
            raise ValueError(
                f"Unsupported section type {kind!r} in dungeon floor "
                f"{floor_name!r}"
            )
    print(f"{floor_name} completed.")
    return True


def choose_dungeon_option(prompt: str, options: List[str]) -> str:
    while True:
        choice = input(prompt).strip()
        try:
            index = int(choice) - 1
        except ValueError:
            print("Invalid selection.")
            continue
        if 0 <= index < len(options):
            return options[index]
        print("Invalid selection.")


def run_dungeon(
    player_team: List[Combatant],
    state: Dict[str, Any],
    data: Dict[str, Any],
) -> bool:
    floors = data["floor_data"]["Floors"]
    missing_floors = [name for name in DUNGEON_FLOORS if name not in floors]
    if missing_floors:
        raise KeyError(f"Dungeon floors missing from Floor_Data.json: {missing_floors}")

    available_floors = list(DUNGEON_FLOORS)
    selected_adversities: List[str] = []
    for floor_number in range(1, 11):
        options = random.sample(available_floors, 3)
        print(f"\nChoose a floor for Dungeon floor {floor_number}/10:")
        for index, floor_name in enumerate(options, 1):
            print(f"{index}. {floor_name}")
        selected_floor = choose_dungeon_option("Select floor: ", options)
        available_floors.remove(selected_floor)

        if not run_dungeon_floor(
            selected_floor, player_team, state, data, selected_adversities,
        ):
            print("Dungeon run ended before completion.")
            return False

        if floor_number % 3 == 0 and floor_number < 10:
            adversity_options = random.sample(
                list(DUNGEON_ADVERSITIES), 3,
            )
            print("\nChoose an Adversity for the remaining Dungeon floors:")
            for index, adversity in enumerate(adversity_options, 1):
                print(f"{index}. {adversity}")
            selected_adversity = choose_dungeon_option(
                "Select Adversity: ", adversity_options,
            )
            selected_adversities.append(selected_adversity)
            print(
                f"Adversity selected: {selected_adversity}. "
                "It will strengthen enemies on the remaining floors."
            )

    state["keys"] += 3600
    save_player_state(state)
    print(f"Dungeon complete! Gained 3600 Keys. Total: {state['keys']}")
    return True


def run_story_chapter(
    floor_name: str,
    start_index: int,
    player_team: List[Combatant],
    state: Dict[str, Any],
    data: Dict[str, Any],
) -> tuple[str, List[Combatant], int]:
    floor_data = data["floor_data"]
    sections = floor_data["Floors"][floor_name]["sections"]
    spectral_abilities: set[str] = (
        {MIST_OF_TRUTH} if floor_name == "Story Branch 2.1" else set()
    )
    if floor_name == "Story Branch 2.1" and start_index > 0:
        spectral_abilities.add(SWORD_OF_THE_FORGOTTEN)
    used_spectral_abilities: set[str] = set()

    def restore_after_victory() -> None:
        data["cash"] += 100
        print(f"Victory! Gained 100 cash. Total: {data['cash']}")
        clear_statuses_and_heal(player_team)
        for unit in player_team:
            unit.skill_slots = 1

    for index in range(start_index, len(sections)):
        section = sections[index]
        if section["type"] == "story":
            while True:
                choice = input(
                    f"\nStory section: {section['pool']}\n"
                    "1. Continue story\n2. Pause for now\nChoose: "
                ).strip()
                if choice == "1":
                    break
                if choice == "2":
                    state["active_story"] = {
                        "floor": floor_name,
                        "section_index": index,
                        "team": serialize_team(player_team),
                    }
                    save_player_state(state)
                    print("Story progress and team saved.")
                    return "paused", player_team, index
                print("Invalid selection.")

        print(f"\nEntering section {index + 1}/{len(sections)}: {section['type']}")
        kind = section["type"]
        enemy_data = data["enemy_data"]
        battle_handler = data["battle_handler"]
        onrush_handler = data["onrush_handler"]
        defeated = False

        if kind == "story":
            handle_story(section["pool"], data["story_handler"])
            if section["pool"] == "Onward2" and MIST_OF_TRUTH not in spectral_abilities:
                spectral_abilities.add(MIST_OF_TRUTH)
                print(f"Unlocked Spectral Ability: {MIST_OF_TRUTH}!")
            if (section["pool"] == "Branch 2.1 Opening"
                    and SWORD_OF_THE_FORGOTTEN not in spectral_abilities):
                spectral_abilities.add(SWORD_OF_THE_FORGOTTEN)
                print(f"Unlocked Spectral Ability: {SWORD_OF_THE_FORGOTTEN}!")
        elif kind == "shop":
            data["cash"] = shop_interface(
                player_team, data["shop_data"], data["reali_gear"],
                data["cash"], data["owned_gear"],
            )
            state["cash"] = data["cash"]
            state["owned_gear"] = sorted(data["owned_gear"])
        elif kind == "reselect":
            print("Reselect your team.")
            player_team = select_starting_team(
                data["combatants"], section.get("can't use", []),
                state["unlocked_combatants"],
                state["unlocked_limbursts"],
            )
        elif kind == "encounters":
            enemies = get_enemies_for_section(section, battle_handler, enemy_data)
            if enemies:
                def run_attempt() -> tuple[List[Combatant], List[Combatant], List[str]]:
                    current_enemies = get_enemies_for_section(
                        section, battle_handler, enemy_data
                    )
                    battle_player_team = add_extra_unit_to_team(
                        player_team, section, data["extra_units_data"],
                    )
                    try:
                        transcript = run_interactive_battle(
                            battle_player_team, current_enemies,
                            spectral_abilities=spectral_abilities,
                            used_spectral_abilities=used_spectral_abilities,
                        )
                    finally:
                        for unit in player_team:
                            unit.team_members = player_team
                    return battle_player_team, current_enemies, transcript

                defeated = not run_battle_with_retry(state, player_team, run_attempt)
                if not defeated:
                    restore_after_victory()
        elif kind == "onrush":
            enemies, reinforcements = get_onrush_teams(
                section, onrush_handler, battle_handler, enemy_data
            )
            if enemies:
                def run_attempt() -> tuple[List[Combatant], List[Combatant], List[str]]:
                    current_enemies, current_reinforcements = get_onrush_teams(
                        section, onrush_handler, battle_handler, enemy_data
                    )
                    all_enemies = current_enemies + list(current_reinforcements)
                    battle_player_team = add_extra_unit_to_team(
                        player_team, section, data["extra_units_data"],
                    )
                    try:
                        transcript = run_interactive_battle(
                            battle_player_team, current_enemies,
                            enemy_replacement_queue=list(current_reinforcements),
                            drowsy_kyla=(
                                floor_name == "Story Mode 2"
                                and section["pool"] in {"Pirates", "Birling and Co. Ship"}
                            ),
                            spectral_abilities=spectral_abilities,
                            used_spectral_abilities=used_spectral_abilities,
                        )
                    finally:
                        for unit in player_team:
                            unit.team_members = player_team
                    return battle_player_team, all_enemies, transcript

                defeated = not run_battle_with_retry(state, player_team, run_attempt)
                if not defeated:
                    restore_after_victory()
        elif kind == "boss":
            boss_name = section["enemy"]
            battle_player_team = player_team
            extra_unit_name = section.get("extra unit")
            if extra_unit_name:
                extra_raw = data["extra_units_data"].get(extra_unit_name)
                if extra_raw is None:
                    raise KeyError(f"Extra unit not found: {extra_unit_name}")
                extra_unit = Combatant(extra_raw, extra_unit_name)
                extra_unit.is_extra_unit = True
                battle_player_team = player_team + [extra_unit]
                for unit in battle_player_team:
                    unit.team_members = battle_player_team

            def run_attempt() -> tuple[List[Combatant], List[Combatant], List[str]]:
                boss_raw = enemy_data["Enemies"][boss_name]
                if boss_raw.get("deformality") == "yes":
                    boss_team = [
                        Combatant(dict(boss_raw, **part), part["Name"])
                        for part in boss_raw.get("parts", [])
                    ]
                else:
                    boss_team = [Combatant(boss_raw, boss_name)]
                transcript = run_interactive_battle(
                    battle_player_team, boss_team,
                    spectral_abilities=spectral_abilities,
                    used_spectral_abilities=used_spectral_abilities,
                )
                return battle_player_team, boss_team, transcript

            try:
                won = run_battle_with_retry(state, battle_player_team, run_attempt)
            finally:
                for unit in player_team:
                    unit.team_members = player_team
            defeated = not won
            if won:
                restore_after_victory()
        elif kind == "special_boss":
            saved_player_team = player_team
            player_team = create_special_boss_team(
                data["combatants"], section["usable_combatants"],
                section.get("skill_slots"),
            )
            boss_name = section["enemy"]
            special_player_team = player_team

            def run_attempt() -> tuple[List[Combatant], List[Combatant], List[str]]:
                boss = Combatant(enemy_data["Enemies"][boss_name], boss_name)
                configure_special_boss(boss, section, data["limburst_data"])
                boss_team = [boss]
                transcript = run_interactive_battle(
                    special_player_team, boss_team,
                    spectral_abilities=spectral_abilities,
                    used_spectral_abilities=used_spectral_abilities,
                )
                return special_player_team, boss_team, transcript

            player_won = run_battle_with_retry(
                state, special_player_team, run_attempt
            )
            player_team = saved_player_team
            defeated = not player_won
        elif kind == "occurrences":
            for occurrence in data["occurance_handler"]["Pools"].get(section["pool"], []):
                result = handle_occurrence(
                    occurrence["occurrence"], data["occurance_handler"], player_team
                )
                if isinstance(result, str):
                    def run_attempt() -> tuple[List[Combatant], List[Combatant], List[str]]:
                        boss_raw = enemy_data["Enemies"][result]
                        if boss_raw.get("deformality") == "yes":
                            boss_team = [
                                Combatant(dict(boss_raw, **part), part["Name"])
                                for part in boss_raw.get("parts", [])
                            ]
                        else:
                            boss_team = [Combatant(boss_raw, result)]
                        transcript = run_interactive_battle(player_team, boss_team)
                        return player_team, boss_team, transcript

                    defeated = not run_battle_with_retry(state, player_team, run_attempt)
                    if defeated:
                        break
                    restore_after_victory()
        else:
            raise ValueError(f"Unsupported story section type: {kind}")

        if (
            defeated
            and kind == "boss"
            and should_continue_story_after_boss_loss(floor_name, section["enemy"])
        ):
            print("The player was defeated by Vin, but Story Branch 1.1 continues.")
            defeated = False

        if defeated:
            state["active_story"] = None
            save_player_state(state)
            print("The team was defeated. This chapter remains unlocked to try again.")
            return "defeated", player_team, index

        state["active_story"] = {
            "floor": floor_name,
            "section_index": index + 1,
            "team": serialize_team(player_team),
        }
        save_player_state(state)

    if floor_name not in state["completed_chapters"]:
        state["completed_chapters"].append(floor_name)
    next_chapter_index = STORY_CHAPTERS.index(floor_name) + 1
    if next_chapter_index < len(STORY_CHAPTERS):
        next_chapter = STORY_CHAPTERS[next_chapter_index]
        if next_chapter not in state["unlocked_chapters"]:
            state["unlocked_chapters"].append(next_chapter)
    state["active_story"] = None
    save_player_state(state)
    print(f"{chapter_display_name(floor_name)} completed.")
    if next_chapter_index < len(STORY_CHAPTERS):
        next_chapter = STORY_CHAPTERS[next_chapter_index]
        print(
            f"Unlocked {chapter_display_name(next_chapter)}. "
            "Select a new team before continuing."
        )
    return "completed", player_team, len(sections)


def main():
    combatants = load_combatants_from_file("combatants.json")
    enemy_data = load_json(ENEMY_FILE)
    floor_data = load_json(FLOOR_DATA_FILE)
    reali_gear = load_json(REALIGEAR_FILE)
    shop_data = load_json(SHOP_FILE).get("Shop", {})
    battle_handler = load_json(BATTLE_HANDLER_FILE)
    occurance_handler = load_json(OCCURANCE_HANDLER_FILE)
    onrush_handler = load_json(ONRUSH_HANDLER_FILE)
    story_handler = load_json(STORY_FILE)
    limburst_data = load_json(LIMBURST_FILE)
    extra_units_data = load_json(EXTRA_UNITS_FILE).get("Extras", {})
    state = load_player_state(combatants, limburst_data)
    state["owned_gear"] = []
    refresh_portraits(state, combatants)
    save_player_state(state)

    data = {
        "combatants": combatants,
        "enemy_data": enemy_data,
        "floor_data": floor_data,
        "reali_gear": reali_gear,
        "shop_data": shop_data,
        "battle_handler": battle_handler,
        "occurance_handler": occurance_handler,
        "onrush_handler": onrush_handler,
        "story_handler": story_handler,
        "limburst_data": limburst_data,
        "extra_units_data": extra_units_data,
        "cash": state["cash"],
        "owned_gear": set(state["owned_gear"]),
    }

    while True:
        print("\n" + "=" * 60)
        print(f"Keys: {state['keys']}")
        print("1. Story")
        print("2. Combatants")
        print("3. The Dungeon")
        print("4. Others")
        choice = input("Choose: ").strip()
        if choice == "1":
            unlocked_chapters = state["unlocked_chapters"]
            active_story = state.get("active_story")
            if active_story:
                available_chapters = [active_story["floor"]]
                print(
                    "Continue in progress: "
                    f"{chapter_display_name(active_story['floor'])}"
                )
            else:
                available_chapters = [
                    chapter for chapter in STORY_CHAPTERS
                    if chapter in unlocked_chapters
                ]
            print("Available Chapters:")
            for index, chapter in enumerate(available_chapters, 1):
                status = "Completed" if chapter in state["completed_chapters"] else "Unlocked"
                print(f"{index}. {chapter_display_name(chapter)} ({status})")
            print(f"{len(available_chapters) + 1}. Back")
            try:
                chapter_choice = int(input("Select chapter: ").strip()) - 1
            except ValueError:
                print("Invalid selection.")
                continue
            if chapter_choice == len(available_chapters):
                continue
            if not 0 <= chapter_choice < len(available_chapters):
                print("Invalid selection.")
                continue
            chapter = available_chapters[chapter_choice]

            if active_story:
                start_index = int(active_story.get("section_index", 0))
                player_team = restore_team(active_story.get("team", []), combatants)
                while True:
                    team_choice = input(
                        "1. Select a new team\n2. Continue with the saved team\nChoose: "
                    ).strip()
                    if team_choice == "1":
                        player_team = select_starting_team(
                            combatants,
                            unlocked_combatants=state["unlocked_combatants"],
                            unlocked_limbursts=state["unlocked_limbursts"],
                        )
                        break
                    if team_choice == "2":
                        break
                    print("Invalid selection.")
            else:
                start_index = 0
                player_team = select_starting_team(
                    combatants,
                    unlocked_combatants=state["unlocked_combatants"],
                    unlocked_limbursts=state["unlocked_limbursts"],
                )
                state["active_story"] = {
                    "floor": chapter,
                    "section_index": 0,
                    "team": serialize_team(player_team),
                }

            refresh_portraits(state, combatants)
            save_player_state(state)
            run_story_chapter(chapter, start_index, player_team, state, data)
        elif choice == "2":
            combatants_menu(state, combatants, limburst_data)
        elif choice == "3":
            player_team = select_starting_team(
                combatants,
                unlocked_combatants=state["unlocked_combatants"],
                unlocked_limbursts=state["unlocked_limbursts"],
            )
            for unit in player_team:
                unit.team_members = player_team
            data["cash"] = state["cash"]
            data["owned_gear"] = set(state["owned_gear"])
            run_dungeon(player_team, state, data)
        elif choice == "4":
            combatants_and_limbursts_menu(state, combatants, limburst_data)
        else:
            print("Invalid selection.")


def legacy_main():
    # Load data
    combatants = load_combatants_from_file("combatants.json")
    enemy_data = load_json(ENEMY_FILE)
    floor_data = load_json(FLOOR_DATA_FILE)
    reali_gear = load_json(REALIGEAR_FILE)
    shop_data = load_json(SHOP_FILE).get("Shop", {})
    battle_handler = load_json(BATTLE_HANDLER_FILE)
    occurance_handler = load_json(OCCURANCE_HANDLER_FILE)
    onrush_handler = load_json(ONRUSH_HANDLER_FILE)
    story_handler = load_json(STORY_FILE)
    limburst_data = load_json(LIMBURST_FILE)
    extra_units_data = load_json(EXTRA_UNITS_FILE).get("Extras", {})

    # Select player
    player_team = select_starting_team(combatants)
    cash = 500
    owned_gear: set[str] = set()
    spectral_abilities: set[str] = set()
    used_spectral_abilities: set[str] = set()
    has_started_floor = False

    for floor, section, floor_started in iter_floor_sections(floor_data):
        if floor_started:
            if has_started_floor:
                while True:
                    choice = input(
                        "Would you like to select a new team for this floor?\n"
                        "1. Select a new team\n"
                        "2. Keep the current team\n"
                        "Choose: "
                    ).strip()
                    if choice == "1":
                        player_team = select_starting_team(combatants)
                        break
                    if choice == "2":
                        break
                    print("Invalid selection. Please choose 1 or 2.")
            has_started_floor = True
            used_spectral_abilities.clear()

        print(f"\nEntering section: {section['type']}")
        if section["type"] == "encounters":
            enemies = get_enemies_for_section(section, battle_handler, enemy_data)
            if enemies:
                print(f"Encounter: {', '.join(e.name for e in enemies)}")
                battle_player_team = add_extra_unit_to_team(
                    player_team, section, extra_units_data,
                )
                try:
                    run_interactive_battle(
                        battle_player_team, enemies,
                        spectral_abilities=spectral_abilities,
                        used_spectral_abilities=used_spectral_abilities,
                    )
                finally:
                    for unit in player_team:
                        unit.team_members = player_team
                # Check if player won
                if not any(c.is_alive() for c in battle_player_team):
                    print("Player defeated. Game over.")
                    return
                else:
                    # Player won, gain cash reward
                    reward = 100
                    cash += reward
                    print(f"Victory! Gained {reward} cash. Total: {cash}")
                    # Post-battle cleanup
                    clear_statuses_and_heal(player_team)
                    # Reset skill slots for all player combatants
                    for c in player_team:
                        c.skill_slots = 1
            else:
                print("No enemies in this encounter.")
        elif section["type"] == "onrush":
            enemies, reinforcements = get_onrush_teams(
                section, onrush_handler, battle_handler, enemy_data
            )
            if enemies:
                print(f"Onrush: {', '.join(e.name for e in enemies)}")
                battle_player_team = add_extra_unit_to_team(
                    player_team, section, extra_units_data,
                )
                try:
                    run_interactive_battle(
                        battle_player_team, enemies,
                        enemy_replacement_queue=reinforcements,
                        drowsy_kyla=(
                            floor == "Story Mode 2"
                            and section["pool"] in {"Pirates", "Birling and Co. Ship"}
                        ),
                        spectral_abilities=spectral_abilities,
                        used_spectral_abilities=used_spectral_abilities,
                    )
                finally:
                    for unit in player_team:
                        unit.team_members = player_team
                if not any(c.is_alive() for c in battle_player_team):
                    print("Player defeated. Game over.")
                    return
                reward = 100
                cash += reward
                print(f"Victory! Gained {reward} cash. Total: {cash}")
                clear_statuses_and_heal(player_team)
                for c in player_team:
                    c.skill_slots = 1
            else:
                print("No enemies in this onrush.")
        elif section["type"] == "occurrences":
            pool = section["pool"]
            occurrences = occurance_handler["Pools"].get(pool, [])
            for occ_item in occurrences:
                occ_name = occ_item["occurrence"]
                result = handle_occurrence(occ_name, occurance_handler, player_team)
                if isinstance(result, str):
                    # Deformality boss
                    boss_raw = enemy_data["Enemies"][result]
                    if boss_raw.get("deformality") == "yes":
                        parts = boss_raw.get("parts", [])
                        boss_team = [Combatant(dict(boss_raw, **part), part["Name"]) for part in parts]
                    else:
                        boss_team = [Combatant(boss_raw, result)]
                    print(f"Boss battle: {result}")
                    run_interactive_battle(
                        player_team, boss_team,
                        spectral_abilities=spectral_abilities,
                        used_spectral_abilities=used_spectral_abilities,
                    )
                    if not any(c.is_alive() for c in player_team):
                        print("Player defeated. Game over.")
                        return
                    # Post-battle cleanup
                    clear_statuses_and_heal(player_team)
                    # Reset skill slots after deformality boss battle
                    for c in player_team:
                        c.skill_slots = 1
        elif section["type"] == "story":
            handle_story(section["pool"], story_handler)
            if section["pool"] == "Onward2" and MIST_OF_TRUTH not in spectral_abilities:
                spectral_abilities.add(MIST_OF_TRUTH)
                print(f"Unlocked Spectral Ability: {MIST_OF_TRUTH}!")
            if (section["pool"] == "Branch 2.1 Opening"
                    and SWORD_OF_THE_FORGOTTEN not in spectral_abilities):
                spectral_abilities.add(SWORD_OF_THE_FORGOTTEN)
                print(f"Unlocked Spectral Ability: {SWORD_OF_THE_FORGOTTEN}!")
        elif section["type"] == "shop":
            cash = shop_interface(player_team, shop_data, reali_gear, cash, owned_gear)
        elif section["type"] == "reselect":
            print("Reselect your team.")
            player_team = select_starting_team(
                combatants, section.get("can't use", [])
            )
            print(f"Your team is now: {', '.join(c.name for c in player_team)}")
        elif section["type"] == "special_boss":
            saved_player_team = player_team
            player_team = create_special_boss_team(
                combatants, section["usable_combatants"],
                section.get("skill_slots"),
            )
            boss_name = section["enemy"]
            boss_raw = enemy_data["Enemies"][boss_name]
            boss_team = [Combatant(boss_raw, boss_name)]
            configure_special_boss(boss_team[0], section, limburst_data)
            print(f"Special Boss battle: {boss_name}")
            run_interactive_battle(
                player_team, boss_team,
                spectral_abilities=spectral_abilities,
                used_spectral_abilities=used_spectral_abilities,
            )
            player_won = any(c.is_alive() for c in player_team)
            player_team = saved_player_team
            if not player_won:
                print("Player defeated. Game over.")
                return
        elif section["type"] == "boss":
            boss_name = section["enemy"]
            boss_raw = enemy_data["Enemies"][boss_name]
            if boss_raw.get("deformality") == "yes":
                parts = boss_raw.get("parts", [])
                boss_team = [Combatant(dict(boss_raw, **part), part["Name"]) for part in parts]
            else:
                boss_team = [Combatant(boss_raw, boss_name)]

            battle_player_team = player_team
            previous_team_members = []
            extra_unit_name = section.get("extra unit")
            if extra_unit_name:
                extra_unit_raw = extra_units_data.get(extra_unit_name)
                if extra_unit_raw is None:
                    raise KeyError(f"Extra unit not found: {extra_unit_name}")
                extra_unit = Combatant(extra_unit_raw, extra_unit_name)
                extra_unit.is_extra_unit = True
                battle_player_team = player_team + [extra_unit]
                previous_team_members = [
                    (combatant, combatant.team_members)
                    for combatant in battle_player_team
                ]
                for combatant in battle_player_team:
                    combatant.team_members = battle_player_team

            print(f"Boss battle: {boss_name}")
            try:
                run_interactive_battle(
                    battle_player_team, boss_team,
                    spectral_abilities=spectral_abilities,
                    used_spectral_abilities=used_spectral_abilities,
                )
            finally:
                for combatant, team_members in previous_team_members:
                    combatant.team_members = team_members

            relevant_unit_lost = (
                any(
                    not c.is_alive() and c.has_special_effect("Relevant")
                    for c in battle_player_team
                )
                and any(c.is_alive() for c in boss_team)
            )
            if not any(c.is_alive() for c in player_team) or relevant_unit_lost:
                if should_continue_story_after_boss_loss(floor, boss_name):
                    print("The player was defeated by Vin, but Story Branch 1.1 continues.")
                    clear_statuses_and_heal(player_team)
                    for c in player_team:
                        c.skill_slots = 1
                    continue
                print("Player defeated. Game over.")
                return
            # Post-battle cleanup
            clear_statuses_and_heal(player_team)
            # Reset skill slots after boss battle
            for c in player_team:
                c.skill_slots = 1

if __name__ == "__main__":
    main()
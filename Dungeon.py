#!/usr/bin/env python3
"""
Dungeon Mode for Havenus Elite
"""
import json
import random
import sys
import time
from typing import List, Dict, Any, Optional
from main import Combatant, load_combatants_from_file, run_interactive_battle

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

    print(f"⚠️ No effect handler for {name}.")
    return


def select_starting_team(
    combatants: Dict[str, Any], excluded_names: Optional[List[str]] = None
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

    roster = sorted(name for name in combatants if not is_excluded(name))
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
                    available_lbs = lb_data.get(base_c.name, [])
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


def create_special_boss_team(combatants: Dict[str, Any], names: List[str]) -> List[Combatant]:
    from copy import deepcopy

    team = []
    for name in names:
        raw = combatants.get(name)
        if raw is None:
            raise KeyError(f"Special boss combatant not found: {name}")
        if raw.get("Class") != "Havenus Elite":
            raise ValueError(f"Special boss combatant is not Havenus Elite: {name}")
        combatant = deepcopy(Combatant(raw, name))
        combatant.skill_slots = 5
        team.append(combatant)
    return team


def configure_special_boss(boss: Combatant, section: Dict[str, Any], limburst_data: Dict[str, Any]) -> None:
    boss.skill_slots = 5
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
    floors = ["Floor 1", "Floor 2", "Floor 3", "Floor 4", "Samurai Dojo", "Pyric Offence", "The Castle Of Flames", "Story Mode 1", "Boss Rush 1", "VS Vin", "VS Macbeth", "Story Branch 1.1", "Story Branch 1.2", "Boss Onrush", "Story Mode 2"]
    print("Choose a floor:")
    for i, floor in enumerate(floors, 1):
        print(f"{i}. {floor}")
    choice = int(input("Select floor (number): ")) - 1
    return floors[choice]

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
    return len(dead_allies)


def shop_interface(player_team: List[Combatant], shop_data: Dict[str, Any], reali_gear: Dict[str, Any], cash: int, owned_gear: set[str]) -> int:
    print(f"Welcome to the shop! You have {cash} cash.")
    print("Options:")
    print("1. Buy RealiGear")
    print("2. Heal")
    print(f"3. Revive all dead allies ({shop_data['revival']['cost']} cash)")
    print("4. Exit")
    choice = input("Choose: ").strip()
    if choice == "1":
        gear = shop_data["realiGear"]
        if not gear:
            print("No RealiGear available.")
            return cash
        print("Available RealiGear:")
        for i, name in enumerate(gear, 1):
            desc = reali_gear["RealiGear"][name]["Description"]
            tier = reali_gear["RealiGear"][name]["Tier"]
            cost = get_reali_gear_cost(name, reali_gear, owned_gear)
            owned_tag = " (owned)" if name in owned_gear else ""
            print(f"{i}. {name} (Tier {tier}, {cost} cash){owned_tag}: {desc}")
        try:
            idx = int(input("Select: ")) - 1
        except ValueError:
            print("Invalid selection.")
            return cash
        if 0 <= idx < len(gear):
            name = gear[idx]
            if name in owned_gear:
                print(f"You already own {name}.")
                return cash
            cost = get_reali_gear_cost(name, reali_gear, owned_gear)
            if cash >= cost:
                cash -= cost
                print(f"Bought {name} for {cost} cash.")
                apply_reali_gear_effect(player_team, reali_gear, name, owned_gear)
            else:
                print("Not enough cash.")
        else:
            print("Invalid selection.")
    elif choice == "2":
        heal_cost = int(shop_data["healing"]["cost_per_hp"] * (0.9 if "Lucky Charm" in owned_gear else 1.0))
        max_heal = shop_data["healing"]["max_heal"]
        try:
            heal_amount = int(input(f"Heal amount (cost {heal_cost} per HP): ").strip())
        except ValueError:
            print("Invalid heal amount.")
            return cash
        heal_amount = min(max_heal, max(0, heal_amount))
        cost = heal_amount * heal_cost
        if cash >= cost:
            cash -= cost
            for c in player_team:
                if c.is_alive():
                    c.heal(heal_amount)
                    print(f"{c.name} healed {heal_amount} HP.")
        else:
            print("Not enough cash.")
    elif choice == "3":
        revival_cost = shop_data["revival"]["cost"]
        dead_allies = [c for c in player_team if not c.is_alive()]
        if not dead_allies:
            print("All allies are already alive.")
        elif cash < revival_cost:
            print("Not enough cash.")
        else:
            cash -= revival_cost
            revived_count = revive_dead_allies(player_team)
            print(f"Revived {revived_count} allies for {revival_cost} cash.")
    return cash

def main():
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

    # Choose floor
    floor = choose_floor()
    sections = floor_data["Floors"][floor]["sections"]

    for section in sections:
        print(f"\nEntering section: {section['type']}")
        if section["type"] == "encounters":
            enemies = get_enemies_for_section(section, battle_handler, enemy_data)
            if enemies:
                print(f"Encounter: {', '.join(e.name for e in enemies)}")
                # Run battle
                run_interactive_battle(player_team, enemies)
                # Check if player won
                if not any(c.is_alive() for c in player_team):
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
                run_interactive_battle(
                    player_team, enemies, enemy_replacement_queue=reinforcements,
                    drowsy_kyla=(
                        floor == "Story Mode 2"
                        and section["pool"] in {"Pirates", "Birling and Co. Ship"}
                    ),
                )
                if not any(c.is_alive() for c in player_team):
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
                    run_interactive_battle(player_team, boss_team)
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
                combatants, section["usable_combatants"]
            )
            boss_name = section["enemy"]
            boss_raw = enemy_data["Enemies"][boss_name]
            boss_team = [Combatant(boss_raw, boss_name)]
            configure_special_boss(boss_team[0], section, limburst_data)
            print(f"Special Boss battle: {boss_name}")
            run_interactive_battle(player_team, boss_team)
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
                run_interactive_battle(battle_player_team, boss_team)
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

    print("Floor completed! Congratulations.")

if __name__ == "__main__":
    main()
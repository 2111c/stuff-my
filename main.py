#!/usr/bin/env python3
"""

This reworks the clash system so that when two combatants target each other
simultaneously their moves "clash" and both actions are resolved together
with a clash resolution that compares Attack-Weight, Offense-Level and coin wins.
Winner's move proceeds at full or boosted effectiveness; loser is heavily reduced.
Ties produce mutual partial resolution.

Keep your combatants JSON (top-level {"Combatants": {...}}) in the same folder.
"""
from __future__ import annotations
from asyncio import FIRST_COMPLETED
import json
import random
import traceback
from copy import deepcopy
from typing import Dict, Any, List, Optional, Tuple

# Use the provided JSON filename
COMBATANTS_FILE = "combatants.json"
LIMBURST_FILE = "LIMBurst.json"
MAX_TEAM_SIZE = 5
MASTERLY_PRESENCE_FEAR_CHANCE = 0.3
CURRENT_SURGE_TURNS = {
    "You know nothing of the sea": 2,
    "READY YOUR WEAPONS, MEN": 10,
    "You know nothing of the waters": 5,
}
DROWSY_REDUCED_STATUSES = {
    "Burn", "Injured", "Quaken", "Winded", "Freezing", "Current", "Quantus",
}



def roll_speed(speed_range: str) -> int:
        lo, hi = map(int, speed_range.split("-"))
        return random.randint(lo, hi)


def clamp(x, a, b):
        return max(a, min(b, x))


def tybalt_is_active_for(unit: Optional["Combatant"]) -> bool:
        if unit is None:
            return False
        if unit.name == "Tybalt - The Frost":
            return unit.is_alive()
        for ally in getattr(unit, "team_members", []) or []:
            if ally and ally.name == "Tybalt - The Frost" and ally.is_alive():
                return True
        return False


def unit_immune_to_freezing_from_tybalt(unit: Optional["Combatant"]) -> bool:
        if unit is None:
            return False
        team = getattr(unit, "team_members", []) or []
        if not team:
            team = [unit]
        for member in team:
            if member is None or not member.is_alive():
                continue
            if member.has_status("Volatile Rage") and tybalt_is_active_for(member):
                return True
        return False


class Combatant:
        def __init__(self, raw: Dict[str, Any], key: str):
            self.key = key
            self.raw = raw
            self.name = raw.get("Name", key)
            self.max_hp = int(raw.get("HP", 1))
            self.hp = int(raw.get("HP", 1))
            self.speed_range = raw.get("Speed-Range", "4-8")
            self.speed = 0 # Rolled each round
            self.defense = int(raw.get("Defense", 0))
            self.resistances = raw.get("Resistances", raw.get("Resistance", {}))
            self.skills = raw.get("Skills", {})
            self.statuses: Dict[str, Dict[str, int]] = {}
            self.gear_bonuses: Dict[str, int] = {}
            self.alive = True
            self.morale = 50  # Morale scale 0-100
            self.special_effects = raw.get("Special-Effects", [])
            self.limit_bursts = []
            self.selected_limit_burst = None
            self.burst_usage_count = 0
            self.team_members: List[Combatant] = []
            self.team_elements: Optional[Dict[str, int]] = None
            self._something_of_substance_triggered = False
            self._something_of_substance_victory_armed = False
            self._vigor_used = False
            self._knight_resolve_triggered = False
            self._burn_turn_start_potency = 1
            self._burn_turn_start_count = 1
            self._last_attack_target: Optional[Combatant] = None
            self._current_surge_active = False
            self._current_surge_permanent = False
            self._current_surge_slot_active = False

            # Skill slots system
            self.skill_slots = 1  # Start with 1 skill slot
            self.is_extra_unit = False
            self.browse_wares_active = False
            self.browse_wares_skill = None
            self.browse_wares_attackers = set()
            self.speed_bonus = 0

            # Stagger mechanic
            self.stagger_thresholds = raw.get("Stagger-Thresholds", [0.6, 0.3, 0.1]) # Percentages of max HP
            self.stagger_level = 0
            self.is_staggered = False
            self._was_alive = True
            for eff in self.special_effects:
                name = eff.get("Name", "")
                
                
                


        def roll_my_speed(self):
            self.speed = roll_speed(self.speed_range)
            if self.has_status("Drowsy"):
                self.speed = max(1, self.speed - 1)
            return self.speed

        def prepare_for_battle(self):
            self.stagger_level = 0
            self.is_staggered = False
            self.burst_usage_count = 0
            self.browse_wares_active = False
            self.browse_wares_skill = None
            self.browse_wares_attackers.clear()
            self.speed_bonus = 0
            self._something_of_substance_triggered = False
            self._something_of_substance_victory_armed = False
            self._vigor_used = False
            self._knight_resolve_triggered = False
            self._burn_turn_start_potency = 1
            self._burn_turn_start_count = 1
            self._last_attack_target = None
            self._current_surge_active = False
            self._current_surge_permanent = False
            self._current_surge_slot_active = False
            self._initialize_battle_start_effects()

        def start_browse_wares(self):
            if not self.has_special_effect("I Beseech You to Browse Our Wares"):
                return False
            self.skills.update({
                "Charms of Elements": {
                    "Type": "Support", "Element": "Charm", "Coin-Count": 1,
                    "Coin-Power": 0, "Effects": {},
                },
                "A Sword of Pure Gold": {
                    "Type": "Attack", "Damage-Type": "Slash", "Element": "Earth",
                    "Base-Power": 7, "Coin-Count": 1, "Coin-Power": 5,
                    "Offense-Level": 60, "Attack-Weight": 1, "Effects": {},
                },
                "An Unbreakable Sheild": {
                    "Type": "Defense", "Element": "Earth", "Coin-Count": 1,
                    "Coin-Power": 0, "Effects": {},
                },
            })
            self.skill_slots = 5 if getattr(self, "forced_skill_sequences", None) else 3
            self.speed_bonus = 10
            self.browse_wares_active = True
            self.browse_wares_skill = None
            self.browse_wares_attackers.clear()
            if not getattr(self, "forced_skill_sequences", None):
                self.forced_skill_sequence = [
                    "Charms of Elements",
                    "A Sword of Pure Gold",
                    "An Unbreakable Sheild",
                ]
                self.forced_skill_sequence_index = 0
            return True

        def _initialize_battle_start_effects(self):
            if self.has_special_effect("Vengeance."):
                self.apply_status("Justified Bullets", potency=22, count=1)
            if self.has_special_effect("Pyric Fury"):
                self.apply_status("Harbinger's Mark", potency=1, count=1)
            if self.has_special_effect("Legendary Weapon: Heaven Flare Sword"):
                self.apply_status("Flare Sword", potency=1, count=1)
            if self.has_special_effect("Legendary Weapon: The Ice Dagger"):
                self.apply_status("Ice Dagger", potency=1, count=1)
            if self.has_special_effect("The Commander's Weapons"):
                self.apply_status("Duel Preping", potency=1, count=1)
            if self.has_special_effect("Extinguisher Weapon Rapier"):
                self.apply_status("Gas Rapier", potency=100, count=1)
                self.apply_status("Gas Reserves", potency=0, count=500)
            if self.has_special_effect("Able Man's Rifle"):
                self.apply_status("Stone Bullets", potency=55, count=1)
            if self.has_special_effect("Birling Coveted Silven Metal - Harpoons"):
                self.apply_status("Silven Harpoons", potency=12, count=1)
            if self.has_special_effect("Gun's of the L Sector"):
                self.apply_status("Bullets", potency=10, count=1)
            if self.has_special_effect("Actively Not Trying"):
                self.apply_status("Clash Power Down", potency=40, count=1)
            if self.has_special_effect("The Quaking Grounds"):
                self.apply_status("Pyro Shield", potency=1, count=1)
            if self.has_special_effect("The One With The Fans"):
                self.apply_status("Cloud-Adorned Fans", potency=5, count=1)
            if self.has_special_effect("Proving Myself"):
                self.apply_status("Growing Reputation", potency=0, count=1)
            if self.has_special_effect("Our Army Of Offense"):
                self.apply_status("Motivation", potency=0, count=1)
            return

        def apply_turn_start_special_effects(self, allies: List["Combatant"], all_combatants: Optional[List["Combatant"]] = None, turn_no: int = 1):
            surge_effect = next(
                (name for name in CURRENT_SURGE_TURNS if self.has_special_effect(name)),
                None,
            )
            surge_active = bool(
                surge_effect
                and (self._current_surge_permanent or turn_no <= CURRENT_SURGE_TURNS[surge_effect])
            )
            if surge_active and not self._current_surge_slot_active:
                self.skill_slots += 1
                self._current_surge_slot_active = True
            elif not surge_active and self._current_surge_slot_active:
                self.skill_slots = max(1, self.skill_slots - 1)
                self._current_surge_slot_active = False
            self._current_surge_active = surge_active

            if self.has_special_effect("Following My Current"):
                self.apply_status("Current", potency=1, count=1)

            if self.has_special_effect("Artic Rapier") and all_combatants:
                for target in all_combatants:
                    if (target is self or not target.is_alive()
                            or target.statuses.get("Frostbite", {}).get("stacks", 0) < 5):
                        continue
                    frostbite_count = target.statuses["Frostbite"]["stacks"]
                    target.remove_status("Frostbite")
                    target.apply_status("Action-Blocked", potency=0, count=max(1, target.skill_slots))
                    print(f"  ❄️ {target.name} is frozen by Artic Rapier ({frostbite_count} Frostbite) and cannot act this turn.")

            if self.has_special_effect("Burning"):
                self.apply_status(
                    "Burn",
                    potency=self._burn_turn_start_potency,
                    count=self._burn_turn_start_count,
                )
                print(
                    f"  🔥 {self.name} gains Burn ({self._burn_turn_start_potency}, "
                    f"{self._burn_turn_start_count}) from Burning."
                )

            if self.has_status("Nerve Chill"):
                nerve_chill_count = self.statuses["Nerve Chill"].get("stacks", 0)
                if nerve_chill_count >= 10:
                    self.remove_status("Nerve Chill")
                    self.apply_status("Action-Blocked", potency=0, count=1)
                    print(f"  ❄️ {self.name} loses all Nerve Chill and is frozen for a turn.")
                elif random.random() < (0.10 * nerve_chill_count):
                    self.apply_status("Action-Blocked", potency=0, count=1)
                    print(f"  ❄️ {self.name} is forced to lose their action by Nerve Chill.")

            if self.has_status("Volatile Rage"):
                if not self.has_status("Clash Power Up"):
                    self.apply_status("Clash Power Up", potency=4, count=1)
                self.apply_status("Current", potency=3, count=3)

            if self.has_special_effect("Proving Myself"):
                reputation = self.get_status_potency("Growing Reputation")
                if reputation >= 2:
                    aggro_potency = 2 + (3 if reputation >= 5 else 0)
                    self.apply_status("Aggro", potency=aggro_potency, count=1)

            if self.has_status("Cloud-Adorned Fans"):
                current_pot = self.get_status_potency("Cloud-Adorned Fans")
                if current_pot == 0:
                    self.apply_status("Cloud-Adorned Fans", potency=5, count=0)
                    self.apply_status("Fragility", potency=2, count=1)
                if current_pot > 0:
                    self.apply_status("Cloud-Adorned Fans", potency=1, count=0)
                    if self.statuses["Cloud-Adorned Fans"]["potency"] > 5:
                        self.statuses["Cloud-Adorned Fans"]["potency"] = 5

            if self.has_status("Freezing") and self.has_status("Clouds Of Nostalgia"):
                self.apply_status("Freezing", potency=1, count=0)
            if self.has_status("Freezing") and self.has_status("Clouds Of Memories"):
                self.apply_status("Freezing", potency=0, count=1)

            if self.has_special_effect("Steel Skin") and self.has_status("Quantus"):
                if self.statuses["Quantus"]["stacks"] >= 20:
                    self.apply_status("Guard", potency=20, count=2)
                    self.remove_status("Quantus", 10)
                    self.apply_status("Lethal Energy", potency=1, count=0)
                    print(f"  ⚙️ {self.name}'s Steel Skin converts 10 Quantus into Lethal Energy and grants Guard.")

            if self.has_special_effect("The Quaking Grounds"):
                self.apply_status("Protection", potency=1, count=1)

            if self.has_special_effect("Extinguisher Weapon Rapier"):
                self.apply_status("Gas Rapier", potency=0, count=1)
                missing = max(0, 100 - self.get_status_potency("Gas Rapier"))
                if missing > 0:
                    self.apply_status("Gas Rapier", potency=missing, count=1)
                    self.remove_status("Gas Reserves", missing)
                if self.has_status("Gas Rapier") and self.statuses["Gas Rapier"]["potency"] > 100:
                    self.statuses["Gas Rapier"]["potency"] = 100
                if self.has_status("Fumes") and self.statuses["Fumes"]["stacks"] > 35:
                    self.statuses["Fumes"]["stacks"] = 35

            if self.has_special_effect("Follow The Script"):
                for ally in allies:
                    if ally.raw.get("Class") == "A Sector" and ally is not self:
                        ally.apply_status("Power", potency=2, count=1)
                        ally.apply_status("Haste", potency=1, count=1)

            if self.has_special_effect("The One Giving Commands"):
                for ally in allies:
                    if ally.raw.get("Class") == "F Sector" and ally is not self:
                        ally.apply_status("Current", potency=2, count=2)

            if self.has_special_effect("Our Army Of Offense"):
                for ally in allies:
                    if ally.raw.get("Class") != "Guillevien" or not ally.is_alive():
                        continue
                    if ally.name == "George" and ally.has_status("Dueling"):
                        ally.apply_status("Dueling", potency=1, count=0)
                    elif ally.name == "Racheal":
                        ally.apply_status("Growing Reputation", potency=1, count=0)

                motivation = self.get_status_potency("Motivation")
                if motivation >= 5:
                    self.spend_status_potency("Motivation", motivation)
                    for ally in allies:
                        if ally.raw.get("Class") == "Guillevien" and ally.is_alive():
                            ally.change_morale(30)
                    print(f"  ⚔️ {self.name}'s Our Army Of Offense grants 30 morale to the Guillevien forces.")

            if self.has_special_effect("I've got your back..."):
                for ally in allies:
                    if ally.name == "Guillevien Branch N Commander Linda" and ally.is_alive():
                        ally.apply_status("Slash Damage Up", potency=3, count=1)

            if self.has_special_effect("...You've got mine"):
                for ally in allies:
                    if ally.name == "Guillevien Branch N Commander Snowball" and ally.is_alive():
                        ally.apply_status("Slash Damage Up", potency=3, count=1)

            if self.has_special_effect("I'll Fix You Up"):
                candidates = [a for a in allies if a.is_alive() and a is not self]
                if candidates:
                    total_burn_potency = 0
                    if all_combatants:
                        for c in all_combatants:
                            if c.is_alive() and c not in allies and c.has_status("Burn"):
                                total_burn_potency += c.get_status_potency("Burn")
                    if total_burn_potency == 0:
                        total_burn_potency = sum(
                            c.get_status_potency("Burn") for c in all_combatants or allies
                            if c is not self and c.is_alive() and c.has_status("Burn")
                        )
                    if total_burn_potency > 0:
                        target = min(candidates, key=lambda c: (c.hp, c.max_hp))
                        heal_amount = total_burn_potency
                        target.heal(heal_amount)
                        print(f"  💚 {target.name} heals {heal_amount} HP from I'll Fix You Up!")

            if not self.has_special_effect("Commander Of The Pyric Fleet"):
                return
            for ally in allies:
                if ally.raw.get("Class") == "Pyric" and not ally.has_status("Lord's Guidance"):
                    ally.apply_status("Lord's Guidance", potency=1, count=1)

        def is_alive(self) -> bool:
            return self.alive and self.hp > 0

        def change_morale(self, amount: int):
            self.morale = clamp(self.morale + amount, 0, 100)

        def has_special_effect(self, effect_name: str) -> bool:
            return any(eff.get("Name") == effect_name for eff in self.special_effects)

        def trigger_something_of_substance(self):
            if self._something_of_substance_triggered:
                return False
            self._something_of_substance_triggered = True
            self._something_of_substance_victory_armed = False
            self.max_hp = 2009
            self.hp = 1002
            self.morale = 50
            self.apply_status("Shifting Colors", potency=1, count=1)
            for ally in self.team_members or [self]:
                if ally is None:
                    continue
                if ally is self:
                    ally.hp = 1002
                    ally.morale = 50
                    continue
                if not ally.is_alive():
                    ally.alive = True
                    ally.hp = max(1, ally.max_hp // 2)
                else:
                    ally.heal(max(0, ally.max_hp - ally.hp))
                ally.morale = 70
            print(f"  ✨ {self.name} triggers Something Of Substance! Max HP becomes 2009 and allies are restored.")
            return True

        def has_fireproof_gear(self) -> bool:
            return self.has_special_effect("Fireproof") or self.has_special_effect("Fireproof Gear")

        def spend_status_potency(self, name: str, amount: int) -> int:
            if name not in self.statuses:
                return 0
            current = self.statuses[name].get("potency", 0)
            spent = min(current, max(0, amount))
            self.statuses[name]["potency"] = max(0, current - spent)
            if self.statuses[name]["potency"] <= 0 and self.statuses[name].get("stacks", 0) <= 0:
                del self.statuses[name]
            return spent

        def apply_status(self, name: str, potency: int = 1, count: int = 1, duration: Optional[int]=None):
            if name == "Nerve Chill" and self.has_status("Volatile Rage"):
                return
            s = self.statuses.setdefault(name, {"potency": 0, "stacks": 0, "duration": duration or 0})
            if name == "Gas Rapier":
                s["potency"] = min(100, s["potency"] + potency)
                s["stacks"] = max(1, count)
                return
            if name == "Fumes":
                s["potency"] = 0
                s["stacks"] = min(35, max(0, s["stacks"] + count))
                return
            s["stacks"] += count
            s["potency"] += potency

        def remove_status(self, name: str, count: Optional[int] = None):
            if name in self.statuses:
                if count is None:
                    del self.statuses[name]
                else:
                    self.statuses[name]["stacks"] -= count
                    # Clamp stacks to 0 minimum (bullets don't go negative, just stay at 0)
                    self.statuses[name]["stacks"] = max(0, self.statuses[name]["stacks"])

                    if self.statuses[name]["stacks"] <= 0:
                        del self.statuses[name]

        def has_status(self, name: str) -> bool:
            return name in self.statuses and self.statuses[name]["stacks"] > 0

        def get_status_potency(self, name: str) -> int:
            return self.statuses.get(name, {}).get("potency", 0)

        def trigger_status(self, name: str, potency: Optional[int] = None):
            if not self.has_status("Remembrance"):
                return
            status = self.statuses.setdefault(
                name, {"potency": potency or 0, "stacks": 0, "duration": 0}
            )
            if potency is not None and status["potency"] == 0:
                status["potency"] = potency
            status["stacks"] = 1

        def take_damage(self, amount: int, damage_source: str = "direct"):

            if amount <= 0 or self.has_status("Nullification"):
                return 0

            if (self.has_special_effect("Vigor") and not self._vigor_used
                    and amount >= self.hp
                    and self.team_elements is not None
                    and self.team_elements.get("Fire", 0) > 5):
                self.team_elements["Fire"] -= 5
                self._vigor_used = True
                self.apply_status("Nullification", potency=1, count=1)
                print(f"  🛡️ {self.name}'s Vigor spends 5 Fire and grants Nullification.")
                return 0

            old_hp_percent = self.hp / self.max_hp
            damage_floor = 0
            if self.has_status("Protection"):
                reduction_pct = 0.10 * self.get_status_potency("Protection")
                amount = max(0, int(amount * (1.0 - reduction_pct)))
            if damage_source == "burn" and self.has_special_effect("Burning"):
                damage_floor = 1
            amount = min(amount, max(0, self.hp - damage_floor))
            self.hp -= amount
            if (self.has_special_effect("A Knight's Resolve")
                    and not self._knight_resolve_triggered
                    and self.hp <= self.max_hp * 0.5):
                self._knight_resolve_triggered = True
                self.hp = min(self.max_hp, self.hp + 50)
                self.change_morale(60)
                self.apply_status("Clash Power Up", potency=2, count=1)
                print(f"  ⚔️ {self.name}'s A Knight's Resolve restores 50 HP, raises morale, and strengthens clashes!")
            if self.has_special_effect("Something Of Substance"):
                if not self._something_of_substance_triggered and self.hp < 600:
                    self.trigger_something_of_substance()
                elif self._something_of_substance_triggered and self.hp < 600:
                    self._something_of_substance_victory_armed = True
            if self.has_special_effect("Enough Games") and self.hp < 2900 and not self.has_status("Seriousness"):
                self.remove_status("Clash Power Down", 1)
                self.apply_status("Seriousness", potency=3, count=1)
                print(f"  🎯 {self.name} has had enough with these games!")
            if self.hp <= 0:
                self.hp = 0
                # Re-awoken Vengence prevents death while allies remain alive
                if self.has_status("Re-awoken Vengence"):
                    self.hp = 1
                    self.alive = True
                    self.morale = 100
                    return
                elif self.has_status("Overruling"):
                    self.hp = 1
                    self.alive = True
                    self.morale = 100
                else:
                    self.alive = False
            else:
                self.check_stagger_thresholds(old_hp_percent)
            return amount

        def record_skill_use(self, skill_name: str):
            if not self.has_special_effect("Burning"):
                return
            if skill_name == "Absolute Burning":
                self._burn_turn_start_potency += 1
                self._burn_turn_start_count += 1
            elif skill_name == "Cooldown":
                self._burn_turn_start_potency = max(0, self._burn_turn_start_potency - 1)
                self._burn_turn_start_count = max(0, self._burn_turn_start_count - 1)

        def check_stagger_thresholds(self, old_hp_percent: float):
            new_hp_percent = self.hp / self.max_hp
            for i, threshold in enumerate(self.stagger_thresholds):
                if old_hp_percent > threshold and new_hp_percent <= threshold:
                    if i >= self.stagger_level:
                        self.trigger_stagger(i + 1)

        def trigger_stagger(self, level: int):
            if self.has_special_effect("Unstaggerable"):
                return
            self.stagger_level = level
            self.is_staggered = True
            print(f"  ⚡ {self.name} reached STAGGER THRESHOLD {self.stagger_level}!")

        def devastate(self, log: List[str]):
            trigger_reasons = (
                self.has_status("Quaken")
                or self.has_status("Bounden")
                or self.has_status("Blazed")
                or self.has_status("Enlighten")
                or self.has_status("Pyro Shield")
                or self.has_special_effect("The Quaking Grounds")
            )
            if not trigger_reasons:
                return
            quaken_potency = self.get_status_potency("Quaken")
            potency = self.statuses["Quaken"]["potency"] if self.has_status("Quaken") else 0
            potency += self.statuses["Blazed"]["potency"] if self.has_status("Blazed") else 0
            msg = f"  💥 Devastation on {self.name}! (Potency: {potency})"
            log.append(msg)
            print(msg)

            if self.has_status("Pyro Shield") or self.has_special_effect("The Quaking Grounds"):
                for ally in getattr(self, "team_members", []):
                    if not ally or not ally.is_alive():
                        continue
                    if ally.raw.get("Class") == "Pyric" or ally.name in {"Macduff", "The 1st Harbinger - Flame Lord Macduff"}:
                        ally.apply_status("Protection (Next Turn)", potency=1, count=1)
                        print(f"  🛡️ {ally.name} gains Protection (Next Turn) from {self.name}'s Pyro Shield devastate!")

            old_hp_percent = self.hp / self.max_hp
            # Reduce stagger thresholds relative to current HP? 
            # Limbus mechanic: Burst reduces current stagger threshold by potency.
            # If current threshold reached, stagger.

            # Simple implementation: Treat potency as damage specifically for stagger thresholds
            # but don't reduce actual HP.
            stagger_only_damage = potency
            virtual_hp = self.hp - stagger_only_damage
            virtual_hp_percent = virtual_hp / self.max_hp

            if self.has_status("Blazed"):
                # Apply burn equal to combined potency and count of all available quakens
                count = self.statuses["Blazed"]["stacks"]
                if self.has_status("Quaken"):
                    count += self.statuses["Quaken"]["stacks"]
                self.apply_status("Burn", potency=potency, count=count)


            for i, threshold in enumerate(self.stagger_thresholds):
                if old_hp_percent > threshold and virtual_hp_percent <= threshold:
                    if i >= self.stagger_level:
                        self.trigger_stagger(i + 1)

            # Reduce Quaken count after burst
            self.remove_status("Quaken", 1)
            if quaken_potency > 0:
                self.trigger_status("Quaken", potency=quaken_potency)

        def heal(self, amount: int):
            if not self.is_alive():
                return
            self.hp = clamp(self.hp + amount, 0, self.max_hp)

        def __repr__(self):
            return f"{self.name} [{self.hp}/{self.max_hp}]"

        def can_afford(self, cost: Dict[str, int], team_elements: Dict[str, int]) -> bool:
            for elem, req in cost.items():
                if team_elements.get(elem, 0) < req:
                    return False
            return True

        def pay_cost(self, cost: Dict[str, int], team_elements: Dict[str, int]):
            for elem, req in cost.items():
                team_elements[elem] = max(0, team_elements.get(elem, 0) - req)

        def add_element(self, elem: str, team_elements: Dict[str, int], amt: int = 1):
            team_elements[elem] = team_elements.get(elem, 0) + amt

        def gain_elements_for_skill(self, skill: Dict[str, Any], team_elements: Dict[str, int], multiplier: int = 1):
            elem = skill.get("Element")
            if elem:
                self.add_element(elem, team_elements, multiplier)

# ---------- Damage & Effects (unchanged core logic) -------------------------
def resistance_multiplier(target: Combatant, damage_type: str) -> float:
        res = target.resistances.get(damage_type, "Normal")

        # Stagger mechanic: staggered targets take more damage and resistances are worsened
        mult_base = 1.0
        if target.is_staggered:
            # Shift resistances one level worse
            if res == "Ineff":
                res = "Normal"
            elif res == "Normal":
                res = "Fatal"


        if res == "Ineff":
            return mult_base * 0.5
        if res == "Fatal":
            return mult_base * 2.0
        return mult_base * 1.0

def effective_coin_power(user: Optional[Combatant], skill: Dict[str, Any]) -> int:
        coin_power = int(skill.get("Coin-Power", 0))
        if user and user.has_status("Fear"):
            coin_power -= 1
        if user and user.has_status("Drowsy"):
            coin_power -= 1
        return coin_power

def drowsy_status_count(source: Combatant, status: str, count: int,
                        is_limit_burst: bool = False) -> int:
        if (source.has_status("Drowsy") and not is_limit_burst
                and status in DROWSY_REDUCED_STATUSES and count > 1):
            return count - 1
        return count

def calc_damage(user: Combatant, target: Combatant, skill: Dict[str, Any], coin_wins: int,
                log: Optional[List[str]] = None, consume_resources: bool = True,
                is_limit_burst: bool = False) -> int:
        base = int(skill.get("Base-Power", 0))
        coin_power = effective_coin_power(user, skill)

        if user.has_status("Fear"):
            base -= 4
        if user.has_status("To Right Wrongs") and skill.get("Name") == "The Pyric Offense Captain":
            base += 10

        offense = skill.get("Offense-Level", 0)
        raw = max(0, base + coin_wins * coin_power)
        fan_critical = False


        # Actual application of Increase Damage and Damage Boost: multiply raw of an attack by X1.its potency of the status
        if user.has_status("Increase-Damage"):
            raw = int(raw * (1.0 + user.get_status_potency("Increase-Damage") * 0.01))
        if user.has_status("Damage Boost"):
            raw = int(raw * (1.0 + user.get_status_potency("Damage Boost") * 0.01))
        if user.has_status("A Sword of Pure Gold"):
            raw = int(raw * (1.0 + 0.07 * max(0, int(skill.get("Base-Power", 0)))))
        if user.has_status("Power"):
            raw = int(raw * (1.0 + user.get_status_potency("Power") * 0.10))
        if user.has_status("Lord's Guidance"):
            raw = int(raw * 1.2)
        if user.has_special_effect("Quantus Charge") and user.has_status("Quantus"):
            raw = int(raw * (1.0 + user.statuses["Quantus"]["stacks"] * 0.05))
        if user.has_special_effect("The One Giving Commands") and target.has_status("Burn"):
            raw = int(raw * 1.3)

        offense_defense_allies = getattr(user, "team_members", [])
        if (target.has_status("Quaken")
                and (user.has_special_effect("Offense is a great Defense")
                     or any(ally.has_special_effect("Offense is a great Defense")
                            for ally in offense_defense_allies))):
            raw = int(raw * 1.2)

        if user.has_special_effect("Overheat") and user.has_status("Burn"):
            raw = int(raw * 1.3)

        if user.has_special_effect("Syndicate - Extinguishing Gas"):
            if target.raw.get("Class") == "Pyric" or target.has_status("Burn"):
                raw = int(raw * 1.3)

        if user.has_special_effect("Blade Encasement: Spilling More Of The Blood"):
            dark_aura_potency = user.get_status_potency("Dark Aura")
            damage_bonus = min((dark_aura_potency // 2) * 0.1, 0.4)
            raw = int(raw * (1.0 + damage_bonus))

        if user.has_status("To Right Wrongs") and target.name == "Lenuff - The Flare":
            raw = int(raw * 1.10)
        if target.has_status("To Right Wrongs") and user.name == "Lenuff - The Flare":
            raw = int(raw * 0.90)
        if user.has_status("Volatile Rage") and target.name == "Tybalt - The Frost":
            raw = int(raw * 1.40)
            if target.hp <= int(target.max_hp * 0.25):
                raw = int(raw * 2.0)
        if target.has_status("Volatile Rage") and user.name == "Tybalt - The Frost":
            raw = int(raw * 1.30)

        if user.has_status("Gas Rapier"):
            user.statuses["Gas Rapier"]["potency"] -= 5
            target.apply_status("Fumes", potency=0, count=4)


        if consume_resources and user.has_status("Current"):
            if random.random() < 0.05 * user.get_status_potency("Current"):
                if (user.has_special_effect("The One With The Fans")
                        and user.get_status_potency("Cloud-Adorned Fans") > 0):
                    raw = int(raw * 2.0)
                    user.spend_status_potency("Cloud-Adorned Fans", 1)
                    fan_critical = True
                elif user.has_special_effect("Legendary Weapon: Dual Diamond Cutters"):
                    raw = int(raw * 1.5)
                    user.apply_status(
                        "Current", potency=0,
                        count=drowsy_status_count(user, "Current", 2, is_limit_burst),
                    )
                    target.apply_status(
                        "Injured", potency=6,
                        count=drowsy_status_count(user, "Injured", 3, is_limit_burst),
                    )
                elif user.has_special_effect("Legendary Weapon: Heaven Flare Sword"):
                    raw = int(raw * 1.2)
                    target.apply_status(
                        "Burn", potency=1,
                        count=drowsy_status_count(user, "Burn", 2, is_limit_burst),
                    )
                elif user.has_special_effect("Legendary Weapon: The Ice Dagger") and user.has_status("Ice Dagger"):
                    raw = int(raw * 1.2)
                    target.apply_status("Nerve Chill", potency=0, count=1)
                elif user.has_status("Gas Rapier"):
                    user.statuses["Gas Rapier"]["potency"] -= 6
                    target.apply_status("Fumes", potency=0, count=6)
                elif user.has_special_effect("F Sector Flame Blades") or user.has_special_effect("F Sector Flame Bow") or user.has_special_effect("F Sector Flame Charging Suit"):
                    if not target.has_fireproof_gear():
                        target.apply_status("Burn", potency=1, count=1)
                else:
                    raw = int(raw * 1.1)

                if user.has_special_effect("Passionate Flame"):
                    if not user.has_status("Passion") or user.statuses["Passion"]["potency"] < 3:
                        user.apply_status("Passion", potency=1, count=1)
                    if user.has_status("Passion") and user.statuses["Passion"]["potency"] >= 3:
                        raw = int(raw * 1.6)
                        user.remove_status("Passion")
                if user.has_status("Shifting Colors") and target.has_status("Freezing") and random.random() < 0.60:
                    freeze_potency = target.get_status_potency("Freezing")
                    freeze_count = target.statuses["Freezing"].get("stacks", 0)
                    converted_potency = max(1, freeze_potency // 2)
                    converted_count = max(1, freeze_count // 2)
                    remaining_potency = max(0, freeze_potency - converted_potency)
                    remaining_count = max(0, freeze_count - converted_count)
                    if remaining_count > 0:
                        target.apply_status("Freezing", potency=remaining_potency, count=remaining_count)
                    else:
                        target.remove_status("Freezing")
                    converted_status = random.choice(["Burn", "Injured", "Winded"])
                    target.apply_status(
                        converted_status, potency=converted_potency,
                        count=drowsy_status_count(
                            user, converted_status, converted_count, is_limit_burst,
                        ),
                    )
                    print(f"  🎨 {user.name}'s Shifting Colors converts half of {target.name}'s Freezing into {converted_status}!")
                current_should_be_removed = not (
                    user.has_status("Volatile Rage")
                    and target.name == "Tybalt - The Frost"
                )
                if current_should_be_removed:
                    user.remove_status("Current", 1)
                msg = f"  💥 {user.name} lands a critical hit!"
                if log is not None:
                    log.append(msg)
                print(msg)
                if (consume_resources
                        and user.has_special_effect("Artic Rapier")
                        and target is not None):
                    target.apply_status("Frostbite", potency=0, count=1)
                    msg = f"  ❄️ {user.name}'s Artic Rapier inflicts Frostbite on {target.name}."
                    if log is not None:
                        log.append(msg)
                    print(msg)
        morale_mult = 0.5 + (user.morale / 100.0)
        raw = int(raw * morale_mult)


        power_ring_bonus = user.gear_bonuses.get("Power Ring", 0)
        if power_ring_bonus:
            raw = int(raw * (1.0 + power_ring_bonus / 100.0))

        if user.has_status("Charm Damage Up"):
            # If skill type is Charm, deal (potency * 10)% more damage (1= +10%, 2= +20%, etc)
            if skill.get("Element") == "Charm":
                raw = int(raw * (1.0 + user.get_status_potency("Charm Damage Up") * 0.1))

        if user.has_status("Wind Damage Up"):
            # If skill type is Wind, deal (potency * 10)% more damage (1= +10%, 2= +20%, etc)
            if skill.get("Element") == "Wind":
                raw = int(raw * (1.0 + user.get_status_potency("Wind Damage Up") * 0.1))

        if user.has_status("Slash Damage Up") and skill.get("Damage-Type") == "Slash":
            raw = int(raw * (1.0 + user.get_status_potency("Slash Damage Up") * 0.1))

        if target.has_status("Slash Fragility"):
            if skill.get("Damage-Type") == "Slash":
                raw = int(raw * 1.2)

        if target.has_status("Pierce Fragility"):
            if skill.get("Damage-Type") == "Pierce":
                raw = int(raw * 1.2)

        if user.has_status("Haste"):
            if user.has_special_effect("Path Recognition"):
                mult_value = 1.0 + (0.1 * user.statuses["Haste"]["potency"])
                if mult_value > 1.3:
                    mult_value = 1.3
                raw = int(raw * mult_value)

        if skill.get("Damage-Type") == "Pierce" and target.has_status("Fumes"):
            fumes_count = target.statuses["Fumes"].get("stacks", 0)
            bonus_pct = min((fumes_count // 4) * 10, 60)
            if bonus_pct > 0:
                raw = int(raw * (1.0 + bonus_pct / 100.0))


        target_defense = target.defense
        if target.has_status("Weakness"):
            target_defense = max(0, target_defense - target.get_status_potency("Weakness"))

        # Vivid Remembrance: Macduff's Harbinger form deals 45% more damage to Lenuff.
        if user.has_status("Vivid Remembrance") and target.raw.get("Name") == "Lenuff - Pyric Offense Captain":
            raw = int(raw * 1.45)

        # Faint Rememberance: When a unit with this status attacks Lenuff - Pyric Offense Captain, deal 25% less damage
        if user.has_status("Faint Rememberance") and target.raw.get("Name") == "Lenuff - Pyric Offense Captain":
            raw = int(raw * 0.75)

        # Overruling: Macduff's Harbinger form deals 215% more damage to Macbeth.
        if user.has_status("Overruling") and target.raw.get("Name") == "Macbeth - The 1st Harbinger Of Flames":
            raw = int(raw * 2.15)

        if user.has_status("Re-awoken Vengence"):
            if target.raw.get("Name") == "Macbeth - The 1st Harbinger Of Flames":
                raw = int(raw * 2.00)

        mult = 1.0 + (offense - target_defense) / 100.0
        mult = max(0.2, mult)
        dmg = int(raw * mult)




        # If the target has status 'Freezing', reduce morale by potency upon getting hit and reduce count by one
        if target.has_status("Freezing"):
            volatile_rage_block = (
                target.has_status("Volatile Rage")
                and tybalt_is_active_for(target)
            )
            if not volatile_rage_block:
                freezing_potency = target.get_status_potency("Freezing")
                target.change_morale(-target.get_status_potency("Freezing"))
                print(f"  💦 {target.name} loses {target.get_status_potency('Freezing')} morale from Freezing!")
                target.remove_status("Freezing", 1)
                target.trigger_status("Freezing", potency=freezing_potency)
        if fan_critical:
            target.apply_status("Freezing", potency=0, count=1)
        # If Target has 'Winded', deak its potency amount as extra damage and reduce count by 1
        if target.has_status("Winded") or target.has_status("Kniving Frost") or target.has_status("Gloom Fog"):
            winded_potency = target.get_status_potency("Winded")
            dmg += winded_potency
            print(f"  💥 {target.name} takes {winded_potency} extra damage from Winded!")
            target.remove_status("Winded", 1)
            target.trigger_status("Winded", potency=winded_potency)




        if target.has_status("Fragility"):
            dmg = int(dmg * (1.0 + target.get_status_potency("Fragility") * 0.1))

        dmg = int(dmg * resistance_multiplier(target, skill.get("Damage-Type", "Normal")))

        if target.has_status("Fear"):
            dmg = int(dmg * 2.0)
        if user.has_status("Fear") and target.has_special_effect("Masterly Presence"):
            dmg = int(dmg * 0.5)

        if user.has_status("Quaken"):
            shielding_allies = getattr(target, "team_members", [])
            if (target.has_special_effect("Sheilding")
                    or any(ally.has_special_effect("Sheilding") for ally in shielding_allies)):
                dmg = int(dmg * 0.8)

        if user.has_special_effect("Execution!!!") and user.speed >= 7:
            dmg *= 3

        if target.has_special_effect("Proving Myself") and user.has_status("Gaze Of The Commander"):
            dmg = int(dmg * 0.3)
            target.apply_status("Growing Reputation", potency=1, count=0)
        elif user.has_status("Gaze Of The Commander"):
            user.remove_status("Gaze Of The Commander")

        if target.has_status("Well Prepared"):
            dmg = int(dmg * 0.8)

        # Bullet statuses: Bullets. (Reduce the potency by one on attack if over 0 potency. at 0 potency, deal 0 damage) do this all on pierce attacks
        if skill.get("Damage-Type") == "Pierce" and consume_resources:
            bullet_statuses = ["Bullets", "Stone Bullets", "Justified Bullets", "Silven Harpoons"]
            for status in bullet_statuses:
                if user.has_status(status):
                    if user.statuses[status]["potency"] <= 0:
                        dmg = 0
                        continue
                    user.statuses[status]["potency"] -= 1
                    if status == "Stone Bullets":
                        target.apply_status("Quaken", potency=1, count=0)
                    elif status == "Justified Bullets" and user.has_special_effect("Vengeance."):
                        user.apply_status("Enraged", potency=0, count=2)
                    elif status == "Silven Harpoons":
                        target.apply_status("Injured", potency=1, count=0)


        # If user name is Lenuff - Pyric Offense Captain, target has 'Burn' and damage is over 20, Heal 50 HP to the user and remove 5 potency of burn
        if user.raw.get("Name") == "Lenuff - Pyric Offense Captain":
            if target.has_status("Burn"):
                if target.statuses["Burn"]["potency"] > 0 and dmg > 20:
                    user.heal(5)
                    target.statuses["Burn"]["potency"] -= 5
                    print(f"  🔥 Lenuff's Pyric Offense Captain heals 5 HP from burn on {target.name}!")

        # If user name is Macbeth - The 1st Harbinger Of Flames, target has 'Burn' and damage is over 20, Heal 30 HP to the user and remove 3 potency of burn
        if user.raw.get("Name") == "Macbeth - The 1st Harbinger Of Flames":
            if target.has_status("Burn"):
                if target.statuses["Burn"]["potency"] > 0 and dmg > 20:
                    user.heal(15)
                    target.statuses["Burn"]["potency"] -= 3
                    print(f"  🔥 Macbeth's Harbinger Of Flames heals 15 HP from burn on {target.name}!")

        if user.has_status("Drowsy"):
            dmg = int(dmg * 0.85)

        return max(0, dmg)

def eval_condition(cond: Optional[str], user: Combatant, target: Optional[Combatant]) -> bool:
        if not cond:
            return True
        cond = cond.strip()
        if cond == "Target Dead":
            return (target is not None) and (not target.is_alive())
        if cond.startswith("Target has "):
            if target is None:
                return False
            name = cond.split("Target has ", 1)[1]
            return any(target.has_status(k) for k in (name, f"Transform-{name}", f"Unlocked-{name}"))
        if cond.startswith("User has "):
            name = cond.split("User has ", 1)[1]
            return any(user.has_status(k) for k in (name, f"Transform-{name}", f"Unlocked-{name}"))
        return False

def iter_effects(effects: Any) -> List[Dict[str, Any]]:
        if isinstance(effects, dict):
            return [effects]
        if isinstance(effects, list):
            return effects
        return []

def apply_skill_effects(effects: Any, source: Combatant, main_target: Combatant,
                        all_targets: List[Combatant], skill: Dict[str, Any],
                        combatants: List[Combatant], log: List[str],
                        is_limit_burst: bool = False):
        """Apply skill effects, optionally splitting target effects across targets."""
        skill_effects = iter_effects(effects)
        equal_application = (
            int(skill.get("Attack-Weight", 1)) > 1
            and any(effect.get("Effect") == "Equal Application" for effect in skill_effects)
        )

        for effect in skill_effects:
            if effect.get("Effect") == "Equal Application":
                continue
            if not equal_application or effect.get("Effect") != "Inflict":
                apply_effect(
                    effect, source, main_target, combatants, log,
                    is_limit_burst=is_limit_burst,
                )
                continue

            target_count = len(all_targets)
            for target_index, target in enumerate(all_targets):
                split_effect = dict(effect)
                for field in ("Potency", "Count"):
                    if field in effect:
                        value = int(effect[field])
                        quotient, remainder = divmod(value, target_count)
                        split_effect[field] = quotient + (1 if target_index == 0 else 0) * remainder
                apply_effect(
                    split_effect, source, target, combatants, log,
                    is_limit_burst=is_limit_burst,
                )


def has_pyric_shield_support(unit: Combatant) -> bool:
    if not getattr(unit, "team_members", None):
        return unit.has_status("Pyro Shield")
    return (
        unit.has_status("Pyro Shield")
        or any(
            ally is not None and ally.has_status("Pyro Shield")
            for ally in unit.team_members
        )
    )


def filter_dancing_skills(actor: Combatant, skill_names: List[str]) -> List[str]:
    excluded = set()
    if actor.has_special_effect("Steel Skin"):
        excluded.add("Self Destruction")
    if actor.has_special_effect("A Gun Shot"):
        if actor.get_status_potency("Justified Bullets") > 0:
            excluded.add("Reload")
        else:
            excluded.add("Chasing Shots")
    if not actor.has_special_effect("Dancing") or actor._something_of_substance_triggered:
        return [name for name in skill_names if name not in excluded]
    excluded.update({"Dance Of The Flames", "Dance Of The Blades", "Dance Of The Winds"})
    return [name for name in skill_names if name not in excluded]


def check_something_of_substance_victory(team_a: List[Combatant], team_b: List[Combatant]) -> Optional[str]:
    for team, team_name in ((team_a, "TEAM A"), (team_b, "TEAM B")):
        for c in team:
            if c.has_special_effect("Something Of Substance") and c._something_of_substance_triggered and c._something_of_substance_victory_armed and c.hp < 600:
                return f"{team_name} WINS!"
    return None


def check_relevant_death_result(team_a: List[Combatant], team_b: List[Combatant]) -> Optional[str]:
    for team, opposing_team, result in (
        (team_a, team_b, "TEAM B WINS!"),
        (team_b, team_a, "TEAM A WINS!"),
    ):
        if (any(not c.is_alive() and c.has_special_effect("Relevant") for c in team)
                and any(c.is_alive() for c in opposing_team)):
            return result
    return None


def apply_effect(effect: Dict[str, Any], source: Combatant, target: Optional[Combatant],
                 combatants: List[Combatant], log: List[str],
                 is_limit_burst: bool = False):
        eff = effect.get("Effect")

        if eff == "Inflict":
            status = effect.get("Status")
            potency = int(effect.get("Potency", 1))
            count = int(effect.get("Count", 1))
            if target and status:
                if status == "Blazed" and target.has_fireproof_gear():
                    msg = f"  🛡️ {target.name}'s Fireproof Gear blocks Blazed."
                    log.append(msg)
                    print(msg)
                    return
                if status == "Burn":
                    if source.has_special_effect("The One Giving Commands"):
                        count += 1
                    if source.has_status("Vivid Remembrance") and target.raw.get("Name") == "Lenuff - Pyric Offense Captain":
                        count += 3
                    if source.has_status("Overruling") and target.raw.get("Name") == "Macbeth - The 1st Harbinger Of Flames":
                        count += 4
                extra_count = 0
                if status == "Burn" and (
                    source.has_status("Flare Sword")
                    or source.has_status("Harbinger's Mark")
                ):
                    extra_count = 1
                count = drowsy_status_count(
                    source, status, count + extra_count, is_limit_burst,
                )
                target.apply_status(status, potency=potency, count=count)
                if (status == "Injured"
                        and source.has_special_effect("Blade Encasement: Spilling More Of The Blood")):
                    source.apply_status("Dark Aura", potency=1, count=1)
                    msg = f"  🩸 {source.name} gains Dark Aura potency 1"
                    log.append(msg)
                    print(msg)
                msg = f"  🔴 {target.name} gains {status} x{count} (potency {potency})"
                if status == "Burn":
                    if source.has_status("Flare Sword") or source.has_status("Harbinger's Mark"):
                        target.apply_status("Burn", potency=1, count=0)
                        msg = f"  🔴 {target.name} gains {status} x{count} (potency {potency + 1})"
                    if source.has_status("Lord's Guidance"):
                        target.apply_status("Burn", potency=1, count=0)
                        msg = f"  🔴 {target.name} gains {status} x{count} (potency {potency + 1})"
                log.append(msg)
                print(msg)
        elif eff == "Gain":
            status = effect.get("Status")
            potency = int(effect.get("Potency", 1))
            count = int(effect.get("Count", 1))
            duration = None
            if status:
                count = drowsy_status_count(source, status, count, is_limit_burst)
                source.apply_status(status, potency=potency, count=count, duration=duration)
                msg = f"  🟢 {source.name} gains {status} x{count} (potency {potency})"
                # Quantus: if count is over 20, floor to 20
                if status == "Quantus":
                    if source.statuses["Quantus"]["stacks"] > 20:
                        source.statuses["Quantus"]["stacks"] = 20

                log.append(msg)
                print(msg)
        elif eff == "Lose":
            status = effect.get("Status")
            potency = int(effect.get("Potency", 1))
            count = int(effect.get("Count", 1))
            if status:
                if potency:
                    source.statuses[status]["potency"] = max(0, source.statuses[status]["potency"] - potency)
                if count:
                    source.remove_status(status, count)
                msg = f"  🟡 {source.name} loses {status} x{count} (potency {potency})"
                log.append(msg)
                print(msg)
        elif eff == "Damage":
            potency = int(effect.get("Potency", 0))
            source.take_damage(potency)
            msg = f"  💔 {source.name} takes {potency} damage"
            log.append(msg)
            print(msg)
        elif eff == "Heal-Ally":
            potency = int(effect.get("Potency", 1))
            if target and target.is_alive():
                target.heal(potency)
                msg = f"  💚 {target.name} healed {potency} HP"
                log.append(msg)
                print(msg)
                return
            allies = [c for c in combatants if c is not source and c.is_alive()]
            if allies:
                tar = random.choice(allies)
                tar.heal(potency)
                msg = f"  💚 {tar.name} healed {potency} HP"
                log.append(msg)
                print(msg)
        elif eff == "Heal-Self":
            potency = int(effect.get("Potency", 1))
            source.heal(potency)
            msg = f"  💚 {source.name} healed {potency} HP"
            log.append(msg)
            print(msg)
        elif eff == "Shield-Ally":
            status = effect.get("Status", "Guard")
            potency = int(effect.get("Potency", 0))
            if target and target.is_alive():
                target.apply_status(status, potency=potency, count=1)
                msg = f"  🛡️  {target.name} gets shield {status} ({potency} HP block)"
                log.append(msg)
                print(msg)
                return
            allies = [c for c in combatants if c is not source and c.is_alive()]
            if allies:
                tar = random.choice(allies)
                tar.apply_status(status, potency=potency, count=1)
                msg = f"  🛡️  {tar.name} gets shield {status} ({potency} HP block)"
                log.append(msg)
                print(msg)
        elif eff == "Reduce":
            if target and effect.get("Target-Stat") == "Defense":
                pot = int(effect.get("Potency", 0))
                target.defense = max(0, target.defense - pot)
                msg = f"  📉 {target.name} defense reduced by {pot}"
                log.append(msg)
                print(msg)
            elif target and effect.get("Target-Stat") == "Speed":
                msg = f"  📉 {target.name} speed reduced (potency {effect.get('Potency')})"
                log.append(msg)
                print(msg)
            elif target and effect.get("Target-Stat") == "Moral":
                pot = int(effect.get("Potency", 0))
                target.change_morale(-pot)
                msg = f"  📉 {target.name} morale reduced by {pot}"
                log.append(msg)
                print(msg)
        elif eff == "Devastate":
            if target:
                target.devastate(log)
        elif eff == "Counter-Attack":
            if target:
                pot = int(effect.get("Potency", 0))
                target.take_damage(pot)
                msg = f"  ⚔️  {target.name} takes counter damage: {pot}"
                log.append(msg)
                print(msg)
        elif eff == "Increase-Damage":
            pot = int(effect.get("Potency", 0))
            source.apply_status("Damage Boost", potency=pot, count=1)
            msg = f"  💥 {source.name} gains Damage Boost +{pot} for next attack"
            log.append(msg)
            print(msg)
        elif eff == "Teleport-User":
            msg = f"  ✨ {source.name} teleports (flavor only)"
            log.append(msg)
            print(msg)
        elif eff == "Push" or eff == "Knockback":
            if target:
                msg = f"  💨 {target.name} is pushed/knocked back (flavor only)"
                log.append(msg)
                print(msg)
        elif eff == "Reveal":
            stat = effect.get("Target-Stat")
            if stat:
                target.apply_status("Revealed-"+str(stat), potency=1, count=1)
                msg = f"  👁️  {source.name} reveals {stat}"
                log.append(msg)
                print(msg)
        elif eff == "Grant":
            status = effect.get("Status")
            potency = int(effect.get("Potency", 1))
            count = int(effect.get("Count", 1))
            if target and status:
                count = drowsy_status_count(source, status, count, is_limit_burst)
                target.apply_status(status, potency=potency, count=count)
                msg = f"  🎁 {target.name} is granted {status} x{count} (potency {potency})"
                log.append(msg)
                print(msg)
        elif eff == "Die":
            source.take_damage(source.hp)
            msg = f"  💀 {source.name} dies"
            log.append(msg)
            print(msg)
        elif eff == "Kill":
            # instant-kill effect. If target is "User" then kill the source instead.
            target_flag = effect.get("Target", "")
            if target_flag == "User":
                source.hp = 0
                source.alive = False
                msg = f"  💀 {source.name} is destroyed by their own Limit Burst!"
                log.append(msg)
                print(msg)
            else:
                if target:
                    target.take_damage(target.hp)  # set HP to 0 via damage flow
                    msg = f"  💀 {target.name} was instantly killed!"
                    log.append(msg)
                    print(msg)
        elif eff == "Reload":
            required_user = effect.get("Required-User")
            if required_user and source.key != required_user:
                return
            potency = int(effect.get("Potency", 5))
            if (source.has_special_effect("Birling Coveted Silven Metal - Harpoons")
                    and source.has_status("Silven Harpoons")):
                source.apply_status("Silven Harpoons", potency=potency, count=0)
                msg = f"  🔋 {source.name} reloads {potency} Silven Harpoons!"
                log.append(msg)
                print(msg)
            elif (source.has_status("Bullets")
                    or source.key == "Divinus LB Suit :: For Correct Justice Macduff"
                    or (source.name == "Sherlock" and source.raw.get("Class") == "Havenus Elite")):
                source.apply_status("Bullets", potency=potency, count=0)
                msg = f"  🔋 {source.name} reloads {potency} Bullets!"
                log.append(msg)
                print(msg)
            elif (source.has_special_effect("Vengeance.")
                    and source.has_status("Justified Bullets")):
                source.apply_status("Justified Bullets", potency=potency, count=0)
                msg = f"  🔋 {source.name} reloads {potency} Bullets!"
                log.append(msg)
                print(msg)
        else:
            msg = f"  ⚠️  (unhandled effect {eff})"
            log.append(msg)
            print(msg)


def on_kill(killer: Combatant, dead: Combatant, all_combatants: List[Combatant], log: List[str]):
    """
    Called when 'killer' defeats 'dead'. Implements:
      - Relentless Purging: if killer has that special-effect and dead had a Marked status,
        apply Brighter Burn.
      - Generic hooks for other 'on kill' special-effect strings.

    Mark transfer behavior:
      - If the defeated combatant had `Marked` or `Mark-Hunting`, remove both statuses from
        the corpse and attempt to apply `Marked` to a random valid alive target (not the killer
        and not already marked).
      - Avoid referencing an undefined `target` when no valid replacement exists.
    """
    if killer is None or dead is None:
        return

    if (killer._current_surge_active
            and any(killer.has_special_effect(name) for name in CURRENT_SURGE_TURNS)):
        killer._current_surge_permanent = True
        msg = f"  🌊 {killer.name}'s Current surge becomes permanent after defeating {dead.name}."
        log.append(msg)
        print(msg)

    if killer.has_special_effect("Vengeance.") and dead.has_status("Trusted"):
        if killer.has_status("Justified Bullets"):
            killer.statuses["Justified Bullets"]["potency"] = 22
        else:
            killer.apply_status("Justified Bullets", potency=22, count=1)
        killer.apply_status("Enraged", potency=0, count=2)
        msg = f"  🎯 {killer.name} defeats Trusted target {dead.name}, restoring Justified Bullets to 22 and gaining 2 Enraged."
        log.append(msg)
        print(msg)

    duel_statuses = {
        "Declared Duel - Ross": "Ross - Noble Sword Artist",
        "Declared Duel - George": "George",
    }
    for declared_duel, duelist_name in duel_statuses.items():
        if not dead.has_status(declared_duel):
            continue

        dead.remove_status(declared_duel)
        for c in all_combatants:
            if c.name != duelist_name or not c.has_status("Dueling"):
                continue

            c.remove_status("Dueling")
            msg = f"  ⚔️ {c.name} loses Dueling because their declared duel target was defeated."
            log.append(msg)
            print(msg)
            if c.name == "George":
                c.apply_status("Duel Preping", potency=1, count=1)
                msg = f"  ⚔️ {c.name} gains Duel Preping for a new declared duel."
                log.append(msg)
                print(msg)


def handle_wotb_death(dead: Combatant, all_combatants: List[Combatant], log: List[str]):
        """
        Called when a combatant is defeated. Applies Way Of The Blade (WOTB) effects:
          - Macduff's "Blade Member's Assemble": grant stackable WOTB-Damage-Bonus (+10% damage per stack)
          - The Monster's "The True Power of the Blades": grant 'Blade-Rage' status (potency 1, stackable)
        all_combatants should be the full list of combatants (team_a + team_b).
        """
        # only proceed if dead was a WOTB unit (class contains "Way Of The Blade")
        dead_class = dead.raw.get("Class", "")
        if "Way Of The Blade" not in dead_class:
            return

        for c in all_combatants:
            if not c.is_alive() or c is dead:
                continue


# ---------- Clash system (reworked) ----------------------------------------
def roll_coins(coin_count: int, actor: Optional[Combatant] = None, opponent: Optional[Combatant] = None, skill: Optional[Dict[str, Any]] = None) -> List[bool]:
        """
        Roll coins and return list of results (True=heads, False=tails).
        Morale affects the probability of getting heads:
        - Morale 0: 10% chance of heads
        - Morale 50: 50% chance of heads (neutral)
        - Morale 100: 90% chance of heads
        """
        heads_probability = 0.5  # Default neutral probability
        if actor:
            # Convert morale (0-100) to probability (0.1-0.9)
            heads_probability = 0.1 + (actor.morale / 100.0) * 0.8


        results = []
        for _ in range(coin_count):
            is_heads = random.random() < heads_probability
            results.append(is_heads)
        return results

def calculate_max_power(skill: Dict[str, Any], coin_wins: int, actor: Optional[Combatant] = None) -> int:
        base_power = int(skill.get("Base-Power", 0))
        coin_power = effective_coin_power(actor, skill)
        coin_count = int(skill.get("Coin-Count", 0))

        if actor and actor.has_status("Fear"):
            base_power -= 4

        if actor and actor.has_status("Paralyse"):
            coin_power = 0
            actor.remove_status("Paralyse", 1)


        if actor and actor.has_status("Clash Power Up"):
            base_power += actor.statuses["Clash Power Up"]["potency"]

        if actor and actor.has_status("Power"):
            base_power += actor.statuses["Power"]["potency"]

        if actor and actor.has_status("Clash Power Down"):
            base_power -= actor.statuses["Clash Power Down"]["potency"]



        max_power = base_power + (coin_wins * coin_power)

        return max(0, max_power)

def resolve_clash(actor_a: Combatant, skill_a: Dict[str, Any], coin_rolls_a: List[bool],
                      actor_b: Combatant, skill_b: Dict[str, Any], coin_rolls_b: List[bool]) -> Tuple[float, float, str]:
        """
        Resolve clash between actor_a vs actor_b (each targeting the other).
        Returns (multiplier_for_a, multiplier_for_b, result_str).

        Rules:
          - Calculate max power for each: Base-Power + (heads_count * Coin-Power)
          - Combatant with higher max power wins
          - Winner: 1.0 multiplier (executes attack at full power)
          - Loser: 0.0 multiplier (does not execute attack)
        """



        coin_wins_a = sum(coin_rolls_a)  # Count heads (True values)
        coin_wins_b = sum(coin_rolls_b)

        power_a = calculate_max_power(skill_a, coin_wins_a, actor_a)
        power_b = calculate_max_power(skill_b, coin_wins_b, actor_b)

        if actor_a.has_status("To Right Wrongs") and skill_b.get("Name") == "The Pyric Offense Captain":
            power_a += 10
        if actor_b.has_status("To Right Wrongs") and skill_a.get("Name") == "The Pyric Offense Captain":
            power_b += 10

        # Counter-type defensive bonus: counter skills are more likely to "win" a clash defensively.
        if skill_a.get("Type", "").lower() == "counter":
            power_a = int(power_a * 1.15)  # +15% effective clash power
        if skill_b.get("Type", "").lower() == "counter":
            power_b = int(power_b * 1.15)

        if power_a > power_b:
            actor_a.change_morale(10)
            actor_b.change_morale(-8)
            if actor_a.has_special_effect("Proving Myself"):
                actor_a.apply_status("Growing Reputation", potency=1, count=0)
            return 1.0, 0.0, "a_wins"
        elif power_b > power_a:
            actor_b.change_morale(10)
            actor_a.change_morale(-8)
            if actor_b.has_special_effect("Proving Myself"):
                actor_b.apply_status("Growing Reputation", potency=1, count=0)
            return 0.0, 1.0, "b_wins"
        else:
            # Exact tie: both execute at full power
            actor_a.change_morale(5)
            actor_b.change_morale(5)
            return 1.0, 1.0, "tie"


    # ---------- Skill output formatter ------------------------------------------
def print_skill_usage(user: Combatant, skill_key: str, target: Combatant, skill: Dict[str, Any],
                      coin_rolls: List[bool], coin_wins: int, damage: int, log: List[str],
                      is_limit_burst: bool = False):
        """
        Print segmented skill usage information: name, rolls, and damage
        """
        coin_display = " ".join(["H" if roll else "T" for roll in coin_rolls]) if coin_rolls else "—"
        base_dmg = int(calc_damage(
            user, target, skill, 0, consume_resources=False,
            is_limit_burst=is_limit_burst,
        ))
        coin_bonus = coin_wins * effective_coin_power(user, skill)
        # Also include element of skill in print

        print("\n┌─ SKILL USAGE ─────────────────────────────────────┐")
        print(f"│ Skill Name: {skill_key:40} │")
        print(f"│ Element:    {skill.get('Element', 'None'):40} │")
        print(f"│ User:       {user.name:40} │")
        print(f"│ Target:     {target.name:40} │")
        print("├─ COIN ROLLS ──────────────────────────────────────┤")
        print(f"│ Rolls:      [{coin_display}] ({coin_wins}/{len(coin_rolls)} heads) {' ' * (22 - len(coin_display))} │")
        print("├─ DAMAGE ──────────────────────────────────────────┤")
        print(f"│ Base Damage: {base_dmg:36} │")
        print(f"│ Coin Bonus:  +{coin_bonus:35} │")
        print(f"│ Final Damage: {damage:35} │")
        print("└───────────────────────────────────────────────────┘")

        msg = f"[SKILL] {user.name} uses {skill_key} on {target.name} | Rolls: {coin_display} | Damage: {damage}"
        log.append(msg)
        # Injured logic
        for c in [user]:
            if c.has_status("Injured"):
                dmg = c.get_status_potency("Injured")
                c.take_damage(dmg)
                print(f"{c.name} suffers {dmg} injury damage")
                c.remove_status("Injured", 1)
                c.trigger_status("Injured", potency=dmg)


# ---------- Attack Weight & Target Selection --------------------------------


def get_attack_targets(skill: Dict[str, Any], user: Combatant, main_target: Combatant, enemies: List[Combatant]) -> List[Combatant]:
    """
    Determine all targets for an attack based on Attack Weight.
    - Attack Weight 1: main target only
    - Attack Weight 2: main target + 1 random other
    - Attack Weight 3: main target + 2 random others, etc.

    Returns list of [main_target, extra_target1, extra_target2, ...]
    """
    attack_weight = int(skill.get("Attack-Weight", 1))
    # Ensure at least 1
    attack_weight = max(1, attack_weight)

    targets = [main_target]

    # For each additional attack weight, select a random extra target
    extra_targets_needed = attack_weight - 1

    # Get available extra targets (alive enemies except main target)
    available_extra = [e for e in enemies if e.is_alive() and e != main_target]

    # Select random extra targets
    if available_extra and extra_targets_needed > 0:
        # Can select up to all available extras
        num_to_select = min(extra_targets_needed, len(available_extra))
        extra_selected = random.sample(available_extra, num_to_select)
        targets.extend(extra_selected)

    return targets

# ---------- Action resolution helpers --------------------------------------
def execute_attack_with_multiplier(user: Combatant, target: Combatant, skill_key_or_dict,
                   allies_and_enemies: Tuple[List[Combatant], List[Combatant]],
                   coin_wins: int, damage_multiplier: float, coin_rolls: List[bool], log: List[str],
                   team_elements: Optional[Dict[str, int]] = None, is_clash: bool = False,
                   is_limit_burst: bool = False):
            """
            Execute the attack portion of a skill using a predetermined coin_wins and applying
            a damage_multiplier to the calculated damage. `team_elements` is the elemental pool
            for the attacker's team and will be granted +1 of the skill's Element when damage > 0.

            Supports multiple targets based on Attack Weight.
            """
            # Handle both skill name (str) and skill dict (for LBs)
            skill_key = ""
            if isinstance(skill_key_or_dict, dict):
                skill = skill_key_or_dict
                skill_key = skill.get("Name", "<LB>")
            else:
                skill_key = skill_key_or_dict
                skill = user.skills.get(skill_key)

            if not skill:
                log.append(f"{user.name} tried to use {skill_key} but doesn't have it.")
                return
            if skill.get("Type", "").lower() not in ("attack", "counter"):
                # Not an attack; do nothing here
                return

            user.record_skill_use(skill_key)

            # Ross specific: gain Dueling potency when attacking a declared duel target
            if user.name == "Ross - Noble Sword Artist" and target and target.has_status("Declared Duel - Ross"):
                user.apply_status("Dueling", potency=1, count=0)

            if user.name == "George" and target and target.has_status("Declared Duel - George"):
                user.apply_status("Dueling", potency=1, count=0)

            # Determine all targets based on Attack Weight
            allies, enemies = allies_and_enemies
            if target is not None and user.raw.get("Class") == "Guillevien":
                for commander in allies:
                    if (commander.has_special_effect("Our Army Of Offense")
                            and commander._last_attack_target is target):
                        commander.apply_status("Motivation", potency=1, count=0)
                        print(f"  ⚔️ {commander.name} gains Motivation from the Guillevien attack on {target.name}.")
                if user.has_special_effect("Our Army Of Offense"):
                    user._last_attack_target = target

            all_targets = get_attack_targets(skill, user, target, enemies)
            main_target = all_targets[0]

            coin_effects = iter_effects(skill.get("Effects", {}).get("On-Coin-Win", []))
            if coin_wins > 0 and any(effect.get("Effect") == "Equal Application" for effect in coin_effects):
                apply_skill_effects(
                    coin_effects,
                    user, main_target, all_targets, skill,
                    allies_and_enemies[0] + allies_and_enemies[1], log,
                    is_limit_burst=is_limit_burst,
                )

            # Calculate damage (base calculation uses main target only)
            if user.has_special_effect("Path Recognition") and main_target.has_status("Burn"):
                user.apply_status("Haste", potency=1, count=1)

            if (user.has_special_effect("Vengeance.")
                    and main_target.has_status("Trusted")
                    and 0 < user.get_status_potency("Justified Bullets") <= 10):
                reload_amount = min(5, 22 - user.get_status_potency("Justified Bullets"))
                if reload_amount > 0:
                    user.apply_status("Justified Bullets", potency=reload_amount, count=0)
                user.apply_status("Enraged", potency=0, count=1)
                msg = f"  🔋 {user.name} reloads {reload_amount} Justified Bullets against Trusted target {main_target.name}."
                log.append(msg)
                print(msg)

            dmg = calc_damage(
                user, main_target, skill, coin_wins,
                is_limit_burst=is_limit_burst,
            )
            if user.has_special_effect("Blind Spot Attack") and not is_clash:
                dmg = int(dmg * 1.3)
            dmg = int(dmg * damage_multiplier)

            # Divide damage evenly among all targets
            dmg_per_target = dmg // len(all_targets)

            # Print skill usage in segmented format
            # Show extra targets if any
            target_display = main_target.name
            if len(all_targets) > 1:
                extra_names = ", ".join([t.name for t in all_targets[1:]])
                target_display += f" + {extra_names}"
            print_skill_usage(
                user, skill_key, main_target, skill, coin_rolls, coin_wins,
                dmg_per_target, log, is_limit_burst=is_limit_burst,
            )
            if len(all_targets) > 1:
                msg = f"    🎯 Multi-target attack! Hitting: {target_display} (Damage per target: {dmg_per_target})"
                print(msg)
                log.append(msg)

            # Record HP before for main target
            target = main_target
            hp_before_main = target.hp

            # Overheat: Lose 10% of max HP on every attack made while having Burn status
            if user.has_special_effect("Overheat") and user.has_status("Burn"):
                hp_loss = int(user.max_hp * 0.1)
                user.take_damage(hp_loss)
                msg = f"  🔥 {user.name} loses {hp_loss} HP from Overheat effect!"
                log.append(msg)
                print(msg)

            # Apply damage to all targets (effects only to main target)
            for target_to_hit in all_targets:
                # record hp before to compute actual damage dealt robustly
                hp_before = target_to_hit.hp

                # Guard handling / damage application
                if target_to_hit.has_status("Guard") or target_to_hit.has_status("Star Barrier"):
                    guard_amount = target_to_hit.get_status_potency("Guard") if target_to_hit.has_status("Guard") else 0
                    guard_amount += target_to_hit.get_status_potency("Star Barrier") if target_to_hit.has_status("Star Barrier") else 0
                    taken = max(0, dmg_per_target - guard_amount)
                    target_to_hit.take_damage(taken)
                    target_to_hit.remove_status("Guard", 1)
                    msg = f"    🛡️  Guard blocked {min(dmg_per_target, guard_amount)} damage | {target_to_hit.name} takes {taken} damage ({target_to_hit.hp}/{target_to_hit.max_hp})"
                    log.append(msg)
                    print(msg)
                else:
                    target_to_hit.take_damage(dmg_per_target)
                    msg = f"    ❤️‍🔥 {target_to_hit.name} takes {dmg_per_target} damage ({target_to_hit.hp}/{target_to_hit.max_hp})"
                    log.append(msg)
                    print(msg)
                if hp_before > 0 and not target_to_hit.is_alive():
                    on_kill(user, target_to_hit, allies_and_enemies[0] + allies_and_enemies[1], log)

            # Compute actual damage dealt using hp from main target
            actual_damage_dealt = max(0, hp_before_main - target.hp)

            if actual_damage_dealt > 0 and team_elements is not None:
                user.gain_elements_for_skill(skill, team_elements)

            if actual_damage_dealt > 0 and user.has_special_effect("Delayed Shock Gauntlets"):
                shock_potency = max(1, actual_damage_dealt // 2)
                target.apply_status("Static Shock", potency=shock_potency, count=1)
                msg = (
                    f"  ⚡ {target.name} gains Static Shock "
                    f"(potency {shock_potency}) from {user.name}'s Delayed Shock Gauntlets."
                )
                log.append(msg)
                print(msg)

            if skill_key == "Final Dance: The Cold Truth":
                for dance_target in all_targets:
                    nostalgia_potency = dance_target.get_status_potency("Clouds Of Nostalgia")
                    if dance_target.has_status("Clouds Of Nostalgia"):
                        dance_target.remove_status("Clouds Of Nostalgia")
                        dance_target.apply_status(
                            "Freezing", potency=5,
                            count=drowsy_status_count(user, "Freezing", 5, is_limit_burst),
                        )
                        dance_target.change_morale(-nostalgia_potency * 2)
                        msg = (f"  ❄️ {dance_target.name} loses Clouds Of Nostalgia, gains "
                               f"Freezing (5, 5), and loses {nostalgia_potency * 2} morale!")
                        log.append(msg)
                        print(msg)

                    memories_potency = dance_target.get_status_potency("Clouds Of Memories")
                    if dance_target.has_status("Clouds Of Memories"):
                        dance_target.remove_status("Clouds Of Memories")
                        dance_target.apply_status(
                            "Freezing", potency=5,
                            count=drowsy_status_count(user, "Freezing", 5, is_limit_burst),
                        )
                        hp_loss = memories_potency * 2
                        dance_target.take_damage(hp_loss)
                        msg = (f"  ❄️ {dance_target.name} loses Clouds Of Memories, gains "
                               f"Freezing (5, 5), and loses {hp_loss} HP!")
                        log.append(msg)
                        print(msg)

            # On-Hit effects (only if damage > 0)
            if actual_damage_dealt > 0:
                if (user._current_surge_active
                        and any(user.has_special_effect(name) for name in CURRENT_SURGE_TURNS)):
                    user.apply_status(
                        "Current", potency=0,
                        count=drowsy_status_count(user, "Current", 2, is_limit_burst),
                    )
                if (target.browse_wares_active
                        and target.has_special_effect("I Beseech You to Browse Our Wares")):
                    target.browse_wares_attackers.add(user)
                if target.has_special_effect("Proving Myself"):
                    user.apply_status("Gaze Of The Commander", potency=1, count=1)
                if user.has_status("An Unbreakable Sheild"):
                    user.apply_status("Guard", potency=10, count=1)
                if (user.has_special_effect("This is just a warm up")
                    and target.has_status("Nerve Chill")
                    and actual_damage_dealt > 0):
                    nerve_chill_count = target.statuses["Nerve Chill"].get("stacks", 0)
                    if nerve_chill_count > 0:
                        burn_potency = 2 * nerve_chill_count
                        target.apply_status("Burn", potency=burn_potency, count=1)
                        target.remove_status("Nerve Chill")
                        msg = (f"  ❄️ {user.name}'s This is just a warm up converts {nerve_chill_count} "
                               f"Nerve Chill into Burn potency {burn_potency}!")
                        log.append(msg)
                        print(msg)

                if (user.has_special_effect("Blazed") and target.has_status("Burn")
                    and not target.has_fireproof_gear()):
                    if target.statuses["Burn"]["stacks"] > 5:
                        burn_dmg = target.statuses["Burn"]["stacks"]
                        target.take_damage(burn_dmg, damage_source="burn")
                        msg = f"  🔥 {target.name} takes early burn damage from Blazed (special effect)!"
                        log.append(msg)
                        print(msg)
                        for retaliator in [
                            c for c in allies_and_enemies[0] + allies_and_enemies[1]
                            if c.has_special_effect("Eternal War") and c.is_alive() and c is not user
                        ]:
                            if retaliator.skills.get("To The Neck"):
                                execute_attack_with_multiplier(
                                    retaliator,
                                    target,
                                    "To The Neck",
                                    allies_and_enemies,
                                    coin_wins=1,
                                    damage_multiplier=1.0,
                                    coin_rolls=[True],
                                    log=log,
                                    team_elements=None,
                                    is_clash=False,
                                    is_limit_burst=is_limit_burst,
                                )
                                msg = f"  ⚔️ {retaliator.name} triggers Eternal War on {target.name}!"
                                log.append(msg)
                                print(msg)

                if (user.has_special_effect("Smouldering Hammer")
                    and not target.has_fireproof_gear()
                    and target.has_status("Burn") and target.has_status("Quaken")):
                    burn_potency = target.get_status_potency("Burn")
                    quaken_stacks = target.statuses["Quaken"]["stacks"]
                    if burn_potency >= 22 and quaken_stacks >= 5:
                        target.remove_status("Burn", 1)
                        target.apply_status("Blazed", potency=9, count=3)
                        target.remove_status("Quaken", 5)
                        msg = f"  🔥 {user.name}'s Smouldering Hammer converts {target.name}'s Quaken into Blazed!"
                        log.append(msg)
                        print(msg)

                if (user.raw.get("Class") == "Pyric" or user.name in {"Macduff", "The 1st Harbinger - Flame Lord Macduff"}) and has_pyric_shield_support(user):
                    target.apply_status("Quaken", potency=1, count=1)
                    msg = f"  🌋 {target.name} gains Quaken from {user.name}'s Pyro Shield!"
                    log.append(msg)
                    print(msg)

                apply_skill_effects(
                    skill.get("Effects", {}).get("On-Hit", []),
                    user, target, all_targets, skill,
                    allies_and_enemies[0] + allies_and_enemies[1], log,
                    is_limit_burst=is_limit_burst,
                )

                if user.speed > target.speed:
                    speed_status = None
                    if user.has_special_effect("Bat Strike"):
                        speed_status = "Winded"
                    elif user.has_special_effect("Knife Strike"):
                        speed_status = "Injured"
                    if speed_status:
                        target.apply_status(speed_status, potency=1, count=1)
                        msg = f"  ⚡ {user.name}'s {speed_status} strike inflicts {speed_status} (1, 1) on {target.name}."
                        log.append(msg)
                        print(msg)

            # On-Tie effects (if damage > 0 and clash was a tie)
            if actual_damage_dealt > 0 and damage_multiplier == 1.0:
                apply_skill_effects(
                    skill.get("Effects", {}).get("On-Tie", []),
                    user, target, all_targets, skill,
                    allies_and_enemies[0] + allies_and_enemies[1], log,
                    is_limit_burst=is_limit_burst,
                )

            # remove Damage Boost usage
            if user.has_status("Damage Boost"):
                user.remove_status("Damage Boost", 1)

def pay_and_execute(user: Combatant,
            target: Combatant,
            skill_obj_or_name,
            allies: List[Combatant],
            enemies: List[Combatant],
            coin_wins: int,
            damage_multiplier: float,
            coin_rolls: List[bool],
            log: List[str],
            team_elements: Optional[Dict[str, int]],
            is_limit_burst: bool = False,
            is_clash: bool = False):
        """
        Pay costs (if LB), handle morale/burst usage/overuse, then execute the attack.
        - skill_obj_or_name may be a skill name (str) or a skill dict (for LB).
        - team_elements is the elemental pool for the user's team (must be passed).
        """
        # Resolve skill dict vs name
        skill_obj = skill_obj_or_name if isinstance(skill_obj_or_name, dict) else None
        skill_name = skill_obj_or_name if isinstance(skill_obj_or_name, str) else skill_obj_or_name.get("Name", "<LB>")

        # Default LB cost/morale (empty for normal skills)
        lb_cost: Dict[str, int] = {}
        lb_morale = 0
        if is_limit_burst and isinstance(skill_obj, dict):
            lb_cost = skill_obj.get("Cost", {}) or {}
            lb_morale = int(skill_obj.get("Morale-Cost", 0))

        # Affordability: only relevant for LBs (lb_cost empty for normal skills)
        if team_elements is None:
            log.append(f"  ⚠️ Execution error: missing team element pool for {user.name}.")
            print(f"  ⚠️ Execution error: missing team element pool for {user.name}.")
            return

        if user.morale < lb_morale:
            log.append(f"  ⚠️ {user.name} lacks Morale ({user.morale}/{lb_morale}) for {skill_name}.")
            print(f"  ⚠️ {user.name} lacks Morale ({user.morale}/{lb_morale}) for {skill_name}.")
            return

        if not user.can_afford(lb_cost, team_elements):
            log.append(f"  ⚠️ {user.name} lacks elemental cost for {skill_name}.")
            print(f"  ⚠️ {user.name} lacks elemental cost for {skill_name}.")
            return

        # Pay LB cost & morale (no-op for normal skills because lb_cost empty & lb_morale 0)
        if lb_cost:
            user.pay_cost(lb_cost, team_elements)
        if lb_morale:
            user.morale -= lb_morale

        # If this is an LB, increment usage and handle overuse now
        if is_limit_burst:
            user.burst_usage_count += 1
            overuse = skill_obj.get("Overuse-Effect")
            if user.burst_usage_count > 3 and overuse == "Kill":
                # kill user and target, do not execute the LB effects normally
                user.take_damage(user.max_hp)
                if target:
                    target.take_damage(target.hp)
                    log.append(f"  💀 {user.name} OVERUSED {skill_name} and was consumed!")
                    print(f"  💀 {user.name} OVERUSED {skill_name} and was consumed!")
                    return
            if user.burst_usage_count > 3 and overuse == "Stagger":
                user.trigger_stagger(1)
                log.append(f"  ⚡ {user.name} is staggered from overusing {skill_name}!")
                print(f"  ⚡ {user.name} is staggered from overusing {skill_name}!")

        # Execute: pass skill dict for LB or name for ordinary skills
        execute_attack_with_multiplier(
            user, target, skill_obj if is_limit_burst else skill_name,
            (allies, enemies), coin_wins, damage_multiplier, coin_rolls, log,
            team_elements, is_clash=is_clash, is_limit_burst=is_limit_burst,
        )

# ---------- AI / Player interaction (unchanged helpers) --------------------
def choose_action(actor: Combatant, allies: List[Combatant], enemies: List[Combatant], current_targets: Dict[Combatant, Combatant], history: Dict[Combatant, List[str]], available_skill_names: List[str], team_elements: Dict[str, int]) -> Tuple[str, Combatant]:
    alive_enemies = [e for e in enemies if e.is_alive()]
    if not alive_enemies:
        return ("", actor)

    # Check if limit burst is available
    lb_name = None
    if actor.selected_limit_burst and actor.selected_limit_burst.get("Name") in available_skill_names:
        lb_name = actor.selected_limit_burst.get("Name")

    available_skill_names = filter_dancing_skills(actor, available_skill_names)

    # Filter actor's skills based on random selection (exclude limit burst from normal skill evaluation)
    filtered_skills = {name: actor.skills[name] for name in available_skill_names if name in actor.skills}

    # Priority 1: Use Limit Burst if conditions are ideal (high morale, have resources, low usage count)
    if lb_name and actor.burst_usage_count <= 5:
        lb = actor.selected_limit_burst
        can_afford = actor.morale >= lb.get("Morale-Cost", 0)
        for elem, amt in lb.get("Cost", {}).items():
            if team_elements.get(elem, 0) < amt:
                can_afford = False
                break
        if can_afford and actor.morale >= 50:  # Use LB when morale is good
            target = random.choice(alive_enemies)
            return (lb_name, target)

    # 2. Support Logic (High priority)
    for name, sk in filtered_skills.items():
        if sk.get("Type") == "Support" and sk.get("Effects", {}).get("On-Use"):
            injured = [a for a in allies if a.hp < a.max_hp * 0.7 and a.is_alive() and a is not actor]
            if injured:
                target = min(injured, key=lambda x: x.hp)
                return (name, target)


    # 3. Strategic "Combo" Scoring
    scored_actions = []

    # Identify which enemies are already being targeted to encourage distribution
    targeted_counts = {}
    for t in current_targets.values():
        targeted_counts[t] = targeted_counts.get(t, 0) + 1

    ross_has_duel_target = (
        actor.name == "Ross - Noble Sword Artist"
        and any(enemy.has_status("Declared Duel - Ross") for enemy in alive_enemies)
    )

    # Get recent skill history for this actor to penalize repetition
    recent_skills = history.get(actor, [])[-2:] # Look at last 2 turns

    for name, sk in filtered_skills.items():
        if sk.get("Type", "").lower() not in ("attack", "counter"):
            continue

        base_score = sk.get("Base-Power", 0) + sk.get("Coin-Power", 0)

        # Repetition Penalty: Discourage spamming the same skill
        repetition_count = recent_skills.count(name)
        if repetition_count > 0:
            base_score -= 10


        for enemy in alive_enemies:
                current_score = base_score

                # Distribution bonus: Encourage targeting someone not yet targeted this turn
                if enemy not in targeted_counts or targeted_counts[enemy] == 0:
                    current_score += 15

                # Ross prefers duel targets, or The Monster when no duel target exists
                if actor.name == "Ross - Noble Sword Artist" and (
                    enemy.has_status("Declared Duel - Ross")
                    or (not ross_has_duel_target and enemy.name == "The Monster")
                ):
                    current_score += 30

                # Malcolm prioritizes Macduff targets
                if actor.name == "Malcolm - Noble Sword Artist" and enemy.name == "Macduff":
                    current_score += 25

                scored_actions.append((name, enemy, current_score))
    if scored_actions:
        # Pick the best scoring action (skill + target combo)
        best_name, best_target, _ = max(scored_actions, key=lambda x: x[2])
        # Gain element on skill use here
        element = actor.skills[best_name].get("Element")
        if element:
            team_elements[element] = team_elements.get(element, 0) + 1
        # If the skill used is an enlightenment moveset skill, remove Enlightenment from the user
        return (best_name, best_target)

    # Fallback to random among available
    if available_skill_names:
        skill_name = random.choice(available_skill_names)
        # Check if it's a limit burst or regular skill
        if skill_name == lb_name:
            # Limit burst targets enemies
            return (skill_name, random.choice(alive_enemies))
        # Defense/Support/Evade target allies
        if filtered_skills.get(skill_name, {}).get("Type", "").lower() in ("support", "defense", "evade"):
            return (skill_name, random.choice([a for a in allies if a.is_alive()]))
        return (skill_name, random.choice(alive_enemies))
    return ("", actor)



def get_actual_skill(actor: Combatant, skill_name: str, target: Optional[Combatant] = None) -> str:
    if actor.name == "George" and actor.has_status("Duel Preping"):
        actor.remove_status("Duel Preping")
        return "Singling Target"
    if (
        actor.has_special_effect("Pyric Fury")
        and skill_name in ("Expelling Flame", "Furious Slash")
        and target is not None
        and target.get_status_potency("Burn") >= 25
        and target.statuses.get("Burn", {}).get("stacks", 0) >= 15
    ):
        return "The Furious Slash Of The 1st Harbinger"
    return skill_name


def format_status_effects(combatant: Combatant) -> str:
        if not combatant.statuses:
            return "None"
        return ", ".join(f"[{k}:{v['stacks']}]" for k, v in combatant.statuses.items())

def print_elemental_pool(elements: Dict[str, int]):
    elems = [f"{k}:{v}" for k, v in elements.items() if v > 0]
    if elems:
        print("Team Elemental Pool:", ", ".join(elems))
    else:
        print("Team Elemental Pool: (empty)")

def get_player_action(actor: Combatant, allies: List[Combatant], enemies: List[Combatant], available_skill_names: List[str], team_elements: Dict[str, int]) -> Tuple[str, Combatant]:
        alive_enemies = [e for e in enemies if e.is_alive()]
        if not alive_enemies:
            return ("", actor)

        available_skill_names = filter_dancing_skills(actor, available_skill_names)

        while True:
            status_display = format_status_effects(actor)
            print(f"\n👤 {actor.name}'s turn (HP: {actor.hp}/{actor.max_hp}) | Effects: {status_display}")
            print_elemental_pool(team_elements)

            print("\n📋 Available Actions:")
            # Filter actor's skills based on random selection and special status conditions
            skill_items = []
            for name in available_skill_names:
                if name not in actor.skills:
                    continue
                if actor.name == "Ross - Noble Sword Artist" and actor.has_status("Dueling") and name == "Singling Target":
                    continue
                data = actor.skills[name]

                display_name = name
                actual_name = name

                skill_items.append((display_name, data, actual_name, False))

            # Insert limit burst at fixed index 2 (always usable if conditions met)
            if actor.selected_limit_burst:
                lb = actor.selected_limit_burst
                can_afford = actor.morale >= lb.get("Morale-Cost", 0)
                for elem, amt in lb.get("Cost", {}).items():
                    if team_elements.get(elem, 0) < amt:
                        can_afford = False
                        break

                lb_prefix = "🔥" if can_afford else "🔒"
                lb_entry = (f"{lb_prefix} LIMBURST: {lb['Name']}", lb, lb['Name'], True)
                # Insert at index 2, shifting remaining skills after it
                if len(skill_items) < 2:
                    skill_items.append(lb_entry)
                else:
                    skill_items.insert(2, lb_entry)

            for i, (disp_name, data, _, is_lb) in enumerate(skill_items):
                if is_lb:
                    skill_type = data.get("Type", "Unknown")
                    skill_element = data.get("Element", "None")
                    print(f"  [{i}] {disp_name:30} ({skill_type} | Element: {skill_element} | COST: {data.get('Cost')}, Morale: {data.get('Morale-Cost')})")
                else:
                    skill_type = data.get("Type", "Unknown")
                    skill_element = data.get("Element", "None")
                    print(f"  [{i}] {disp_name:30} ({skill_type} | Element: {skill_element})")

            try:
                choice = input("\nSelect action (index): ")
                skill_idx = int(choice)
                if not (0 <= skill_idx < len(skill_items)):
                    print("❌ Invalid index. Try again.")
                    continue

                # Gain elements for the skill, 1 element per use
                skill_data = skill_items[skill_idx][1]

                print("Gained 1 element from skill use.")

                disp_name, skill_data, actual_name, is_lb = skill_items[skill_idx]

                if is_lb:
                    # The Code never makes it past that point before whenit came lb and just voids your action for the tun. re-do
                    if actor.morale < skill_data.get("Morale-Cost", 0):
                        print("❌ Not enough morale for this Limit Burst!")
                        continue

                    if not actor.can_afford(skill_data.get("Cost", {}), team_elements):
                        print("❌ Not enough elemental resources for this Limit Burst!")
                        continue


                    # do not increment burst_usage_count at selection — it is applied at execution
                    if actor.burst_usage_count > 3:
                        overuse = skill_data.get("Overuse-Effect", "Stagger")
                        if overuse == "Kill":
                            print(f"💀 {actor.name} OVERUSED LIMBURST! Mutual destruction imminent!")
                        else:
                            print(f"⚡ {actor.name} OVERUSED LIMBURST! Will be staggered upon use!")

                skill_type = skill_data.get("Type", "").lower()

                # Support/Defense/Evade skills target allies; Attack/Counter skills target enemies
                if skill_type in ("support", "defense", "evade"):
                    target_list = [a for a in allies if a.is_alive()]
                    target_name = "allies"
                else:
                    target_list = [e for e in enemies if e.is_alive()]
                    target_name = "enemies"

                if not target_list:
                    print(f"❌ No available {target_name} to target.")
                    continue

                print(f"\n🎯 Available {target_name.title()}:")
                for i, target_cand in enumerate(target_list):
                    status_str = format_status_effects(target_cand) if target_cand.statuses else "—"
                    print(f"  [{i}] {target_cand.name:20} (HP: {target_cand.hp:3}/{target_cand.max_hp:<3}) | {status_str}")

                target_idx = int(input("Select target (index): "))

                if 0 <= target_idx < len(target_list):
                    target = target_list[target_idx]
                    # Gain elemental resource here
                    # Get the element from the skill
                    element = skill_data.get("Element")
                    if element:
                        team_elements[element] = team_elements.get(element, 0) + 1
                        print(f"Gained 1 {element} element from skill use.")
                    return (actual_name, target) 
                else:
                    print("❌ Invalid target index. Try again.")
            except ValueError:
                print("❌ Invalid input. Please enter numbers.")

    # ---------- End-of-turn effects & display ----------------------------------
def get_simple_sparing_result(team_a: List[Combatant], team_b: List[Combatant]) -> Optional[str]:
        for combatant in team_b:
            if combatant.has_special_effect("Simple Sparing") and combatant.hp < 600:
                return "TEAM A WINS!"
        for combatant in team_a:
            if combatant.has_special_effect("Simple Sparing") and combatant.hp < 600:
                return "TEAM B WINS!"
        return None

def apply_end_of_turn_effects(team_a: List[Combatant], team_b: List[Combatant], log: List[str]):
        forced_result = None
        for c in team_a + team_b:
            can_self_destruct_at_zero_hp = (
                c.name == "Anti-Theft Android"
                and c.hp <= 0
                and c.has_special_effect("Steel Skin")
            )
            if not c.is_alive() and not can_self_destruct_at_zero_hp:
                continue

            if c.has_status("Static Shock"):
                shock_damage = c.get_status_potency("Static Shock")
                c.take_damage(shock_damage)
                c.remove_status("Static Shock")
                msg = f"  ⚡ {c.name} takes {shock_damage} Static Shock damage; the status wears off."
                log.append(msg)
                print(msg)
                if not c.is_alive() and not can_self_destruct_at_zero_hp:
                    continue

            if c.has_status("Injured"):
                if c.has_status("Wash Away"):
                    c.remove_status("Wash Away", 1)
                    dmg = c.get_status_potency("Injured")
                    c.take_damage(dmg)
                    c.remove_status("Injured", 1)
                    msg = (f"  🩸 {c.name}'s Wash Away consumes 1 Injured and "
                           f"1 Wash Away; they suffer {dmg} injury damage.")
                    log.append(msg)
                    print(msg)
                    c.trigger_status("Injured", potency=dmg)

            if (c.has_special_effect("Steel Skin")
                    and c.get_status_potency("Lethal Energy") >= 3
                    and c.raw.get("Self Destruction")):
                targets = [unit for unit in (team_b if c in team_a else team_a) if unit.is_alive()]
                if targets:
                    msg = f"  💣 {c.name}'s Steel Skin reaches 3 Lethal Energy and uses Self Destruction!"
                    log.append(msg)
                    print(msg)
                    self_destruction = dict(c.raw["Self Destruction"])
                    self_destruction["Name"] = "Self Destruction"
                    execute_attack_with_multiplier(
                        c, targets[0], self_destruction,
                        (team_a if c in team_a else team_b, team_b if c in team_a else team_a),
                        0, 1.0, [], log, None,
                    )
                    if not c.is_alive():
                        continue

            if c.has_status("Seriousness"):
                c.statuses["Seriousness"]["potency"] -= 1
                log.append(f"  🎯 {c.name}'s Seriousness decreases to {c.statuses['Seriousness']['potency']}.")
                if c.statuses["Seriousness"]["potency"] <= 0:
                    c.remove_status("Seriousness")
                    if c.has_special_effect("Enough Games"):
                        if c in team_a:
                            forced_result = "TEAM B WINS!"
                            losing_team = team_a
                        else:
                            forced_result = "TEAM A WINS!"
                            losing_team = team_b
                        log.append(f"  🎯 {c.name}'s Seriousness has expired; {forced_result}")
                        for member in losing_team:
                            if member.is_alive():
                                member.hp = 0
                                member.alive = False
                        return forced_result

            if c.has_status("Burn") or c.has_status("Blazed"):
                had_burn = c.has_status("Burn")
                dmg = c.get_status_potency("Burn")
                dmg += c.get_status_potency("Blazed") if c.has_status("Blazed") else 0
                burn_potency = c.get_status_potency("Burn")
                # Fireproof Gear prevents both Burn and Blazed damage.
                if c.has_status("Scorched"):
                    dmg = int(dmg * 1.5)
                if c.has_fireproof_gear():
                    print(f"  🔥 {c.name}'s Fireproof Gear negates {dmg} burn damage!")
                else:
                    c.take_damage(dmg, damage_source="burn")
                    print(f"{c.name} suffers {dmg} burn damage")

                c.remove_status("Burn", 1)
                if had_burn:
                    c.trigger_status("Burn", potency=burn_potency)
                # Apply Quaken effects if Blazed is active
                if c.has_status("Blazed"):
                    c.remove_status("Blazed", 1)
                    c.devastate(log)

            if c.has_special_effect("Iron Skin"):
                if c.has_status("Quantus"):
                    if c.statuses["Quantus"]["stacks"] >= 20:
                        c.remove_status("Quantus")
                        c.apply_status("Lethal Charge", potency=0, count=1)
                        log.append(f"  🛡️ {c.name}'s Quantus reaches 20 and converts to Lethal Charge!")
                        print(f"  🛡️ {c.name}'s Quantus reaches 20 and converts to Lethal Charge!")

        for c in team_a + team_b:
            if c.has_status("Nullification"):
                c.remove_status("Nullification")

        return forced_result

def display_battle_state(team_a: List[Combatant], team_b: List[Combatant], team_a_elements: Dict[str, int], team_b_elements: Dict[str, int], team_a_speeds: Optional[Dict[Combatant, List[int]]] = None, team_b_speeds: Optional[Dict[Combatant, List[int]]] = None):
        def get_morale_bar(morale: int) -> str:
            filled = morale // 5
            return "▼" * filled + "▽" * (20 - filled)

        print("\n" + "="*70)
        print("TEAM A")
        team_a_elem_str = ", ".join([f"{k}:{v}" for k, v in team_a_elements.items() if v > 0])
        print(f"Elements: {team_a_elem_str if team_a_elem_str else '(empty)'}")
        print("="*70)
        for i, c in enumerate(team_a):
            hp_bar = "█" * (c.hp // max(1, c.max_hp // 20)) + "░" * (20 - (c.hp // max(1, c.max_hp // 20)))
            morale_bar = get_morale_bar(c.morale)
            status_str = ", ".join(f"{k}({v['potency']})({v['stacks']})" for k, v in c.statuses.items()) if c.statuses else "—"
            alive_str = "ALIVE" if c.is_alive() else "DEAD"

            speed_info = f"Speed: {c.speed_range}"
            if team_a_speeds and c in team_a_speeds:
                speed_info = f"Speed: {team_a_speeds[c]}"

            print(f"[{i}] {c.name:20} | Morale: [{morale_bar}] {c.morale:3}/100 | {speed_info}")
            print(f"    HP: [{hp_bar}] {c.hp:3}/{c.max_hp:<3} {alive_str:5} | {status_str}")

        print("\n" + "="*70)
        print("TEAM B")
        team_b_elem_str = ", ".join([f"{k}:{v}" for k, v in team_b_elements.items() if v > 0])
        print(f"Elements: {team_b_elem_str if team_b_elem_str else '(empty)'}")
        print("="*70)
        for i, c in enumerate(team_b):
            hp_bar = "█" * (c.hp // max(1, c.max_hp // 20)) + "░" * (20 - (c.hp // max(1, c.max_hp // 20)))
            morale_bar = get_morale_bar(c.morale)
            status_str = ", ".join(f"{k}({v['potency']})({v['stacks']})" for k, v in c.statuses.items()) if c.statuses else "—"
            alive_str = "ALIVE" if c.is_alive() else "DEAD"

            speed_info = f"Speed: {c.speed_range}"
            if team_b_speeds and c in team_b_speeds:
                speed_info = f"Speed: {team_b_speeds[c]}"

            print(f"[{i}] {c.name:20} | Morale: [{morale_bar}] {c.morale:3}/100 | {speed_info}")
            print(f"    HP: [{hp_bar}] {c.hp:3}/{c.max_hp:<3} {alive_str:5} | {status_str}")
        print("="*70 + "\n")

# ---------- Team selection --------------------------------------------------
def load_json_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def select_teams(all_combatants: Dict[str, Dict[str, Any]]) -> Tuple[List[Combatant], List[Combatant]]:
    name_to_obj = {k: Combatant(raw, k) for k, raw in all_combatants.items()}
    combatant_list = list(name_to_obj.items())

    # Load Limit Bursts
    lb_data = {}
    try:
        lb_data = load_json_file(LIMBURST_FILE).get("LimitBursts", {})
    except Exception as e:
        print(f"Warning: Could not load {LIMBURST_FILE}: {e}")

    print("\n" + "="*60)
    print("TEAM SELECTION - Choose 5 combatants for each team")
    print("="*60)
    for i, (key, combatant) in enumerate(combatant_list):
        c_class = combatant.raw.get("Class", "Unknown")
        print(f"[{i}] {combatant.name} ({c_class}) [ID: {key}]")

    def select_team(team_name: str) -> List[Combatant]:
        selected_combatants = []
        while len(selected_combatants) < MAX_TEAM_SIZE:
            try:
                print(f"\n{team_name} - Remaining slots: {MAX_TEAM_SIZE - len(selected_combatants)}")
                idx_input = input(f"Enter combatant index (0-{len(combatant_list)-1}): ").strip()
                if not idx_input: 
                    print("Must select a combatant.")
                    continue
                idx = int(idx_input)
                if not (0 <= idx < len(combatant_list)):
                    print("Invalid index.")
                    continue


                base_c = deepcopy(combatant_list[idx][1]) 
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


                selected_combatants.append(base_c)
                Names = [c.name for c in selected_combatants]
                if Names.count(base_c.name) > 1:
                    print(f"⚠️  Duplicate combatant {base_c.name} selected. Please restart selection process over again.")
                    selected_combatants = []
            except ValueError:
                print("Invalid input.")
        return selected_combatants

    team_a = select_team("TEAM A")
    team_b = select_team("TEAM B")
    for c in team_a:
        c.team_members = team_a
    for c in team_b:
        c.team_members = team_b
    return team_a, team_b

# ---------- Interactive battle run with clash handling -----------------------
def run_interactive_battle(team_a: List[Combatant], team_b: List[Combatant], max_turns: int = 200,
                           enemy_replacement_queue: Optional[List[Combatant]] = None,
                           drowsy_kyla: bool = False):
    transcript = []
    transcript.append(f"\n{'='*60}")
    transcript.append(f"BATTLE START: {', '.join(c.name for c in team_a)} vs {', '.join(c.name for c in team_b)}")
    transcript.append(f"{'='*60}\n")

    team_a_elements = {elem: 0 for elem in ["Fire", "Water", "Earth", "Charm", "Ice", "Wind", "Void"]}
    team_b_elements = {elem: 0 for elem in ["Fire", "Water", "Earth", "Charm", "Ice", "Wind", "Void"]}

    for c in team_a:
        c.team_elements = team_a_elements
    for c in team_b:
        c.team_elements = team_b_elements

    skill_history: Dict[Combatant, List[str]] = {}

    # Skill slot distribution - separate round-robin for each team
    team_a_slot_index = 0  # Tracks which team A unit gets the next skill slot
    team_b_slot_index = 0  # Tracks which team B unit gets the next skill slot

    # Track last damage dealt to targets for Revert healing
    last_damage_taken: Dict[Combatant, int] = {}

    for c in team_a + team_b:
        c.prepare_for_battle()
        if drowsy_kyla and c.name == "Kyla":
            c.apply_status("Drowsy", potency=1, count=1)
            msg = f"  😴 {c.name} gains Drowsy for this battle."
            transcript.append(msg)
            print(msg)
        if c.name == "Lenuff - Pyric Offense Captain":
            c.skill_slots = 3
        if c.name == "Lenuff - The Flare":
            c.skill_slots = 3
        if c.name == "Tybalt - The Frost":
            c.skill_slots = 3
        if c.name == "Macbeth - The 1st Harbinger Of Flames":
            c.skill_slots = 7
        if c.name == "Ross - Noble Sword Artist":
            c.skill_slots = 3
        if c.name == "Malcolm - Noble Sword Artist":
            c.skill_slots = 2
        if c.name == "Banquo - The Ghost Long Forgotten":
            c.skill_slots = 4
        if c.name == "Pyro Lord":
            c.skill_slots = 6
        if c.name == "Vin - The Diamond Commander":
            c.skill_slots = 7
        if c.name == "Jack - Wounding Commander":
            c.skill_slots = 5
        if c.has_special_effect("Blitzing Speed"):
            c.skill_slots = 2

        if c.has_special_effect("Phantom Parrade"):
            allies = team_a if c in team_a else team_b
            for ally in allies:
                if ally is not c and ally.raw.get("Class") == "Spectre":
                    ally.apply_status("Parrading", potency=1, count=1)
                    msg = f"  👻 {ally.name} gains Parrading from {c.name}!"
                    transcript.append(msg)
                    print(msg)

        if c.has_special_effect("Legendary Weapon: Dual Diamond Cutters"):
            allies = team_a if c in team_a else team_b
            for ally in allies:
                if ally.raw.get("Class") == "Coal Army":
                    ally.apply_status("Current", potency=10, count=5)
                    msg = f"  🎯 {ally.name} gains Current from {c.name}'s Dual Diamond Cutters!"
                    transcript.append(msg)
                    print(msg)

        if c.has_special_effect("Enough Games") and c.hp < 2900 and not c.has_status("Seriousness"):
            c.remove_status("Clash Power Down", 1)
            c.apply_status("Seriousness", potency=3, count=1)
            msg = f"  🎯 {c.name} enters Seriousness and loses Clash Power Down!"
            transcript.append(msg)
            print(msg)

        if c.name == "Lenuff - Pyric Offense Captain":
            enemy_team = team_b if c in team_a else team_a
            alive_enemies = [e for e in enemy_team if e.is_alive()]
            if alive_enemies:
                to_mark = next((e for e in alive_enemies if e.key == "The 1st Harbinger - Flame Lord Macduff"), None)
                if to_mark:
                    to_mark.apply_status("Vivid Remembrance", potency=1, count=1)
                else:
                    to_mark = next((e for e in alive_enemies if e.name == "Macduff"), None)
                    if to_mark:
                        to_mark.apply_status("Faint Rememberance", potency=1, count=1)
        
        if c.name == "Lenuff - The Flare":
            enemy_team = team_b if c in team_a else team_a
            alive_enemies = [e for e in enemy_team if e.is_alive()]
            if alive_enemies:
                to_mark = next((e for e in alive_enemies if e.name == "Macduff"), None)
                if to_mark:
                    to_mark.apply_status("To Right Wrongs", potency=1, count=1)
        
        if c.name == "Tybalt - The Frost":
            enemy_team = team_b if c in team_a else team_a
            alive_enemies = [e for e in enemy_team if e.is_alive()]
            if alive_enemies:
                to_mark = next((e for e in alive_enemies if e.name == "Romeo"), None)
                if to_mark:
                    to_mark.apply_status("Volatile Rage", potency=1, count=1)

        if c.name == "Macbeth - The 1st Harbinger Of Flames":
             enemy_team = team_b if c in team_a else team_a
             alive_enemies = [e for e in enemy_team if e.is_alive()]
             if alive_enemies:
                to_mark = next((e for e in alive_enemies if e.key == "The 1st Harbinger - Flame Lord Macduff"), None)
                if to_mark:
                    to_mark.apply_status("Overruling", potency=1, count=1)
                else:
                    to_mark = next((e for e in alive_enemies if e.name == "Macduff"), None)
                    if to_mark:
                        to_mark.apply_status("Re-awoken Vengence", potency=1, count=1)
                    else:
                        c.apply_status("Clash Power Down", potency=20, count=1)

    for presence_user, opposing_team in (
        [(c, team_b if c in team_a else team_a) for c in team_a + team_b
         if c.has_special_effect("Masterly Presence")]
    ):
        for opponent in opposing_team:
            if (not opponent.has_status("Fear")
                    and random.random() < MASTERLY_PRESENCE_FEAR_CHANCE):
                opponent.apply_status("Fear", potency=1, count=1)
                msg = f"  😨 {opponent.name} gains Fear from {presence_user.name}'s Fear Gas!"
                transcript.append(msg)
                print(msg)

    turn_no = 1
    result = None
    # Bullets initialization
    for actor in team_a + team_b:
        if actor.name == "Sherlock" and turn_no == 1 and actor.raw.get("Class") == "Havenus Elite":
            actor.apply_status("Bullets", potency=12, count=1)

    for actor in team_a + team_b:
        if not actor.has_special_effect("Vengeance."):
            continue
        opposing_team = team_b if actor in team_a else team_a
        candidates = [unit for unit in opposing_team if unit.is_alive()]
        if candidates:
            trusted = random.choice(candidates)
            trusted.apply_status("Trusted", potency=1, count=1)
            actor.apply_status("Enraged", potency=0, count=10)
            msg = f"  🎯 {actor.name} marks {trusted.name} as Trusted and gains 10 Enraged."
            transcript.append(msg)
            print(msg)


    enemy_replacement_queue = enemy_replacement_queue or []
    while (result is None
           and any(c.is_alive() for c in team_a)
           and (any(c.is_alive() for c in team_b) or enemy_replacement_queue)):
        for c in team_a + team_b:
            if c.has_special_effect("I Beseech You to Browse Our Wares"):
                c.browse_wares_active = False
                c.browse_wares_skill = None
                c.browse_wares_attackers.clear()
                c.speed_bonus = 0

        if turn_no % 5 == 0:
            for c in team_a + team_b:
                if c.is_alive() and c.start_browse_wares():
                    msg = f"  🛍️ {c.name} opens the shop for this turn: three wares are available."
                    transcript.append(msg)
                    print(msg)

        for index, enemy in enumerate(team_b):
            if not enemy.is_alive() and enemy_replacement_queue:
                replacement = enemy_replacement_queue.pop(0)
                replacement.prepare_for_battle()
                team_b[index] = replacement
                print(f"  Reinforcements: {replacement.name} enters the battle.")

        # 1. Roll speeds for all combatants
        for c in team_a + team_b:
            if c.is_alive():
                c.roll_my_speed()
                c.speed += c.speed_bonus
                # Apply Haste/Bind modifiers
                if c.has_status("Haste"):
                    c.speed += c.get_status_potency("Haste")
                if c.has_status("Bind"):
                    c.speed -= c.get_status_potency("Bind")


        display_battle_state(team_a, team_b, team_a_elements, team_b_elements)
        print(f"\n{'='*60} TURN {turn_no} {'='*60}")

        for c in team_a + team_b:
            
            # Re-Awoken Vengence:
            # If this unit has the status 'Re-awoken Vengence' and is the last unit left on their team, gain Clash Power Up (10, 50)
            if c.is_alive() and c.has_status("Re-awoken Vengence"):
                team = team_a if c in team_a else team_b
                alive_teammates = [ally for ally in team if ally.is_alive()]
                if len(alive_teammates) == 1 and alive_teammates[0] is c:
                    if not c.has_status("Clash Power Up"):
                        c.apply_status("Clash Power Up", potency=10, count=50)
                        msg = f"  🎯 {c.name} has gained Clash Power Up from Re-awoken Vengence!"
                        transcript.append(msg)
                        print(msg)

            # If this unit has the status 'Overulling' and is the last unit left on their team, gain Clash Power Up (10, 50)
            if c.is_alive() and c.has_status("Overruling"):
                team = team_a if c in team_a else team_b
                alive_teammates = [ally for ally in team if ally.is_alive()]
                if len(alive_teammates) == 1 and alive_teammates[0] is c:
                    if not c.has_status("Clash Power Up"):
                        c.apply_status("Clash Power Up", potency=10, count=50)
                        msg = f"  🎯 {c.name} aims to finish what they started!"
                        transcript.append(msg)
                        print(msg)

            
        for c in team_a + team_b:
            if c.is_alive() and c.has_status("Current"):
                c.remove_status("Current", 1)

            if c.is_alive() and c.has_status("Haste"):
                c.remove_status("Haste", 1)

            if c.is_alive() and c.has_status("Power"):
                c.remove_status("Power", 1)

            if c.is_alive() and c.has_status("Quaken"):
                c.remove_status("Quaken", 1)

            if c.has_status("Protection (Next Turn)"):
                c.remove_status("Protection (Next Turn)", 1)
                c.apply_status("Protection", potency=1, count=1)

            if c.is_alive() and c.has_status("Bind"):
                c.remove_status("Bind", 1)

            if c.is_alive() and c.has_status("Slash Fragility"):
                c.remove_status("Slash Fragility", 1)

            if c.is_alive() and c.has_status("Pierce Fragility"):
                c.remove_status("Pierce Fragility", 1)

            if c.is_alive() and c.has_status("Wind Damage Up"):
                c.remove_status("Wind Damage Up")

            if c.is_alive() and c.has_status("Slash Damage Up"):
                c.remove_status("Slash Damage Up")

            if c.is_alive() and c.has_status("Charm Damage Up"):
                c.remove_status("Charm Damage Up")

            if c.has_status("Slash Fragility (Next Turn)"):
                c.remove_status("Slash Fragility (Next Turn)", 1)
                c.apply_status("Slash Fragility", potency=1, count=1)

            if c.has_status("3 Slash Fragility (Next Turn)"):
                c.remove_status("3 Slash Fragility (Next Turn)", 1)
                c.apply_status("Slash Fragility", potency=1, count=3)

            if c.has_status("Pierce Fragility (Next Turn)"):
                c.remove_status("Pierce Fragility (Next Turn)", 1)
                c.apply_status("Pierce Fragility", potency=1, count=1)

            if c.has_special_effect("Path Recognition"):
                c.apply_status("Haste", potency=1, count=1)

            if c.has_status("Fragility"):
                c.remove_status("Fragility")

            if c.has_status("Protection"):
                c.remove_status("Protection")

            if c.has_status("Fragility(2, 2) (Next Turn)"):
                c.remove_status("Fragility(2, 2) (Next Turn)", 1)
                c.apply_status("Fragility", potency=2, count=2)

        for c in team_a + team_b:
            if c.is_alive():
                c.apply_turn_start_special_effects(
                    team_a if c in team_a else team_b,
                    team_a + team_b,
                    turn_no,
                )

        for c in team_a + team_b:
            if c.has_status("Charms of Elements"):
                element_pool = team_a_elements if c in team_a else team_b_elements
                for element in element_pool:
                    element_pool[element] += 2
                c.remove_status("Charms of Elements")

        for c in team_b:
            forced_sequences = getattr(c, "forced_skill_sequences", None) or {}
            if not c.is_alive() or not forced_sequences:
                continue
            affordable = all(
                team_b_elements.get(element, 0) >= amount
                for element, amount in getattr(c, "forced_limit_burst_cost", {}).items()
            )
            sequence_key = "affordable" if affordable and "affordable" in forced_sequences else "default"
            c.forced_skill_sequence = forced_sequences.get(
                sequence_key,
                forced_sequences.get("default", []),
            )
            c.forced_skill_sequence_index = 0

        



        # gather actions
        pending_actions: List[Tuple[Combatant, bool, str, Combatant, Dict[str, Any], bool]] = []
        current_targets: Dict[Combatant, Combatant] = {}

        # New: List to store action parameters for participants
        action_params = []

        # Track active EVADE skills by defender: {unit: (evade_skill_name, evade_skill_data, coin_rolls)}
        active_evade_skills: Dict[Combatant, Tuple[str, Dict[str, Any], List[bool]]] = {}

        # Track turn-based usage for certain skills
        turn_skill_usage: Dict[Combatant, Dict[str, int]] = {}

        # Build participants list with all alive units and their speeds
        # Each (character, skill_slot_number) pair will act once
        all_alive_units = [c for c in team_a + team_b if c.is_alive() and c.speed > 0]

        # Create sorted list by speed: (combatant, is_team_a, speed, skill_slot)
        # We'll create one entry per skill slot per character
        participants = []
        for c in all_alive_units:
            is_team_a = c in team_a
            speed = c.speed
            # Create entries for each skill slot this character has
            for slot in range(c.skill_slots):
                participants.append((c, is_team_a, speed, slot))

        # Sort by speed (descending)
        participants.sort(key=lambda x: x[2], reverse=True)

        # Track which units were already staggered at turn start (to skip all their slots)
        staggered_units_this_turn = set()

        for actor, is_team_a, speed, slot_num in participants:

            if not actor.is_alive():
                continue

            # If this unit is staggered, skip all their slots
            if actor in staggered_units_this_turn:
                continue

            # Check stagger on first slot only
            if slot_num == 0 and actor.is_staggered:
                print(f"💥 {actor.name} is STAGGERED! Skipping all {actor.skill_slots} action slot(s).")
                staggered_units_this_turn.add(actor)
                continue

            allies = team_a if is_team_a else team_b
            enemies = team_b if is_team_a else team_a

            print(f"\n>>> {actor.name}'s turn (Speed: {speed}, Slot {slot_num + 1}/{actor.skill_slots})")
            available_skills = filter_dancing_skills(actor, list(actor.skills.keys()))

            if actor.has_status("Action-Blocked"):
                print(f"⏮️  {actor.name} is stopped! Action reversed!")
                actor.remove_status("Action-Blocked", 1)
                continue

            elif ((actor.name in ("Ross - Noble Sword Artist", "George") and actor.has_status("Dueling"))
                  or actor.has_status("Duel Preping")):
                filtered = [name for name in available_skills if name != "Singling Target"]
                if actor.has_special_effect("Pyric Fury"):
                    filtered = [name for name in filtered if name != "The Furious Slash Of The 1st Harbinger"]
                if not filtered:
                    filtered = available_skills

            elif actor.has_special_effect("Pyric Fury"):
                filtered = [name for name in available_skills if name != "The Furious Slash Of The 1st Harbinger"]
                if not filtered:
                    filtered = available_skills
            
            elif actor.has_special_effect("Iron Skin"):
                if actor.has_status("Lethal Charge"):
                    actor.remove_status("Lethal Charge", 1)
                    filtered = [name for name in available_skills if name != "Quantus Beam"]
                    if not filtered:
                        filtered = available_skills
                else:
                    filtered = [name for name in available_skills if name != "Incomplete Explosion"]
                    if not filtered:
                        filtered = available_skills
            
            elif actor.has_special_effect("Proving Myself"):
                filtered = [name for name in available_skills if name != "Prince Guard"]
                if not filtered:
                    filtered = available_skills

            else:
                filtered = available_skills

            # Randomly select 2 available skills
            available_skills = random.sample(filtered, min(2, len(filtered)))

            # Add limit burst to available choices if unit has one selected
            if actor.selected_limit_burst:
                available_skills = list(available_skills) + [actor.selected_limit_burst.get("Name")]


            if is_team_a and actor.is_extra_unit:
                skill_name, target = choose_action(
                    actor, allies, enemies, current_targets, skill_history,
                    available_skills, team_a_elements,
                )
                print(f"  🎯 {actor.name} chooses {skill_name} on {target.name}")
            elif is_team_a:
                skill_name, target = get_player_action(actor, allies, enemies, available_skills, team_a_elements)
                print(f"  🎯 {actor.name} chooses {skill_name} on {target.name}")
            elif getattr(actor, "forced_skill_sequence", None):
                sequence_index = actor.forced_skill_sequence_index % len(actor.forced_skill_sequence)
                skill_name = actor.forced_skill_sequence[sequence_index]
                actor.forced_skill_sequence_index += 1
                target = random.choice([enemy for enemy in enemies if enemy.is_alive()])
                forced_skill = actor.skills.get(skill_name, actor.selected_limit_burst)
                if actor.has_special_effect("I Beseech You to Browse Our Wares"):
                    actor.browse_wares_skill = skill_name
                element = forced_skill.get("Element") if forced_skill else None
                if element:
                    team_b_elements[element] = team_b_elements.get(element, 0) + 1
                print(f"  🎯 {actor.name} chooses {skill_name} on {target.name}")
            else:
                skill_name, target = choose_action(actor, allies, enemies, current_targets, skill_history, available_skills, team_b_elements)
                print(f"  🎯 {actor.name} chooses {skill_name} on {target.name}")

            if not skill_name:
                continue

            # Record history
            if actor not in skill_history:
                skill_history[actor] = []
            skill_history[actor].append(skill_name)

            current_targets[actor] = target
            # Check for skill replacement (e.g., Book Swipe -> Twisted Amputation)
            skill_name = get_actual_skill(actor, skill_name, target)

            # Detect if the chosen action is the unit's selected Limit Burst
            is_lb = False
            skill_obj = None
            if actor.selected_limit_burst and actor.selected_limit_burst.get("Name") == skill_name:
                is_lb = True
                skill_obj = actor.selected_limit_burst
            else:
                skill_obj = actor.skills.get(skill_name)

            if not skill_obj:
                # invalid skill (neither a standard skill nor the selected LB)
                continue

            if skill_obj.get("Type", "").lower() in ("attack", "counter"):
                for aggro_target in enemies:
                    if (aggro_target is target or not aggro_target.is_alive()
                            or not aggro_target.has_status("Aggro")):
                        continue
                    redirect_chance = min(1.0, 0.1 * aggro_target.get_status_potency("Aggro"))
                    if random.random() < redirect_chance:
                        target = aggro_target
                        aggro_target.statuses["Aggro"]["potency"] //= 2
                        if aggro_target.get_status_potency("Aggro") <= 0:
                            aggro_target.remove_status("Aggro")
                        if aggro_target.get_status_potency("Growing Reputation") >= 7:
                            aggro_target.apply_status("Well Prepared", potency=1, count=1)
                        msg = f"  🎯 {actor.name}'s attack is redirected to {target.name} by Aggro."
                        transcript.append(msg)
                        print(msg)
                        break

            # Handle EVADE skills specially: store them for defensive clash checking
            if skill_obj.get("Type", "").lower() == "evade":
                # EVADE skills target self/allies but are stored for when attacks come in
                # Roll coins immediately for EVADE skills (they have 0 Coin-Count by default)
                evade_coin_count = int(skill_obj.get("Coin-Count", 0))
                evade_coin_rolls = roll_coins(evade_coin_count, actor, target, skill_obj)
                active_evade_skills[target] = (skill_name, skill_obj, evade_coin_rolls)


            # Append action param with is_lb flag and the skill object (skill_obj may be LB dict)
            action_params.append((actor, is_team_a, skill_name, target, skill_obj, is_lb))

            # Trigger death check immediately after each action
            for c in team_a + team_b:
                if not c.is_alive() and getattr(c, '_was_alive', False):
                    handle_wotb_death(c, team_a + team_b, transcript)
                    c._was_alive = False

            # Trigger death check immediately after each action
            for c in team_a + team_b:
                if not c.is_alive() and getattr(c, '_was_alive', False):
                    handle_wotb_death(c, team_a + team_b, transcript)
                    c._was_alive = False

        # Check for auto-triggered passives (like Kyla's morale-based transformation)
        for actor in team_a + team_b:
            if not actor.is_alive():
                continue


        def validate_action_params(action_params: List[Tuple[Any, ...]]):
            """
            Ensure each entry in action_params is the expected 6-tuple:
              (actor: Combatant, is_team_a: bool, skill_name: str, target: Combatant, skill_obj: dict, is_lb: bool)
            Raises AssertionError with helpful message if invalid.
            """
            for idx, entry in enumerate(action_params):
                if not isinstance(entry, tuple):
                    raise AssertionError(f"action_params[{idx}] is not a tuple: {entry!r}")
                if len(entry) != 6:
                    raise AssertionError(f"action_params[{idx}] length is {len(entry)}, expected 6. Entry: {entry!r}")
                actor, is_team_a, skill_name, target, skill_obj, is_lb = entry
                if not isinstance(actor, Combatant):
                    raise AssertionError(f"action_params[{idx}][0] not Combatant: {actor!r}")
                if not isinstance(is_team_a, bool):
                    raise AssertionError(f"action_params[{idx}][1] is_team_a not bool: {is_team_a!r}")
                if not isinstance(skill_name, str):
                    raise AssertionError(f"action_params[{idx}][2] skill_name not str: {skill_name!r}")
                if target is not None and not isinstance(target, Combatant):
                    raise AssertionError(f"action_params[{idx}][3] target not Combatant or None: {target!r}")
                if not isinstance(skill_obj, dict):
                    raise AssertionError(f"action_params[{idx}][4] skill_obj must be dict (skill data or LB): {skill_obj!r}")
                if not isinstance(is_lb, bool):
                    raise AssertionError(f"action_params[{idx}][5] is_lb not bool: {is_lb!r}")
        # Validate action_params shape (must be 6-tuples) before processing
        validate_action_params(action_params)

        # Apply On-Use and roll coins for all actions first
        coin_rolls_map: Dict[int, List[bool]] = {}
        for idx, (actor, is_team_a, skill_name, target, skill, is_lb) in enumerate(action_params):
            # Apply On-Use (targets a chosen target when appropriate)
            for eff in iter_effects(skill.get("Effects", {}).get("On-Use", [])):
                apply_effect(
                    eff, actor, target, team_a + team_b, transcript,
                    is_limit_burst=is_lb,
                )
            # resolve coin flips now and apply On-Coin-Win effects
            coin_count = int(skill.get("Coin-Count", 0))

            if actor.has_special_effect("Blade Encasement: Spilling More Of The Blood"):
                dark_aura_potency = actor.get_status_potency("Dark Aura")
                coin_count += min(dark_aura_potency // 7, 2)

            if actor.name in ("Ross - Noble Sword Artist", "George") and actor.has_status("Dueling") and actor.get_status_potency("Dueling") >= 3:
                coin_count += 1

            coin_rolls = roll_coins(coin_count, actor, target, skill)
            coin_wins = sum(coin_rolls)
            coin_rolls_map[idx] = coin_rolls
            coin_effects = iter_effects(skill.get("Effects", {}).get("On-Coin-Win", []))
            if coin_wins > 0 and not any(effect.get("Effect") == "Equal Application" for effect in coin_effects):
                for eff in coin_effects:
                    if eval_condition(eff.get("Condition"), actor, target):
                        apply_effect(
                            eff, actor, target, team_a + team_b, transcript,
                            is_limit_burst=is_lb,
                        )

        # Now detect mutual pairs (A targets B and B targets A) to trigger clashes.
        # Also detect EVADE clashes (if defender has EVADE and attacker is attacking them)
        handled = set()
        for i, action in enumerate(action_params):
            sparing_result = get_simple_sparing_result(team_a, team_b)
            if sparing_result:
                result = sparing_result
                msg = f"  🪭 Simple Sparing ends the encounter: {result}"
                print(msg)
                transcript.append(msg)
                break
            if i in handled:
                continue
            actor, is_team_a, skill_name, target, skill, is_lb = action

            # Check for EVADE clash: if target has active EVADE and this is an attack
            if target in active_evade_skills and skill.get("Type", "").lower() in ("attack", "counter"):
                evade_skill_name, evade_skill, evade_coin_rolls = active_evade_skills[target]

                # Perform clash between attack and evade
                coin_rolls_a = coin_rolls_map.get(i, [])
                coin_rolls_b = evade_coin_rolls
                coin_wins_a = sum(coin_rolls_a)
                coin_wins_b = sum(coin_rolls_b)

                mult_a, mult_b, clash_result = resolve_clash(actor, skill, coin_rolls_a, target, evade_skill, coin_rolls_b)
                power_a = calculate_max_power(skill, coin_wins_a, actor)
                power_b = calculate_max_power(evade_skill, coin_wins_b, target)

                # Display clash results
                clash_msg = f"🛡️ EVADE CLASH: {actor.name}'s {skill_name} blocked by {target.name}'s {evade_skill_name}!"
                print(clash_msg)

                coin_display_a = " ".join(["H" if roll else "T" for roll in coin_rolls_a]) if coin_rolls_a else "—"
                coin_display_b = " ".join(["H" if roll else "T" for roll in coin_rolls_b]) if coin_rolls_b else "—"
                print(f"  {actor.name} ({skill_name}): [{coin_display_a}] {coin_wins_a}/{len(coin_rolls_a)} heads | Power: {power_a}")
                print(f"  {target.name} ({evade_skill_name}): [{coin_display_b}] {coin_wins_b}/{len(coin_rolls_b)} heads | Power: {power_b}")

                if clash_result == "b_wins":
                    print(f"  Result: {target.name}'s EVADE wins! {target.name} takes NO DAMAGE!")
                    transcript.append(f"🛡️ EVADE CLASH: {target.name}'s {evade_skill_name} successfully defended!")
                    # The attack still executes but with 0 damage multiplier
                    allies_a = team_a if is_team_a else team_b
                    enemies_a = team_b if is_team_a else team_a
                    team_pool = team_a_elements if is_team_a else team_b_elements
                    pay_and_execute(actor, target, skill if is_lb else skill_name,
                                        allies_a, enemies_a, coin_wins_a, 0.0, coin_rolls_a, transcript,
                                        team_pool, is_limit_burst=bool(is_lb), is_clash=True)
                else:
                    print(f"  Result: {actor.name}'s attack breaks through! Full damage incoming!")
                    transcript.append(f"🛡️ EVADE CLASH: {target.name}'s {evade_skill_name} was overwhelmed!")
                    # The attack executes at full power
                    allies_a = team_a if is_team_a else team_b
                    enemies_a = team_b if is_team_a else team_a
                    team_pool = team_a_elements if is_team_a else team_b_elements
                    pay_and_execute(actor, target, skill if is_lb else skill_name,
                                        allies_a, enemies_a, coin_wins_a, 1.0, coin_rolls_a, transcript,
                                        team_pool, is_limit_burst=bool(is_lb), is_clash=True)

                handled.add(i)
                # Note: EVADE skills themselves are not "used" - they just determine damage
                continue

            # find if there's an action where target acts on actor
            clash_idx = None
            for j, other_action in enumerate(action_params):
                if i == j or j in handled:
                    continue
                other_actor, _, other_skill_name, other_target, other_skill, other_is_lb = other_action
                if other_actor == target and other_target == actor:
                    clash_idx = j
                    break

            counter_clash = (
                clash_idx is None
                and skill.get("Type", "").lower() in ("attack", "counter")
                and target.is_alive()
                and target.has_special_effect("Proving Myself")
                and target.get_status_potency("Growing Reputation") >= 5
                and "Prince Guard" in target.skills
            )

            if clash_idx is not None or counter_clash:
                # Mutual-direct clash detected
                # get coin results
                coin_rolls_a = coin_rolls_map.get(i, [])
                if counter_clash:
                    other_actor = target
                    other_is_team_a = other_actor in team_a
                    other_skill_name = "Prince Guard"
                    other_target = actor
                    other_skill = other_actor.skills[other_skill_name]
                    other_is_lb = False
                    coin_rolls_b = roll_coins(int(other_skill.get("Coin-Count", 0)), other_actor, actor, other_skill)
                else:
                    other_actor, other_is_team_a, other_skill_name, other_target, other_skill, other_is_lb = action_params[clash_idx]
                    coin_rolls_b = coin_rolls_map.get(clash_idx, [])
                coin_wins_a = sum(coin_rolls_a)
                coin_wins_b = sum(coin_rolls_b)

                # compute clash outcome multipliers based on max power
                mult_a, mult_b, clash_result = resolve_clash(actor, skill, coin_rolls_a, other_actor, other_skill, coin_rolls_b)
                power_a = calculate_max_power(skill, coin_wins_a, actor)
                power_b = calculate_max_power(other_skill, coin_wins_b, other_actor)

                # Display clash results
                clash_kind = "COUNTER CLASH" if counter_clash else "CLASH"
                clash_msg = f"⚡ {clash_kind} between {actor.name} and {other_actor.name}!"
                print(clash_msg)

                # Show individual coin flips
                coin_display_a = " ".join(["H" if roll else "T" for roll in coin_rolls_a]) if coin_rolls_a else "—"
                coin_display_b = " ".join(["H" if roll else "T" for roll in coin_rolls_b]) if coin_rolls_b else "—"
                print(f"  {actor.name} ({skill_name}): [{coin_display_a}] {coin_wins_a}/{len(coin_rolls_a)} heads | Base: {int(skill.get('Base-Power', 0))}, Max Power: {power_a}")
                print(f"  {other_actor.name} ({other_skill_name}): [{coin_display_b}] {coin_wins_b}/{len(coin_rolls_b)} heads | Base: {int(other_skill.get('Base-Power', 0))}, Max Power: {power_b}")
                print(f"  Result: {clash_result.upper()} — {actor.name if clash_result == 'a_wins' else other_actor.name if clash_result == 'b_wins' else 'Both'} execute!")

                transcript.append(f"⚡ {clash_kind}: {actor.name} ({skill_name}) vs {other_actor.name} ({other_skill_name}) | {actor.name} power={power_a}, {other_actor.name} power={power_b} | Result: {clash_result}")

                # Allies/enemies contexts
                allies_a = team_a if is_team_a else team_b
                enemies_a = team_b if is_team_a else team_a
                allies_b = team_a if other_is_team_a else team_b
                enemies_b = team_b if other_is_team_a else team_a

                # --- CLASH: execute actor's part (replace existing call) ---
                if mult_a > 0:
                    actor_team_pool = team_a_elements if is_team_a else team_b_elements
                    # skill is either a dict (LB) or a skill dict from actor.skills; is_lb was unpacked earlier
                    pay_and_execute(actor, target, skill if is_lb else skill_name,
                                        allies_a, enemies_a, coin_wins_a, mult_a, coin_rolls_a, transcript,
                                        actor_team_pool, is_limit_burst=bool(is_lb), is_clash=True)
                else:
                    transcript.append(f"{actor.name}'s {skill_name} is overwhelmed and fails to connect!")

                # --- CLASH: execute other_actor's part (replace existing call) ---
                if mult_b > 0:
                    other_actor_team_pool = team_a_elements if other_is_team_a else team_b_elements
                    pay_and_execute(other_actor, other_target, other_skill if other_is_lb else other_skill_name,
                                        allies_b, enemies_b, coin_wins_b, mult_b, coin_rolls_b, transcript,
                                        other_actor_team_pool, is_limit_burst=bool(other_is_lb), is_clash=True)
                else:
                    transcript.append(f"{other_actor.name}'s {other_skill_name} is overwhelmed and fails to connect!")

                # On-Final-Hit effects
                if mult_a > 0:
                    for eff in iter_effects(skill.get("Effects", {}).get("On-Final-Hit", [])):
                        apply_effect(
                            eff, actor, target, team_a + team_b, transcript,
                            is_limit_burst=is_lb,
                        )

                if mult_b > 0:
                    for eff in iter_effects(other_skill.get("Effects", {}).get("On-Final-Hit", [])):
                        apply_effect(
                            eff, other_actor, other_target, team_a + team_b, transcript,
                            is_limit_burst=other_is_lb,
                        )

                handled.add(i)
                if not counter_clash:
                    handled.add(clash_idx)


            else:
                # No mutual clash; resolve normally (single action)

                # EVADE skills only trigger on clashes; if not clashing, they don't execute
                if skill.get("Type", "").lower() == "evade":
                    # EVADE skill wasn't attacked, so it doesn't do anything
                    handled.add(i)
                    continue

                allies = team_a if is_team_a else team_b
                enemies = team_b if is_team_a else team_a

                # Resolve with the pre-rolled coin wins
                coin_rolls = coin_rolls_map.get(i, [])
                coin_wins = sum(coin_rolls)

                team_pool = team_a_elements if is_team_a else team_b_elements

                if skill.get("Type", "").lower() in ("attack", "counter"):
                    # Centralized execution (handles LB cost/morale/overuse and standard attacks)
                    pay_and_execute(actor, target, skill if is_lb else skill_name,
                                                allies, enemies, coin_wins, 1.0, coin_rolls, transcript,
                                                team_pool, is_limit_burst=bool(is_lb))
                else:
                    # Support/Defense types: apply effects
                    for eff in iter_effects(skill.get("Effects", {}).get("On-Coin-Win", [])):
                        if coin_wins > 0 and eval_condition(eff.get("Condition"), actor, target):
                            apply_effect(
                                eff, actor, target, team_a + team_b, transcript,
                                is_limit_burst=is_lb,
                            )

                    # Gain elements for support skills if successfully used
                    if coin_wins > 0 and team_pool is not None:
                        element_multiplier = 1
                        actor.gain_elements_for_skill(skill, team_pool, element_multiplier)
                        transcript.append(f"  ✨ {actor.name} generates {element_multiplier} {skill.get('Element', 'None')} for their team.")



                log_lines = []


                # On-Final-Hit
                for eff in iter_effects(skill.get("Effects", {}).get("On-Final-Hit", [])):
                    if (not target.is_alive()) or eval_condition(eff.get("Condition"), actor, target):
                        apply_effect(
                            eff, actor, target, team_a + team_b, log_lines,
                            is_limit_burst=is_lb,
                        )

                for ln in log_lines:
                    transcript.append(ln)
                handled.add(i)

            relevant_result = check_relevant_death_result(team_a, team_b)
            if relevant_result:
                result = relevant_result
                break
            if not any(c.is_alive() for c in team_a) or not any(c.is_alive() for c in team_b):
                break

        # <-- end of for actor, is_team_a, speed, slot_num in participants loop

        if result is None:
            victory_result = check_something_of_substance_victory(team_a, team_b)
            if victory_result:
                result = victory_result
                msg = f"  ✨ Something Of Substance ends the encounter: {result}"
                print(msg)
                transcript.append(msg)

        if result is None:
            sparing_result = get_simple_sparing_result(team_a, team_b)
            if sparing_result:
                result = sparing_result
                msg = f"  🪭 Simple Sparing ends the encounter: {result}"
                print(msg)
                transcript.append(msg)

        if result is not None:
            break

        for merchant in team_a + team_b:
            if (merchant.browse_wares_active
                    and len(merchant.browse_wares_attackers) > 1
                    and merchant.browse_wares_skill):
                for attacker in merchant.browse_wares_attackers:
                    attacker.apply_status(merchant.browse_wares_skill, potency=1, count=1)
                msg = (f"  🛒 Multiple customers attacked {merchant.name}'s "
                       f"{merchant.browse_wares_skill}; the matching status was applied.")
                transcript.append(msg)
                print(msg)

        for c in team_a + team_b:
            if c.has_status("Well Prepared"):
                c.remove_status("Well Prepared")

        # Recover from stagger at end of turn for units that were staggered
        for actor in staggered_units_this_turn:
            actor.is_staggered = False
            msg = f"  🔄 {actor.name} recovered from stagger."
            print(msg)
            transcript.append(msg)

        # After processing all actions for this turn, apply end-of-turn effects and update slots
        log = []
        turn_result = apply_end_of_turn_effects(team_a, team_b, log)
        for ln in log:
            transcript.append(ln)

        relevant_result = check_relevant_death_result(team_a, team_b)
        if relevant_result:
            result = relevant_result
            break

        if turn_result:
            result = turn_result
            break

        # Displace status dissipation
        for c in team_a + team_b:
            if c.has_status("Displace"):
                c.remove_status("Displace", 1)

        # Round-robin skill slot distribution at end of turn
        # Grant 1 skill slot to next unit in each team simultaneously

        # Distribute to Team A (skip dead units)
        for _ in range(len(team_a)):
            if team_a[team_a_slot_index].is_alive():
                team_a[team_a_slot_index].skill_slots += 1
                if team_a[team_a_slot_index].name == "Ross - Noble Sword Artist":
                    team_a[team_a_slot_index].skill_slots = 3
                if team_a[team_a_slot_index].name == "Malcolm - Noble Sword Artist":
                    team_a[team_a_slot_index].skill_slots = 2
                if team_a[team_a_slot_index].name == "Banquo - The Ghost Long Forgotten":
                    team_a[team_a_slot_index].skill_slots = 4
                if team_a[team_a_slot_index].name == "Jack - Wounding Commander":
                    team_a[team_a_slot_index].skill_slots = 5
                msg = f"  📊 {team_a[team_a_slot_index].name} gained 1 skill slot! (Now has {team_a[team_a_slot_index].skill_slots})"
                print(msg)
                transcript.append(msg)
                team_a_slot_index = (team_a_slot_index + 1) % len(team_a)
                break
            else:
                # Skip dead units
                team_a_slot_index = (team_a_slot_index + 1) % len(team_a)

        # Distribute to Team B (skip dead units)
        for _ in range(len(team_b)):
            if team_b[team_b_slot_index].is_alive():
                team_b[team_b_slot_index].skill_slots += 1
                if team_b[team_b_slot_index].name == "Daehon - WOTB Shogun of the West":
                    team_b[team_b_slot_index].skill_slots = 5  # Special case for Daehon
                if team_b[team_b_slot_index].name == "Spirited Shogun":
                    team_b[team_b_slot_index].skill_slots = 5  # Special case for Spirited Shogun
                if team_b[team_b_slot_index].name == "Lenuff - Pyric Offense Captain":
                    team_b[team_b_slot_index].skill_slots = 3  # Special case for Lenuff
                if team_b[team_b_slot_index].name == "Ross - Noble Sword Artist":
                    team_b[team_b_slot_index].skill_slots = 3
                if team_b[team_b_slot_index].name == "Malcolm - Noble Sword Artist":
                    team_b[team_b_slot_index].skill_slots = 3
                if team_b[team_b_slot_index].name == "Banquo - The Ghost Long Forgotten":
                    team_b[team_b_slot_index].skill_slots = 4
                if team_b[team_b_slot_index].name == "Macbeth - The 1st Harbinger Of Flames":
                    team_b[team_b_slot_index].skill_slots = 7  # Special case for Macbeth
                if team_b[team_b_slot_index].name == "Pyro Lord":
                    team_b[team_b_slot_index].skill_slots = 6  # Special case for Pyro Lord
                if team_b[team_b_slot_index].name == "Vin - The Diamond Commander":
                    team_b[team_b_slot_index].skill_slots = 7  # Special case for Vin
                if team_b[team_b_slot_index].name == "Jack - Wounding Commander":
                    team_b[team_b_slot_index].skill_slots = 5
                if team_b[team_b_slot_index].name == "Unknown Fan-Weilding Indiviual":
                    team_b[team_b_slot_index].skill_slots = 5
                if team_b[team_b_slot_index].name == "Lila - Sage of Memory":
                    team_b[team_b_slot_index].skill_slots = 5
                if team_b[team_b_slot_index].name == "Anti-Theft Android":
                    team_b[team_b_slot_index].skill_slots = 3
                if getattr(team_b[team_b_slot_index], "forced_skill_sequences", None):
                    team_b[team_b_slot_index].skill_slots = 5
                msg = f"  📊 {team_b[team_b_slot_index].name} gained 1 skill slot! (Now has {team_b[team_b_slot_index].skill_slots})"
                print(msg)
                transcript.append(msg)
                team_b_slot_index = (team_b_slot_index + 1) % len(team_b)
                break
            else:
                # Skip dead units
                team_b_slot_index = (team_b_slot_index + 1) % len(team_b)

        turn_no += 1

    # <-- end of while loop

    if result is None:
        result = "None"

    # Final display / result after all turns complete (moved outside the while loop)
    display_battle_state(team_a, team_b, team_a_elements, team_b_elements)
    a_alive = [c for c in team_a if c.is_alive()]
    b_alive = [c for c in team_b if c.is_alive()]

    if not b_alive:
        result = "TEAM A WINS!"
    elif not a_alive:
        result = "TEAM B WINS!"

    print(f"\n{'='*60}")
    print(result)
    print(f"{'='*60}\n")
    transcript.append(f"\n{result}\n")
    return transcript

    # ---------- File I/O & main -----------------------------------------------
def load_combatants_from_file(path: str) -> Dict[str, Dict[str, Any]]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "Combatants" in data:
            return data["Combatants"]
        return data

def main():
        try:
            print("\nLoading combatants...")
            try:
                all_combatants = load_combatants_from_file(COMBATANTS_FILE)
                print(f"Loaded {len(all_combatants)} combatants: {list(all_combatants.keys())}")
            except Exception as e:
                print(f"Could not load {COMBATANTS_FILE}: {e}")
                return

            team_a, team_b = select_teams(all_combatants)
            transcript = run_interactive_battle(team_a, team_b)

        except Exception:
            print("Exception occurred:")
            traceback.print_exc()

if __name__ == "__main__":
        main()

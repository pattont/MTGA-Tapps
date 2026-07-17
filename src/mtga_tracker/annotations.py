"""Helpers for parsed MTGA annotation details."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _first_int(detail: Dict[str, Any]) -> Optional[int]:
    values = detail.get("valueInt32", [])
    if isinstance(values, list):
        return values[0] if values else None
    return values if isinstance(values, int) else None


def _first_string(detail: Dict[str, Any]) -> Optional[str]:
    values = detail.get("valueString", [])
    if isinstance(values, list):
        return values[0] if values else None
    return values if isinstance(values, str) else None


def _int_list(detail: Dict[str, Any]) -> List[int]:
    values = detail.get("valueInt32", [])
    if not isinstance(values, list):
        values = [values]
    parsed = []
    for value in values:
        try:
            parsed.append(int(value))
        except (TypeError, ValueError):
            continue
    return parsed


@dataclass(frozen=True)
class AnnotationDetails:
    """Commonly used annotation details parsed once from raw payload data."""

    category: Optional[str] = None
    zone_src: Optional[int] = None
    zone_dest: Optional[int] = None
    target_id: Optional[int] = None
    target_ids: List[int] = field(default_factory=list)
    source_id: Optional[int] = None
    orig_instance_id: Optional[int] = None
    new_instance_id: Optional[int] = None
    damage: Optional[int] = None
    damage_type: Optional[int] = None
    counter_type: Optional[int] = None
    counter_amount: Optional[int] = None
    ability_grp_id: Optional[int] = None
    target_index: Optional[int] = None
    life: Optional[int] = None
    power: Optional[int] = None
    toughness: Optional[int] = None
    source_zone: Optional[int] = None
    mana_payment_id: Optional[int] = None
    mana_color: Optional[int] = None
    action_type: Optional[int] = None
    top_ids: List[int] = field(default_factory=list)
    bottom_ids: List[int] = field(default_factory=list)
    shuffle_old_ids: List[int] = field(default_factory=list)
    shuffle_new_ids: List[int] = field(default_factory=list)
    designation_instance_id: Optional[int] = None
    designation_type: Optional[int] = None
    conjuration_type: Optional[str] = None
    source_grp_id: Optional[int] = None
    grpid: Optional[int] = None
    value: Optional[int] = None
    controller_id: Optional[int] = None

    @classmethod
    def from_annotation(cls, annotation: Dict[str, Any]) -> "AnnotationDetails":
        category = None
        zone_src = None
        zone_dest = None
        target_id = None
        target_ids: List[int] = []
        source_id = None
        orig_instance_id = None
        new_instance_id = None
        damage = None
        damage_type = None
        counter_type = None
        counter_amount = None
        ability_grp_id = None
        target_index = None
        life = None
        power = None
        toughness = None
        source_zone = None
        mana_payment_id = None
        mana_color = None
        action_type = None
        top_ids: List[int] = []
        bottom_ids: List[int] = []
        shuffle_old_ids: List[int] = []
        shuffle_new_ids: List[int] = []
        designation_instance_id = None
        designation_type = None
        conjuration_type = None
        source_grp_id = None
        grpid = None
        value = None
        controller_id = None

        details = annotation.get("details", [])
        for detail in details if isinstance(details, list) else []:
            key = detail.get("key", "")
            if key == "category":
                category = _first_string(detail)
            elif key == "zone_src":
                zone_src = _first_int(detail)
            elif key == "zone_dest":
                zone_dest = _first_int(detail)
            elif key in ("target", "target_id"):
                target_id = _first_int(detail)
                if target_id:
                    target_ids.append(target_id)
            elif key == "targets":
                target_list = detail.get("valueInt32", [])
                if target_list:
                    target_ids.extend(target_list)
                    if target_id is None:
                        target_id = target_list[0]
            elif key in ("source", "source_id", "sourceId", "abilitySource", "affector", "cause"):
                source_id = _first_int(detail)
            elif key == "orig_id":
                orig_instance_id = _first_int(detail)
            elif key == "new_id":
                new_instance_id = _first_int(detail)
            elif key == "damage":
                damage = _first_int(detail)
            elif key == "type":
                damage_type = _first_int(detail)
            elif key == "counter_type":
                counter_type = _first_int(detail)
            elif key == "transaction_amount":
                counter_amount = _first_int(detail)
            elif key == "abilityGrpId":
                ability_grp_id = _first_int(detail)
            elif key == "index":
                target_index = _first_int(detail)
            elif key == "life":
                life = _first_int(detail)
            elif key == "power":
                power = _first_int(detail)
            elif key == "toughness":
                toughness = _first_int(detail)
            elif key == "source_zone":
                source_zone = _first_int(detail)
            elif key == "id":
                mana_payment_id = _first_int(detail)
            elif key == "color":
                mana_color = _first_int(detail)
            elif key == "actionType":
                action_type = _first_int(detail)
            elif key == "topIds":
                top_ids = _int_list(detail)
            elif key == "bottomIds":
                bottom_ids = _int_list(detail)
            elif key == "OldIds":
                shuffle_old_ids = _int_list(detail)
            elif key == "NewIds":
                shuffle_new_ids = _int_list(detail)
            elif key == "DesignationType":
                designation_type = _first_int(detail)
            elif key == "conjuration_type":
                conjuration_type = _first_string(detail)
            elif key == "source_grpid":
                source_grp_id = _first_int(detail)
            elif key == "grpid":
                grpid = _first_int(detail)
            elif key == "value":
                value = _first_int(detail)
            elif key == "ControllerId":
                controller_id = _first_int(detail)

        affected_ids = annotation.get("affectedIds", [])
        if isinstance(affected_ids, list) and affected_ids:
            try:
                designation_instance_id = int(affected_ids[0])
            except (TypeError, ValueError):
                designation_instance_id = None

        return cls(
            category=category,
            zone_src=zone_src,
            zone_dest=zone_dest,
            target_id=target_id,
            target_ids=target_ids,
            source_id=source_id,
            orig_instance_id=orig_instance_id,
            new_instance_id=new_instance_id,
            damage=damage,
            damage_type=damage_type,
            counter_type=counter_type,
            counter_amount=counter_amount,
            ability_grp_id=ability_grp_id,
            target_index=target_index,
            life=life,
            power=power,
            toughness=toughness,
            source_zone=source_zone,
            mana_payment_id=mana_payment_id,
            mana_color=mana_color,
            action_type=action_type,
            top_ids=top_ids,
            bottom_ids=bottom_ids,
            shuffle_old_ids=shuffle_old_ids,
            shuffle_new_ids=shuffle_new_ids,
            designation_instance_id=designation_instance_id,
            designation_type=designation_type,
            conjuration_type=conjuration_type,
            source_grp_id=source_grp_id,
            grpid=grpid,
            value=value,
            controller_id=controller_id,
        )

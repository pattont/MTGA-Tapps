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

        return cls(
            category=category,
            zone_src=zone_src,
            zone_dest=zone_dest,
            target_id=target_id,
            target_ids=target_ids,
            source_id=source_id,
            orig_instance_id=orig_instance_id,
            new_instance_id=new_instance_id,
        )


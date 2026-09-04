"""Schedule columns vs caja shift_nos. Yessi night = T4 today + T1 tomorrow."""

from __future__ import annotations

from typing import Any

YESSI_ID = 2


def schedule_slot_defs(drogueria_id: int, shift_count: int) -> list[dict[str, Any]]:
    if drogueria_id == YESSI_ID:
        return [
            {
                "slot_no": 1,
                "label": "T1",
                "legs": [{"shift_no": 2, "day_offset": 0}],
            },
            {
                "slot_no": 2,
                "label": "T2",
                "legs": [{"shift_no": 3, "day_offset": 0}],
            },
            {
                "slot_no": 3,
                "label": "T3",
                "legs": [
                    {"shift_no": 4, "day_offset": 0},
                    {"shift_no": 1, "day_offset": 1},
                ],
            },
        ]
    return [
        {
            "slot_no": n,
            "label": f"T{n}",
            "legs": [{"shift_no": n, "day_offset": 0}],
        }
        for n in range(1, shift_count + 1)
    ]


def schedule_count(drogueria_id: int, shift_count: int) -> int:
    return len(schedule_slot_defs(drogueria_id, shift_count))


def get_slot(
    drogueria_id: int, shift_count: int, slot_no: int
) -> dict[str, Any] | None:
    for slot in schedule_slot_defs(drogueria_id, shift_count):
        if slot["slot_no"] == slot_no:
            return slot
    return None

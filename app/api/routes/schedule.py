"""Employees and schedule cells."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import get_settings
from app.services.schedule.service import (
    MAX_BATCH,
    ScheduleError,
    assign_extra,
    assign_shift,
    clear_extra,
    clear_shift,
    create_employee,
    list_employees_dto,
    list_schedule_range,
    rename_employee,
    save_schedule_batch,
)

router = APIRouter(tags=["schedule"])


class EmployeeItem(BaseModel):
    id: int
    name: str


class EmployeeNameBody(BaseModel):
    name: str

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class ScheduleShiftItem(BaseModel):
    shift_no: int
    employee_id: int | None = None
    employee: str | None = None


class ScheduleExtraItem(BaseModel):
    employee_id: int | None = None
    employee: str | None = None


class ScheduleDayDto(BaseModel):
    date: date
    shifts: list[ScheduleShiftItem]
    extra: ScheduleExtraItem


class ScheduleRangeDto(BaseModel):
    drogueria_id: int
    shift_count: int
    schedule_count: int
    date_from: date
    date_to: date
    days: list[ScheduleDayDto]


class AssignBody(BaseModel):
    employee_id: int = Field(ge=1)


class ScheduleBatchItem(BaseModel):
    work_date: date
    shift_no: int | None = Field(default=None, ge=1, le=6)
    extra: bool = False
    employee_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def shift_or_extra(self) -> ScheduleBatchItem:
        if self.extra:
            if self.shift_no is not None:
                raise ValueError("extra items must not include shift_no")
            return self
        if self.shift_no is None:
            raise ValueError("shift_no is required unless extra=true")
        return self


class ScheduleBatchBody(BaseModel):
    drogueria_id: int = Field(ge=1)
    items: list[ScheduleBatchItem] = Field(min_length=1, max_length=MAX_BATCH)


def _http(e: ScheduleError) -> HTTPException:
    status = (
        404
        if e.code in {"drogueria_not_found", "employee_not_found"}
        else 400
    )
    return HTTPException(status_code=status, detail=e.message)


def _db_or_503() -> None:
    if not get_settings().database_url.strip():
        raise HTTPException(status_code=503, detail="Falta DATABASE_URL en .env")


@router.get("/employees", response_model=list[EmployeeItem])
async def get_employees(
    q: Annotated[str | None, Query(description="Name contains, case-insensitive")] = None,
) -> list[EmployeeItem]:
    _db_or_503()
    try:
        rows = await asyncio.to_thread(list_employees_dto, get_settings(), q=q)
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return [EmployeeItem(**r) for r in rows]


@router.post("/employees", response_model=EmployeeItem)
async def post_employee(body: EmployeeNameBody) -> EmployeeItem:
    _db_or_503()
    try:
        row = await asyncio.to_thread(create_employee, get_settings(), body.name)
    except ScheduleError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return EmployeeItem(**row)


@router.patch("/employees/{employee_id}", response_model=EmployeeItem)
async def patch_employee(
    employee_id: Annotated[int, Path(ge=1)],
    body: EmployeeNameBody,
) -> EmployeeItem:
    _db_or_503()
    try:
        row = await asyncio.to_thread(
            rename_employee, get_settings(), employee_id, body.name
        )
    except ScheduleError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return EmployeeItem(**row)


@router.get("/schedule", response_model=ScheduleRangeDto)
async def get_schedule(
    drogueria_id: Annotated[int, Query(ge=1)],
    date_from: Annotated[date, Query(description="Start inclusive")],
    date_to: Annotated[date, Query(description="End inclusive")],
) -> ScheduleRangeDto:
    _db_or_503()
    try:
        payload = await asyncio.to_thread(
            list_schedule_range,
            get_settings(),
            drogueria_id=drogueria_id,
            date_from=date_from,
            date_to=date_to,
        )
    except ScheduleError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return ScheduleRangeDto(**payload)


@router.put("/schedule", response_model=ScheduleRangeDto)
async def put_schedule_batch(body: ScheduleBatchBody) -> ScheduleRangeDto:
    _db_or_503()
    items: list[dict[str, Any]] = [x.model_dump() for x in body.items]
    try:
        payload = await asyncio.to_thread(
            save_schedule_batch,
            get_settings(),
            drogueria_id=body.drogueria_id,
            items=items,
        )
    except ScheduleError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return ScheduleRangeDto(**payload)


@router.put(
    "/schedule/{drogueria_id}/{work_date}/extra",
    response_model=ScheduleDayDto,
)
async def put_schedule_extra(
    drogueria_id: Annotated[int, Path(ge=1)],
    work_date: date,
    body: AssignBody,
) -> ScheduleDayDto:
    _db_or_503()
    try:
        day = await asyncio.to_thread(
            assign_extra,
            get_settings(),
            drogueria_id=drogueria_id,
            work_date=work_date,
            employee_id=body.employee_id,
        )
    except ScheduleError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return ScheduleDayDto(**day)


@router.delete(
    "/schedule/{drogueria_id}/{work_date}/extra",
    response_model=ScheduleDayDto,
)
async def delete_schedule_extra(
    drogueria_id: Annotated[int, Path(ge=1)],
    work_date: date,
) -> ScheduleDayDto:
    _db_or_503()
    try:
        day = await asyncio.to_thread(
            clear_extra,
            get_settings(),
            drogueria_id=drogueria_id,
            work_date=work_date,
        )
    except ScheduleError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return ScheduleDayDto(**day)


@router.put(
    "/schedule/{drogueria_id}/{work_date}/{shift_no}",
    response_model=ScheduleDayDto,
)
async def put_schedule_cell(
    drogueria_id: Annotated[int, Path(ge=1)],
    work_date: date,
    shift_no: Annotated[int, Path(ge=1, le=6)],
    body: AssignBody,
) -> ScheduleDayDto:
    _db_or_503()
    try:
        day = await asyncio.to_thread(
            assign_shift,
            get_settings(),
            drogueria_id=drogueria_id,
            work_date=work_date,
            shift_no=shift_no,
            employee_id=body.employee_id,
        )
    except ScheduleError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return ScheduleDayDto(**day)


@router.delete(
    "/schedule/{drogueria_id}/{work_date}/{shift_no}",
    response_model=ScheduleDayDto,
)
async def delete_schedule_cell(
    drogueria_id: Annotated[int, Path(ge=1)],
    work_date: date,
    shift_no: Annotated[int, Path(ge=1, le=6)],
) -> ScheduleDayDto:
    _db_or_503()
    try:
        day = await asyncio.to_thread(
            clear_shift,
            get_settings(),
            drogueria_id=drogueria_id,
            work_date=work_date,
            shift_no=shift_no,
        )
    except ScheduleError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return ScheduleDayDto(**day)

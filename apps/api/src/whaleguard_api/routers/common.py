from __future__ import annotations

import math
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from ..schemas import Page

T = TypeVar("T")


def get_or_404(db: Session, model, object_id, message: str = "资源不存在"):
    value = db.get(model, object_id)
    if value is None:
        raise HTTPException(status_code=404, detail=message)
    return value


def paginate(db: Session, query: Select, page: int, page_size: int) -> Page:
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="分页参数无效")
    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    total = int(db.scalar(count_query) or 0)
    items = list(db.scalars(query.offset((page - 1) * page_size).limit(page_size)))
    return Page(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


def apply_updates(instance, values: dict) -> None:
    for key, value in values.items():
        setattr(instance, key, value)

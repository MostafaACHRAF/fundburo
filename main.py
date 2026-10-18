from datetime import datetime, timezone
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import SessionLocal
from models import AppUser, Item, ItemMatch


app = FastAPI(title="LostAndFound API")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ClaimCreate(BaseModel):
    username: str
    email: EmailStr
    description: str
    color: str | None = None
    size: str | None = None
    usage: str | None = None
    address_text: str | None = None
    lat: float | None = None
    lng: float | None = None
    event_time: datetime | None = None
    feel: str | None = None
    smell: str | None = None
    model: str | None = None
    image_url: str | None = None


class ClaimCreateResponse(BaseModel):
    user_id: int
    item_id: int
    status: str


class ClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    item_type: str
    description: str
    color: str | None = None
    size: str | None = None
    usage: str | None = None
    address_text: str | None = None
    lat: float | None = None
    lng: float | None = None
    event_time: datetime | None = None
    feel: str | None = None
    smell: str | None = None
    model: str | None = None
    image_url: str | None = None
    status: str
    created_at: datetime

class ReportCreate(BaseModel):
    username: str
    email: EmailStr
    description: str
    color: str | None = None
    size: str | None = None
    usage: str | None = None
    address_text: str | None = None
    lat: float | None = None
    lng: float | None = None
    event_time: datetime | None = None
    feel: str | None = None
    smell: str | None = None
    model: str | None = None
    image_url: str | None = None

class ReportCreateResponse(BaseModel):
    user_id: int
    item_id: int
    status: str

class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    item_type: str
    description: str
    color: str | None = None
    size: str | None = None
    usage: str | None = None
    address_text: str | None = None
    lat: float | None = None
    lng: float | None = None
    event_time: datetime | None = None
    feel: str | None = None
    smell: str | None = None
    model: str | None = None
    image_url: str | None = None
    status: str
    created_at: datetime

class MatchCreate(BaseModel):
    item_id: int

class MatchItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    found_item_id: int
    lost_item_id: int
    score: Decimal
    confidence: str

class MatchCreateResponse(BaseModel):
    item_id: int
    list_of_matches: list[MatchItem]
    date: datetime

@app.post("/claims", response_model=ClaimCreateResponse)
def submit_claim(payload: ClaimCreate, db: Session = Depends(get_db)):
    user_stmt = select(AppUser).where(
        AppUser.email == payload.email
    )
    user = db.scalar(user_stmt)

    if user is None:
        user = AppUser(username=payload.username, email=payload.email, role="claimer")
        db.add(user)
        db.flush()

    item = Item(
        user_id=user.id,
        item_type="lost",
        description=payload.description,
        color=payload.color,
        size=payload.size,
        usage=payload.usage,
        address_text=payload.address_text,
        lat=payload.lat,
        lng=payload.lng,
        event_time=payload.event_time,
        feel=payload.feel,
        smell=payload.smell,
        model=payload.model,
        image_url=payload.image_url,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return ClaimCreateResponse(user_id=user.id, item_id=item.id, status=item.status)


@app.get("/claims", response_model=list[ClaimOut])
def get_claims(db: Session = Depends(get_db)):
    stmt = select(Item).where(Item.item_type == "lost").order_by(Item.created_at.desc())
    return db.scalars(stmt).all()

@app.post("/reports", response_model = ReportCreateResponse)
def submit_report(payload: ReportCreate, db: Session = Depends(get_db)):
    user_stmt = select(AppUser).where(
        AppUser.email == payload.email
    )
    user = db.scalar(user_stmt)

    if user is None:
        user = AppUser(username=payload.username, email=payload.email, role="reporter")
        db.add(user)
        db.flush()

    item = Item(
        user_id=user.id,
        item_type="found",
        description=payload.description,
        color=payload.color,
        size=payload.size,
        usage=payload.usage,
        address_text=payload.address_text,
        lat=payload.lat,
        lng=payload.lng,
        event_time=payload.event_time,
        feel=payload.feel,
        smell=payload.smell,
        model=payload.model,
        image_url=payload.image_url,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return ReportCreateResponse(user_id=user.id, item_id=item.id, status=item.status)

@app.get("/reports", response_model = list[ReportOut])
def get_reports(db: Session = Depends(get_db)):
    stmt = select(Item).where(Item.item_type == "found").order_by(Item.created_at.desc()) 
    return db.scalars(stmt).all()

@app.post("/match/run", response_model = MatchCreateResponse)
def submit_match(payload: MatchCreate, db: Session = Depends(get_db)):
    item_stmt = select(Item).where(Item.id == payload.item_id)
    item = db.scalar(item_stmt)

    if item is None:
        raise HTTPException(status_code = 404, detail = "Item not found") 

    reverse_type = "found" if item.item_type == "lost" else "lost"
    target_items_stmt = select(Item).where(Item.item_type == reverse_type)
    target_items = db.scalars(target_items_stmt).all()

    matches: list[MatchItem] = []
    for target_item in target_items:
        match_score = 0

        if target_item.event_time is not None and item.event_time is not None:
            time_distance = abs((item.event_time - target_item.event_time).total_seconds())
            if time_distance <= 86400:
                match_score += 0.2

        if item.color == target_item.color:
             match_score += 0.1

        if item.size == target_item.size:
            match_score += 0.1

        if item.model == target_item.model:
            match_score += 0.1

        if match_score >= 0.4:
            lost_id = item.id if item.item_type == "lost" else target_item.id
            found_id = item.id if item.item_type == "found" else target_item.id

            existing_match_stmt = select(ItemMatch).where(ItemMatch.lost_item_id == lost_id, ItemMatch.found_item_id == found_id)
            existing_match = db.scalar(existing_match_stmt)

            if existing_match is None:
                item_match = ItemMatch(lost_item_id = lost_id, found_item_id = found_id, score = Decimal(str(match_score)), confidence = "medium")  
                db.add(item_match)
            else:
                existing_match.score = Decimal(str(match_score))
                existing_match.confidence = "medium"


            match = MatchItem(lost_item_id = lost_id, found_item_id = found_id, score = Decimal(str(match_score)), confidence = "medium") 
            matches.append(match)

    db.commit()
    return MatchCreateResponse(item_id = item.id, list_of_matches = matches, date = datetime.now(timezone.utc))


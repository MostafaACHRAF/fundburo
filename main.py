from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from math import radians, sin, cos, sqrt, atan2
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import SessionLocal
from models import AppUser, Item, ItemMatch


app = FastAPI(title="LostAndFound API")

GEOCODER_URL = "https://nominatim.openstreetmap.org/search"
GEOCODER_USER_AGENT = "LostAndFound/1.0 (contact: support@lostandfound.local)"
AI_EXTRACT_URL = os.getenv("AI_EXTRACT_URL", "https://api.openai.com/v1/chat/completions")
AI_EXTRACT_MODEL = os.getenv("AI_EXTRACT_MODEL", "gpt-4o-mini")
AI_EXTRACT_API_KEY = os.getenv("AI_EXTRACT_API_KEY")


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


class FreeTextCreate(BaseModel):
    item_type: str
    free_text: str


class ExtractedItemFields(BaseModel):
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


class FreeTextExtractResponse(BaseModel):
    item_type: str
    free_text: str
    extracted_fields: ExtractedItemFields
    missing_fields: list[str]


class IntakeApproveRequest(BaseModel):
    username: str
    email: EmailStr
    item_type: str
    free_text: str | None = None
    extracted_fields: ExtractedItemFields


class IntakeApproveResponse(BaseModel):
    user_id: int
    item_id: int
    item_type: str
    status: str

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


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lost_item_id: int
    found_item_id: int
    score: Decimal
    confidence: str
    created_at: datetime


def calculate_matches_for_item(db: Session, item: Item) -> list[MatchItem]:
    reverse_type = "found" if item.item_type == "lost" else "lost"
    target_items_stmt = select(Item).where(
        Item.item_type == reverse_type,
        Item.status == "active",
    )
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

        if item.lat is not None and target_item.lat is not None:
            if item.lng is not None and target_item.lng is not None:
                distance = distance_km(item.lat, item.lng, target_item.lat, target_item.lng)
                if distance <= 3:
                    match_score += 0.3

        if match_score >= 0.4:
            confidence = "high" if match_score >= 0.6 else "medium"
            lost_id = item.id if item.item_type == "lost" else target_item.id
            found_id = item.id if item.item_type == "found" else target_item.id

            existing_match_stmt = select(ItemMatch).where(
                ItemMatch.lost_item_id == lost_id,
                ItemMatch.found_item_id == found_id,
            )
            existing_match = db.scalar(existing_match_stmt)

            if existing_match is None:
                item_match = ItemMatch(
                    lost_item_id=lost_id,
                    found_item_id=found_id,
                    score=Decimal(str(match_score)),
                    confidence=confidence,
                )
                db.add(item_match)
            else:
                existing_match.score = Decimal(str(match_score))
                existing_match.confidence = confidence

            match = MatchItem(
                lost_item_id=lost_id,
                found_item_id=found_id,
                score=Decimal(str(match_score)),
                confidence=confidence,
            )
            matches.append(match)

    db.commit()
    return matches


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def parse_iso_datetime(value: str | None) -> datetime | None:
    normalized = normalize_text(value)
    if normalized is None:
        return None

    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None


def sanitize_address_text(value: str | None) -> str | None:
    normalized = normalize_text(value)
    if normalized is None:
        return None

    cleaned = re.sub(
        r"\s+(?:on|around|at)\s+\d{4}-\d{2}-\d{2}.*$",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    return cleaned or None


def heuristic_extract_fields(free_text: str) -> dict:
    address_match = re.search(
        r"(?:near|at|in)\s+([A-Za-z0-9\s,.-]+?)(?=\s+(?:on|around)\s+\d{4}-\d{2}-\d{2}|$)",
        free_text,
        flags=re.IGNORECASE,
    )
    event_time_match = re.search(
        r"(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)",
        free_text,
    )

    return {
        "description": free_text,
        "color": None,
        "size": None,
        "usage": None,
        "address_text": sanitize_address_text(address_match.group(1)) if address_match else None,
        "lat": None,
        "lng": None,
        "event_time": event_time_match.group(1) if event_time_match else None,
        "feel": None,
        "smell": None,
        "model": None,
        "image_url": None,
    }


def extract_fields_with_ai(item_type: str, free_text: str) -> dict:
    if not AI_EXTRACT_API_KEY:
        return heuristic_extract_fields(free_text)

    system_prompt = (
        "You extract structured data for a lost-and-found application in Berlin. "
        "Return JSON only with keys: description,color,size,usage,address_text,lat,lng,"
        "event_time,feel,smell,model,image_url. "
        "description must preserve user intent and include the core object description. "
        "If a field is unknown, set it to null. "
        "event_time must be ISO-8601 with timezone when possible."
    )

    user_prompt = (
        f"Item type: {item_type}\n"
        f"Free text:\n{free_text}"
    )

    request_payload = {
        "model": AI_EXTRACT_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    request = Request(
        url=AI_EXTRACT_URL,
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {AI_EXTRACT_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
    except Exception:
        pass

    return heuristic_extract_fields(free_text)


def normalize_extracted_fields(raw_fields: dict, free_text: str) -> dict:
    description = normalize_text(raw_fields.get("description")) or free_text

    normalized = {
        "description": description,
        "color": normalize_text(raw_fields.get("color")),
        "size": normalize_text(raw_fields.get("size")),
        "usage": normalize_text(raw_fields.get("usage")),
        "address_text": sanitize_address_text(raw_fields.get("address_text")),
        "lat": raw_fields.get("lat"),
        "lng": raw_fields.get("lng"),
        "event_time": raw_fields.get("event_time"),
        "feel": normalize_text(raw_fields.get("feel")),
        "smell": normalize_text(raw_fields.get("smell")),
        "model": normalize_text(raw_fields.get("model")),
        "image_url": normalize_text(raw_fields.get("image_url")),
    }

    if isinstance(normalized["event_time"], str):
        normalized["event_time"] = parse_iso_datetime(normalized["event_time"])

    return normalized


def compute_missing_required_fields(fields: dict) -> list[str]:
    missing_fields: list[str] = []
    if not fields.get("description"):
        missing_fields.append("description")
    if not fields.get("address_text"):
        missing_fields.append("address_text")
    if fields.get("event_time") is None:
        missing_fields.append("event_time")
    return missing_fields


def geocode_address(address_text: str) -> tuple[float | None, float | None]:
    normalized_address = address_text.strip()
    if not normalized_address:
        return None, None

    query = normalized_address
    if "berlin" not in normalized_address.lower():
        query = f"{normalized_address}, Berlin, Germany"

    query_params = urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
        }
    )
    request = Request(
        url=f"{GEOCODER_URL}?{query_params}",
        headers={"User-Agent": GEOCODER_USER_AGENT},
    )

    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None, None

    if not payload:
        return None, None

    first_result = payload[0]
    lat = first_result.get("lat")
    lng = first_result.get("lon")
    if lat is None or lng is None:
        return None, None

    try:
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None, None


def resolve_coordinates(
    address_text: str | None,
    lat: float | None,
    lng: float | None,
) -> tuple[float | None, float | None]:
    lat_missing = lat is None or lat == 0.0
    lng_missing = lng is None or lng == 0.0

    if not lat_missing and not lng_missing:
        return lat, lng

    if address_text is None or not address_text.strip():
        return lat, lng

    geocoded_lat, geocoded_lng = geocode_address(address_text)

    final_lat = geocoded_lat if lat_missing else lat
    final_lng = geocoded_lng if lng_missing else lng
    return final_lat, final_lng

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

    lat, lng = resolve_coordinates(
        address_text=payload.address_text,
        lat=payload.lat,
        lng=payload.lng,
    )

    item = Item(
        user_id=user.id,
        item_type="lost",
        description=payload.description,
        color=payload.color,
        size=payload.size,
        usage=payload.usage,
        address_text=payload.address_text,
        lat=lat,
        lng=lng,
        event_time=payload.event_time,
        feel=payload.feel,
        smell=payload.smell,
        model=payload.model,
        image_url=payload.image_url,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    calculate_matches_for_item(db, item)

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

    lat, lng = resolve_coordinates(
        address_text=payload.address_text,
        lat=payload.lat,
        lng=payload.lng,
    )

    item = Item(
        user_id=user.id,
        item_type="found",
        description=payload.description,
        color=payload.color,
        size=payload.size,
        usage=payload.usage,
        address_text=payload.address_text,
        lat=lat,
        lng=lng,
        event_time=payload.event_time,
        feel=payload.feel,
        smell=payload.smell,
        model=payload.model,
        image_url=payload.image_url,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    calculate_matches_for_item(db, item)

    return ReportCreateResponse(user_id=user.id, item_id=item.id, status=item.status)


@app.post("/intake/extract", response_model=FreeTextExtractResponse)
def extract_freetext(payload: FreeTextCreate):
    if payload.item_type not in {"lost", "found"}:
        raise HTTPException(status_code=400, detail="item_type must be 'lost' or 'found'")

    normalized_text = payload.free_text.strip()
    if not normalized_text:
        raise HTTPException(status_code=400, detail="free_text cannot be empty")

    ai_fields = extract_fields_with_ai(payload.item_type, normalized_text)
    normalized_fields = normalize_extracted_fields(ai_fields, normalized_text)
    missing_fields = compute_missing_required_fields(normalized_fields)

    return FreeTextExtractResponse(
        item_type=payload.item_type,
        free_text=normalized_text,
        extracted_fields=ExtractedItemFields(**normalized_fields),
        missing_fields=missing_fields,
    )


@app.post("/intake/approve", response_model=IntakeApproveResponse)
def approve_intake(payload: IntakeApproveRequest, db: Session = Depends(get_db)):
    if payload.item_type not in {"lost", "found"}:
        raise HTTPException(status_code=400, detail="item_type must be 'lost' or 'found'")

    extracted = payload.extracted_fields.model_dump()
    if payload.free_text is not None and payload.free_text.strip():
        extracted["description"] = payload.free_text.strip()

    missing_fields = compute_missing_required_fields(extracted)
    if missing_fields:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Missing required fields for approval",
                "missing_fields": missing_fields,
            },
        )

    user_stmt = select(AppUser).where(AppUser.email == payload.email)
    user = db.scalar(user_stmt)

    user_role = "claimer" if payload.item_type == "lost" else "reporter"
    if user is None:
        user = AppUser(username=payload.username, email=payload.email, role=user_role)
        db.add(user)
        db.flush()

    lat, lng = resolve_coordinates(
        address_text=extracted.get("address_text"),
        lat=extracted.get("lat"),
        lng=extracted.get("lng"),
    )

    if lat is None or lng is None:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Unable to resolve coordinates from address_text",
                "address_text": extracted.get("address_text"),
            },
        )

    item = Item(
        user_id=user.id,
        item_type=payload.item_type,
        description=extracted["description"],
        color=extracted.get("color"),
        size=extracted.get("size"),
        usage=extracted.get("usage"),
        address_text=extracted.get("address_text"),
        lat=lat,
        lng=lng,
        event_time=extracted.get("event_time"),
        feel=extracted.get("feel"),
        smell=extracted.get("smell"),
        model=extracted.get("model"),
        image_url=extracted.get("image_url"),
    )

    db.add(item)
    db.commit()
    db.refresh(item)
    calculate_matches_for_item(db, item)

    return IntakeApproveResponse(
        user_id=user.id,
        item_id=item.id,
        item_type=item.item_type,
        status=item.status,
    )

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
    matches = calculate_matches_for_item(db, item)
    return MatchCreateResponse(item_id = item.id, list_of_matches = matches, date = datetime.now(timezone.utc))


@app.get("/matches", response_model=list[MatchOut])
def get_matches(db: Session = Depends(get_db)):
    stmt = select(ItemMatch).order_by(ItemMatch.created_at.desc())
    return db.scalars(stmt).all()

def distance_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    rlat1 = radians(lat1)
    rlat2 = radians(lat2)
    a = sin(dlat/2)**2 + cos(rlat1) * cos(rlat2) * sin(dlng/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    distance = r * c
    return distance

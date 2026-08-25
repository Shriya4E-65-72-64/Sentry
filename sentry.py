import logging
from datetime import datetime
from typing import List, Optional

import httpx
import pandas as pd
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Boolean,
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, Session

DATABASE_URL = "sqlite:///./sentry.db" #baad me rakh lenge jo bhi rakhenge

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    condition = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    logs = relationship("SymptomLog", back_populates="user", cascade="all, delete-orphan")
    insights = relationship("TriggerInsight", back_populates="user", cascade="all, delete-orphan")


class SymptomLog(Base):
    __tablename__ = "symptom_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    is_flare = Column(Boolean, nullable=False, default=True)
    severity = Column(Integer, nullable=True)
    notes = Column(String, nullable=True)

    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    logged_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    temperature_c = Column(Float, nullable=True)
    humidity_pct = Column(Float, nullable=True)
    pressure_hpa = Column(Float, nullable=True)
    pm2_5 = Column(Float, nullable=True)
    pm10 = Column(Float, nullable=True)
    us_aqi = Column(Float, nullable=True)

    user = relationship("User", back_populates="logs")


class TriggerInsight(Base):
    __tablename__ = "trigger_insights"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    factor = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    threshold = Column(Float, nullable=False)
    confidence_pct = Column(Float, nullable=False)
    support_count = Column(Integer, nullable=False)
    human_summary = Column(String, nullable=False)
    computed_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="insights")


class UserCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    condition: str = Field(..., min_length=1, max_length=100)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    condition: str
    created_at: datetime


class SymptomLogCreate(BaseModel):
    user_id: int
    is_flare: bool = True
    severity: Optional[int] = Field(None, ge=1, le=5)
    notes: Optional[str] = Field(None, max_length=500)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    logged_at: Optional[datetime] = None


class SymptomLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    is_flare: bool
    severity: Optional[int]
    notes: Optional[str]
    latitude: float
    longitude: float
    logged_at: datetime
    temperature_c: Optional[float]
    humidity_pct: Optional[float]
    pressure_hpa: Optional[float]
    pm2_5: Optional[float]
    pm10: Optional[float]
    us_aqi: Optional[float]


class TriggerInsightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    factor: str
    direction: str
    threshold: float
    confidence_pct: float
    support_count: int
    human_summary: str
    computed_at: datetime


class InsightsResponse(BaseModel):
    user_id: int
    total_flare_logs: int
    total_baseline_logs: int
    insights: List[TriggerInsightOut]
    message: str


class AlertCheckRequest(BaseModel):
    user_id: int
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class AlertResponse(BaseModel):
    user_id: int
    at_risk: bool
    triggered_factors: List[str]
    message: str
    current_conditions: dict


logger = logging.getLogger("sentry")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
REQUEST_TIMEOUT_SECONDS = 6.0


async def fetch_current_weather(latitude: float, longitude: float) -> dict:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,surface_pressure",
    }
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.get(WEATHER_URL, params=params)
            resp.raise_for_status()
            current = resp.json().get("current", {})
            return {
                "temperature_c": current.get("temperature_2m"),
                "humidity_pct": current.get("relative_humidity_2m"),
                "pressure_hpa": current.get("surface_pressure"),
            }
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Weather fetch failed: %s", exc)
        return {}


async def fetch_current_air_quality(latitude: float, longitude: float) -> dict:
    params = {"latitude": latitude, "longitude": longitude, "current": "pm2_5,pm10,us_aqi"}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.get(AIR_QUALITY_URL, params=params)
            resp.raise_for_status()
            current = resp.json().get("current", {})
            return {
                "pm2_5": current.get("pm2_5"),
                "pm10": current.get("pm10"),
                "us_aqi": current.get("us_aqi"),
            }
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Air quality fetch failed: %s", exc)
        return {}


async def get_environmental_snapshot(latitude: float, longitude: float) -> dict:
    weather = await fetch_current_weather(latitude, longitude)
    air = await fetch_current_air_quality(latitude, longitude)
    return {
        "temperature_c": weather.get("temperature_c"),
        "humidity_pct": weather.get("humidity_pct"),
        "pressure_hpa": weather.get("pressure_hpa"),
        "pm2_5": air.get("pm2_5"),
        "pm10": air.get("pm10"),
        "us_aqi": air.get("us_aqi"),
    }

#ok
FACTORS = [
    ("temperature_c", "temperature", "°C"),
    ("humidity_pct", "humidity", "%"),
    ("pressure_hpa", "barometric pressure", "hPa"),
    ("pm2_5", "PM2.5 particulate matter", "µg/m³"),
    ("pm10", "PM10 particulate matter", "µg/m³"),
    ("us_aqi", "air quality index", "AQI"),
]
MIN_FLARE_LOGS_FOR_INSIGHT = 5
MIN_CONFIDENCE_GAP_PCT = 20.0


class TriggerCandidate:
    def __init__(self, factor, direction, threshold, confidence_pct, support_count, human_summary):
        self.factor = factor
        self.direction = direction
        self.threshold = threshold
        self.confidence_pct = confidence_pct
        self.support_count = support_count
        self.human_summary = human_summary


def _analyze_factor(df: pd.DataFrame, column: str, label: str, unit: str) -> Optional[TriggerCandidate]:
    valid = df.dropna(subset=[column])
    if valid.empty:
        return None

    median_value = valid[column].median()
    flare_rows = valid[valid["is_flare"]]
    baseline_rows = valid[~valid["is_flare"]]

    if len(flare_rows) < MIN_FLARE_LOGS_FOR_INSIGHT:
        return None

    flare_above_pct = (flare_rows[column] > median_value).mean() * 100 if len(flare_rows) else 0.0
    baseline_above_pct = (
        (baseline_rows[column] > median_value).mean() * 100 if len(baseline_rows) else 50.0
    )

    gap = flare_above_pct - baseline_above_pct
    if abs(gap) < MIN_CONFIDENCE_GAP_PCT:
        return None

    direction = "above" if gap > 0 else "below"
    confidence_pct = flare_above_pct if direction == "above" else (100 - flare_above_pct)

    summary = (
        f"Your flares are notably more common when {label} is {direction} "
        f"{median_value:.1f}{unit} -- {confidence_pct:.0f}% of your logged "
        f"flares happened under that condition, based on {len(flare_rows)} flare entries."
    )

    return TriggerCandidate(column, direction, float(median_value), float(confidence_pct), int(len(flare_rows)), summary)


def compute_trigger_insights(logs: List[SymptomLog]) -> List[TriggerCandidate]:
    if not logs:
        return []

    records = [
        {
            "is_flare": log.is_flare,
            "temperature_c": log.temperature_c,
            "humidity_pct": log.humidity_pct,
            "pressure_hpa": log.pressure_hpa,
            "pm2_5": log.pm2_5,
            "pm10": log.pm10,
            "us_aqi": log.us_aqi,
        }
        for log in logs
    ]
    df = pd.DataFrame.from_records(records)

    candidates = []
    for column, label, unit in FACTORS:
        result = _analyze_factor(df, column, label, unit)
        if result:
            candidates.append(result)

    candidates.sort(key=lambda c: c.confidence_pct, reverse=True)
    return candidates


class AlertResult:
    def __init__(self, at_risk: bool, triggered_factors: List[str], message: str):
        self.at_risk = at_risk
        self.triggered_factors = triggered_factors
        self.message = message


def check_current_risk(insights: List[TriggerInsight], current_conditions: dict) -> AlertResult:
    triggered_factors = []
    triggered_messages = []

    for insight in insights:
        current_value = current_conditions.get(insight.factor)
        if current_value is None:
            continue

        is_triggered = (
            current_value > insight.threshold
            if insight.direction == "above"
            else current_value < insight.threshold
        )
        if is_triggered:
            triggered_factors.append(insight.factor)
            triggered_messages.append(
                f"{insight.factor.replace('_', ' ')} is currently {current_value:.1f}, "
                f"{insight.direction} your usual threshold of {insight.threshold:.1f} "
                f"({insight.confidence_pct:.0f}% historical match)"
            )

    if not triggered_factors:
        return AlertResult(False, [], "Current conditions don't match any known flare pattern.")

    return AlertResult(True, triggered_factors, "Elevated flare risk detected: " + "; ".join(triggered_messages) + ".")


Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Project Sentry API",
    description="Logs chronic-condition flares, auto-enriches with environmental "
    "data, and surfaces which ecological factors are driving symptoms.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def health_check():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED, tags=["users"])
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    user = User(name=payload.name, condition=payload.condition)
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("Created user id=%s condition=%s", user.id, user.condition)
    return user


@app.get("/users/{user_id}", response_model=UserOut, tags=["users"])
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.post("/logs", response_model=SymptomLogOut, status_code=status.HTTP_201_CREATED, tags=["logs"])
async def create_log(payload: SymptomLogCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == payload.user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    snapshot = await get_environmental_snapshot(payload.latitude, payload.longitude)

    log = SymptomLog(
        user_id=payload.user_id,
        is_flare=payload.is_flare,
        severity=payload.severity,
        notes=payload.notes,
        latitude=payload.latitude,
        longitude=payload.longitude,
        logged_at=payload.logged_at or datetime.utcnow(),
        **snapshot,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    logger.info("Logged entry id=%s user_id=%s is_flare=%s", log.id, log.user_id, log.is_flare)
    return log


@app.get("/logs/{user_id}", response_model=List[SymptomLogOut], tags=["logs"])
def list_logs(user_id: int, db: Session = Depends(get_db)):
    return (
        db.query(SymptomLog)
        .filter(SymptomLog.user_id == user_id)
        .order_by(SymptomLog.logged_at.desc())
        .all()
    )


@app.get("/insights/{user_id}", response_model=InsightsResponse, tags=["insights"])
def get_insights(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    logs = db.query(SymptomLog).filter(SymptomLog.user_id == user_id).all()
    flare_count = sum(1 for log in logs if log.is_flare)
    baseline_count = len(logs) - flare_count

    candidates = compute_trigger_insights(logs)
    db.query(TriggerInsight).filter(TriggerInsight.user_id == user_id).delete()

    if not candidates:
        db.commit()
        message = (
            "Not enough data yet to identify confident trigger patterns. Keep logging."
            if flare_count < MIN_FLARE_LOGS_FOR_INSIGHT
            else "No environmental factor showed a strong enough pattern yet."
        )
        return InsightsResponse(
            user_id=user_id, total_flare_logs=flare_count,
            total_baseline_logs=baseline_count, insights=[], message=message,
        )

    saved = []
    for c in candidates:
        insight = TriggerInsight(
            user_id=user_id, factor=c.factor, direction=c.direction,
            threshold=c.threshold, confidence_pct=c.confidence_pct,
            support_count=c.support_count, human_summary=c.human_summary,
        )
        db.add(insight)
        saved.append(insight)

    db.commit()
    for insight in saved:
        db.refresh(insight)

    return InsightsResponse(
        user_id=user_id, total_flare_logs=flare_count, total_baseline_logs=baseline_count,
        insights=saved, message=f"Found {len(saved)} likely trigger pattern(s).",
    )


@app.post("/alerts/check", response_model=AlertResponse, tags=["alerts"])
async def check_alert(payload: AlertCheckRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == payload.user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    insights = db.query(TriggerInsight).filter(TriggerInsight.user_id == payload.user_id).all()

    if not insights:
        return AlertResponse(
            user_id=payload.user_id, at_risk=False, triggered_factors=[],
            message="No trigger patterns learned yet -- log more flares first.",
            current_conditions={},
        )

    snapshot = await get_environmental_snapshot(payload.latitude, payload.longitude)
    result = check_current_risk(insights, snapshot)

    return AlertResponse(
        user_id=payload.user_id, at_risk=result.at_risk,
        triggered_factors=result.triggered_factors, message=result.message,
        current_conditions=snapshot,
    )

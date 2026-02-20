import os
import uuid
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from typing import Optional, Union
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy.orm import Session

load_dotenv()

from logger import get_logger
from database import engine, get_db, Base
from models.common import CloudProvider
from models.credentials import AWSCredentials, GCPCredentials, AzureCredentials
from models.database_models import User, CloudCredential
from providers.factory import ProviderFactory
from services.ai_recommendations import generate_recommendations
from services.chat_agent import run_chat
from services.resource_deep_dive import deep_dive_top_services, demo_deep_dive
from services.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
)
from services.encryption import encrypt_credentials, decrypt_credentials

log = get_logger("main")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# In-memory chat sessions
CHAT_SESSIONS: dict = {}

app = FastAPI(title="Cloud Cost Optimizer API")

# Auto-create tables on startup
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic request/response models ────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    provider: CloudProvider
    credentials: Union[AWSCredentials, GCPCredentials, AzureCredentials]


class AnalyzeByCredentialRequest(BaseModel):
    credential_id: str
    provider: Optional[CloudProvider] = None  # inferred from stored credential if omitted


class RecommendationsRequest(BaseModel):
    analysis_data: dict
    api_key: Optional[str] = None


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    credentials: Optional[dict] = None
    credential_id: Optional[str] = None
    demo: bool = False


class SignupRequest(BaseModel):
    username: str
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class CredentialCreate(BaseModel):
    provider: str  # aws / gcp / azure
    label: str
    credentials: dict  # raw creds – will be encrypted at rest
    region: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _cleanup_sessions():
    """Remove sessions older than 1 hour."""
    cutoff = datetime.now() - timedelta(hours=1)
    expired = [k for k, v in CHAT_SESSIONS.items() if v["created_at"] < cutoff]
    for k in expired:
        del CHAT_SESSIONS[k]


def _resolve_credentials(credential_id: str, user: User, db: Session):
    """Look up a stored credential and decrypt it. Returns (creds_dict, provider, region)."""
    cred = (
        db.query(CloudCredential)
        .filter(CloudCredential.id == credential_id, CloudCredential.user_id == user.id)
        .first()
    )
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    decrypted = decrypt_credentials(cred.encrypted_data)
    return decrypted, cred.provider, cred.region


# ── Auth endpoints (public) ─────────────────────────────────────────────────

@app.post("/api/auth/signup")
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == body.username).first()
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(str(user.id), user.username)
    return {"token": token, "username": user.username}


@app.post("/api/auth/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(str(user.id), user.username)
    return {"token": token, "username": user.username}


# ── Credential CRUD (protected) ─────────────────────────────────────────────

@app.get("/api/credentials")
def list_credentials(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    creds = (
        db.query(CloudCredential)
        .filter(CloudCredential.user_id == user.id)
        .order_by(CloudCredential.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(c.id),
            "provider": c.provider,
            "label": c.label,
            "region": c.region,
            "created_at": str(c.created_at),
        }
        for c in creds
    ]


@app.post("/api/credentials")
def save_credential(
    body: CredentialCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cred = CloudCredential(
        user_id=user.id,
        provider=body.provider,
        label=body.label,
        encrypted_data=encrypt_credentials(body.credentials),
        region=body.region,
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return {
        "id": str(cred.id),
        "provider": cred.provider,
        "label": cred.label,
        "region": cred.region,
    }


class CredentialUpdate(BaseModel):
    credentials: dict  # partial or full – merged into stored creds
    region: Optional[str] = None


@app.patch("/api/credentials/{credential_id}")
def update_credential(
    credential_id: str,
    body: CredentialUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Merge new values (e.g. a refreshed session token) into a stored credential."""
    cred = (
        db.query(CloudCredential)
        .filter(CloudCredential.id == credential_id, CloudCredential.user_id == user.id)
        .first()
    )
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    existing = decrypt_credentials(cred.encrypted_data)
    existing.update({k: v for k, v in body.credentials.items() if v})
    cred.encrypted_data = encrypt_credentials(existing)
    if body.region:
        cred.region = body.region

    db.commit()
    db.refresh(cred)
    log.info("Credential updated | id=%s user=%s", credential_id, user.username)
    return {"id": str(cred.id), "provider": cred.provider, "label": cred.label, "region": cred.region}


@app.delete("/api/credentials/{credential_id}")
def delete_credential(
    credential_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cred = (
        db.query(CloudCredential)
        .filter(CloudCredential.id == credential_id, CloudCredential.user_id == user.id)
        .first()
    )
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    db.delete(cred)
    db.commit()
    return {"detail": "Deleted"}


# ── Chat (protected) ────────────────────────────────────────────────────────

@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI chat agent that can make AWS API calls to investigate cost questions."""
    _cleanup_sessions()

    # Resolve credentials from credential_id if provided
    aws_credentials = request.credentials
    if request.credential_id and not request.demo:
        decrypted, _provider, region = _resolve_credentials(request.credential_id, user, db)
        aws_credentials = {**decrypted, "region": region or "us-east-1"}

    # Get or create session
    session_id = request.session_id
    if session_id and session_id in CHAT_SESSIONS:
        session = CHAT_SESSIONS[session_id]
    else:
        session_id = str(uuid.uuid4())
        session = {
            "messages": [],
            "aws_credentials": aws_credentials,
            "region": (aws_credentials or {}).get("region", "us-east-1"),
            "analysis_context": "",
            "created_at": datetime.now(),
            "demo": request.demo,
        }
        CHAT_SESSIONS[session_id] = session

    # Update credentials if provided
    if aws_credentials:
        session["aws_credentials"] = aws_credentials
        session["region"] = aws_credentials.get("region", "us-east-1")

    # Add user message
    session["messages"].append({"role": "user", "content": request.message})

    try:
        response_text, tools_used = run_chat(
            messages=session["messages"],
            aws_creds=session["aws_credentials"],
            region=session["region"],
            analysis_context=session["analysis_context"],
            demo=session.get("demo", request.demo),
        )

        session["messages"].append({"role": "assistant", "content": response_text})

        return {
            "session_id": session_id,
            "response": response_text,
            "tools_used": tools_used,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")


# ── Public endpoints ─────────────────────────────────────────────────────────

@app.get("/")
def read_root():
    return {
        "message": "Cloud Cost Optimizer API",
        "version": "2.0",
        "supported_providers": ProviderFactory.get_supported_providers(),
    }


@app.get("/api/demo")
def demo_report():
    """Return a realistic demo report with rich sample data."""
    top_services = [
        {"service": "Amazon Elastic Compute Cloud", "cost": 4230.50},
        {"service": "Amazon Relational Database Service", "cost": 2150.75},
        {"service": "Amazon Simple Storage Service", "cost": 890.20},
        {"service": "AWS Lambda", "cost": 645.30},
        {"service": "Amazon CloudFront", "cost": 432.10},
        {"service": "Amazon DynamoDB", "cost": 310.45},
        {"service": "Amazon Elastic Load Balancing", "cost": 275.80},
        {"service": "Amazon ElastiCache", "cost": 198.60},
        {"service": "AWS Key Management Service", "cost": 85.25},
        {"service": "Amazon Route 53", "cost": 52.40},
    ]

    idle_instances = [
        {
            "instance_id": "i-0a1b2c3d4e5f60001",
            "instance_type": "m5.xlarge",
            "estimated_monthly_cost": 140.00,
            "recommendation": "Idle: Avg CPU 1.2% (<5%), network 0.34 MB/hr (<1 MB/hr). Stop or terminate to save costs.",
            "avg_cpu": 1.2, "max_cpu": 4.8, "avg_network_in": 180000, "avg_network_out": 160000,
        },
        {
            "instance_id": "i-0a1b2c3d4e5f60002",
            "instance_type": "t3.medium",
            "estimated_monthly_cost": 30.00,
            "recommendation": "Idle: Avg CPU 0.5% (<5%), network 0.12 MB/hr (<1 MB/hr). Stop or terminate to save costs.",
            "avg_cpu": 0.5, "max_cpu": 2.1, "avg_network_in": 65000, "avg_network_out": 55000,
        },
        {
            "instance_id": "i-0a1b2c3d4e5f60003",
            "instance_type": "c5.large",
            "estimated_monthly_cost": 62.00,
            "recommendation": "Idle: Avg CPU 3.1% (<5%), network 0.78 MB/hr (<1 MB/hr). Stop or terminate to save costs.",
            "avg_cpu": 3.1, "max_cpu": 12.5, "avg_network_in": 420000, "avg_network_out": 360000,
        },
        {
            "instance_id": "i-0a1b2c3d4e5f60004",
            "instance_type": "r5.large",
            "estimated_monthly_cost": 91.00,
            "recommendation": "Idle: Avg CPU 2.4% (<5%), network 0.45 MB/hr (<1 MB/hr). Stop or terminate to save costs.",
            "avg_cpu": 2.4, "max_cpu": 8.3, "avg_network_in": 250000, "avg_network_out": 200000,
        },
        {
            "instance_id": "i-0a1b2c3d4e5f60005",
            "instance_type": "t2.small",
            "estimated_monthly_cost": 17.00,
            "recommendation": "Idle: Avg CPU 0.8% (<5%), network 0.05 MB/hr (<1 MB/hr). Stop or terminate to save costs.",
            "avg_cpu": 0.8, "max_cpu": 3.2, "avg_network_in": 28000, "avg_network_out": 22000,
        },
    ]

    unattached_volumes = [
        {"volume_id": "vol-0a1b2c3d4e5f6001", "size_gb": 500, "volume_type": "gp3", "estimated_monthly_cost": 50.00, "recommendation": "Delete if not needed"},
        {"volume_id": "vol-0a1b2c3d4e5f6002", "size_gb": 1000, "volume_type": "gp2", "estimated_monthly_cost": 100.00, "recommendation": "Delete if not needed"},
        {"volume_id": "vol-0a1b2c3d4e5f6003", "size_gb": 200, "volume_type": "io1", "estimated_monthly_cost": 20.00, "recommendation": "Delete if not needed"},
        {"volume_id": "vol-0a1b2c3d4e5f6004", "size_gb": 750, "volume_type": "gp3", "estimated_monthly_cost": 75.00, "recommendation": "Delete if not needed"},
    ]

    old_snapshots = [
        {"snapshot_id": "snap-0a1b2c3d4e5f6001", "size_gb": 500, "created_date": "2025-06-15", "age_days": 243, "estimated_monthly_cost": 25.00, "recommendation": "Review and delete if not needed"},
        {"snapshot_id": "snap-0a1b2c3d4e5f6002", "size_gb": 200, "created_date": "2025-08-20", "age_days": 177, "estimated_monthly_cost": 10.00, "recommendation": "Review and delete if not needed"},
        {"snapshot_id": "snap-0a1b2c3d4e5f6003", "size_gb": 1000, "created_date": "2025-05-01", "age_days": 288, "estimated_monthly_cost": 50.00, "recommendation": "Review and delete if not needed"},
        {"snapshot_id": "snap-0a1b2c3d4e5f6004", "size_gb": 100, "created_date": "2025-09-10", "age_days": 156, "estimated_monthly_cost": 5.00, "recommendation": "Review and delete if not needed"},
        {"snapshot_id": "snap-0a1b2c3d4e5f6005", "size_gb": 300, "created_date": "2025-07-05", "age_days": 223, "estimated_monthly_cost": 15.00, "recommendation": "Review and delete if not needed"},
    ]

    resource_costs = [
        {"resource_id": "i-0a1b2c3d4e5f60010", "resource_type": "ec2", "service": "Amazon Elastic Compute Cloud", "cost": 892.50, "name": "prod-api-server-1"},
        {"resource_id": "i-0a1b2c3d4e5f60011", "resource_type": "ec2", "service": "Amazon Elastic Compute Cloud", "cost": 743.20, "name": "prod-api-server-2"},
        {"resource_id": "i-0a1b2c3d4e5f60012", "resource_type": "ec2", "service": "Amazon Elastic Compute Cloud", "cost": 560.00, "name": "prod-worker-1"},
        {"resource_id": "i-0a1b2c3d4e5f60013", "resource_type": "ec2", "service": "Amazon Elastic Compute Cloud", "cost": 420.80, "name": "staging-api"},
        {"resource_id": "db-prod-main-cluster", "resource_type": "rds", "service": "Amazon Relational Database Service", "cost": 1250.00, "name": "prod-postgres-main"},
        {"resource_id": "db-prod-read-replica", "resource_type": "rds", "service": "Amazon Relational Database Service", "cost": 625.00, "name": "prod-postgres-replica"},
        {"resource_id": "db-staging-001", "resource_type": "rds", "service": "Amazon Relational Database Service", "cost": 275.75, "name": "staging-postgres"},
        {"resource_id": "prod-assets-bucket", "resource_type": "s3", "service": "Amazon Simple Storage Service", "cost": 340.20, "name": "prod-assets-bucket"},
        {"resource_id": "prod-logs-bucket", "resource_type": "s3", "service": "Amazon Simple Storage Service", "cost": 285.00, "name": "prod-logs-bucket"},
        {"resource_id": "prod-backups-bucket", "resource_type": "s3", "service": "Amazon Simple Storage Service", "cost": 165.00, "name": "prod-backups-bucket"},
        {"resource_id": "i-0a1b2c3d4e5f60014", "resource_type": "ec2", "service": "Amazon Elastic Compute Cloud", "cost": 350.00, "name": "prod-worker-2"},
        {"resource_id": "cache-prod-001", "resource_type": "elasticache", "service": "Amazon ElastiCache", "cost": 198.60, "name": "prod-redis"},
        {"resource_id": "i-0a1b2c3d4e5f60015", "resource_type": "ec2", "service": "Amazon Elastic Compute Cloud", "cost": 264.00, "name": "dev-server"},
        {"resource_id": "data-lake-bucket", "resource_type": "s3", "service": "Amazon Simple Storage Service", "cost": 100.00, "name": "data-lake-bucket"},
        {"resource_id": "i-0a1b2c3d4e5f60001", "resource_type": "ec2", "service": "Amazon Elastic Compute Cloud", "cost": 140.00, "name": "idle-test-server"},
    ]

    today = datetime.now().date()
    anomalies = [
        {
            "date": str(today - timedelta(days=10)),
            "service": "Amazon Elastic Compute Cloud",
            "expected_cost": 145.00, "actual_cost": 312.50, "impact": 167.50,
            "impact_percentage": 115.5, "severity": "critical", "source": "statistical",
            "description": "Daily EC2 cost $312.50 is 3.2 std devs above 7-day rolling avg ($145.00)",
        },
        {
            "date": str(today - timedelta(days=5)),
            "service": "Amazon Relational Database Service",
            "expected_cost": 72.00, "actual_cost": 148.30, "impact": 76.30,
            "impact_percentage": 105.9, "severity": "medium", "source": "statistical",
            "description": "Daily RDS cost $148.30 is 2.4 std devs above 7-day rolling avg ($72.00)",
        },
        {
            "date": str(today - timedelta(days=18)),
            "service": "AWS Lambda",
            "expected_cost": 22.00, "actual_cost": 89.50, "impact": 67.50,
            "impact_percentage": 306.8, "severity": "high", "source": "aws",
            "description": "AWS detected anomaly: $67.50 above expected spend",
        },
        {
            "date": str(today - timedelta(days=3)),
            "service": "Amazon Simple Storage Service",
            "expected_cost": 30.00, "actual_cost": 52.40, "impact": 22.40,
            "impact_percentage": 74.7, "severity": "low", "source": "statistical",
            "description": "Daily S3 cost $52.40 is 2.1 std devs above 7-day rolling avg ($30.00)",
        },
    ]

    idle_savings = sum(i["estimated_monthly_cost"] for i in idle_instances)
    volume_savings = sum(v["estimated_monthly_cost"] for v in unattached_volumes)
    snapshot_savings = sum(s["estimated_monthly_cost"] for s in old_snapshots)
    total_savings = idle_savings + volume_savings + snapshot_savings

    demo_result = {
        "provider": "aws",
        "monthly_cost": {
            "total_cost": 9271.35, "projected_cost": 19966.00,
            "days_elapsed": 13, "days_in_month": 28,
            "currency": "USD", "period": "2026-02-01 to 2026-02-13",
        },
        "daily_costs": _generate_demo_daily_costs(),
        "daily_costs_by_service": _generate_demo_daily_costs_by_service(),
        "top_services": top_services,
        "resource_costs": resource_costs,
        "savings_opportunities": {
            "total_potential_savings": round(total_savings, 2),
            "idle_ec2_instances": {"count": len(idle_instances), "potential_savings": round(idle_savings, 2), "items": idle_instances},
            "unattached_ebs_volumes": {"count": len(unattached_volumes), "potential_savings": round(volume_savings, 2), "items": unattached_volumes},
            "old_snapshots": {"count": len(old_snapshots), "potential_savings": round(snapshot_savings, 2), "items": old_snapshots},
        },
        "anomalies": anomalies,
    }

    demo_result["deep_dive"] = demo_deep_dive()

    try:
        demo_result["recommendations"] = generate_recommendations(demo_result, ANTHROPIC_API_KEY)
    except Exception:
        demo_result["recommendations"] = None

    return demo_result


@app.get("/api/providers")
def list_providers():
    return {"providers": ProviderFactory.get_supported_providers()}


@app.get("/api/health")
def health_check():
    return {"status": "healthy"}


# ── Protected analysis endpoints ─────────────────────────────────────────────

@app.post("/api/analyze")
async def analyze_costs(
    request: AnalyzeByCredentialRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Analyze cloud costs using a stored credential (lightweight)."""
    log.info("POST /api/analyze | user=%s credential_id=%s", user.username, request.credential_id)
    try:
        creds_dict, provider_str, stored_region = _resolve_credentials(
            request.credential_id, user, db
        )
        provider_enum = request.provider or CloudProvider(provider_str)
        region = creds_dict.pop("region", None) or stored_region

        provider = ProviderFactory.create_provider(
            provider=provider_enum, credentials=creds_dict, region=region,
        )

        monthly_cost = provider.get_monthly_cost()
        top_services = provider.get_cost_by_service(limit=10)
        idle_instances = provider.find_idle_compute_instances()
        unattached_volumes = provider.find_unattached_storage_volumes()
        old_snapshots = provider.find_old_snapshots(days_old=90)

        idle_savings = sum(i.estimated_monthly_cost for i in idle_instances)
        volume_savings = sum(v.estimated_monthly_cost for v in unattached_volumes)
        snapshot_savings = sum(s.estimated_monthly_cost for s in old_snapshots)
        total_savings = idle_savings + volume_savings + snapshot_savings

        return {
            "provider": provider_enum.value,
            "monthly_cost": {
                "total_cost": monthly_cost.total_cost,
                "currency": monthly_cost.currency,
                "period": f"{monthly_cost.period_start} to {monthly_cost.period_end}",
            },
            "top_services": [{"service": s.service_name, "cost": s.cost} for s in top_services],
            "savings_opportunities": {
                "total_potential_savings": round(total_savings, 2),
                "idle_ec2_instances": {
                    "count": len(idle_instances),
                    "potential_savings": round(idle_savings, 2),
                    "items": [
                        {"instance_id": i.resource_id, "instance_type": i.instance_type, "estimated_monthly_cost": i.estimated_monthly_cost, "recommendation": i.recommendation}
                        for i in idle_instances
                    ],
                },
                "unattached_ebs_volumes": {
                    "count": len(unattached_volumes),
                    "potential_savings": round(volume_savings, 2),
                    "items": [
                        {"volume_id": v.resource_id, "size_gb": v.size_gb, "volume_type": v.volume_type, "estimated_monthly_cost": v.estimated_monthly_cost, "recommendation": v.recommendation}
                        for v in unattached_volumes
                    ],
                },
                "old_snapshots": {
                    "count": len(old_snapshots),
                    "potential_savings": round(snapshot_savings, 2),
                    "items": [
                        {"snapshot_id": s.resource_id, "size_gb": s.size_gb, "created_date": s.created_date, "age_days": s.age_days, "estimated_monthly_cost": s.estimated_monthly_cost, "recommendation": s.recommendation}
                        for s in old_snapshots[:10]
                    ],
                },
            },
        }

    except NotImplementedError as e:
        log.error("POST /api/analyze FAILED (not implemented): %s", e)
        raise HTTPException(status_code=501, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        log.error("POST /api/analyze FAILED: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analyze/detailed")
async def analyze_costs_detailed(
    request: AnalyzeByCredentialRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Full deep analysis using a stored credential."""
    log.info("POST /api/analyze/detailed | user=%s credential_id=%s", user.username, request.credential_id)
    try:
        creds_dict, provider_str, stored_region = _resolve_credentials(
            request.credential_id, user, db
        )
        provider_enum = request.provider or CloudProvider(provider_str)
        region = creds_dict.pop("region", None) or stored_region

        provider = ProviderFactory.create_provider(
            provider=provider_enum, credentials=creds_dict, region=region,
        )

        monthly_cost = provider.get_monthly_cost()
        top_services = provider.get_cost_by_service(limit=10)
        idle_instances = provider.find_idle_compute_instances()
        unattached_volumes = provider.find_unattached_storage_volumes()
        old_snapshots = provider.find_old_snapshots(days_old=90)
        daily_costs = provider.get_daily_costs(days=30)
        daily_costs_by_service = provider.get_daily_costs_by_service(days=30)
        resource_costs = provider.get_resource_costs(days=30)
        anomalies = provider.detect_anomalies(days=30)

        idle_savings = sum(i.estimated_monthly_cost for i in idle_instances)
        volume_savings = sum(v.estimated_monthly_cost for v in unattached_volumes)
        snapshot_savings = sum(s.estimated_monthly_cost for s in old_snapshots)
        total_savings = idle_savings + volume_savings + snapshot_savings

        import calendar
        today = datetime.now().date()
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        days_elapsed = today.day - 1 or 1
        projected_monthly = round((monthly_cost.total_cost / days_elapsed) * days_in_month, 2)

        analysis_result = {
            "provider": provider_enum.value,
            "monthly_cost": {
                "total_cost": monthly_cost.total_cost,
                "projected_cost": projected_monthly,
                "days_elapsed": days_elapsed,
                "days_in_month": days_in_month,
                "currency": monthly_cost.currency,
                "period": f"{monthly_cost.period_start} to {monthly_cost.period_end}",
            },
            "daily_costs": [{"date": d.date, "cost": d.cost} for d in daily_costs],
            "daily_costs_by_service": [{"date": d.date, "cost": d.cost, "service": d.service} for d in daily_costs_by_service],
            "top_services": [{"service": s.service_name, "cost": s.cost} for s in top_services],
            "resource_costs": [{"resource_id": r.resource_id, "resource_type": r.resource_type, "service": r.service, "cost": r.cost, "name": r.name} for r in resource_costs],
            "savings_opportunities": {
                "total_potential_savings": round(total_savings, 2),
                "idle_ec2_instances": {
                    "count": len(idle_instances), "potential_savings": round(idle_savings, 2),
                    "items": [{"instance_id": i.resource_id, "instance_type": i.instance_type, "estimated_monthly_cost": i.estimated_monthly_cost, "recommendation": i.recommendation} for i in idle_instances],
                },
                "unattached_ebs_volumes": {
                    "count": len(unattached_volumes), "potential_savings": round(volume_savings, 2),
                    "items": [{"volume_id": v.resource_id, "size_gb": v.size_gb, "volume_type": v.volume_type, "estimated_monthly_cost": v.estimated_monthly_cost, "recommendation": v.recommendation} for v in unattached_volumes],
                },
                "old_snapshots": {
                    "count": len(old_snapshots), "potential_savings": round(snapshot_savings, 2),
                    "items": [{"snapshot_id": s.resource_id, "size_gb": s.size_gb, "created_date": s.created_date, "age_days": s.age_days, "estimated_monthly_cost": s.estimated_monthly_cost, "recommendation": s.recommendation} for s in old_snapshots[:10]],
                },
            },
            "anomalies": [{"date": a.date, "service": a.service, "expected_cost": a.expected_cost, "actual_cost": a.actual_cost, "impact": a.impact, "impact_percentage": a.impact_percentage, "severity": a.severity, "source": a.source, "description": a.description} for a in anomalies],
        }

        try:
            top_service_names = [{"service": s["service"], "cost": s["cost"]} for s in analysis_result["top_services"]]
            analysis_result["deep_dive"] = deep_dive_top_services(top_service_names, creds_dict, region or "us-east-1")
        except Exception:
            analysis_result["deep_dive"] = {}

        try:
            analysis_result["recommendations"] = generate_recommendations(analysis_result, ANTHROPIC_API_KEY)
        except Exception:
            analysis_result["recommendations"] = None

        return analysis_result

    except NotImplementedError as e:
        log.error("POST /api/analyze/detailed FAILED (not implemented): %s", e)
        raise HTTPException(status_code=501, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        log.error("POST /api/analyze/detailed FAILED: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/recommendations")
async def get_recommendations(
    request: RecommendationsRequest,
    user: User = Depends(get_current_user),
):
    api_key = request.api_key or ANTHROPIC_API_KEY
    try:
        result = generate_recommendations(request.analysis_data, api_key)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate recommendations: {str(e)}")


# ── Demo data generators ─────────────────────────────────────────────────────

def _generate_demo_daily_costs():
    import random
    random.seed(42)
    base = 310.0
    today = datetime.now().date()
    costs = []
    for i in range(30, 0, -1):
        date = today - timedelta(days=i)
        day_factor = 1.0 if date.weekday() < 5 else 0.7
        noise = random.uniform(-30, 30)
        spike = 180.0 if i == 10 else 0.0
        cost = round(max(0, base * day_factor + noise + spike), 2)
        costs.append({"date": str(date), "cost": cost})
    return costs


def _generate_demo_daily_costs_by_service():
    import random
    random.seed(42)
    today = datetime.now().date()
    services = {
        "Amazon Elastic Compute Cloud": 145.0,
        "Amazon Relational Database Service": 72.0,
        "Amazon Simple Storage Service": 30.0,
        "AWS Lambda": 22.0,
        "Amazon CloudFront": 15.0,
    }
    results = []
    for i in range(30, 0, -1):
        date = today - timedelta(days=i)
        day_factor = 1.0 if date.weekday() < 5 else 0.7
        for service, base in services.items():
            noise = random.uniform(-base * 0.15, base * 0.15)
            spike = 60.0 if i == 10 and service == "Amazon Elastic Compute Cloud" else 0.0
            cost = round(max(0, base * day_factor + noise + spike), 2)
            results.append({"date": str(date), "cost": cost, "service": service})
    return results

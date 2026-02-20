from pydantic import BaseModel
from typing import List, Optional
from enum import Enum


class CloudProvider(str, Enum):
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"


class MonthlyCost(BaseModel):
    total_cost: float
    currency: str = "USD"
    period_start: str
    period_end: str
    provider: CloudProvider


class ServiceCost(BaseModel):
    service_name: str
    cost: float
    provider: CloudProvider


class ComputeInstance(BaseModel):
    resource_id: str
    instance_type: str
    state: str
    estimated_monthly_cost: float
    recommendation: str
    provider: CloudProvider
    region: Optional[str] = None
    tags: Optional[dict] = None


class StorageVolume(BaseModel):
    resource_id: str
    size_gb: int
    volume_type: str
    state: str
    estimated_monthly_cost: float
    recommendation: str
    provider: CloudProvider
    region: Optional[str] = None
    attached_to: Optional[str] = None


class Snapshot(BaseModel):
    resource_id: str
    size_gb: int
    created_date: str
    age_days: int
    estimated_monthly_cost: float
    recommendation: str
    provider: CloudProvider
    source_volume_id: Optional[str] = None


class DailyCost(BaseModel):
    date: str
    cost: float
    service: Optional[str] = None


class ResourceCost(BaseModel):
    resource_id: str
    resource_type: str  # "ec2", "rds", "s3", etc.
    service: str
    cost: float
    name: Optional[str] = None  # from tags


class UtilizationMetrics(BaseModel):
    resource_id: str
    avg_cpu: Optional[float] = None
    max_cpu: Optional[float] = None
    avg_network_in: Optional[float] = None  # bytes/hour
    avg_network_out: Optional[float] = None
    is_idle: bool = False
    idle_reason: Optional[str] = None


class CostAnomaly(BaseModel):
    date: str
    service: str
    expected_cost: float
    actual_cost: float
    impact: float  # actual - expected
    impact_percentage: float
    severity: str  # "low", "medium", "high", "critical"
    source: str  # "aws" or "statistical"
    description: str

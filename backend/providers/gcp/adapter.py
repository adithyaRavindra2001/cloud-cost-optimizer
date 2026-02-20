from typing import List
from providers.base import CloudCostProvider
from models.common import (
    MonthlyCost,
    ServiceCost,
    ComputeInstance,
    StorageVolume,
    Snapshot,
    CloudProvider,
    DailyCost,
    ResourceCost,
    CostAnomaly,
)


class GCPCostProvider(CloudCostProvider):
    """GCP implementation of the CloudCostProvider interface (stub)."""

    provider = CloudProvider.GCP

    def __init__(self, credentials: dict, region: str = None):
        region = region or "us-central1"
        super().__init__(credentials, region)
        # TODO: Initialize GCP clients
        # from google.cloud import billing_v1, compute_v1
        raise NotImplementedError("GCP provider is not yet implemented")

    def get_monthly_cost(self) -> MonthlyCost:
        raise NotImplementedError("GCP cost retrieval not implemented")

    def get_cost_by_service(self, limit: int = 10) -> List[ServiceCost]:
        raise NotImplementedError("GCP service cost breakdown not implemented")

    def find_idle_compute_instances(self) -> List[ComputeInstance]:
        raise NotImplementedError("GCP compute instance detection not implemented")

    def find_unattached_storage_volumes(self) -> List[StorageVolume]:
        raise NotImplementedError("GCP storage volume detection not implemented")

    def find_old_snapshots(self, days_old: int = 90) -> List[Snapshot]:
        raise NotImplementedError("GCP snapshot detection not implemented")

    def get_daily_costs(self, days: int = 30) -> List[DailyCost]:
        raise NotImplementedError("GCP daily costs not implemented")

    def get_daily_costs_by_service(self, days: int = 30) -> List[DailyCost]:
        raise NotImplementedError("GCP daily costs by service not implemented")

    def get_resource_costs(self, days: int = 30) -> List[ResourceCost]:
        raise NotImplementedError("GCP resource costs not implemented")

    def detect_anomalies(self, days: int = 30) -> List[CostAnomaly]:
        raise NotImplementedError("GCP anomaly detection not implemented")

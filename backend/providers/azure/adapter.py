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


class AzureCostProvider(CloudCostProvider):
    """Azure implementation of the CloudCostProvider interface (stub)."""

    provider = CloudProvider.AZURE

    def __init__(self, credentials: dict, region: str = None):
        region = region or "eastus"
        super().__init__(credentials, region)
        # TODO: Initialize Azure clients
        # from azure.mgmt.costmanagement import CostManagementClient
        # from azure.mgmt.compute import ComputeManagementClient
        # from azure.identity import ClientSecretCredential
        raise NotImplementedError("Azure provider is not yet implemented")

    def get_monthly_cost(self) -> MonthlyCost:
        raise NotImplementedError("Azure cost retrieval not implemented")

    def get_cost_by_service(self, limit: int = 10) -> List[ServiceCost]:
        raise NotImplementedError("Azure service cost breakdown not implemented")

    def find_idle_compute_instances(self) -> List[ComputeInstance]:
        raise NotImplementedError("Azure compute instance detection not implemented")

    def find_unattached_storage_volumes(self) -> List[StorageVolume]:
        raise NotImplementedError("Azure storage volume detection not implemented")

    def find_old_snapshots(self, days_old: int = 90) -> List[Snapshot]:
        raise NotImplementedError("Azure snapshot detection not implemented")

    def get_daily_costs(self, days: int = 30) -> List[DailyCost]:
        raise NotImplementedError("Azure daily costs not implemented")

    def get_daily_costs_by_service(self, days: int = 30) -> List[DailyCost]:
        raise NotImplementedError("Azure daily costs by service not implemented")

    def get_resource_costs(self, days: int = 30) -> List[ResourceCost]:
        raise NotImplementedError("Azure resource costs not implemented")

    def detect_anomalies(self, days: int = 30) -> List[CostAnomaly]:
        raise NotImplementedError("Azure anomaly detection not implemented")

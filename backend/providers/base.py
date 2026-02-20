from abc import ABC, abstractmethod
from typing import List
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


class CloudCostProvider(ABC):
    """Abstract base class for cloud cost providers."""

    provider: CloudProvider

    def __init__(self, credentials: dict, region: str = None):
        self.credentials = credentials
        self.region = region

    @abstractmethod
    def get_monthly_cost(self) -> MonthlyCost:
        pass

    @abstractmethod
    def get_cost_by_service(self, limit: int = 10) -> List[ServiceCost]:
        pass

    @abstractmethod
    def find_idle_compute_instances(self) -> List[ComputeInstance]:
        pass

    @abstractmethod
    def find_unattached_storage_volumes(self) -> List[StorageVolume]:
        pass

    @abstractmethod
    def find_old_snapshots(self, days_old: int = 90) -> List[Snapshot]:
        pass

    @abstractmethod
    def get_daily_costs(self, days: int = 30) -> List[DailyCost]:
        pass

    @abstractmethod
    def get_daily_costs_by_service(self, days: int = 30) -> List[DailyCost]:
        pass

    @abstractmethod
    def get_resource_costs(self, days: int = 30) -> List[ResourceCost]:
        pass

    @abstractmethod
    def detect_anomalies(self, days: int = 30) -> List[CostAnomaly]:
        pass

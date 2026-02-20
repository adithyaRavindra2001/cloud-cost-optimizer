import boto3
from datetime import datetime, timedelta
from typing import List
from providers.base import CloudCostProvider
from logger import get_logger
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
from providers.aws.cost_breakdown import AWSCostBreakdown
from providers.aws.metrics import AWSMetrics
from providers.aws.anomalies import AWSAnomalyDetector


log = get_logger("aws.adapter")


class AWSCostProvider(CloudCostProvider):
    """AWS implementation of the CloudCostProvider interface."""

    provider = CloudProvider.AWS

    def __init__(self, credentials: dict, region: str = None):
        region = region or "us-east-1"
        super().__init__(credentials, region)

        session_token = credentials.get("session_token") or None
        has_session_token = bool(session_token)
        log.info(
            "Initialising AWS provider | region=%s access_key=%s...%s session_token=%s",
            region,
            credentials["access_key"][:4],
            credentials["access_key"][-4:],
            "present" if has_session_token else "not provided",
        )
        boto3_kwargs = {
            "aws_access_key_id": credentials["access_key"],
            "aws_secret_access_key": credentials["secret_key"],
            "aws_session_token": session_token,
            "region_name": region,
        }

        self.ce_client = boto3.client("ce", **boto3_kwargs)
        self.ec2_client = boto3.client("ec2", **boto3_kwargs)
        self.cloudwatch_client = boto3.client("cloudwatch", **boto3_kwargs)
        self.ecs_client = boto3.client("ecs", **boto3_kwargs)
        self.rds_client = boto3.client("rds", **boto3_kwargs)
        self.s3_client = boto3.client("s3", **boto3_kwargs)
        self.lambda_client = boto3.client("lambda", **boto3_kwargs)

        self._cost_breakdown = AWSCostBreakdown(self.ce_client)
        self._metrics = AWSMetrics(self.cloudwatch_client)
        self._anomaly_detector = AWSAnomalyDetector(self.ce_client)

    def get_monthly_cost(self) -> MonthlyCost:
        end_date = datetime.now().date()
        start_date = end_date.replace(day=1)
        log.info("GetCostAndUsage → monthly total | period=%s to %s", start_date, end_date)
        try:
            response = self.ce_client.get_cost_and_usage(
                TimePeriod={"Start": str(start_date), "End": str(end_date)},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
            )
        except Exception as exc:
            log.error("GetCostAndUsage monthly total FAILED: %s", exc)
            raise

        total_cost = float(
            response["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"]
        )
        log.info("GetCostAndUsage → monthly total OK | cost=$%.2f", total_cost)

        return MonthlyCost(
            total_cost=round(total_cost, 2),
            currency="USD",
            period_start=str(start_date),
            period_end=str(end_date),
            provider=CloudProvider.AWS,
        )

    def get_cost_by_service(self, limit: int = 10) -> List[ServiceCost]:
        end_date = datetime.now().date()
        start_date = end_date.replace(day=1)
        log.info("GetCostAndUsage → by-service | period=%s to %s limit=%d", start_date, end_date, limit)
        try:
            response = self.ce_client.get_cost_and_usage(
                TimePeriod={"Start": str(start_date), "End": str(end_date)},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
        except Exception as exc:
            log.error("GetCostAndUsage by-service FAILED: %s", exc)
            raise

        services = []
        for group in response["ResultsByTime"][0]["Groups"]:
            service_name = group["Keys"][0]
            cost = float(group["Metrics"]["UnblendedCost"]["Amount"])

            if cost > 0:
                services.append(
                    ServiceCost(
                        service_name=service_name,
                        cost=round(cost, 2),
                        provider=CloudProvider.AWS,
                    )
                )

        services.sort(key=lambda x: x.cost, reverse=True)
        log.info("GetCostAndUsage → by-service OK | %d services returned", len(services[:limit]))
        return services[:limit]

    def find_idle_compute_instances(self) -> List[ComputeInstance]:
        response = self.ec2_client.describe_instances(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
        )

        instances = []
        instance_ids = []
        for reservation in response["Reservations"]:
            for instance in reservation["Instances"]:
                tags = {
                    tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])
                }
                estimated_cost = self._estimate_instance_cost(instance["InstanceType"])
                instance_ids.append(instance["InstanceId"])

                instances.append(
                    ComputeInstance(
                        resource_id=instance["InstanceId"],
                        instance_type=instance["InstanceType"],
                        state="running",
                        estimated_monthly_cost=estimated_cost,
                        recommendation="Review instance utilization",
                        provider=CloudProvider.AWS,
                        region=self.region,
                        tags=tags,
                    )
                )

        # Enrich with CloudWatch metrics for real idle detection
        if instance_ids:
            try:
                utilization = self._metrics.get_instance_utilization(instance_ids)
                util_map = {u.resource_id: u for u in utilization}
                idle_instances = []
                for inst in instances:
                    metrics = util_map.get(inst.resource_id)
                    if metrics and metrics.is_idle:
                        inst.recommendation = (
                            f"Idle: {metrics.idle_reason}. "
                            "Stop or terminate to save costs."
                        )
                        idle_instances.append(inst)
                if idle_instances:
                    return idle_instances
            except Exception:
                pass

        # Fallback: return all running instances as candidates
        for inst in instances:
            inst.recommendation = "Stop or terminate if not needed"
        return instances

    def find_unattached_storage_volumes(self) -> List[StorageVolume]:
        response = self.ec2_client.describe_volumes(
            Filters=[{"Name": "status", "Values": ["available"]}]
        )

        volumes = []
        for volume in response["Volumes"]:
            monthly_cost = volume["Size"] * 0.10

            volumes.append(
                StorageVolume(
                    resource_id=volume["VolumeId"],
                    size_gb=volume["Size"],
                    volume_type=volume["VolumeType"],
                    state="available",
                    estimated_monthly_cost=round(monthly_cost, 2),
                    recommendation="Delete if not needed",
                    provider=CloudProvider.AWS,
                    region=self.region,
                    attached_to=None,
                )
            )

        return volumes

    def find_old_snapshots(self, days_old: int = 90) -> List[Snapshot]:
        response = self.ec2_client.describe_snapshots(OwnerIds=["self"])

        cutoff_date = datetime.now() - timedelta(days=days_old)
        snapshots = []

        for snapshot in response["Snapshots"]:
            snapshot_time = snapshot["StartTime"].replace(tzinfo=None)

            if snapshot_time < cutoff_date:
                monthly_cost = snapshot["VolumeSize"] * 0.05

                snapshots.append(
                    Snapshot(
                        resource_id=snapshot["SnapshotId"],
                        size_gb=snapshot["VolumeSize"],
                        created_date=str(snapshot_time.date()),
                        age_days=(datetime.now() - snapshot_time).days,
                        estimated_monthly_cost=round(monthly_cost, 2),
                        recommendation="Review and delete if not needed",
                        provider=CloudProvider.AWS,
                        source_volume_id=snapshot.get("VolumeId"),
                    )
                )

        return snapshots

    def get_daily_costs(self, days: int = 30) -> List[DailyCost]:
        return self._cost_breakdown.get_daily_costs(days)

    def get_daily_costs_by_service(self, days: int = 30) -> List[DailyCost]:
        return self._cost_breakdown.get_daily_costs_by_service(days)

    def get_resource_costs(self, days: int = 30) -> List[ResourceCost]:
        return self._cost_breakdown.get_resource_costs(days)

    def detect_anomalies(self, days: int = 30) -> List[CostAnomaly]:
        anomalies = self._anomaly_detector.get_aws_anomalies(days)
        daily_costs = self._cost_breakdown.get_daily_costs(days)
        statistical = self._anomaly_detector.detect_statistical_anomalies(daily_costs)
        anomalies.extend(statistical)
        anomalies.sort(key=lambda a: a.date, reverse=True)
        return anomalies

    def _estimate_instance_cost(self, instance_type: str) -> float:
        pricing = {
            "t2.micro": 8.50,
            "t2.small": 17.00,
            "t2.medium": 34.00,
            "t3.micro": 7.50,
            "t3.small": 15.00,
            "t3.medium": 30.00,
            "m5.large": 70.00,
            "m5.xlarge": 140.00,
            "m5.2xlarge": 280.00,
            "c5.large": 62.00,
            "c5.xlarge": 124.00,
            "r5.large": 91.00,
            "r5.xlarge": 182.00,
        }
        return pricing.get(instance_type, 50.00)

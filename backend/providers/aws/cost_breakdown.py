from datetime import datetime, timedelta
from typing import List
from models.common import DailyCost, ResourceCost
from logger import get_logger

log = get_logger("aws.cost_breakdown")


SERVICE_TO_TYPE = {
    "Amazon Elastic Compute Cloud": "ec2",
    "Amazon Relational Database Service": "rds",
    "Amazon Simple Storage Service": "s3",
    "Amazon DynamoDB": "dynamodb",
    "AWS Lambda": "lambda",
    "Amazon ElastiCache": "elasticache",
    "Amazon Redshift": "redshift",
}


class AWSCostBreakdown:
    def __init__(self, ce_client):
        self.ce_client = ce_client

    def get_daily_costs(self, days: int = 30) -> List[DailyCost]:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        log.info("GetCostAndUsage → daily totals | period=%s to %s (%d days)", start_date, end_date, days)
        try:
            response = self.ce_client.get_cost_and_usage(
                TimePeriod={"Start": str(start_date), "End": str(end_date)},
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
            )
        except Exception as exc:
            log.error("GetCostAndUsage daily totals FAILED: %s", exc)
            raise

        results = []
        for period in response["ResultsByTime"]:
            cost = float(period["Total"]["UnblendedCost"]["Amount"])
            results.append(DailyCost(
                date=period["TimePeriod"]["Start"],
                cost=round(cost, 2),
            ))
        log.info("GetCostAndUsage → daily totals OK | %d data points", len(results))
        return results

    def get_daily_costs_by_service(self, days: int = 30) -> List[DailyCost]:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        log.info("GetCostAndUsage → daily by-service | period=%s to %s (%d days)", start_date, end_date, days)
        try:
            response = self.ce_client.get_cost_and_usage(
                TimePeriod={"Start": str(start_date), "End": str(end_date)},
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
        except Exception as exc:
            log.error("GetCostAndUsage daily by-service FAILED: %s", exc)
            raise

        results = []
        for period in response["ResultsByTime"]:
            date = period["TimePeriod"]["Start"]
            for group in period["Groups"]:
                service = group["Keys"][0]
                cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                if cost > 0.01:
                    results.append(DailyCost(
                        date=date,
                        cost=round(cost, 2),
                        service=service,
                    ))
        log.info("GetCostAndUsage → daily by-service OK | %d rows", len(results))
        return results

    def get_resource_costs(self, days: int = 30) -> List[ResourceCost]:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        log.info("GetCostAndUsage → resource costs | period=%s to %s (%d days)", start_date, end_date, days)
        try:
            response = self.ce_client.get_cost_and_usage(
                TimePeriod={"Start": str(start_date), "End": str(end_date)},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                GroupBy=[
                    {"Type": "DIMENSION", "Key": "SERVICE"},
                    {"Type": "DIMENSION", "Key": "USAGE_TYPE"},
                ],
            )
        except Exception as exc:
            log.error("GetCostAndUsage resource costs FAILED: %s", exc)
            raise

        results = []
        for period in response["ResultsByTime"]:
            for group in period["Groups"]:
                service = group["Keys"][0]
                usage_type = group["Keys"][1]
                cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                if cost > 0.01:
                    resource_type = SERVICE_TO_TYPE.get(service, "other")
                    results.append(ResourceCost(
                        resource_id=usage_type,
                        resource_type=resource_type,
                        service=service,
                        cost=round(cost, 2),
                        name=usage_type,
                    ))

        results.sort(key=lambda x: x.cost, reverse=True)
        log.info("GetCostAndUsage → resource costs OK | %d resources", len(results))
        return results

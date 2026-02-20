from datetime import datetime, timedelta
from typing import List
from models.common import UtilizationMetrics

IDLE_CPU_THRESHOLD = 5.0  # percent
IDLE_NETWORK_THRESHOLD = 1_000_000  # 1MB/hr in bytes


class AWSMetrics:
    def __init__(self, cloudwatch_client):
        self.cw_client = cloudwatch_client

    def get_instance_utilization(
        self, instance_ids: List[str], days: int = 14
    ) -> List[UtilizationMetrics]:
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days)
        period = 3600  # 1 hour

        results = []
        for instance_id in instance_ids:
            metrics = self._get_metrics_for_instance(
                instance_id, start_time, end_time, period
            )
            results.append(metrics)
        return results

    def _get_metrics_for_instance(
        self, instance_id: str, start_time, end_time, period: int
    ) -> UtilizationMetrics:
        metric_queries = [
            {
                "Id": "avg_cpu",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/EC2",
                        "MetricName": "CPUUtilization",
                        "Dimensions": [
                            {"Name": "InstanceId", "Value": instance_id}
                        ],
                    },
                    "Period": period,
                    "Stat": "Average",
                },
            },
            {
                "Id": "max_cpu",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/EC2",
                        "MetricName": "CPUUtilization",
                        "Dimensions": [
                            {"Name": "InstanceId", "Value": instance_id}
                        ],
                    },
                    "Period": period,
                    "Stat": "Maximum",
                },
            },
            {
                "Id": "net_in",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/EC2",
                        "MetricName": "NetworkIn",
                        "Dimensions": [
                            {"Name": "InstanceId", "Value": instance_id}
                        ],
                    },
                    "Period": period,
                    "Stat": "Average",
                },
            },
            {
                "Id": "net_out",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/EC2",
                        "MetricName": "NetworkOut",
                        "Dimensions": [
                            {"Name": "InstanceId", "Value": instance_id}
                        ],
                    },
                    "Period": period,
                    "Stat": "Average",
                },
            },
        ]

        response = self.cw_client.get_metric_data(
            MetricDataQueries=metric_queries,
            StartTime=start_time,
            EndTime=end_time,
        )

        values = {}
        for result in response["MetricDataResults"]:
            if result["Values"]:
                values[result["Id"]] = result["Values"]

        avg_cpu = _safe_avg(values.get("avg_cpu"))
        max_cpu = _safe_max(values.get("max_cpu"))
        avg_net_in = _safe_avg(values.get("net_in"))
        avg_net_out = _safe_avg(values.get("net_out"))

        is_idle = False
        idle_reason = None
        if avg_cpu is not None and avg_cpu < IDLE_CPU_THRESHOLD:
            net_total = (avg_net_in or 0) + (avg_net_out or 0)
            if net_total < IDLE_NETWORK_THRESHOLD:
                is_idle = True
                idle_reason = (
                    f"Avg CPU {avg_cpu:.1f}% (<{IDLE_CPU_THRESHOLD}%), "
                    f"network {net_total / 1_000_000:.2f} MB/hr (<1 MB/hr)"
                )

        return UtilizationMetrics(
            resource_id=instance_id,
            avg_cpu=round(avg_cpu, 2) if avg_cpu is not None else None,
            max_cpu=round(max_cpu, 2) if max_cpu is not None else None,
            avg_network_in=round(avg_net_in, 2) if avg_net_in is not None else None,
            avg_network_out=round(avg_net_out, 2) if avg_net_out is not None else None,
            is_idle=is_idle,
            idle_reason=idle_reason,
        )


def _safe_avg(values):
    if not values:
        return None
    return sum(values) / len(values)


def _safe_max(values):
    if not values:
        return None
    return max(values)

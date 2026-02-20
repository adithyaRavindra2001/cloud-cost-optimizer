import math
from datetime import datetime, timedelta
from typing import List
from models.common import CostAnomaly, DailyCost


class AWSAnomalyDetector:
    def __init__(self, ce_client):
        self.ce_client = ce_client

    def get_aws_anomalies(self, days: int = 30) -> List[CostAnomaly]:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)

        try:
            # Get anomaly monitors first
            monitors_response = self.ce_client.get_anomaly_monitors()
            if not monitors_response.get("AnomalyMonitors"):
                return []

            monitor_arn = monitors_response["AnomalyMonitors"][0]["MonitorArn"]

            response = self.ce_client.get_anomalies(
                MonitorArn=monitor_arn,
                DateInterval={
                    "StartDate": str(start_date),
                    "EndDate": str(end_date),
                },
            )
        except Exception:
            # Anomaly detection may not be set up
            return []

        results = []
        for anomaly in response.get("Anomalies", []):
            impact = anomaly.get("Impact", {})
            expected = float(impact.get("ExpectedSpend", 0))
            actual = float(impact.get("TotalActualSpend", 0))
            diff = actual - expected

            if expected > 0:
                pct = (diff / expected) * 100
            else:
                pct = 100.0

            severity = _classify_severity(diff, pct)

            results.append(CostAnomaly(
                date=anomaly.get("AnomalyStartDate", str(end_date)),
                service=anomaly.get("DimensionValue", "Unknown"),
                expected_cost=round(expected, 2),
                actual_cost=round(actual, 2),
                impact=round(diff, 2),
                impact_percentage=round(pct, 1),
                severity=severity,
                source="aws",
                description=f"AWS detected anomaly: ${diff:.2f} above expected spend",
            ))
        return results

    def detect_statistical_anomalies(
        self, daily_costs: List[DailyCost], z_threshold: float = 2.0
    ) -> List[CostAnomaly]:
        if len(daily_costs) < 10:
            return []

        # Group costs by date (sum across services if needed)
        date_totals = {}
        for dc in daily_costs:
            date_totals.setdefault(dc.date, 0)
            date_totals[dc.date] += dc.cost

        sorted_dates = sorted(date_totals.keys())
        results = []

        for i in range(7, len(sorted_dates)):
            window = [date_totals[sorted_dates[j]] for j in range(i - 7, i)]
            mean = sum(window) / len(window)
            variance = sum((x - mean) ** 2 for x in window) / len(window)
            stddev = math.sqrt(variance) if variance > 0 else 0

            current_date = sorted_dates[i]
            current_cost = date_totals[current_date]

            if stddev > 0:
                z_score = (current_cost - mean) / stddev
            else:
                z_score = 0

            if z_score > z_threshold:
                diff = current_cost - mean
                pct = (diff / mean) * 100 if mean > 0 else 100.0
                severity = _classify_severity(diff, pct)

                results.append(CostAnomaly(
                    date=current_date,
                    service="Total",
                    expected_cost=round(mean, 2),
                    actual_cost=round(current_cost, 2),
                    impact=round(diff, 2),
                    impact_percentage=round(pct, 1),
                    severity=severity,
                    source="statistical",
                    description=(
                        f"Daily cost ${current_cost:.2f} is {z_score:.1f} std devs "
                        f"above 7-day rolling avg (${mean:.2f})"
                    ),
                ))

        return results


def _classify_severity(impact: float, percentage: float) -> str:
    if impact > 500 or percentage > 100:
        return "critical"
    elif impact > 200 or percentage > 50:
        return "high"
    elif impact > 50 or percentage > 25:
        return "medium"
    return "low"

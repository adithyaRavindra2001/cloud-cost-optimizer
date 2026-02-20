"""AWS tool implementations for the chat agent. Each returns a JSON string."""

import json
import boto3
from datetime import datetime, timedelta


def _make_ce_client(creds, region):
    return boto3.client(
        "ce",
        aws_access_key_id=creds["access_key"],
        aws_secret_access_key=creds["secret_key"],
        aws_session_token=creds.get("session_token") or None,
        region_name=region,
    )


def _make_client(service, creds, region):
    return boto3.client(
        service,
        aws_access_key_id=creds["access_key"],
        aws_secret_access_key=creds["secret_key"],
        aws_session_token=creds.get("session_token") or None,
        region_name=region,
    )


# ── Cost Tools ────────────────────────────────────────────────────────────────


def get_cost_by_service(creds, region, start_date, end_date, limit=10):
    """Cost Explorer grouped by SERVICE."""
    ce = _make_ce_client(creds, region)
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start_date, "End": end_date},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    services = []
    for group in resp["ResultsByTime"][0]["Groups"]:
        cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
        if cost > 0.01:
            services.append({"service": group["Keys"][0], "cost": round(cost, 2)})
    services.sort(key=lambda x: x["cost"], reverse=True)
    return json.dumps({"services": services[:int(limit)], "period": f"{start_date} to {end_date}"})


def get_daily_costs(creds, region, start_date, end_date, service_filter=None):
    """Cost Explorer daily, with optional service filter."""
    ce = _make_ce_client(creds, region)
    kwargs = dict(
        TimePeriod={"Start": start_date, "End": end_date},
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
    )
    if service_filter:
        kwargs["Filter"] = {"Dimensions": {"Key": "SERVICE", "Values": [service_filter]}}
    resp = ce.get_cost_and_usage(**kwargs)
    days = []
    for r in resp["ResultsByTime"]:
        days.append({
            "date": r["TimePeriod"]["Start"],
            "cost": round(float(r["Total"]["UnblendedCost"]["Amount"]), 2),
        })
    return json.dumps({"daily_costs": days, "service_filter": service_filter})


def compare_cost_periods(creds, region, p1_start, p1_end, p2_start, p2_end):
    """Two CE calls + compute deltas between periods."""
    ce = _make_ce_client(creds, region)

    def _total(start, end):
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
        )
        return sum(
            float(r["Total"]["UnblendedCost"]["Amount"])
            for r in resp["ResultsByTime"]
        )

    p1_cost = round(_total(p1_start, p1_end), 2)
    p2_cost = round(_total(p2_start, p2_end), 2)
    delta = round(p2_cost - p1_cost, 2)
    pct = round((delta / p1_cost) * 100, 2) if p1_cost else 0
    return json.dumps({
        "period1": {"start": p1_start, "end": p1_end, "cost": p1_cost},
        "period2": {"start": p2_start, "end": p2_end, "cost": p2_cost},
        "delta": delta,
        "change_percent": pct,
    })


def get_cost_by_usage_type(creds, region, start_date, end_date, service_filter=None):
    """Cost Explorer grouped by USAGE_TYPE."""
    ce = _make_ce_client(creds, region)
    kwargs = dict(
        TimePeriod={"Start": start_date, "End": end_date},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "USAGE_TYPE"}],
    )
    if service_filter:
        kwargs["Filter"] = {"Dimensions": {"Key": "SERVICE", "Values": [service_filter]}}
    resp = ce.get_cost_and_usage(**kwargs)
    items = []
    for group in resp["ResultsByTime"][0]["Groups"]:
        cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
        if cost > 0.01:
            items.append({"usage_type": group["Keys"][0], "cost": round(cost, 2)})
    items.sort(key=lambda x: x["cost"], reverse=True)
    return json.dumps({"usage_types": items[:20], "service_filter": service_filter})


# ── Infrastructure Tools ──────────────────────────────────────────────────────


def describe_ec2_instances(creds, region, state_filter=None):
    """ec2.describe_instances with optional state filter."""
    ec2 = _make_client("ec2", creds, region)
    kwargs = {}
    if state_filter:
        kwargs["Filters"] = [{"Name": "instance-state-name", "Values": [state_filter]}]
    resp = ec2.describe_instances(**kwargs)
    instances = []
    for res in resp["Reservations"]:
        for inst in res["Instances"]:
            tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
            instances.append({
                "instance_id": inst["InstanceId"],
                "type": inst["InstanceType"],
                "state": inst["State"]["Name"],
                "launch_time": str(inst.get("LaunchTime", "")),
                "name": tags.get("Name", ""),
            })
    return json.dumps({"instances": instances, "count": len(instances)})


def describe_ecs_services(creds, region, cluster=None):
    """ecs.list_services + describe_services."""
    ecs = _make_client("ecs", creds, region)
    clusters = [cluster] if cluster else []
    if not clusters:
        cl_resp = ecs.list_clusters()
        clusters = cl_resp.get("clusterArns", [])
    results = []
    for cl in clusters:
        svc_resp = ecs.list_services(cluster=cl, maxResults=50)
        svc_arns = svc_resp.get("serviceArns", [])
        if not svc_arns:
            continue
        desc = ecs.describe_services(cluster=cl, services=svc_arns)
        for svc in desc.get("services", []):
            results.append({
                "name": svc["serviceName"],
                "cluster": cl.split("/")[-1] if "/" in cl else cl,
                "status": svc["status"],
                "running_count": svc["runningCount"],
                "desired_count": svc["desiredCount"],
                "launch_type": svc.get("launchType", "UNKNOWN"),
                "cpu": svc.get("cpu", ""),
                "memory": svc.get("memory", ""),
            })
    return json.dumps({"ecs_services": results, "count": len(results)})


def describe_rds_instances(creds, region):
    """rds.describe_db_instances."""
    rds = _make_client("rds", creds, region)
    resp = rds.describe_db_instances()
    instances = []
    for db in resp["DBInstances"]:
        instances.append({
            "db_id": db["DBInstanceIdentifier"],
            "class": db["DBInstanceClass"],
            "engine": db["Engine"],
            "status": db["DBInstanceStatus"],
            "multi_az": db.get("MultiAZ", False),
            "storage_gb": db.get("AllocatedStorage", 0),
            "storage_type": db.get("StorageType", ""),
        })
    return json.dumps({"rds_instances": instances, "count": len(instances)})


# ── Metrics ───────────────────────────────────────────────────────────────────


def get_cloudwatch_metrics(creds, region, namespace, metric_name, dimension_name, dimension_value, days=7, stat="Average"):
    """Generic CloudWatch metrics query."""
    cw = _make_client("cloudwatch", creds, region)
    end = datetime.utcnow()
    start = end - timedelta(days=int(days))
    resp = cw.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric_name,
        Dimensions=[{"Name": dimension_name, "Value": dimension_value}],
        StartTime=start,
        EndTime=end,
        Period=3600,
        Statistics=[stat],
    )
    points = sorted(resp["Datapoints"], key=lambda d: d["Timestamp"])
    data = [{"timestamp": str(p["Timestamp"]), "value": round(p[stat], 4)} for p in points]
    return json.dumps({
        "metric": f"{namespace}/{metric_name}",
        "dimension": f"{dimension_name}={dimension_value}",
        "stat": stat,
        "datapoints": data[-48:],  # last 48 hours of hourly data
    })


# ── Demo implementations ─────────────────────────────────────────────────────

DEMO_TOOLS = {}


def _demo(name):
    def decorator(fn):
        DEMO_TOOLS[name] = fn
        return fn
    return decorator


@_demo("get_cost_by_service")
def _demo_cost_by_service(**kwargs):
    return json.dumps({"services": [
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
    ][:int(kwargs.get("limit", 10))], "period": f"{kwargs.get('start_date', '2026-02-01')} to {kwargs.get('end_date', '2026-02-14')}"})


@_demo("get_daily_costs")
def _demo_daily_costs(**kwargs):
    import random
    random.seed(99)
    today = datetime.now().date()
    days = []
    for i in range(14, 0, -1):
        d = today - timedelta(days=i)
        days.append({"date": str(d), "cost": round(280 + random.uniform(-40, 40), 2)})
    return json.dumps({"daily_costs": days, "service_filter": kwargs.get("service_filter")})


@_demo("compare_cost_periods")
def _demo_compare(**kwargs):
    return json.dumps({
        "period1": {"start": kwargs.get("p1_start", "2026-01-01"), "end": kwargs.get("p1_end", "2026-02-01"), "cost": 8540.20},
        "period2": {"start": kwargs.get("p2_start", "2026-02-01"), "end": kwargs.get("p2_end", "2026-02-14"), "cost": 9271.35},
        "delta": 731.15,
        "change_percent": 8.56,
    })


@_demo("get_cost_by_usage_type")
def _demo_usage_type(**kwargs):
    return json.dumps({"usage_types": [
        {"usage_type": "USW2-BoxUsage:m5.xlarge", "cost": 1420.00},
        {"usage_type": "USW2-BoxUsage:r5.large", "cost": 890.50},
        {"usage_type": "USW2-RDS:db.r5.large", "cost": 750.00},
        {"usage_type": "USW2-TimedStorage-ByteHrs", "cost": 340.20},
        {"usage_type": "USW2-DataTransfer-Out-Bytes", "cost": 285.00},
    ], "service_filter": kwargs.get("service_filter")})


@_demo("describe_ec2_instances")
def _demo_ec2(**kwargs):
    return json.dumps({"instances": [
        {"instance_id": "i-0a1b2c3d4e5f60001", "type": "m5.xlarge", "state": "running", "name": "prod-api-server-1"},
        {"instance_id": "i-0a1b2c3d4e5f60002", "type": "t3.medium", "state": "running", "name": "prod-worker-1"},
        {"instance_id": "i-0a1b2c3d4e5f60003", "type": "c5.large", "state": "running", "name": "staging-api"},
        {"instance_id": "i-0a1b2c3d4e5f60004", "type": "r5.large", "state": "stopped", "name": "dev-test"},
    ], "count": 4})


@_demo("describe_ecs_services")
def _demo_ecs(**kwargs):
    return json.dumps({"ecs_services": [
        {"name": "prod-api", "cluster": "prod", "status": "ACTIVE", "running_count": 3, "desired_count": 3, "launch_type": "FARGATE", "cpu": "1024", "memory": "2048"},
        {"name": "prod-worker", "cluster": "prod", "status": "ACTIVE", "running_count": 5, "desired_count": 5, "launch_type": "FARGATE", "cpu": "2048", "memory": "4096"},
        {"name": "staging-api", "cluster": "staging", "status": "ACTIVE", "running_count": 2, "desired_count": 2, "launch_type": "FARGATE", "cpu": "512", "memory": "1024"},
    ], "count": 3})


@_demo("describe_rds_instances")
def _demo_rds(**kwargs):
    return json.dumps({"rds_instances": [
        {"db_id": "prod-postgres-main", "class": "db.r5.large", "engine": "postgres", "status": "available", "multi_az": True, "storage_gb": 500, "storage_type": "gp3"},
        {"db_id": "prod-postgres-replica", "class": "db.r5.large", "engine": "postgres", "status": "available", "multi_az": False, "storage_gb": 500, "storage_type": "gp3"},
        {"db_id": "staging-postgres", "class": "db.t3.medium", "engine": "postgres", "status": "available", "multi_az": False, "storage_gb": 100, "storage_type": "gp2"},
    ], "count": 3})


@_demo("get_cloudwatch_metrics")
def _demo_cw(**kwargs):
    import random
    random.seed(42)
    points = []
    now = datetime.utcnow()
    for i in range(48, 0, -1):
        t = now - timedelta(hours=i)
        points.append({"timestamp": str(t), "value": round(random.uniform(1, 15), 2)})
    return json.dumps({
        "metric": f"{kwargs.get('namespace', 'AWS/EC2')}/{kwargs.get('metric_name', 'CPUUtilization')}",
        "dimension": f"{kwargs.get('dimension_name', 'InstanceId')}={kwargs.get('dimension_value', 'i-0a1b2c3d4e5f60001')}",
        "stat": kwargs.get("stat", "Average"),
        "datapoints": points,
    })

"""
Deep dive investigation of top cost-driving AWS services.

Inspects actual resources behind each service via AWS APIs and flags
potential cost-optimization opportunities for the AI recommendation engine.
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Map AWS service names (from Cost Explorer) to handler functions
SERVICE_HANDLERS = {}


def _handler(service_name):
    """Decorator to register a handler for an AWS service."""
    def decorator(func):
        SERVICE_HANDLERS[service_name] = func
        return func
    return decorator


def deep_dive_top_services(top_services: list[dict], creds: dict, region: str) -> dict:
    """
    Inspect the top cost-driving services via AWS APIs.

    Args:
        top_services: List of {"service": name, "cost": amount} dicts.
        creds: AWS credentials dict with access_key/secret_key.
        region: AWS region.

    Returns:
        Dict keyed by service name, each with "resources" and "findings" lists.
    """
    import boto3

    results = {}
    for svc in top_services[:5]:
        service_name = svc["service"]
        handler = SERVICE_HANDLERS.get(service_name)
        if handler:
            try:
                results[service_name] = handler(creds, region)
            except Exception as e:
                logger.warning("Deep dive failed for %s: %s", service_name, e)
                results[service_name] = {
                    "resources": [],
                    "findings": [f"Unable to inspect: {e}"],
                }
    return results


# ---------------------------------------------------------------------------
# Per-service handlers
# ---------------------------------------------------------------------------

@_handler("Amazon Elastic Compute Cloud")
def _inspect_ec2(creds: dict, region: str) -> dict:
    import boto3

    ec2 = boto3.client(
        "ec2",
        aws_access_key_id=creds["access_key"],
        aws_secret_access_key=creds["secret_key"],
        aws_session_token=creds.get("session_token") or None,
        region_name=region,
    )
    cw = boto3.client(
        "cloudwatch",
        aws_access_key_id=creds["access_key"],
        aws_secret_access_key=creds["secret_key"],
        aws_session_token=creds.get("session_token") or None,
        region_name=region,
    )

    response = ec2.describe_instances(
        Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
    )

    resources = []
    findings = []
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=7)

    for reservation in response["Reservations"]:
        for inst in reservation["Instances"]:
            iid = inst["InstanceId"]
            itype = inst["InstanceType"]
            tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
            name = tags.get("Name", iid)

            # Get average CPU over the last 7 days
            avg_cpu = None
            try:
                cpu_resp = cw.get_metric_statistics(
                    Namespace="AWS/EC2",
                    MetricName="CPUUtilization",
                    Dimensions=[{"Name": "InstanceId", "Value": iid}],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=86400,
                    Statistics=["Average"],
                )
                datapoints = cpu_resp.get("Datapoints", [])
                if datapoints:
                    avg_cpu = round(
                        sum(d["Average"] for d in datapoints) / len(datapoints), 1
                    )
            except Exception:
                pass

            resource_info = {
                "instance_id": iid,
                "instance_type": itype,
                "name": name,
                "avg_cpu_7d": avg_cpu,
            }
            resources.append(resource_info)

            if avg_cpu is not None and avg_cpu < 10:
                findings.append(
                    f"{name} ({iid}, {itype}) avg CPU {avg_cpu}% over 7d — "
                    f"consider rightsizing or switching to a smaller instance"
                )

    return {"resources": resources, "findings": findings}


@_handler("Amazon Relational Database Service")
def _inspect_rds(creds: dict, region: str) -> dict:
    import boto3

    rds = boto3.client(
        "rds",
        aws_access_key_id=creds["access_key"],
        aws_secret_access_key=creds["secret_key"],
        aws_session_token=creds.get("session_token") or None,
        region_name=region,
    )

    response = rds.describe_db_instances()
    resources = []
    findings = []

    for db in response["DBInstances"]:
        db_id = db["DBInstanceIdentifier"]
        db_class = db["DBInstanceClass"]
        engine = db.get("Engine", "unknown")
        engine_ver = db.get("EngineVersion", "unknown")
        multi_az = db.get("MultiAZ", False)
        storage_type = db.get("StorageType", "unknown")
        encrypted = db.get("StorageEncrypted", False)
        allocated = db.get("AllocatedStorage", 0)

        resource_info = {
            "db_id": db_id,
            "instance_class": db_class,
            "engine": f"{engine} {engine_ver}",
            "multi_az": multi_az,
            "storage_type": storage_type,
            "storage_gb": allocated,
            "encrypted": encrypted,
        }
        resources.append(resource_info)

        # Flag non-prod Multi-AZ (heuristic: name contains dev/staging/test)
        lower_id = db_id.lower()
        is_nonprod = any(kw in lower_id for kw in ("dev", "staging", "test", "demo"))
        if multi_az and is_nonprod:
            findings.append(
                f"{db_id} ({db_class}) has Multi-AZ enabled but appears non-production "
                f"— disabling Multi-AZ could save ~50% on this instance"
            )

        if not encrypted:
            findings.append(
                f"{db_id} storage is NOT encrypted — enable encryption for compliance"
            )

        if storage_type == "gp2":
            findings.append(
                f"{db_id} uses gp2 storage — migrate to gp3 for ~20% cost reduction "
                f"with better baseline performance"
            )

        # Flag potentially oversized instances
        large_classes = ("db.r5.2xlarge", "db.r5.4xlarge", "db.r6g.2xlarge",
                         "db.r6g.4xlarge", "db.m5.2xlarge", "db.m5.4xlarge")
        if db_class in large_classes and is_nonprod:
            findings.append(
                f"{db_id} is {db_class} in a non-production environment "
                f"— consider downsizing to reduce costs"
            )

    return {"resources": resources, "findings": findings}


@_handler("Amazon Elastic Container Service")
def _inspect_ecs(creds: dict, region: str) -> dict:
    import boto3

    ecs = boto3.client(
        "ecs",
        aws_access_key_id=creds["access_key"],
        aws_secret_access_key=creds["secret_key"],
        aws_session_token=creds.get("session_token") or None,
        region_name=region,
    )

    clusters_resp = ecs.list_clusters()
    cluster_arns = clusters_resp.get("clusterArns", [])

    resources = []
    findings = []

    for cluster_arn in cluster_arns:
        cluster_name = cluster_arn.split("/")[-1]
        services_resp = ecs.list_services(cluster=cluster_arn, maxResults=50)
        service_arns = services_resp.get("serviceArns", [])

        if not service_arns:
            continue

        described = ecs.describe_services(cluster=cluster_arn, services=service_arns)
        for svc in described.get("services", []):
            svc_name = svc["serviceName"]
            desired = svc.get("desiredCount", 0)
            running = svc.get("runningCount", 0)
            cpu = svc.get("cpu", "unknown")
            memory = svc.get("memory", "unknown")

            resource_info = {
                "cluster": cluster_name,
                "service": svc_name,
                "desired_count": desired,
                "running_count": running,
                "cpu": cpu,
                "memory": memory,
            }
            resources.append(resource_info)

            if desired > 0 and running == 0:
                findings.append(
                    f"ECS service {svc_name} in {cluster_name} has {desired} desired "
                    f"but 0 running tasks — check for deployment issues or remove"
                )

    return {"resources": resources, "findings": findings}


@_handler("Amazon Simple Storage Service")
def _inspect_s3(creds: dict, region: str) -> dict:
    import boto3

    s3 = boto3.client(
        "s3",
        aws_access_key_id=creds["access_key"],
        aws_secret_access_key=creds["secret_key"],
        aws_session_token=creds.get("session_token") or None,
        region_name=region,
    )

    buckets_resp = s3.list_buckets()
    resources = []
    findings = []

    for bucket in buckets_resp.get("Buckets", []):
        bucket_name = bucket["Name"]
        has_lifecycle = False
        try:
            s3.get_bucket_lifecycle_configuration(Bucket=bucket_name)
            has_lifecycle = True
        except s3.exceptions.ClientError:
            pass
        except Exception:
            pass

        resource_info = {
            "bucket_name": bucket_name,
            "created": str(bucket.get("CreationDate", "")),
            "has_lifecycle_policy": has_lifecycle,
        }
        resources.append(resource_info)

        if not has_lifecycle:
            findings.append(
                f"Bucket '{bucket_name}' has no lifecycle policy — add lifecycle "
                f"rules to transition old objects to cheaper storage classes or expire them"
            )

    return {"resources": resources, "findings": findings}


@_handler("AWS Lambda")
def _inspect_lambda(creds: dict, region: str) -> dict:
    import boto3

    lam = boto3.client(
        "lambda",
        aws_access_key_id=creds["access_key"],
        aws_secret_access_key=creds["secret_key"],
        aws_session_token=creds.get("session_token") or None,
        region_name=region,
    )

    response = lam.list_functions(MaxItems=50)
    resources = []
    findings = []

    for fn in response.get("Functions", []):
        fn_name = fn["FunctionName"]
        memory = fn.get("MemorySize", 128)
        timeout = fn.get("Timeout", 3)
        runtime = fn.get("Runtime", "unknown")

        resource_info = {
            "function_name": fn_name,
            "runtime": runtime,
            "memory_mb": memory,
            "timeout_sec": timeout,
        }
        resources.append(resource_info)

        if memory >= 1024:
            findings.append(
                f"Lambda '{fn_name}' has {memory}MB memory — "
                f"review if this much memory is needed, reducing can lower cost"
            )

        if timeout >= 300:
            findings.append(
                f"Lambda '{fn_name}' has {timeout}s timeout — "
                f"long timeouts may indicate inefficient code or a need for async processing"
            )

    return {"resources": resources, "findings": findings}


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

def demo_deep_dive() -> dict:
    """Return realistic hardcoded deep dive data for demo mode."""
    return {
        "Amazon Elastic Compute Cloud": {
            "resources": [
                {"instance_id": "i-0a1b2c3d4e5f60010", "instance_type": "m5.2xlarge", "name": "prod-api-server-1", "avg_cpu_7d": 34.2},
                {"instance_id": "i-0a1b2c3d4e5f60011", "instance_type": "m5.2xlarge", "name": "prod-api-server-2", "avg_cpu_7d": 28.7},
                {"instance_id": "i-0a1b2c3d4e5f60012", "instance_type": "c5.xlarge", "name": "prod-worker-1", "avg_cpu_7d": 61.5},
                {"instance_id": "i-0a1b2c3d4e5f60013", "instance_type": "m5.xlarge", "name": "staging-api", "avg_cpu_7d": 4.3},
                {"instance_id": "i-0a1b2c3d4e5f60014", "instance_type": "c5.xlarge", "name": "prod-worker-2", "avg_cpu_7d": 55.8},
                {"instance_id": "i-0a1b2c3d4e5f60015", "instance_type": "m5.large", "name": "dev-server", "avg_cpu_7d": 2.1},
                {"instance_id": "i-0a1b2c3d4e5f60001", "instance_type": "m5.xlarge", "name": "idle-test-server", "avg_cpu_7d": 1.2},
            ],
            "findings": [
                "staging-api (i-0a1b2c3d4e5f60013, m5.xlarge) avg CPU 4.3% over 7d — consider rightsizing or switching to a smaller instance",
                "dev-server (i-0a1b2c3d4e5f60015, m5.large) avg CPU 2.1% over 7d — consider rightsizing or switching to a smaller instance",
                "idle-test-server (i-0a1b2c3d4e5f60001, m5.xlarge) avg CPU 1.2% over 7d — consider rightsizing or switching to a smaller instance",
                "prod-api-server-1 and prod-api-server-2 (m5.2xlarge) avg CPU ~31% — could fit into m5.xlarge to save ~50%",
            ],
        },
        "Amazon Relational Database Service": {
            "resources": [
                {"db_id": "prod-postgres-main", "instance_class": "db.r5.xlarge", "engine": "postgres 14.9", "multi_az": True, "storage_type": "gp3", "storage_gb": 500, "encrypted": True},
                {"db_id": "prod-postgres-replica", "instance_class": "db.r5.large", "engine": "postgres 14.9", "multi_az": False, "storage_type": "gp3", "storage_gb": 500, "encrypted": True},
                {"db_id": "staging-postgres", "instance_class": "db.r5.large", "engine": "postgres 13.11", "multi_az": True, "storage_type": "gp2", "storage_gb": 200, "encrypted": False},
            ],
            "findings": [
                "staging-postgres (db.r5.large) has Multi-AZ enabled but appears non-production — disabling Multi-AZ could save ~50% on this instance",
                "staging-postgres storage is NOT encrypted — enable encryption for compliance",
                "staging-postgres uses gp2 storage — migrate to gp3 for ~20% cost reduction with better baseline performance",
                "staging-postgres runs postgres 13.11 — consider upgrading to 14.x or 15.x for performance improvements",
            ],
        },
        "Amazon Simple Storage Service": {
            "resources": [
                {"bucket_name": "prod-assets-bucket", "created": "2024-03-15", "has_lifecycle_policy": True},
                {"bucket_name": "prod-logs-bucket", "created": "2024-03-15", "has_lifecycle_policy": False},
                {"bucket_name": "prod-backups-bucket", "created": "2024-04-01", "has_lifecycle_policy": True},
                {"bucket_name": "data-lake-bucket", "created": "2024-06-20", "has_lifecycle_policy": False},
                {"bucket_name": "dev-artifacts-bucket", "created": "2025-01-10", "has_lifecycle_policy": False},
            ],
            "findings": [
                "Bucket 'prod-logs-bucket' has no lifecycle policy — add lifecycle rules to transition old objects to cheaper storage classes or expire them",
                "Bucket 'data-lake-bucket' has no lifecycle policy — add lifecycle rules to transition old objects to cheaper storage classes or expire them",
                "Bucket 'dev-artifacts-bucket' has no lifecycle policy — add lifecycle rules to transition old objects to cheaper storage classes or expire them",
            ],
        },
        "AWS Lambda": {
            "resources": [
                {"function_name": "prod-image-processor", "runtime": "python3.11", "memory_mb": 2048, "timeout_sec": 300},
                {"function_name": "prod-api-authorizer", "runtime": "nodejs18.x", "memory_mb": 128, "timeout_sec": 5},
                {"function_name": "prod-data-pipeline", "runtime": "python3.11", "memory_mb": 3008, "timeout_sec": 900},
                {"function_name": "prod-webhook-handler", "runtime": "python3.11", "memory_mb": 512, "timeout_sec": 30},
                {"function_name": "dev-test-runner", "runtime": "python3.11", "memory_mb": 1024, "timeout_sec": 600},
            ],
            "findings": [
                "Lambda 'prod-image-processor' has 2048MB memory — review if this much memory is needed, reducing can lower cost",
                "Lambda 'prod-data-pipeline' has 3008MB memory — review if this much memory is needed, reducing can lower cost",
                "Lambda 'prod-image-processor' has 300s timeout — long timeouts may indicate inefficient code or a need for async processing",
                "Lambda 'prod-data-pipeline' has 900s timeout — long timeouts may indicate inefficient code or a need for async processing",
                "Lambda 'dev-test-runner' has 1024MB memory — review if this much memory is needed, reducing can lower cost",
                "Lambda 'dev-test-runner' has 600s timeout — long timeouts may indicate inefficient code or a need for async processing",
            ],
        },
        "Amazon CloudFront": {
            "resources": [
                {"distribution_id": "E1A2B3C4D5E6F7", "domain": "cdn.example.com", "price_class": "PriceClass_All"},
                {"distribution_id": "E7F6E5D4C3B2A1", "domain": "static.example.com", "price_class": "PriceClass_All"},
            ],
            "findings": [
                "Distribution E1A2B3C4D5E6F7 (cdn.example.com) uses PriceClass_All — switching to PriceClass_100 or PriceClass_200 can reduce costs if traffic is primarily US/EU",
                "Distribution E7F6E5D4C3B2A1 (static.example.com) uses PriceClass_All — switching to PriceClass_100 or PriceClass_200 can reduce costs if traffic is primarily US/EU",
            ],
        },
    }

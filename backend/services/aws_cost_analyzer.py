import boto3
from datetime import datetime, timedelta
from typing import Dict, List


class AWSCostAnalyzer:
    def __init__(self, access_key: str, secret_key: str, region: str = 'us-east-1'):
        self.client = boto3.client(
            'ce',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )
        self.ec2_client = boto3.client(
            'ec2',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )

    def get_monthly_cost(self) -> Dict:
        """Get current month's total cost."""
        end_date = datetime.now().date()
        start_date = end_date.replace(day=1)

        response = self.client.get_cost_and_usage(
            TimePeriod={
                'Start': str(start_date),
                'End': str(end_date)
            },
            Granularity='MONTHLY',
            Metrics=['UnblendedCost']
        )

        total_cost = float(
            response['ResultsByTime'][0]['Total']['UnblendedCost']['Amount']
        )

        return {
            'total_cost': round(total_cost, 2),
            'currency': 'USD',
            'period': f"{start_date} to {end_date}"
        }

    def get_cost_by_service(self) -> List[Dict]:
        """Get top 10 cost drivers by service."""
        end_date = datetime.now().date()
        start_date = end_date.replace(day=1)

        response = self.client.get_cost_and_usage(
            TimePeriod={
                'Start': str(start_date),
                'End': str(end_date)
            },
            Granularity='MONTHLY',
            Metrics=['UnblendedCost'],
            GroupBy=[
                {
                    'Type': 'DIMENSION',
                    'Key': 'SERVICE'
                }
            ]
        )

        services = []
        for group in response['ResultsByTime'][0]['Groups']:
            service_name = group['Keys'][0]
            cost = float(group['Metrics']['UnblendedCost']['Amount'])

            if cost > 0:
                services.append({
                    'service': service_name,
                    'cost': round(cost, 2)
                })

        services.sort(key=lambda x: x['cost'], reverse=True)
        return services[:10]

    def find_idle_ec2_instances(self) -> List[Dict]:
        """Find running EC2 instances (potential idle resources)."""
        response = self.ec2_client.describe_instances(
            Filters=[
                {'Name': 'instance-state-name', 'Values': ['running']}
            ]
        )

        idle_instances = []

        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                instance_id = instance['InstanceId']
                instance_type = instance['InstanceType']

                estimated_cost = self._estimate_instance_cost(instance_type)

                idle_instances.append({
                    'instance_id': instance_id,
                    'instance_type': instance_type,
                    'estimated_monthly_cost': estimated_cost,
                    'recommendation': 'Stop or terminate if not needed'
                })

        return idle_instances

    def find_unattached_ebs_volumes(self) -> List[Dict]:
        """Find EBS volumes not attached to any instance."""
        response = self.ec2_client.describe_volumes(
            Filters=[
                {'Name': 'status', 'Values': ['available']}
            ]
        )

        unattached_volumes = []

        for volume in response['Volumes']:
            volume_id = volume['VolumeId']
            size_gb = volume['Size']
            volume_type = volume['VolumeType']

            monthly_cost = size_gb * 0.10

            unattached_volumes.append({
                'volume_id': volume_id,
                'size_gb': size_gb,
                'volume_type': volume_type,
                'estimated_monthly_cost': round(monthly_cost, 2),
                'recommendation': 'Delete if not needed'
            })

        return unattached_volumes

    def find_old_snapshots(self, days_old: int = 90) -> List[Dict]:
        """Find snapshots older than X days."""
        response = self.ec2_client.describe_snapshots(
            OwnerIds=['self']
        )

        cutoff_date = datetime.now() - timedelta(days=days_old)
        old_snapshots = []

        for snapshot in response['Snapshots']:
            snapshot_time = snapshot['StartTime'].replace(tzinfo=None)

            if snapshot_time < cutoff_date:
                snapshot_id = snapshot['SnapshotId']
                size_gb = snapshot['VolumeSize']

                monthly_cost = size_gb * 0.05

                old_snapshots.append({
                    'snapshot_id': snapshot_id,
                    'size_gb': size_gb,
                    'created_date': str(snapshot_time.date()),
                    'age_days': (datetime.now() - snapshot_time).days,
                    'estimated_monthly_cost': round(monthly_cost, 2),
                    'recommendation': 'Review and delete if not needed'
                })

        return old_snapshots

    def _estimate_instance_cost(self, instance_type: str) -> float:
        """Simplified instance cost estimation."""
        pricing = {
            't2.micro': 8.50,
            't2.small': 17.00,
            't2.medium': 34.00,
            't3.micro': 7.50,
            't3.small': 15.00,
            't3.medium': 30.00,
            'm5.large': 70.00,
            'm5.xlarge': 140.00,
            'm5.2xlarge': 280.00,
            'c5.large': 62.00,
            'c5.xlarge': 124.00,
            'r5.large': 91.00,
            'r5.xlarge': 182.00,
        }

        return pricing.get(instance_type, 50.00)

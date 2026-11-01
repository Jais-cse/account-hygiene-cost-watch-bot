
import os
import re
import logging
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# Logging
log = logging.getLogger()
log.setLevel(logging.INFO)

# Environment variables
TOPIC_ARN = os.environ["TOPIC_ARN"]

REQUIRED_TAGS = [
    t.strip()
    for t in os.environ.get(
        "REQUIRED_TAGS", "Owner,Environment,CostCenter"
    ).split(",")
]

STOPPED_DAYS = int(os.environ.get("STOPPED_DAYS", "7"))
EBS_GB_MONTH = float(os.environ.get("EBS_GB_MONTH_USD", "0.08"))
EIP_MONTH = float(os.environ.get("EIP_MONTH_USD", "3.65"))

# AWS clients
ec2 = boto3.client("ec2")
s3 = boto3.client("s3")
sns = boto3.client("sns")
cw = boto3.client("cloudwatch")


def missing_tags(tags):
    """Return required tags that are missing."""
    present = {tag["Key"] for tag in (tags or [])}
    return [key for key in REQUIRED_TAGS if key not in present]


def stopped_age_days(reason):
    """Calculate how many days an EC2 instance has been stopped."""
    match = re.search(
        r"\(([0-9-]+ [0-9:]+) GMT\)",
        reason or ""
    )

    if not match:
        return None

    stopped_time = datetime.strptime(
        match.group(1),
        "%Y-%m-%d %H:%M:%S"
    ).replace(tzinfo=timezone.utc)

    return (datetime.now(timezone.utc) - stopped_time).days


def scan_volumes():
    """Find unattached EBS volumes and volumes missing tags."""
    unattached = []
    untagged = []

    paginator = ec2.get_paginator("describe_volumes")

    for page in paginator.paginate():
        for volume in page["Volumes"]:

            if volume["State"] == "available":
                unattached.append({
                    "id": volume["VolumeId"],
                    "gb": volume["Size"]
                })

            missing = missing_tags(volume.get("Tags"))

            if missing:
                untagged.append({
                    "id": volume["VolumeId"],
                    "type": "volume",
                    "missing": missing
                })

    return unattached, untagged


def scan_instances():
    """Find stopped EC2 instances and instances missing tags."""
    stopped = []
    untagged = []

    paginator = ec2.get_paginator("describe_instances")

    for page in paginator.paginate():
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:

                state = instance["State"]["Name"]

                if state == "terminated":
                    continue

                missing = missing_tags(instance.get("Tags"))

                if missing:
                    untagged.append({
                        "id": instance["InstanceId"],
                        "type": "instance",
                        "missing": missing
                    })

                if state == "stopped":
                    days = stopped_age_days(
                        instance.get("StateTransitionReason")
                    )

                    if days is None or days >= STOPPED_DAYS:
                        stopped.append({
                            "id": instance["InstanceId"],
                            "days": days
                        })

    return stopped, untagged


def scan_eips():
    """Find Elastic IP addresses that are not associated."""
    addresses = ec2.describe_addresses()["Addresses"]

    return [
        {"ip": address["PublicIp"]}
        for address in addresses
        if "AssociationId" not in address
    ]


def is_public(bucket_name):
    """Check bucket public access block, policy and ACL."""

    # Check Public Access Block configuration
    try:
        pab = s3.get_public_access_block(
            Bucket=bucket_name
        )["PublicAccessBlockConfiguration"]

        if all(pab.values()):
            return False

    except ClientError as error:
        code = error.response["Error"]["Code"]

        if code != "NoSuchPublicAccessBlockConfiguration":
            log.warning(
                "Public access block check failed for %s: %s",
                bucket_name,
                error
            )

    # Check bucket policy
    try:
        policy_status = s3.get_bucket_policy_status(
            Bucket=bucket_name
        )["PolicyStatus"]

        if policy_status["IsPublic"]:
            return True

    except ClientError as error:
        code = error.response["Error"]["Code"]

        if code != "NoSuchBucketPolicy":
            log.warning(
                "Bucket policy check failed for %s: %s",
                bucket_name,
                error
            )

    # Check bucket ACL
    try:
        grants = s3.get_bucket_acl(
            Bucket=bucket_name
        )["Grants"]

        for grant in grants:
            uri = grant.get("Grantee", {}).get("URI", "")

            if (
                uri.endswith("/AllUsers")
                or uri.endswith("/AuthenticatedUsers")
            ):
                return True

    except ClientError as error:
        log.warning(
            "Bucket ACL check failed for %s: %s",
            bucket_name,
            error
        )

    return False


def scan_buckets():
    """Find potentially public S3 buckets."""
    buckets = s3.list_buckets()["Buckets"]

    return [
        bucket["Name"]
        for bucket in buckets
        if is_public(bucket["Name"])
    ]


def publish_metrics(counts, waste):
    """Publish five finding counts and one cost metric."""
    metric_data = [
        {
            "MetricName": name,
            "Value": value,
            "Unit": "Count"
        }
        for name, value in counts.items()
    ]

    metric_data.append({
        "MetricName": "EstimatedMonthlyWasteUSD",
        "Value": waste,
        "Unit": "None"
    })

    cw.put_metric_data(
        Namespace="AccountHygiene",
        MetricData=metric_data
    )


def section(title, rows, formatter):
    """Format a section of the email report."""
    if not rows:
        return []

    lines = ["", f"{title} ({len(rows)})"]

    lines += [
        " - " + formatter(row)
        for row in rows[:10]
    ]

    if len(rows) > 10:
        lines.append(
            f" ...and {len(rows) - 10} more"
        )

    return lines


def lambda_handler(event, context):

    # Run all scanners
    volumes, untagged_volumes = scan_volumes()
    stopped, untagged_instances = scan_instances()
    eips = scan_eips()
    public_buckets = scan_buckets()

    untagged = untagged_volumes + untagged_instances

    # Estimate monthly waste
    waste = round(
        sum(volume["gb"] for volume in volumes) * EBS_GB_MONTH
        + len(eips) * EIP_MONTH,
        2
    )

    # Count findings
    counts = {
        "UnattachedVolumes": len(volumes),
        "IdleElasticIPs": len(eips),
        "UntaggedResources": len(untagged),
        "StoppedInstances": len(stopped),
        "PublicBuckets": len(public_buckets)
    }

    total = sum(counts.values())

    # Publish CloudWatch metrics
    publish_metrics(counts, waste)

    # Prepare email report
    lines = [
        (
            f"Account hygiene report - "
            f"{datetime.now(timezone.utc):%Y-%m-%d} "
            f"- region {os.environ.get('AWS_REGION')}"
        ),
        (
            f"Findings: {total}   "
            f"Estimated monthly waste: ${waste} "
            "(estimate, not billed data)"
        )
    ]

    lines += section(
        "PUBLIC S3 BUCKETS (fix first)",
        public_buckets,
        lambda row: row
    )

    lines += section(
        "Unattached EBS volumes",
        volumes,
        lambda row: f"{row['id']} ({row['gb']} GB)"
    )

    lines += section(
        "Idle Elastic IPs",
        eips,
        lambda row: row["ip"]
    )

    lines += section(
        f"Stopped instances (>= {STOPPED_DAYS} days)",
        stopped,
        lambda row: f"{row['id']} ({row['days']} days)"
    )

    lines += section(
        "Missing required tags",
        untagged,
        lambda row: (
            f"{row['type']} {row['id']} "
            f"missing {','.join(row['missing'])}"
        )
    )

    if total == 0:
        lines.extend(["", "All clear."])

    # Send SNS email
    subject = (
        f"[Hygiene] {total} findings, "
        f"~${waste}/mo waste"
    )

    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject=subject[:100],
        Message="\n".join(lines)
    )

    log.info(
        "Report sent. Findings=%s, estimated waste=$%s",
        total,
        waste
    )

    return {
        "findings": total,
        "waste_usd": waste
    }

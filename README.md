# Account Hygiene and Cost-Watch Bot

A serverless AWS automation project that scans AWS resources for common account hygiene issues, identifies potential monthly waste, and sends automated email alerts.

## Project Overview

The Account Hygiene and Cost-Watch Bot helps identify unused, misconfigured, and potentially risky AWS resources through scheduled automated scans.

It uses AWS Lambda, EventBridge Scheduler, SNS, and CloudWatch to automate resource monitoring and reporting.

## Architecture

```text
Amazon EventBridge Scheduler
            |
            v
      AWS Lambda
   (Python 3.12 Scanner)
            |
     +------+------+
     |      |      |
     v      v      v
    EC2     S3   CloudWatch
     |             |
     v             v
 Resource       Metrics,
  Checks        Dashboard
     |
     v
 Amazon SNS
     |
     v
 Email Alerts
```

## Features

The scanner checks for five categories of resource hygiene issues:

1. **Unattached EBS Volumes** – Identifies EBS volumes that are not attached to EC2 instances.
2. **Idle Elastic IPs** – Detects allocated Elastic IP addresses that are not associated with instances.
3. **Untagged Resources** – Finds EC2 instances and EBS volumes missing required tags.
4. **Stopped EC2 Instances** – Identifies instances that have remained stopped beyond the configured threshold.
5. **Public S3 Buckets** – Detects buckets with public access configurations.

It also estimates potential monthly waste using configured EBS and Elastic IP cost assumptions.

## AWS Services Used

- AWS Lambda – Executes the scanning logic.
- Amazon EventBridge Scheduler – Triggers daily scans.
- Amazon SNS – Sends email notifications.
- Amazon CloudWatch – Stores custom metrics, dashboards, logs, and alarms.
- Amazon EC2 – Provides instance, volume, and Elastic IP information.
- Amazon S3 – Provides bucket security configuration information.
- AWS IAM – Manages permissions for the scanner.

## Configuration

| Environment Variable | Purpose |
|---|---|
| `TOPIC_ARN` | SNS topic ARN for notifications |
| `REQUIRED_TAGS` | Required resource tags |
| `STOPPED_DAYS` | Minimum stopped duration threshold |
| `EBS_GB_MONTH_USD` | Estimated EBS cost per GB-month |
| `EIP_MONTH_USD` | Estimated monthly idle Elastic IP cost |

## CloudWatch Custom Metrics

The project publishes metrics under the namespace `AccountHygiene`:

- `UnattachedVolumes`
- `IdleElasticIPs`
- `UntaggedResources`
- `StoppedInstances`
- `PublicBuckets`
- `EstimatedMonthlyWasteUSD`

## Monitoring and Alerts

A CloudWatch dashboard provides:

- Resource hygiene counts.
- Estimated monthly waste.
- Metric trends over time.
- Lambda execution errors and duration.

Four CloudWatch alarms monitor:

- Public S3 bucket findings.
- Estimated monthly waste threshold.
- Scanner heartbeat.
- Lambda execution errors.

Alarm notifications are configured through the SNS topic.

## Security and Cost Considerations

- Uses IAM permissions for required AWS operations.
- Keeps Lambda outside a VPC because it does not require VPC access.
- Configures CloudWatch log retention for 14 days.
- Uses configured pricing assumptions for waste estimation instead of Cost Explorer API calls.
- Public S3 findings should be reviewed and approved individually. The portfolio bucket `ms-portfolio-2026` is an intentional public-access exception.

## Deployment Summary

- AWS Region: `ap-south-1` (Mumbai)
- Runtime: Python 3.12
- Execution: Daily at 8:00 AM IST
- Notifications: Amazon SNS email
- Monitoring: Amazon CloudWatch

## Project Outcome

Built a serverless AWS account hygiene monitoring solution that automates resource checks, highlights potential cost waste and security risks, and provides centralized monitoring through CloudWatch.

# ==============================================================================
# Infrastructure as Code — Lakehouse Platform Terraform Specification
# Demonstrates Cloud Platform Engineering & FinOps Best Practices.
# (Note: Used as an architectural portfolio showcase; no paid deployment required).
# ==============================================================================

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.30"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Environment = var.environment
      Project     = "TechIntelligence-Lakehouse"
      ManagedBy   = "Terraform"
      CostCenter  = "DataPlatform"
    }
  }
}

# ------------------------------------------------------------------------------
# Variables
# ------------------------------------------------------------------------------
variable "aws_region" {
  description = "AWS deployment region"
  type        = string
  default     = "ap-south-1" # Asia Pacific (Mumbai)
}

variable "environment" {
  description = "Target deployment tier"
  type        = string
  default     = "production"
}

variable "lake_bucket_name" {
  description = "Globally unique S3 Data Lake bucket name"
  type        = string
  default     = "tech-intelligence-lakehouse-data"
}

# ------------------------------------------------------------------------------
# S3 Data Lakehouse Storage
# ------------------------------------------------------------------------------
resource "aws_s3_bucket" "lakehouse_storage" {
  bucket = var.lake_bucket_name
}

# Block all public access for enterprise security
resource "aws_s3_bucket_public_access_block" "lake_security" {
  bucket                  = aws_s3_bucket.lakehouse_storage.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Versioning for data governance & disaster recovery
resource "aws_s3_bucket_versioning" "lake_versioning" {
  bucket = aws_s3_bucket.lakehouse_storage.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Server-side encryption using AES-256
resource "aws_s3_bucket_server_side_encryption_configuration" "lake_encryption" {
  bucket = aws_s3_bucket.lakehouse_storage.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# FinOps Lifecycle Policy: Transition and expire data to optimize storage cost
resource "aws_s3_bucket_lifecycle_configuration" "lake_lifecycle" {
  bucket = aws_s3_bucket.lakehouse_storage.id

  # Bronze Layer: Retain raw JSONL for 90 days then transition/expire
  rule {
    id     = "bronze-raw-lifecycle"
    status = "Enabled"
    filter {
      prefix = "bronze/"
    }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    expiration {
      days = 90
    }
  }

  # Quarantine Layer: Auto-clean unrecovered corrupt records after 30 days
  rule {
    id     = "quarantine-auto-expire"
    status = "Enabled"
    filter {
      prefix = "quarantine/"
    }
    expiration {
      days = 30
    }
  }
}

# ------------------------------------------------------------------------------
# AWS Glue Data Catalog
# ------------------------------------------------------------------------------
resource "aws_glue_catalog_database" "lakehouse_catalog" {
  name        = "tech_intelligence_lake"
  description = "Data catalog for Silver Parquet and Gold analytical marts"
}

# ------------------------------------------------------------------------------
# AWS Athena Workgroup with FinOps Guardrails
# ------------------------------------------------------------------------------
resource "aws_athena_workgroup" "analytics_workgroup" {
  name        = "tech_intelligence_analytics"
  description = "Workgroup for analytical queries with cost-control scan limits"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    
    # FinOps Guardrail: Abort queries scanning more than 500 MB to prevent accidental cost
    bytes_scanned_cutoff_per_query     = 524288000 # 500 MB

    result_configuration {
      output_location = "s3://${aws_s3_bucket.lakehouse_storage.bucket}/athena_query_results/"
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}

# ------------------------------------------------------------------------------
# IAM Least-Privilege Policy for Read-Only Analytics
# ------------------------------------------------------------------------------
resource "aws_iam_policy" "lakehouse_readonly_access" {
  name        = "TechIntelligenceLakeReadOnly"
  description = "Allows read-only access to Silver and Gold Parquet layers"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.lakehouse_storage.arn,
          "${aws_s3_bucket.lakehouse_storage.arn}/silver/*",
          "${aws_s3_bucket.lakehouse_storage.arn}/gold/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:GetPartitions"
        ]
        Resource = "*"
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Outputs
# ------------------------------------------------------------------------------
output "lakehouse_bucket" {
  description = "S3 Lakehouse bucket name"
  value       = aws_s3_bucket.lakehouse_storage.bucket
}

output "glue_database_name" {
  description = "Glue Catalog Database"
  value       = aws_glue_catalog_database.lakehouse_catalog.name
}

output "athena_workgroup_name" {
  description = "Athena Analytics Workgroup"
  value       = aws_athena_workgroup.analytics_workgroup.name
}

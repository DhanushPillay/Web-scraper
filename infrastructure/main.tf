# Sniffer — Terraform stub (S3 lake, IAM read-only)
# ponytail: demo for resume; not applied on free tier. Shows IaC thinking without billing.
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
  # use env AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
}

variable "region" {
  description = "AWS region for lake"
  type        = string
  default     = "ap-south-1" # Mumbai — close to Pune
}

variable "bucket_name" {
  description = "S3 bucket for Bronze/Silver/Gold (must be globally unique)"
  type        = string
  default     = "sniffer-lake-demo-CHANGE_ME"
}

resource "aws_s3_bucket" "lake" {
  bucket = var.bucket_name
  tags = { Project = "Sniffer", Tier = "free-demo" }
}

resource "aws_s3_bucket_versioning" "lake" {
  bucket = aws_s3_bucket.lake.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "lake" {
  bucket = aws_s3_bucket.lake.id
  rule {
    id     = "expire-bronze-90d"
    status = "Enabled"
    filter { prefix = "bronze/" }
    expiration { days = 90 }
  }
}

# Read-only IAM for app / Athena
resource "aws_iam_policy" "lake_readonly" {
  name        = "sniffer-lake-readonly"
  description = "Read-only for DuckDB/Athena on S3 lake"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect   = "Allow",
      Action   = ["s3:GetObject", "s3:ListBucket"],
      Resource = [aws_s3_bucket.lake.arn, "${aws_s3_bucket.lake.arn}/*"]
    }]
  })
}

output "bucket" { value = aws_s3_bucket.lake.bucket }

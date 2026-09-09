terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # 1단계: 로컬 state (요청 디렉터리마다 1개).
  # 2단계에서 이 블록을 backend "s3" 로 교체하고 DynamoDB 잠금을 붙인다.
  # 그때까지 이 디렉터리를 지우면 리소스가 추적 불가능해지므로 destroy 전에는 지우지 않는다.
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      ManagedBy = "mcp-provisioning"
      RequestId = var.request_id
    }
  }
}

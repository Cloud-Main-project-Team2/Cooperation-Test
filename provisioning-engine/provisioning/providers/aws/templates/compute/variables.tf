variable "name" {
  description = "리소스 이름 (Name 태그 및 접두사로 사용)"
  type        = string
}

variable "request_id" {
  description = "프로비저닝 요청 ID. 모든 리소스에 태그로 남겨 추적한다."
  type        = string
}

variable "region" {
  description = "AWS 리전 코드"
  type        = string
}

variable "instance_type" {
  description = "EC2 인스턴스 타입"
  type        = string
}

variable "image_ssm_parameter" {
  description = "AMI ID를 조회할 SSM Public Parameter 경로"
  type        = string
}

variable "image_id" {
  description = "AMI ID를 직접 지정하는 경우. 비어 있으면 SSM 파라미터로 조회한다."
  type        = string
  default     = ""
}

variable "disk_gb" {
  description = "루트 볼륨 크기(GB)"
  type        = number
  default     = 30

  validation {
    condition     = var.disk_gb >= 8 && var.disk_gb <= 16384
    error_message = "disk_gb는 8 이상 16384 이하여야 합니다."
  }
}

variable "tags" {
  description = "사용자 지정 태그"
  type        = map(string)
  default     = {}
}

variable "vpc_id" {
  description = "비어 있으면 기본 VPC를 사용한다."
  type        = string
  default     = ""
}

variable "subnet_id" {
  description = "비어 있으면 VPC의 서브넷 중 하나를 자동 선택한다."
  type        = string
  default     = ""
}

variable "key_name" {
  description = "SSH 키 페어 이름. 비어 있으면 키를 붙이지 않는다(SSM 접속 전제)."
  type        = string
  default     = ""
}

variable "create_security_group" {
  description = "전용 보안 그룹을 생성할지 여부"
  type        = bool
  default     = true
}

variable "security_group_ids" {
  description = "create_security_group = false 일 때 사용할 기존 보안 그룹"
  type        = list(string)
  default     = []
}

variable "allowed_ssh_cidrs" {
  description = "SSH(22) 인바운드를 허용할 CIDR. 기본값은 빈 목록 = 인바운드 없음."
  type        = list(string)
  default     = []

  validation {
    condition     = !contains(var.allowed_ssh_cidrs, "0.0.0.0/0")
    error_message = "0.0.0.0/0 전체 개방은 허용하지 않습니다. 사내 IP 범위를 지정하세요."
  }
}

variable "associate_public_ip" {
  description = "공인 IP 할당 여부. 기본값 false (미사용 공인 IP는 과금 대상)."
  type        = bool
  default     = false
}

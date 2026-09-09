# ─────────────────────────────────────────────────────────────
# 조회 (Data sources)
# ─────────────────────────────────────────────────────────────
data "aws_ssm_parameter" "image" {
  count = var.image_id == "" ? 1 : 0
  name  = var.image_ssm_parameter
}

data "aws_vpc" "default" {
  count   = var.vpc_id == "" ? 1 : 0
  default = true
}

data "aws_subnets" "candidates" {
  count = var.subnet_id == "" ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [local.vpc_id]
  }
}

locals {
  vpc_id = var.vpc_id != "" ? var.vpc_id : data.aws_vpc.default[0].id

  # 서브넷 자동 선택 시 정렬해서 첫 번째를 고른다.
  # 정렬하지 않으면 실행할 때마다 다른 서브넷이 잡혀 불필요한 재생성이 발생한다.
  subnet_id = var.subnet_id != "" ? var.subnet_id : sort(data.aws_subnets.candidates[0].ids)[0]

  ami_id = var.image_id != "" ? var.image_id : nonsensitive(data.aws_ssm_parameter.image[0].value)

  tags = merge(var.tags, {
    Name = var.name
  })

  security_group_ids = var.create_security_group ? [aws_security_group.this[0].id] : var.security_group_ids
}

# ─────────────────────────────────────────────────────────────
# 보안 그룹
#   - 인바운드는 명시한 CIDR에만 연다. 기본값은 빈 목록 = 인바운드 없음.
#   - 0.0.0.0/0 은 variables.tf의 validation에서 막힌다.
# ─────────────────────────────────────────────────────────────
resource "aws_security_group" "this" {
  count = var.create_security_group ? 1 : 0

  name_prefix = "${var.name}-"
  description = "Managed by mcp-provisioning (${var.request_id})"
  vpc_id      = local.vpc_id

  dynamic "ingress" {
    for_each = length(var.allowed_ssh_cidrs) > 0 ? [1] : []
    content {
      description = "SSH from allowed ranges"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = var.allowed_ssh_cidrs
    }
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, { Name = "${var.name}-sg" })

  lifecycle {
    create_before_destroy = true
  }
}

# ─────────────────────────────────────────────────────────────
# EC2 인스턴스
# ─────────────────────────────────────────────────────────────
resource "aws_instance" "this" {
  ami           = local.ami_id
  instance_type = var.instance_type
  subnet_id     = local.subnet_id
  key_name      = var.key_name != "" ? var.key_name : null

  vpc_security_group_ids      = local.security_group_ids
  associate_public_ip_address = var.associate_public_ip

  root_block_device {
    volume_size           = var.disk_gb
    volume_type           = "gp3"
    encrypted             = true # 기본값으로 암호화한다. 나중에 켜려면 볼륨 교체가 필요하다.
    delete_on_termination = true
    tags                  = merge(local.tags, { Name = "${var.name}-root" })
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required" # IMDSv2 강제
  }

  tags = local.tags

  lifecycle {
    # AMI가 갱신됐다는 이유로 운영 중 인스턴스가 재생성되는 사고를 막는다.
    ignore_changes = [ami]
  }
}

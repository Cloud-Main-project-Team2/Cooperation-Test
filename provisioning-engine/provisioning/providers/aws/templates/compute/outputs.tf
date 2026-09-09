# Python이 곧바로 ResourceRecord로 옮길 수 있도록 한 덩어리로 내보낸다.
# 개별 output도 함께 두어 terraform 콘솔에서 사람이 확인하기 쉽게 한다.

output "resource_summary" {
  description = "인벤토리 레코드로 정규화하기 위한 요약"
  value = {
    instance_id           = aws_instance.this.id
    name                  = var.name
    instance_type         = aws_instance.this.instance_type
    region                = var.region
    availability_zone     = aws_instance.this.availability_zone
    state                 = aws_instance.this.instance_state
    arn                   = aws_instance.this.arn
    private_ip            = aws_instance.this.private_ip
    public_ip             = aws_instance.this.public_ip
    ami_id                = aws_instance.this.ami
    subnet_id             = aws_instance.this.subnet_id
    security_group_ids    = aws_instance.this.vpc_security_group_ids
    root_volume_encrypted = true
    tags                  = aws_instance.this.tags_all
  }
}

output "instance_id" {
  value = aws_instance.this.id
}

output "private_ip" {
  value = aws_instance.this.private_ip
}

output "public_ip" {
  description = "associate_public_ip = false 이면 빈 문자열"
  value       = aws_instance.this.public_ip
}

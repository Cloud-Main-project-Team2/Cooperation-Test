"""공통 스펙의 논리 값 → AWS 실제 값 매핑.

이 파일이 '서비스 매핑 표'의 AWS 열이다.
GCP/Azure Provider도 같은 키(seoul, 2vcpu-8gb, ubuntu-22.04)를 갖는
자기 매핑 파일을 갖게 되며, 그래서 화면에서는 한 벌의 공통 입력만 받으면 된다.

매핑에 없는 값은 조용히 넘기지 않고 예외로 막는다.
잘못 추측해서 만들면 과금이 발생하기 때문이다.
"""

from __future__ import annotations

# 논리 리전명 → AWS 리전 코드
REGIONS: dict[str, str] = {
    "seoul": "ap-northeast-2",
    "tokyo": "ap-northeast-1",
    "singapore": "ap-southeast-1",
    "virginia": "us-east-1",
    "oregon": "us-west-2",
    "frankfurt": "eu-central-1",
}

# 논리 사양명 → EC2 인스턴스 타입
SIZES: dict[str, str] = {
    "1vcpu-1gb": "t3.micro",
    "2vcpu-4gb": "t3.medium",
    "2vcpu-8gb": "t3.large",
    "4vcpu-16gb": "m5.xlarge",
    "8vcpu-32gb": "m5.2xlarge",
}

# 논리 이미지명 → SSM Public Parameter 경로
# AMI ID를 하드코딩하지 않는다. 리전마다 다르고 갱신되면 낡기 때문이다.
IMAGES: dict[str, str] = {
    "ubuntu-22.04": "/aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2/ami-id",
    "ubuntu-24.04": "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id",
    "amazonlinux-2023": "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64",
}


def region(logical: str) -> str:
    try:
        return REGIONS[logical]
    except KeyError:
        raise ValueError(
            f"AWS에 매핑되지 않은 리전: '{logical}' (가능: {', '.join(REGIONS)})"
        ) from None


def instance_type(logical: str) -> str:
    try:
        return SIZES[logical]
    except KeyError:
        raise ValueError(
            f"AWS에 매핑되지 않은 사양: '{logical}' (가능: {', '.join(SIZES)})"
        ) from None


def image_parameter(logical: str) -> str:
    try:
        return IMAGES[logical]
    except KeyError:
        raise ValueError(
            f"AWS에 매핑되지 않은 이미지: '{logical}' (가능: {', '.join(IMAGES)})"
        ) from None


def provider_type_label(instance_type_value: str) -> str:
    """인벤토리 화면의 'CSP 원본 유형' 열에 그대로 들어갈 문자열."""
    return f"EC2 / {instance_type_value}"

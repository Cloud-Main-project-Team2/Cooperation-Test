"""AWS Provider (1단계: Compute만).

TerraformProvider가 실행 흐름을 다 갖고 있으므로 여기에는
'AWS라서 다른 것'만 남는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from provisioning.core.models import (
    CloudPlatform,
    ResourceRecord,
    ResourceSpec,
    ResourceType,
)
from provisioning.core.provider import TerraformProvider

from . import mapping

TEMPLATE_ROOT = Path(__file__).parent / "templates"

# 태그 키는 CSP마다 제약이 다르다. (GCP Label은 소문자만 허용 등)
MAX_TAGS = 50


class AwsProvider(TerraformProvider):
    platform = CloudPlatform.AWS
    supported_types = frozenset({ResourceType.COMPUTE})   # 2단계에서 확장

    # ── 검증 ────────────────────────────────────────────────
    def validate_spec(self, spec: ResourceSpec) -> list[str]:
        problems: list[str] = []

        if not spec.name or not spec.name.strip():
            problems.append("name이 비어 있습니다.")
        elif len(spec.name) > 60:
            problems.append("name은 60자를 넘을 수 없습니다.")

        for label, fn, value in (
            ("region", mapping.region, spec.region),
            ("size", mapping.instance_type, spec.size),
            ("image", mapping.image_parameter, spec.image),
        ):
            try:
                fn(value)
            except ValueError as exc:
                problems.append(str(exc))

        if not (8 <= spec.disk_gb <= 16384):
            problems.append(f"disk_gb는 8~16384 사이여야 합니다 (입력: {spec.disk_gb}).")

        if len(spec.tags) > MAX_TAGS:
            problems.append(f"태그는 최대 {MAX_TAGS}개까지 지원합니다.")

        opts = spec.provider_options
        unknown = set(opts) - {
            "vpc_id",
            "subnet_id",
            "key_name",
            "allowed_ssh_cidrs",
            "associate_public_ip",
            "create_security_group",
            "security_group_ids",
        }
        if unknown:
            problems.append(f"AWS가 모르는 추가 설정: {', '.join(sorted(unknown))}")

        cidrs = opts.get("allowed_ssh_cidrs", [])
        if not isinstance(cidrs, list):
            problems.append("allowed_ssh_cidrs는 배열이어야 합니다.")
        elif "0.0.0.0/0" in cidrs:
            # 막지는 않되 통과시키지도 않는다. 보안 규칙 SEC-01에 걸릴 설정이다.
            problems.append(
                "allowed_ssh_cidrs에 0.0.0.0/0이 있습니다. "
                "전체 개방 SSH는 생성 단계에서 차단합니다. 사내 IP 범위를 지정하세요."
            )

        if opts.get("create_security_group") is False and not opts.get("security_group_ids"):
            problems.append(
                "create_security_group=false인 경우 security_group_ids를 지정해야 합니다."
            )
        return problems

    # ── 템플릿 ──────────────────────────────────────────────
    def template_dir(self, resource_type: ResourceType) -> Path:
        return TEMPLATE_ROOT / resource_type.value

    # ── 변수 매핑 ───────────────────────────────────────────
    def build_variables(self, spec: ResourceSpec, request_id: str) -> dict[str, Any]:
        opts = spec.provider_options
        return {
            "name": spec.name,
            "request_id": request_id,
            "region": mapping.region(spec.region),
            "instance_type": mapping.instance_type(spec.size),
            "image_ssm_parameter": mapping.image_parameter(spec.image),
            "image_id": opts.get("image_id", ""),
            "disk_gb": spec.disk_gb,
            "tags": spec.tags,
            "vpc_id": opts.get("vpc_id", ""),
            "subnet_id": opts.get("subnet_id", ""),
            "key_name": opts.get("key_name", ""),
            "allowed_ssh_cidrs": opts.get("allowed_ssh_cidrs", []),
            "associate_public_ip": bool(opts.get("associate_public_ip", False)),
            "create_security_group": bool(opts.get("create_security_group", True)),
            "security_group_ids": opts.get("security_group_ids", []),
        }

    # ── 결과 정규화 ─────────────────────────────────────────
    def normalize_outputs(
        self, spec: ResourceSpec, outputs: dict[str, Any]
    ) -> list[ResourceRecord]:
        """terraform output → 인벤토리 레코드.

        정규화를 Terraform output 쪽에서 절반 해두었기 때문에(resource_summary)
        Python은 형만 맞춰 옮긴다. CSP가 늘어도 이 함수의 모양은 같다.
        """
        summary = outputs.get("resource_summary")
        if not summary:
            return []

        return [
            ResourceRecord(
                resource_id=summary["instance_id"],
                name=summary["name"],
                platform=CloudPlatform.AWS,
                resource_type=ResourceType.COMPUTE,
                provider_type=mapping.provider_type_label(summary["instance_type"]),
                region=summary["region"],
                state=summary.get("state", "unknown"),
                tags=summary.get("tags", {}) or {},
                attributes={
                    "arn": summary.get("arn"),
                    "availability_zone": summary.get("availability_zone"),
                    "private_ip": summary.get("private_ip"),
                    "public_ip": summary.get("public_ip") or None,
                    "ami_id": summary.get("ami_id"),
                    "subnet_id": summary.get("subnet_id"),
                    "security_group_ids": summary.get("security_group_ids", []),
                    "root_volume_encrypted": summary.get("root_volume_encrypted"),
                },
            )
        ]

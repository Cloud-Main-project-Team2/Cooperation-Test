"""CSP에 종속되지 않는 공통 도메인 모델.

여기 정의된 타입은 어떤 Provider에서도 동일하게 쓰인다.
AWS 전용 개념(인스턴스 타입, AMI ID 등)은 절대 이 파일에 들어오지 않는다.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class CloudPlatform(str, Enum):
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"


class ResourceType(str, Enum):
    COMPUTE = "compute"
    DB_RDBMS = "db_rdbms"
    STORAGE_OBJECT = "storage_object"
    CDN = "cdn"


class ProvisionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"       # 여러 리소스 중 일부만 성공 (2단계에서 사용)
    DESTROYED = "DESTROYED"


# ──────────────────────────────────────────────────────────────
# 공통 스펙
# ──────────────────────────────────────────────────────────────
@dataclass
class ResourceSpec:
    """사용자가 화면에서 입력하는 '공통 설정' 그 자체.

    region / size / image 는 CSP 값이 아니라 **논리 값**이다.
    (예: region="seoul" → AWS ap-northeast-2 / Azure koreacentral / GCP asia-northeast3)
    실제 CSP 값으로의 변환은 각 Provider의 mapping 모듈이 담당한다.
    """

    name: str
    platform: CloudPlatform
    resource_type: ResourceType
    region: str                                   # 논리 리전명
    size: str = "2vcpu-8gb"                       # 논리 사양명
    image: str = "ubuntu-22.04"                   # 논리 이미지명
    disk_gb: int = 30
    tags: dict[str, str] = field(default_factory=dict)
    # CSP 고유 설정. 화면의 '플랫폼별 추가 설정'에 해당한다.
    provider_options: dict[str, Any] = field(default_factory=dict)
    # 사용자가 등록한 계정(자격증명) 식별자. 1단계에서는 환경변수/프로파일로 대체.
    account_ref: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResourceSpec":
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"알 수 없는 스펙 항목: {', '.join(sorted(unknown))}")
        payload = dict(data)
        payload["platform"] = CloudPlatform(payload["platform"])
        payload["resource_type"] = ResourceType(payload["resource_type"])
        return cls(**payload)

    @classmethod
    def from_file(cls, path: str | Path) -> "ResourceSpec":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["platform"] = self.platform.value
        d["resource_type"] = self.resource_type.value
        return d


# ──────────────────────────────────────────────────────────────
# 결과
# ──────────────────────────────────────────────────────────────
@dataclass
class ResourceRecord:
    """생성된 리소스 1건. 인벤토리 화면 한 행에 그대로 대응된다."""

    resource_id: str                  # CSP가 부여한 ID (i-0abc..., /subscriptions/... 등)
    name: str
    platform: CloudPlatform
    resource_type: ResourceType
    provider_type: str                # CSP 원본 유형 표기 (예: "EC2 / t3.large")
    region: str                       # CSP 실제 리전 (예: ap-northeast-2)
    state: str                        # running, stopped 등 CSP 원문
    tags: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)   # public_ip 등 부가 정보
    monthly_cost_estimate: float | None = None                 # 2단계

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["platform"] = self.platform.value
        d["resource_type"] = self.resource_type.value
        return d


@dataclass
class PlanSummary:
    add: int
    change: int
    destroy: int
    addresses: list[str] = field(default_factory=list)

    def is_noop(self) -> bool:
        return self.add == 0 and self.change == 0 and self.destroy == 0


@dataclass
class ProvisionResult:
    request_id: str
    platform: CloudPlatform
    resource_type: ResourceType
    status: ProvisionStatus
    resources: list[ResourceRecord] = field(default_factory=list)
    error: str | None = None
    error_stage: str | None = None      # init / validate / plan / apply / destroy
    started_at: str = ""
    finished_at: str = ""
    duration_sec: float = 0.0
    workspace: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "platform": self.platform.value,
            "resource_type": self.resource_type.value,
            "status": self.status.value,
            "resources": [r.to_dict() for r in self.resources],
            "error": self.error,
            "error_stage": self.error_stage,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_sec": round(self.duration_sec, 2),
            "workspace": self.workspace,
        }


def new_request_id() -> str:
    """추적 가능한 요청 ID. 리소스 태그에도 그대로 박아 넣는다."""
    return f"req-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8]}"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

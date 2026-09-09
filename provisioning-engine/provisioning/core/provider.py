"""Provider 추상화.

계층은 두 겹이다.

  CloudProvider       — 순수 인터페이스. Terraform을 쓰지 않는 Provider도 만들 수 있다.
  TerraformProvider   — init/plan/apply/destroy 흐름을 전부 구현한 베이스.

GCP·Azure를 추가할 때 새로 작성할 것은 아래 4개뿐이다.
  1) template_dir()       : 그 CSP의 .tf 모듈 위치
  2) build_variables()    : 공통 스펙 → 그 CSP의 tfvars
  3) normalize_outputs()  : terraform output → ResourceRecord
  4) validate_spec()      : 그 CSP 고유 제약 검사

apply 흐름 자체는 한 곳에만 존재하므로 CSP가 늘어도 분기되지 않는다.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .errors import ProvisioningError, SpecValidationError, TerraformError, UnsupportedResourceType
from .models import (
    CloudPlatform,
    PlanSummary,
    ProvisionResult,
    ProvisionStatus,
    ResourceRecord,
    ResourceSpec,
    ResourceType,
    new_request_id,
    utcnow,
)
from .terraform import EventHandler, TerraformRunner
from .workspace import Workspace, WorkspaceManager


class CloudProvider(ABC):
    platform: CloudPlatform
    supported_types: frozenset[ResourceType]

    @abstractmethod
    def validate_spec(self, spec: ResourceSpec) -> list[str]:
        """문제점 목록을 돌려준다. 빈 리스트면 통과."""

    @abstractmethod
    def plan(self, spec: ResourceSpec, request_id: str | None = None): ...

    @abstractmethod
    def apply(self, spec: ResourceSpec, request_id: str | None = None): ...

    @abstractmethod
    def destroy(self, request_id: str): ...

    def estimate_monthly_cost(self, spec: ResourceSpec) -> float | None:
        """2단계에서 구현. 1단계에서는 항상 None을 돌려준다.

        None은 '0원'이 아니라 '모른다'는 뜻이며, 화면에서도 그렇게 표시해야 한다.
        """
        return None


class TerraformProvider(CloudProvider):
    """Terraform으로 동작하는 Provider의 공통 구현."""

    def __init__(
        self,
        workspaces: WorkspaceManager | None = None,
        tf_binary: str = "terraform",
        timeout: int = 1800,
    ):
        self.workspaces = workspaces or WorkspaceManager()
        self.tf_binary = tf_binary
        self.timeout = timeout

    # ── Provider가 구현할 것 ────────────────────────────────
    @abstractmethod
    def template_dir(self, resource_type: ResourceType) -> Path: ...

    @abstractmethod
    def build_variables(self, spec: ResourceSpec, request_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def normalize_outputs(
        self, spec: ResourceSpec, outputs: dict[str, Any]
    ) -> list[ResourceRecord]: ...

    def terraform_env(self, spec: ResourceSpec) -> dict[str, str]:
        """자격증명 등 terraform 프로세스에 넘길 환경변수.

        1단계는 실행 환경의 기본 자격증명(환경변수·프로파일)을 그대로 쓴다.
        2단계에서 account_ref로 조회한 키를 여기에 주입한다.
        """
        return {}

    # ── 공통 흐름 ──────────────────────────────────────────
    def _prepare(self, spec: ResourceSpec, request_id: str) -> tuple[Workspace, TerraformRunner]:
        if spec.platform is not self.platform:
            raise ProvisioningError(
                f"{self.platform.value} Provider에 {spec.platform.value} 스펙이 전달됐습니다."
            )
        if spec.resource_type not in self.supported_types:
            raise UnsupportedResourceType(self.platform.value, spec.resource_type.value)

        problems = self.validate_spec(spec)
        if problems:
            raise SpecValidationError(problems)

        ws = self.workspaces.create(
            request_id, self.template_dir(spec.resource_type), self.platform, spec.resource_type
        )
        ws.write_spec(spec)
        ws.write_vars(self.build_variables(spec, request_id))
        runner = TerraformRunner(
            ws.path, binary=self.tf_binary, env=self.terraform_env(spec), timeout=self.timeout
        )
        return ws, runner

    def plan(
        self, spec: ResourceSpec, request_id: str | None = None
    ) -> tuple[str, PlanSummary]:
        """계획만 세운다. 작업 디렉터리는 남겨두므로 곧바로 apply_prepared()로 이어갈 수 있다."""
        request_id = request_id or new_request_id()
        ws, tf = self._prepare(spec, request_id)
        ws.update_meta(status="PLANNING", created_at=utcnow(), name=spec.name)
        tf.init()
        tf.validate()
        summary = tf.plan()
        ws.update_meta(
            status="PLANNED",
            plan={"add": summary.add, "change": summary.change, "destroy": summary.destroy},
        )
        return request_id, summary

    def apply_prepared(
        self, request_id: str, on_event: EventHandler | None = None
    ) -> ProvisionResult:
        """이미 plan이 끝난 작업 디렉터리에 계획을 적용한다."""
        ws = self.workspaces.load(request_id)
        spec = ws.read_spec()
        tf = TerraformRunner(
            ws.path, binary=self.tf_binary, env=self.terraform_env(spec), timeout=self.timeout
        )
        started = time.time()
        result = ProvisionResult(
            request_id=request_id,
            platform=self.platform,
            resource_type=spec.resource_type,
            status=ProvisionStatus.RUNNING,
            started_at=utcnow(),
            workspace=str(ws.path),
        )
        ws.update_meta(status="RUNNING")
        try:
            tf.apply(on_event=on_event)
            result.resources = self.normalize_outputs(spec, tf.outputs())
            result.status = ProvisionStatus.SUCCEEDED
        except TerraformError as exc:
            result.status = ProvisionStatus.FAILED
            result.error = str(exc)
            result.error_stage = exc.stage
            # 실패해도 일부가 만들어졌을 수 있다. state를 확인해 기록을 남긴다.
            if tf.has_state():
                try:
                    result.resources = self.normalize_outputs(spec, tf.outputs())
                except Exception:
                    pass
        finally:
            result.finished_at = utcnow()
            result.duration_sec = time.time() - started
            ws.update_meta(
                status=result.status.value,
                finished_at=result.finished_at,
                error=result.error,
                resources=[r.to_dict() for r in result.resources],
            )
        return result

    def apply(
        self,
        spec: ResourceSpec,
        request_id: str | None = None,
        on_event: EventHandler | None = None,
    ) -> ProvisionResult:
        request_id, _ = self.plan(spec, request_id)
        return self.apply_prepared(request_id, on_event=on_event)

    def destroy(
        self, request_id: str, on_event: EventHandler | None = None
    ) -> ProvisionResult:
        ws = self.workspaces.load(request_id)
        spec = ws.read_spec()
        tf = TerraformRunner(
            ws.path, binary=self.tf_binary, env=self.terraform_env(spec), timeout=self.timeout
        )
        started = time.time()
        result = ProvisionResult(
            request_id=request_id,
            platform=self.platform,
            resource_type=spec.resource_type,
            status=ProvisionStatus.RUNNING,
            started_at=utcnow(),
            workspace=str(ws.path),
        )
        try:
            tf.init()
            tf.destroy(on_event=on_event)
            result.status = ProvisionStatus.DESTROYED
        except TerraformError as exc:
            result.status = ProvisionStatus.FAILED
            result.error = str(exc)
            result.error_stage = exc.stage
        finally:
            result.finished_at = utcnow()
            result.duration_sec = time.time() - started
            ws.update_meta(status=result.status.value, finished_at=result.finished_at)
        return result

"""요청 단위 Terraform 작업 디렉터리 관리.

요청 하나 = 디렉터리 하나 = state 파일 하나.
요청끼리 state를 공유하지 않으므로 동시 실행이 서로를 깨뜨리지 않는다.

1단계는 로컬 state를 쓴다. 2단계에서 backend.tf를 주입해
S3 + DynamoDB 잠금으로 바꿀 수 있도록 backend_config 훅만 열어 두었다.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import WorkspaceNotFound
from .models import CloudPlatform, ResourceSpec, ResourceType

META_FILE = "meta.json"
SPEC_FILE = "spec.json"
VARS_FILE = "terraform.tfvars.json"


@dataclass
class Workspace:
    request_id: str
    path: Path
    platform: CloudPlatform
    resource_type: ResourceType

    @property
    def meta_path(self) -> Path:
        return self.path / META_FILE

    def write_vars(self, variables: dict[str, Any]) -> None:
        (self.path / VARS_FILE).write_text(
            json.dumps(variables, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def write_spec(self, spec: ResourceSpec) -> None:
        (self.path / SPEC_FILE).write_text(
            json.dumps(spec.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def read_spec(self) -> ResourceSpec:
        return ResourceSpec.from_dict(
            json.loads((self.path / SPEC_FILE).read_text(encoding="utf-8"))
        )

    def update_meta(self, **fields: Any) -> dict[str, Any]:
        meta = self.read_meta()
        meta.update(fields)
        self.meta_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return meta

    def read_meta(self) -> dict[str, Any]:
        if not self.meta_path.exists():
            return {}
        return json.loads(self.meta_path.read_text(encoding="utf-8"))


class WorkspaceManager:
    def __init__(self, root: str | Path = ".workspaces"):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        request_id: str,
        template_dir: Path,
        platform: CloudPlatform,
        resource_type: ResourceType,
    ) -> Workspace:
        path = self.root / request_id
        if path.exists():
            raise FileExistsError(f"이미 존재하는 작업 디렉터리: {path}")
        # .tf 템플릿만 복사한다. 템플릿 원본은 절대 수정하지 않는다.
        shutil.copytree(template_dir, path)
        ws = Workspace(request_id, path, platform, resource_type)
        ws.update_meta(
            request_id=request_id,
            platform=platform.value,
            resource_type=resource_type.value,
            status="PENDING",
        )
        return ws

    def load(self, request_id: str) -> Workspace:
        path = self.root / request_id
        if not path.is_dir():
            raise WorkspaceNotFound(request_id)
        meta = json.loads((path / META_FILE).read_text(encoding="utf-8"))
        return Workspace(
            request_id=request_id,
            path=path,
            platform=CloudPlatform(meta["platform"]),
            resource_type=ResourceType(meta["resource_type"]),
        )

    def list(self) -> list[dict[str, Any]]:
        items = []
        for d in sorted(self.root.iterdir()):
            meta_path = d / META_FILE
            if d.is_dir() and meta_path.exists():
                items.append(json.loads(meta_path.read_text(encoding="utf-8")))
        return items

    def remove(self, request_id: str) -> None:
        """destroy가 끝난 뒤에만 호출한다. state가 남아 있으면 리소스가 미아가 된다."""
        shutil.rmtree(self.root / request_id, ignore_errors=True)

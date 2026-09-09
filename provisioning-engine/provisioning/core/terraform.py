"""Terraform CLI 실행 래퍼.

CSP와 무관하다. 어떤 Provider든 이 클래스를 통해서만 terraform을 실행한다.

apply/destroy 는 `-json` 스트리밍으로 실행하고 이벤트를 콜백으로 넘긴다.
3단계 진행률 모달이 이 콜백 위에 그대로 올라간다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterator

from .errors import TerraformError, TerraformNotFound
from .models import PlanSummary

EventHandler = Callable[[dict[str, Any]], None]

PLAN_FILE = "tfplan"


class TerraformRunner:
    def __init__(
        self,
        workdir: Path,
        binary: str = "terraform",
        env: dict[str, str] | None = None,
        timeout: int = 1800,
    ):
        self.workdir = Path(workdir)
        self.binary = binary
        self.timeout = timeout
        self._extra_env = env or {}

    # ── 환경 ────────────────────────────────────────────────
    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(self._extra_env)
        env["TF_IN_AUTOMATION"] = "1"
        env["TF_INPUT"] = "0"
        env["TF_CLI_ARGS"] = env.get("TF_CLI_ARGS", "")
        env.setdefault("CHECKPOINT_DISABLE", "1")   # HashiCorp 버전 체크 호출 차단
        return env

    def _require_binary(self) -> None:
        if shutil.which(self.binary) is None:
            raise TerraformNotFound(self.binary)

    # ── 실행 ────────────────────────────────────────────────
    def _run(self, args: list[str], stage: str) -> str:
        """버퍼링 실행. 출력 전체를 문자열로 돌려준다."""
        self._require_binary()
        proc = subprocess.run(
            [self.binary, *args],
            cwd=self.workdir,
            env=self._env(),
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        output = proc.stdout + proc.stderr
        if proc.returncode != 0:
            raise TerraformError(stage, proc.returncode, output)
        return output

    def _stream(self, args: list[str], stage: str, on_event: EventHandler | None) -> str:
        """`-json` 스트리밍 실행. 라인 단위로 콜백을 호출한다."""
        self._require_binary()
        proc = subprocess.Popen(
            [self.binary, *args],
            cwd=self.workdir,
            env=self._env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        collected: list[str] = []
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            collected.append(line)
            if on_event is None:
                continue
            on_event(_parse_event(line))
        returncode = proc.wait(timeout=self.timeout)
        output = "\n".join(collected)
        if returncode != 0:
            raise TerraformError(stage, returncode, output)
        return output

    # ── 명령 ────────────────────────────────────────────────
    def version(self) -> str:
        out = self._run(["version", "-json"], "version")
        try:
            return json.loads(out)["terraform_version"]
        except (json.JSONDecodeError, KeyError):
            return out.splitlines()[0] if out else "unknown"

    def init(self, upgrade: bool = False) -> None:
        args = ["init", "-input=false", "-no-color"]
        if upgrade:
            args.append("-upgrade")
        self._run(args, "init")

    def validate(self) -> None:
        self._run(["validate", "-no-color"], "validate")

    def plan(self, destroy: bool = False) -> PlanSummary:
        args = ["plan", "-input=false", "-no-color", f"-out={PLAN_FILE}"]
        if destroy:
            args.append("-destroy")
        self._run(args, "plan")
        return self._plan_summary()

    def _plan_summary(self) -> PlanSummary:
        raw = self._run(["show", "-json", PLAN_FILE], "plan")
        data = json.loads(raw)
        add = change = destroy = 0
        addresses: list[str] = []
        for rc in data.get("resource_changes", []):
            actions = rc.get("change", {}).get("actions", [])
            if actions == ["no-op"]:
                continue
            addresses.append(rc.get("address", "?"))
            if "create" in actions:
                add += 1
            if "update" in actions:
                change += 1
            if "delete" in actions:
                destroy += 1
        return PlanSummary(add=add, change=change, destroy=destroy, addresses=addresses)

    def apply(self, on_event: EventHandler | None = None) -> str:
        """plan()으로 만든 계획 파일을 그대로 적용한다.

        저장된 계획을 적용하므로 '보여준 것과 다른 것이 만들어지는' 상황이 없다.
        """
        return self._stream(
            ["apply", "-input=false", "-no-color", "-json", PLAN_FILE],
            "apply",
            on_event,
        )

    def destroy(self, on_event: EventHandler | None = None) -> str:
        return self._stream(
            ["destroy", "-input=false", "-no-color", "-json", "-auto-approve"],
            "destroy",
            on_event,
        )

    def outputs(self) -> dict[str, Any]:
        raw = self._run(["output", "-json", "-no-color"], "output")
        data = json.loads(raw or "{}")
        return {k: v.get("value") for k, v in data.items()}

    def state_resources(self) -> list[dict[str, Any]]:
        """현재 state에 실제로 존재하는 리소스 목록."""
        raw = self._run(["show", "-json"], "show")
        data = json.loads(raw or "{}")
        root = data.get("values", {}).get("root_module", {})
        return list(root.get("resources", []))

    def has_state(self) -> bool:
        try:
            return bool(self.state_resources())
        except Exception:
            return False


def _parse_event(line: str) -> dict[str, Any]:
    line = line.strip()
    if line.startswith("{"):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            pass
    return {"@level": "info", "@message": line, "type": "raw"}


def progress_printer(prefix: str = "  ") -> EventHandler:
    """CLI용 기본 이벤트 핸들러.

    관심 있는 이벤트만 사람이 읽을 수 있게 출력한다.
    (3단계에서는 같은 이벤트를 WebSocket으로 흘려 진행률 바를 그린다.)
    """
    interesting = {
        "apply_start": "시작",
        "apply_progress": "진행",
        "apply_complete": "완료",
        "apply_errored": "실패",
    }

    def handler(evt: dict[str, Any]) -> None:
        etype = evt.get("type")
        if etype in interesting:
            hook = evt.get("hook", {})
            addr = hook.get("resource", {}).get("addr", "?")
            elapsed = hook.get("elapsed_seconds")
            tail = f" ({elapsed}s)" if elapsed else ""
            print(f"{prefix}[{interesting[etype]}] {addr}{tail}", flush=True)
        elif evt.get("@level") == "error":
            print(f"{prefix}[오류] {evt.get('@message', '')}", flush=True)

    return handler

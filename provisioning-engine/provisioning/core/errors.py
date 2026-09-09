"""프로비저닝 예외.

원칙: Terraform이 뱉은 원문(stderr)을 절대 삼키지 않는다.
사용자 화면에는 요약을, 로그에는 원문을 남긴다.
"""

from __future__ import annotations


class ProvisioningError(Exception):
    """모든 프로비저닝 예외의 부모."""


class TerraformNotFound(ProvisioningError):
    def __init__(self, binary: str = "terraform"):
        super().__init__(
            f"'{binary}' 실행 파일을 찾을 수 없습니다. "
            "Terraform을 설치하고 PATH에 등록한 뒤 다시 시도하세요."
        )


class TerraformError(ProvisioningError):
    """terraform 명령이 0이 아닌 코드로 종료된 경우."""

    def __init__(self, stage: str, returncode: int, output: str):
        self.stage = stage
        self.returncode = returncode
        self.output = output
        summary = _summarize(output)
        super().__init__(f"[{stage}] terraform 실패 (exit {returncode}): {summary}")


class SpecValidationError(ProvisioningError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("스펙 검증 실패:\n  - " + "\n  - ".join(problems))


class UnsupportedResourceType(ProvisioningError):
    def __init__(self, platform: str, resource_type: str):
        super().__init__(
            f"{platform} Provider는 아직 '{resource_type}' 타입을 지원하지 않습니다."
        )


class ProviderNotFound(ProvisioningError):
    def __init__(self, platform: str):
        super().__init__(f"'{platform}' Provider가 등록되어 있지 않습니다.")


class WorkspaceNotFound(ProvisioningError):
    def __init__(self, request_id: str):
        super().__init__(f"작업 디렉터리를 찾을 수 없습니다: {request_id}")


def _summarize(output: str, max_lines: int = 6) -> str:
    """Terraform 출력에서 오류만 뽑아 짧게 요약한다.

    사람이 읽는 텍스트 출력(plan/init)과 `-json` 스트리밍 출력(apply/destroy)을
    모두 처리한다. 원문 전체는 TerraformError.output에 그대로 남는다.
    """
    import json

    picked: list[str] = []
    fallback: list[str] = []

    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                fallback.append(line)
                continue
            if evt.get("@level") == "error":
                msg = evt.get("@message", "")
                detail = (evt.get("diagnostic") or {}).get("detail", "")
                picked.append(f"{msg} {detail}".strip())
            continue
        fallback.append(line)
        if line.lstrip("│ ").startswith("Error:"):
            picked.append(line.lstrip("│ ").strip())

    chosen = picked or fallback[-max_lines:]
    text = " / ".join(dict.fromkeys(chosen))[:600]
    return text or "출력 없음"

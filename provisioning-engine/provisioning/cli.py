"""프로비저닝 CLI (1단계 테스트용).

  python -m provisioning.cli doctor
  python -m provisioning.cli validate -f examples/aws-compute-dev.json
  python -m provisioning.cli plan     -f examples/aws-compute-dev.json
  python -m provisioning.cli apply    -f examples/aws-compute-dev.json
  python -m provisioning.cli list
  python -m provisioning.cli show    <request_id>
  python -m provisioning.cli destroy <request_id>

이 CLI는 얇게 유지한다. 로직은 전부 core/ 와 providers/ 에 있고,
2단계에서 API 서버가 붙을 때 같은 함수를 그대로 호출한다.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from provisioning.core.errors import ProvisioningError
from provisioning.core.models import ResourceSpec
from provisioning.core.registry import available_platforms, get_provider
from provisioning.core.terraform import TerraformRunner, progress_printer
from provisioning.core.workspace import WorkspaceManager

DEFAULT_ROOT = ".workspaces"


# ── 출력 도우미 ────────────────────────────────────────────
def _print(obj, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, ensure_ascii=False))


def _rule(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 56 - len(title)))


def _load_spec(path: str) -> ResourceSpec:
    spec = ResourceSpec.from_file(path)
    print(f"스펙: {spec.name} · {spec.platform.value} · {spec.resource_type.value} "
          f"· {spec.region} · {spec.size}")
    return spec


def _provider_for(spec: ResourceSpec, root: str):
    return get_provider(spec.platform, workspaces=WorkspaceManager(root))


# ── 명령 ──────────────────────────────────────────────────
def cmd_doctor(args) -> int:
    ok = True

    tf = shutil.which("terraform")
    if tf:
        version = TerraformRunner(Path.cwd()).version()
        print(f"✅ terraform {version}  ({tf})")
    else:
        print("❌ terraform 을 찾을 수 없습니다. https://developer.hashicorp.com/terraform/install")
        ok = False

    print(f"✅ python {sys.version.split()[0]}")

    import os
    if os.environ.get("AWS_ACCESS_KEY_ID"):
        print("✅ AWS 자격증명: 환경변수 AWS_ACCESS_KEY_ID 사용")
    elif os.environ.get("AWS_PROFILE"):
        print(f"✅ AWS 자격증명: 프로파일 {os.environ['AWS_PROFILE']}")
    elif (Path.home() / ".aws" / "credentials").exists():
        print("✅ AWS 자격증명: ~/.aws/credentials 발견 (default 프로파일 사용)")
    else:
        print("⚠️  AWS 자격증명을 찾지 못했습니다. 환경변수 또는 ~/.aws/credentials 를 설정하세요.")
        ok = False

    print(f"✅ 등록된 Provider: {', '.join(p.value for p in available_platforms())}")
    print(f"✅ 작업 디렉터리 루트: {Path(args.root).resolve()}")
    return 0 if ok else 1


def cmd_validate(args) -> int:
    spec = _load_spec(args.file)
    provider = _provider_for(spec, args.root)
    problems = provider.validate_spec(spec)
    if problems:
        print("\n검증 실패:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\n✅ 검증 통과")
    _print({"valid": True, "variables": provider.build_variables(spec, "req-dryrun")}, args.json)
    return 0


def cmd_plan(args) -> int:
    spec = _load_spec(args.file)
    provider = _provider_for(spec, args.root)
    _rule("terraform init · validate · plan")
    request_id, summary = provider.plan(spec)
    print(f"\n요청 ID : {request_id}")
    print(f"생성 {summary.add} · 변경 {summary.change} · 삭제 {summary.destroy}")
    for addr in summary.addresses:
        print(f"  + {addr}")
    print(f"\n적용하려면:  python -m provisioning.cli apply-prepared {request_id}")
    _print({"request_id": request_id, "add": summary.add, "addresses": summary.addresses}, args.json)
    return 0


def _confirm(summary_text: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    print(f"\n⚠️  {summary_text}")
    print("   실제 리소스가 생성되며 과금이 발생합니다.")
    return input("   진행하려면 'yes' 를 입력하세요: ").strip().lower() == "yes"


def cmd_apply(args) -> int:
    spec = _load_spec(args.file)
    provider = _provider_for(spec, args.root)

    _rule("terraform init · validate · plan")
    request_id, summary = provider.plan(spec)
    print(f"요청 ID : {request_id}")
    print(f"생성 {summary.add} · 변경 {summary.change} · 삭제 {summary.destroy}")
    for addr in summary.addresses:
        print(f"  + {addr}")

    if summary.is_noop():
        print("\n변경 사항이 없습니다.")
        return 0

    if not _confirm(f"{summary.add}개 리소스를 AWS에 생성합니다.", args.yes):
        print("취소했습니다. (작업 디렉터리는 남겨둡니다)")
        return 1

    _rule("terraform apply")
    result = provider.apply_prepared(request_id, on_event=progress_printer())

    _rule("결과")
    print(f"상태     : {result.status.value}")
    print(f"소요     : {result.duration_sec:.1f}초")
    if result.error:
        print(f"실패 단계 : {result.error_stage}")
        print(f"오류     : {result.error}")
    for r in result.resources:
        print(f"\n  리소스 ID : {r.resource_id}")
        print(f"  유형      : {r.provider_type}")
        print(f"  리전      : {r.region}")
        print(f"  상태      : {r.state}")
        print(f"  사설 IP   : {r.attributes.get('private_ip')}")
        print(f"  공인 IP   : {r.attributes.get('public_ip') or '없음'}")
    print(f"\n정리하려면:  python -m provisioning.cli destroy {request_id}")
    _print(result.to_dict(), args.json)
    return 0 if result.status.value == "SUCCEEDED" else 1


def cmd_apply_prepared(args) -> int:
    ws = WorkspaceManager(args.root).load(args.request_id)
    spec = ws.read_spec()
    provider = _provider_for(spec, args.root)
    if not _confirm(f"{args.request_id} 계획을 적용합니다.", args.yes):
        return 1
    _rule("terraform apply")
    result = provider.apply_prepared(args.request_id, on_event=progress_printer())
    print(f"\n상태: {result.status.value}")
    _print(result.to_dict(), args.json)
    return 0 if result.status.value == "SUCCEEDED" else 1


def cmd_list(args) -> int:
    items = WorkspaceManager(args.root).list()
    if not items:
        print("작업 이력이 없습니다.")
        return 0
    print(f"{'요청 ID':<26} {'플랫폼':<7} {'타입':<10} {'상태':<12} 이름")
    print("─" * 78)
    for m in items:
        print(f"{m.get('request_id',''):<26} {m.get('platform',''):<7} "
              f"{m.get('resource_type',''):<10} {m.get('status',''):<12} {m.get('name','')}")
    _print(items, args.json)
    return 0


def cmd_show(args) -> int:
    meta = WorkspaceManager(args.root).load(args.request_id).read_meta()
    print(json.dumps(meta, indent=2, ensure_ascii=False))
    return 0


def cmd_destroy(args) -> int:
    manager = WorkspaceManager(args.root)
    ws = manager.load(args.request_id)
    spec = ws.read_spec()
    provider = _provider_for(spec, args.root)

    if not args.yes:
        print(f"\n⚠️  {args.request_id} 가 만든 리소스를 삭제합니다. 되돌릴 수 없습니다.")
        if input("   'destroy' 를 입력하세요: ").strip().lower() != "destroy":
            print("취소했습니다.")
            return 1

    _rule("terraform destroy")
    result = provider.destroy(args.request_id, on_event=progress_printer())
    print(f"\n상태: {result.status.value}")
    if result.error:
        print(f"오류: {result.error}")
        return 1
    if args.purge:
        manager.remove(args.request_id)
        print("작업 디렉터리를 삭제했습니다.")
    return 0


# ── 파서 ──────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    # 공통 옵션. 하위 명령 앞뒤 어디에 써도 인식되도록 부모 파서로 붙인다.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=DEFAULT_ROOT, help="작업 디렉터리 루트 (기본: .workspaces)")
    common.add_argument("--json", action="store_true", help="결과를 JSON으로도 출력")

    p = argparse.ArgumentParser(
        prog="provisioning",
        parents=[common],
        description="멀티클라우드 프로비저닝 CLI (1단계: AWS)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("doctor", parents=[common], help="실행 환경 점검")
    s.set_defaults(func=cmd_doctor)

    for name, fn, help_text in (
        ("validate", cmd_validate, "스펙 검증만 수행 (AWS 호출 없음)"),
        ("plan", cmd_plan, "terraform plan까지 수행"),
    ):
        s = sub.add_parser(name, parents=[common], help=help_text)
        s.add_argument("-f", "--file", required=True, help="스펙 JSON 경로")
        s.set_defaults(func=fn)

    s = sub.add_parser("apply", parents=[common], help="plan 후 확인을 받고 생성")
    s.add_argument("-f", "--file", required=True)
    s.add_argument("-y", "--yes", action="store_true", help="확인 절차 생략")
    s.set_defaults(func=cmd_apply)

    s = sub.add_parser("apply-prepared", parents=[common], help="이미 plan한 요청을 적용")
    s.add_argument("request_id")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(func=cmd_apply_prepared)

    s = sub.add_parser("list", parents=[common], help="요청 목록")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("show", parents=[common], help="요청 상세")
    s.add_argument("request_id")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("destroy", parents=[common], help="요청이 만든 리소스 삭제")
    s.add_argument("request_id")
    s.add_argument("-y", "--yes", action="store_true")
    s.add_argument("--purge", action="store_true", help="삭제 후 작업 디렉터리도 제거")
    s.set_defaults(func=cmd_destroy)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ProvisioningError as exc:
        print(f"\n❌ {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n중단했습니다. 진행 중이던 terraform 작업은 계속될 수 있습니다.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

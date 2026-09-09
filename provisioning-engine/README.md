# 멀티클라우드 프로비저닝 엔진 — 1단계 (AWS Compute)

Terraform을 실행 엔진으로 쓰고 Python CLI로 조작한다.
1단계 범위는 **AWS EC2 생성 → 조회 → 삭제**이며, GCP/Azure는 3단계에 추가한다.

## 1. 구조

```
provisioning/
├─ core/                      CSP에 종속되지 않는 코드
│  ├─ models.py               공통 스펙(ResourceSpec) · 결과(ProvisionResult)
│  ├─ provider.py             CloudProvider(인터페이스) / TerraformProvider(공통 흐름)
│  ├─ terraform.py            terraform CLI 실행 래퍼 (-json 스트리밍 포함)
│  ├─ workspace.py            요청 단위 작업 디렉터리 · state 관리
│  ├─ registry.py             platform → Provider 조회
│  └─ errors.py
├─ providers/
│  └─ aws/
│     ├─ provider.py          AwsProvider (검증 · 변수 매핑 · 출력 정규화)
│     ├─ mapping.py           논리값 → AWS 실제값 매핑 표
│     └─ templates/compute/   Terraform 모듈 (.tf)
└─ cli.py                     테스트용 CLI
```

### 설계 판단 세 가지

**HCL을 Python으로 생성하지 않는다.** `.tf`는 CSP별 정적 모듈로 두고 Python은
`terraform.tfvars.json`만 쓴다. HCL을 문자열로 조립하면 리뷰도 디버깅도 불가능해지고,
CSP가 늘어날수록 무너진다.

**실행 흐름은 베이스 클래스에 한 번만 존재한다.** init→validate→plan→apply→output→destroy는
`TerraformProvider`에 있다. GCP/Azure Provider가 구현할 것은 네 개뿐이다.

| 구현할 것 | 하는 일 |
|---|---|
| `template_dir()` | 그 CSP의 `.tf` 모듈 위치 |
| `build_variables()` | 공통 스펙 → 그 CSP의 tfvars |
| `normalize_outputs()` | terraform output → `ResourceRecord` |
| `validate_spec()` | 그 CSP 고유 제약 검사 |

**공통 스펙은 CSP 값을 쓰지 않는다.** `region="seoul"`, `size="2vcpu-8gb"`처럼 논리 값을
받고, `mapping.py`가 CSP 값으로 옮긴다. 이 파일이 곧 서비스 매핑 표의 AWS 열이다.
매핑에 없는 값은 조용히 통과시키지 않고 예외로 막는다. 잘못 추측해서 만들면 과금이 발생한다.

### 요청 하나 = 디렉터리 하나 = state 하나

`.workspaces/<request_id>/` 안에 `.tf` 사본, `terraform.tfvars.json`, `spec.json`,
`meta.json`, `terraform.tfstate`가 함께 있다. 요청끼리 state를 공유하지 않으므로
동시 실행이 서로를 깨뜨리지 않는다. **destroy 전에 이 디렉터리를 지우면 리소스가
추적 불가능해진다.** 2단계에서 S3 + DynamoDB 백엔드로 옮긴다.

## 2. 준비

```bash
# Terraform 1.6+ (Ubuntu/WSL)
wget -O - https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" \
  | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install terraform

# AWS 자격증명 (테스트 계정 권장)
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
# 또는  export AWS_PROFILE=mcp-test
```

Python 3.10 이상, 외부 패키지 없음(표준 라이브러리만 사용).

필요한 IAM 권한: `ec2:RunInstances`, `ec2:TerminateInstances`, `ec2:Describe*`,
`ec2:CreateSecurityGroup`, `ec2:DeleteSecurityGroup`, `ec2:AuthorizeSecurityGroup*`,
`ec2:CreateTags`, `ssm:GetParameter`.

## 3. 실행

```bash
python -m provisioning.cli doctor                                   # 환경 점검
python -m provisioning.cli validate -f examples/aws-compute-dev.json  # AWS 호출 없음
python -m provisioning.cli plan     -f examples/aws-compute-dev.json  # 계획만
python -m provisioning.cli apply    -f examples/aws-compute-dev.json  # 생성 (확인 후)
python -m provisioning.cli list
python -m provisioning.cli show    <request_id>
python -m provisioning.cli destroy <request_id>
```

`apply`는 `plan`이 저장한 계획 파일을 그대로 적용한다. 보여준 것과 다른 것이
만들어지는 상황이 생기지 않는다.

## 4. 스펙 파일

```json
{
  "name": "mcp-test-vm",
  "platform": "aws",
  "resource_type": "compute",
  "region": "seoul",
  "size": "1vcpu-1gb",
  "image": "ubuntu-22.04",
  "disk_gb": 10,
  "tags": { "env": "dev", "owner": "seunghyun" },
  "provider_options": {
    "associate_public_ip": false,
    "create_security_group": true,
    "allowed_ssh_cidrs": []
  }
}
```

`provider_options`가 화면의 '플랫폼별 추가 설정'에 해당한다.
지원하는 키: `vpc_id`, `subnet_id`, `key_name`, `allowed_ssh_cidrs`,
`associate_public_ip`, `create_security_group`, `security_group_ids`.

### 기본값에 담긴 보안 판단

| 설정 | 기본값 | 이유 |
|---|---|---|
| 루트 볼륨 암호화 | 켬 | 나중에 켜려면 스냅샷 → 새 볼륨 교체가 필요하다 |
| IMDSv2 | 강제 | SSRF를 통한 자격증명 탈취 차단 |
| 인바운드 | 없음 | `allowed_ssh_cidrs`에 명시한 범위만 연다 |
| `0.0.0.0/0` | 차단 | Python 검증과 Terraform validation 양쪽에서 막는다 |
| 공인 IP | 미할당 | 미사용 공인 IP는 상태와 무관하게 과금된다 |
| AMI 변경 | 무시 | AMI 갱신을 이유로 운영 인스턴스가 재생성되는 사고를 막는다 |

## 5. 실제 AWS 테스트 체크리스트

작은 인스턴스(`1vcpu-1gb` = t3.micro)로 시작하고, **끝나면 반드시 destroy**한다.

- [ ] `doctor` — terraform 버전과 자격증명이 모두 ✅
- [ ] `validate` — 통과. 리전을 `mars`로 바꾸면 실패 메시지가 나오는지도 확인
- [ ] `plan` — `생성 2` (인스턴스 + 보안 그룹). AMI가 SSM으로 조회되는지 확인
- [ ] `apply` — 확인 프롬프트가 뜨고, `yes` 입력 후 진행 로그가 리소스별로 출력
- [ ] AWS 콘솔에서 인스턴스 확인 — 태그에 `ManagedBy=mcp-provisioning`, `RequestId=req-...`
- [ ] 루트 볼륨이 암호화되어 있고, 보안 그룹 인바운드가 비어 있는지
- [ ] `list` / `show <id>` — 상태와 리소스 정보가 저장돼 있는지
- [ ] `destroy <id>` — 삭제 후 콘솔에서 terminated 확인
- [ ] 같은 스펙을 두 번 `apply` — 요청 ID가 달라 서로 간섭하지 않는지

**실패 케이스도 한 번 봐 주세요.** 존재하지 않는 `subnet_id`를 넣고 apply하면
`상태: FAILED`, `실패 단계: apply`와 함께 AWS 원문 오류가 요약돼 나와야 합니다.

## 6. 보고해 주실 것

- 위 체크리스트 중 실패한 항목과 그때 출력 전문
- `apply` 총 소요 시간 (진행률 UI 설계에 필요)
- 매핑 표에 추가할 리전/사양 (현재 리전 6개, 사양 5개)
- 실제로 필요한 `provider_options` 중 빠진 것

## 7. 다음 단계

**2단계** — 리소스 타입 확장(RDS·S3), state를 S3 백엔드로, apply 이벤트를 진행률
스트림으로 노출, 비용 추정(`estimate_monthly_cost`) 구현, DB 저장 인터페이스.

**3단계** — GCP·Azure Provider 추가, 매핑 표 3사 확정, 다중 계정 병렬 실행과 취소.

"""Provider 레지스트리.

CLI와 상위 서비스는 CloudPlatform 값만 알면 되고, 구체 클래스는 모른다.
GCP/Azure를 추가할 때 _PROVIDERS에 한 줄을 더하면 끝난다.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .errors import ProviderNotFound
from .models import CloudPlatform
from .provider import CloudProvider

# platform -> "모듈경로:클래스명"
_PROVIDERS: dict[CloudPlatform, str] = {
    CloudPlatform.AWS: "provisioning.providers.aws.provider:AwsProvider",
    # 3단계:
    # CloudPlatform.AZURE: "provisioning.providers.azure.provider:AzureProvider",
    # CloudPlatform.GCP:   "provisioning.providers.gcp.provider:GcpProvider",
}


def available_platforms() -> list[CloudPlatform]:
    return list(_PROVIDERS)


def get_provider(platform: CloudPlatform | str, **kwargs: Any) -> CloudProvider:
    platform = CloudPlatform(platform)
    target = _PROVIDERS.get(platform)
    if target is None:
        raise ProviderNotFound(platform.value)
    module_path, class_name = target.split(":")
    cls = getattr(import_module(module_path), class_name)
    return cls(**kwargs)

from models.common import CloudProvider
from providers.base import CloudCostProvider
from providers.aws.adapter import AWSCostProvider
from providers.gcp.adapter import GCPCostProvider
from providers.azure.adapter import AzureCostProvider


class ProviderFactory:
    """Factory for creating cloud provider instances."""

    _providers = {
        CloudProvider.AWS: AWSCostProvider,
        CloudProvider.GCP: GCPCostProvider,
        CloudProvider.AZURE: AzureCostProvider,
    }

    @classmethod
    def create_provider(cls, provider: CloudProvider, credentials: dict, region: str = None) -> CloudCostProvider:
        if provider not in cls._providers:
            raise ValueError(f"Unsupported provider: {provider}")

        provider_class = cls._providers[provider]
        return provider_class(credentials=credentials, region=region)

    @classmethod
    def get_supported_providers(cls) -> list:
        return [p.value for p in cls._providers.keys()]

"""Official API integration scaffolding and payload normalizers."""

from .base import ApiCredentialsError, ApiIntegrationError, DeliveryPlatformClient
from .doordash import DoorDashCredentials, DoorDashDriveClient
from .grubhub import GrubhubCredentials, GrubhubPartnerClient
from .manual import offers_from_json
from .uber import UberCredentials, UberEatsClient

__all__ = [
    "ApiCredentialsError",
    "ApiIntegrationError",
    "DeliveryPlatformClient",
    "DoorDashCredentials",
    "DoorDashDriveClient",
    "GrubhubCredentials",
    "GrubhubPartnerClient",
    "UberCredentials",
    "UberEatsClient",
    "offers_from_json",
]

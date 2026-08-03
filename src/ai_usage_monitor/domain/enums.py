from enum import StrEnum


class ProviderStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    AUTH_REQUIRED = "auth_required"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    STALE = "stale"
    MANUAL = "manual"


class SourceType(StrEnum):
    OFFICIAL_API = "official_api"
    LOCAL_BRIDGE = "local_bridge"
    LOCAL_RPC = "local_rpc"
    MANUAL = "manual"
    MOCK = "mock"

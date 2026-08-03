from __future__ import annotations

import keyring

SERVICE_NAME = "AIUsageMonitor"


class SecretStore:
    def __init__(self, service_name: str = SERVICE_NAME) -> None:
        self.service_name = service_name

    def get(self, key: str) -> str | None:
        value = keyring.get_password(self.service_name, key)
        return value

    def set(self, key: str, value: str) -> None:
        keyring.set_password(self.service_name, key, value)

    def delete(self, key: str) -> None:
        keyring.delete_password(self.service_name, key)


class FakeSecretStore(SecretStore):
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._values.get(key)

    def set(self, key: str, value: str) -> None:
        self._values[key] = value

    def delete(self, key: str) -> None:
        self._values.pop(key, None)

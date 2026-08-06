from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator

import httpx

from ai_usage_monitor.domain.enums import ProviderStatus, SourceType
from ai_usage_monitor.domain.models import QuotaWindow, UsageSnapshot

from .base import Collector

GROK_CONFIG_DIR = Path(r"C:\Users\sswce\.grok")
GROK_AUTH_PATH = GROK_CONFIG_DIR / "auth.json"
GROK_TIMEOUT_SECONDS = 10.0
GROK_CREDITS_CONFIG_ENDPOINT = (
    "https://grok.com/grok_api_v2.GrokBuildBilling/GetGrokCreditsConfig"
)
GROK_GRPC_WEB_REQUEST = b"\x00\x00\x00\x00\x00"

@dataclass(frozen=True)
class _GrokCreditsConfig:
    used_percent: Decimal
    period_end: datetime | None


class GrokCollector(Collector):
    provider_id = "grok"
    provider_name = "Grok"

    def is_configured(self) -> bool:
        return GROK_AUTH_PATH.is_file()

    def collect(self) -> UsageSnapshot:
        now = datetime.now(timezone.utc)
        bearer_token = self._load_bearer_token()
        if not bearer_token:
            return self._snapshot(
                status=ProviderStatus.AUTH_REQUIRED,
                message=f"Grok 로그인 정보를 찾을 수 없습니다: {GROK_AUTH_PATH}",
                collected_at=now,
                error_code="GROK_AUTH_NOT_CONFIGURED",
            )

        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Accept": "application/grpc-web+proto",
            "Content-Type": "application/grpc-web+proto",
            "Connect-Protocol-Version": "1",
            "X-Grpc-Web": "1",
            "Origin": "https://grok.com",
            "Referer": "https://grok.com/?_s=usage",
        }
        try:
            with httpx.Client(timeout=GROK_TIMEOUT_SECONDS) as client:
                response = client.post(
                    GROK_CREDITS_CONFIG_ENDPOINT,
                    headers=headers,
                    content=GROK_GRPC_WEB_REQUEST,
                )
        except httpx.TimeoutException:
            return self._snapshot(
                status=ProviderStatus.ERROR,
                message="Grok 응답 시간이 초과되었습니다.",
                collected_at=now,
                error_code="NETWORK_TIMEOUT",
            )
        except httpx.HTTPError:
            return self._snapshot(
                status=ProviderStatus.ERROR,
                message="Grok 연결 오류입니다.",
                collected_at=now,
                error_code="NETWORK_ERROR",
            )

        if response.status_code in {401, 403}:
            return self._snapshot(
                status=ProviderStatus.AUTH_REQUIRED,
                message="Grok 인증이 만료되었습니다. Grok에 다시 로그인해 주세요.",
                collected_at=now,
                error_code="AUTH_FAILED",
            )
        if response.status_code == 429:
            return self._snapshot(
                status=ProviderStatus.WARNING,
                message="Grok 사용량 조회가 제한되었습니다.",
                collected_at=now,
                error_code="RATE_LIMITED",
            )
        if response.status_code != 200 or not response.content:
            return self._snapshot(
                status=ProviderStatus.UNAVAILABLE,
                message="Grok 주간한 정보를 확인할 수 없습니다.",
                collected_at=now,
                error_code="USAGE_DATA_UNAVAILABLE",
            )

        try:
            config = self._parse_credits_config(response.content)
        except (ValueError, struct.error):
            return self._snapshot(
                status=ProviderStatus.ERROR,
                message="Grok 사용량 응답 형식을 해석할 수 없습니다.",
                collected_at=now,
                error_code="INVALID_RESPONSE",
            )

        quota = QuotaWindow(
            key="weekly",
            label="주간 사용량",
            used_percent=config.used_percent,
            unit="percent",
            window_minutes=7 * 24 * 60,
            resets_at=config.period_end,
        )
        return self._snapshot(
            status=ProviderStatus.OK,
            message="정상 조회",
            collected_at=now,
            last_success_at=now,
            quota_windows=[quota],
        )

    @staticmethod
    def _load_bearer_token() -> str | None:
        if not GROK_AUTH_PATH.is_file():
            return None
        try:
            raw = GROK_AUTH_PATH.read_text(encoding="utf-8")
        except OSError:
            return None

        # Current Grok CLI auth.json stores the account object under an issuer key;
        # older versions stored the key at the root. Support both formats.
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        token = GrokCollector._find_string_value(payload, "key")
        if token:
            return token.strip()

        # Keep compatibility with occasionally malformed auth files.
        match = re.search(r'"key"\s*:\s*"([^"\r\n]+)"', raw)
        return match.group(1).strip() if match else None

    @classmethod
    def _parse_credits_config(cls, body: bytes) -> _GrokCreditsConfig:
        payload = cls._grpc_web_data(body)
        outer_fields = list(cls._parse_proto_fields(payload))
        config_payload = next(
            (
                value
                for field_number, wire_type, value in outer_fields
                if field_number == 1 and wire_type == 2
            ),
            None,
        )
        if not isinstance(config_payload, bytes):
            raise ValueError("Missing Grok credits config message")

        fields = list(cls._parse_proto_fields(config_payload))
        used_percent = cls._first_fixed32_decimal(fields, 1)
        if used_percent is None:
            raise ValueError("Missing Grok usage percentage")

        period_end = cls._first_timestamp(fields, 5)

        return _GrokCreditsConfig(
            used_percent=cls._clamp_percent(used_percent),
            period_end=period_end,
        )

    @staticmethod
    def _grpc_web_data(body: bytes) -> bytes:
        """Return concatenated data frames, ignoring the gRPC-Web trailer frame."""
        offset = 0
        data_frames: list[bytes] = []
        while offset < len(body):
            if len(body) - offset < 5:
                raise ValueError("Incomplete gRPC-Web frame header")
            flags = body[offset]
            frame_length = int.from_bytes(body[offset + 1 : offset + 5], "big")
            offset += 5
            frame_end = offset + frame_length
            if frame_end > len(body):
                raise ValueError("Incomplete gRPC-Web frame payload")
            frame = body[offset:frame_end]
            offset = frame_end
            if not flags & 0x80:
                data_frames.append(frame)
        if not data_frames:
            raise ValueError("Missing gRPC-Web data frame")
        return b"".join(data_frames)

    @classmethod
    def _parse_proto_fields(cls, payload: bytes) -> Iterator[tuple[int, int, int | bytes]]:
        offset = 0
        while offset < len(payload):
            tag, offset = cls._read_varint(payload, offset)
            field_number = tag >> 3
            wire_type = tag & 0x07
            if field_number <= 0:
                raise ValueError("Invalid protobuf field number")
            if wire_type == 0:
                value, offset = cls._read_varint(payload, offset)
            elif wire_type == 1:
                end = offset + 8
                if end > len(payload):
                    raise ValueError("Incomplete fixed64 field")
                value = payload[offset:end]
                offset = end
            elif wire_type == 2:
                length, offset = cls._read_varint(payload, offset)
                end = offset + length
                if end > len(payload):
                    raise ValueError("Incomplete length-delimited field")
                value = payload[offset:end]
                offset = end
            elif wire_type == 5:
                end = offset + 4
                if end > len(payload):
                    raise ValueError("Incomplete fixed32 field")
                value = payload[offset:end]
                offset = end
            else:
                raise ValueError(f"Unsupported protobuf wire type: {wire_type}")
            yield field_number, wire_type, value

    @staticmethod
    def _read_varint(payload: bytes, offset: int) -> tuple[int, int]:
        value = 0
        shift = 0
        while offset < len(payload):
            byte = payload[offset]
            offset += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value, offset
            shift += 7
            if shift >= 64:
                raise ValueError("Protobuf varint is too long")
        raise ValueError("Incomplete protobuf varint")

    @classmethod
    def _first_varint(
        cls, fields: list[tuple[int, int, int | bytes]], field_number: int
    ) -> int | None:
        for number, wire_type, value in fields:
            if number == field_number and wire_type == 0 and isinstance(value, int):
                return value
        return None

    @staticmethod
    def _first_fixed32_decimal(
        fields: list[tuple[int, int, int | bytes]], field_number: int
    ) -> Decimal | None:
        for number, wire_type, value in fields:
            if number == field_number and wire_type == 5 and isinstance(value, bytes):
                return Decimal(str(struct.unpack("<f", value)[0]))
        return None

    @classmethod
    def _first_timestamp(
        cls, fields: list[tuple[int, int, int | bytes]], field_number: int
    ) -> datetime | None:
        for number, wire_type, value in fields:
            if number == field_number and wire_type == 2 and isinstance(value, bytes):
                timestamp_fields = list(cls._parse_proto_fields(value))
                seconds = cls._first_varint(timestamp_fields, 1)
                nanos = cls._first_varint(timestamp_fields, 2) or 0
                if seconds is None:
                    return None
                return datetime.fromtimestamp(seconds, tz=timezone.utc) + timedelta(
                    microseconds=nanos // 1000
                )
        return None

    @staticmethod
    def _clamp_percent(value: Decimal) -> Decimal:
        return max(Decimal("0"), min(Decimal("100"), value))

    @classmethod
    def _find_string_value(cls, value: object, key: str) -> str | None:
        if isinstance(value, dict):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return found
            for child in value.values():
                result = cls._find_string_value(child, key)
                if result:
                    return result
        elif isinstance(value, list):
            for child in value:
                result = cls._find_string_value(child, key)
                if result:
                    return result
        return None

    def _snapshot(
        self,
        *,
        status: ProviderStatus,
        message: str,
        collected_at: datetime,
        error_code: str | None = None,
        last_success_at: datetime | None = None,
        quota_windows: list[QuotaWindow] | None = None,
    ) -> UsageSnapshot:
        return UsageSnapshot(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            source_type=SourceType.OFFICIAL_API,
            status=status,
            collected_at=collected_at,
            last_success_at=last_success_at,
            stale_after_seconds=900,
            quota_windows=quota_windows or [],
            message=message,
            error_code=error_code,
        )

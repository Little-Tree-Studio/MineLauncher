import base64
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import AuthConfig, AuthType


@dataclass
class TokenInfo:
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    refresh_token: str | None = None
    scope: str | None = None
    created_at: float = field(default_factory=time.time)

    @property
    def expires_at(self) -> float:
        return self.created_at + self.expires_in

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

    def expires_in_seconds(self, buffer: int = 300) -> int:
        remaining = self.expires_at - time.time() - buffer
        return max(0, int(remaining))

    def is_expiring_soon(self, buffer: int = 300) -> bool:
        return self.expires_in_seconds(buffer) <= 0

    @classmethod
    def from_oauth_response(cls, data: dict[str, Any]) -> "TokenInfo":
        return cls(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_in=data.get("expires_in", 3600),
            refresh_token=data.get("refresh_token"),
            scope=data.get("scope"),
        )


class AuthManager:
    def __init__(self, config: AuthConfig) -> None:
        self.config = config
        self._token_info: TokenInfo | None = None
        self._oauth_client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        return self.config.auth_type != AuthType.NONE

    @property
    def needs_token_refresh(self) -> bool:
        if self.config.auth_type != AuthType.OAUTH2:
            return False
        return bool(self._token_info and self._token_info.is_expiring_soon(self.config.refresh_before_expiry))

    def get_auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.config.auth_type == AuthType.NONE:
            return headers
        if self.config.auth_type == AuthType.BASIC:
            if self.config.username and self.config.password:
                credentials = f"{self.config.username}:{self.config.password}"
                encoded = base64.b64encode(credentials.encode()).decode()
                headers["Authorization"] = f"Basic {encoded}"
        elif self.config.auth_type == AuthType.BEARER:
            token = self._token_info.access_token if self._token_info else self.config.token
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif self.config.auth_type == AuthType.DIGEST:
            pass
        elif self.config.auth_type == AuthType.API_KEY:
            if self.config.api_key:
                headers[self.config.api_key_header] = self.config.api_key
        elif self.config.auth_type == AuthType.OAUTH2:
            token = self._token_info.access_token if self._token_info else self.config.token
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif self.config.auth_type == AuthType.CUSTOM:
            headers.update(self.config.custom_headers)
        return headers

    def get_auth_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.config.auth_type == AuthType.API_KEY and self.config.api_key:
            params["api_key"] = self.config.api_key
        return params

    async def refresh_token(self) -> bool:
        if self.config.auth_type != AuthType.OAUTH2:
            return False
        if not self.config.oauth2_refresh_token:
            return False
        if not self.config.oauth2_token_url:
            return False

        try:
            if self._oauth_client is None:
                self._oauth_client = httpx.AsyncClient()

            data = {
                "grant_type": "refresh_token",
                "refresh_token": self.config.oauth2_refresh_token,
            }

            if self.config.oauth2_client_id:
                data["client_id"] = self.config.oauth2_client_id
            if self.config.oauth2_client_secret:
                data["client_secret"] = self.config.oauth2_client_secret

            headers = {"Content-Type": "application/x-www-form-urlencoded"}

            response = await self._oauth_client.post(
                self.config.oauth2_token_url,
                data=data,
                headers=headers,
            )
            response.raise_for_status()

            token_data = response.json()
            self._token_info = TokenInfo.from_oauth_response(token_data)

            if self._token_info.refresh_token:
                self.config.oauth2_refresh_token = self._token_info.refresh_token

            return True

        except Exception:
            return False

    async def authenticate_oauth2(
        self,
        authorization_code: str | None = None,
        redirect_uri: str | None = None,
    ) -> TokenInfo | None:
        if self.config.auth_type != AuthType.OAUTH2:
            return None
        if not self.config.oauth2_token_url:
            return None

        try:
            if self._oauth_client is None:
                self._oauth_client = httpx.AsyncClient()

            data: dict[str, Any] = {}
            if authorization_code:
                data["grant_type"] = "authorization_code"
                data["code"] = authorization_code
                if redirect_uri:
                    data["redirect_uri"] = redirect_uri
            elif self.config.oauth2_client_id and self.config.oauth2_client_secret:
                data["grant_type"] = "client_credentials"

            if self.config.oauth2_client_id:
                data["client_id"] = self.config.oauth2_client_id
            if self.config.oauth2_client_secret:
                data["client_secret"] = self.config.oauth2_client_secret

            headers = {"Content-Type": "application/x-www-form-urlencoded"}

            response = await self._oauth_client.post(
                self.config.oauth2_token_url,
                data=data,
                headers=headers,
            )
            response.raise_for_status()

            token_data = response.json()
            self._token_info = TokenInfo.from_oauth_response(token_data)

            if self._token_info.refresh_token:
                self.config.oauth2_refresh_token = self._token_info.refresh_token

            return self._token_info

        except Exception:
            return None

    def set_token(self, token: str, token_type: str = "Bearer") -> None:
        self._token_info = TokenInfo(
            access_token=token,
            token_type=token_type,
        )

    def set_token_info(self, token_info: TokenInfo) -> None:
        self._token_info = token_info

    async def close(self) -> None:
        if self._oauth_client:
            await self._oauth_client.aclose()
            self._oauth_client = None

    @staticmethod
    def create_basic_auth(username: str, password: str) -> AuthConfig:
        return AuthConfig(
            auth_type=AuthType.BASIC,
            username=username,
            password=password,
        )

    @staticmethod
    def create_bearer_auth(token: str) -> AuthConfig:
        return AuthConfig(
            auth_type=AuthType.BEARER,
            token=token,
        )

    @staticmethod
    def create_api_key_auth(api_key: str, header_name: str = "X-API-Key") -> AuthConfig:
        return AuthConfig(
            auth_type=AuthType.API_KEY,
            api_key=api_key,
            api_key_header=header_name,
        )

    @staticmethod
    def create_oauth2_auth(
        token_url: str,
        client_id: str,
        client_secret: str,
        refresh_token: str | None = None,
    ) -> AuthConfig:
        return AuthConfig(
            auth_type=AuthType.OAUTH2,
            oauth2_token_url=token_url,
            oauth2_client_id=client_id,
            oauth2_client_secret=client_secret,
            oauth2_refresh_token=refresh_token,
        )

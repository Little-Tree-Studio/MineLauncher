from __future__ import annotations
import hashlib
import uuid as uuid_lib
import requests
import time
from typing import Optional, Tuple
from app.services.account_service import (
    Account,
    AccountService,
    LoginResult,
    LOGIN_LEGACY,
    LOGIN_NIDE,
    LOGIN_AUTHLIB,
    LOGIN_MICROSOFT,
    LoginType,
)
from app.services.oauth_funcs import (
    microsoft_login as oauth_microsoft_login,
    refresh_ms_token,
    access_token_to_xbl,
    xbl_to_xsts,
    xsts_to_mc_token,
    get_mc_profile,
    check_minecraft_ownership,
)


class AuthService:
    def __init__(self) -> None:
        self.account_service = AccountService()

    def legacy_login(
        self, username: str, skin_type: str = "classic", skin_name: str = ""
    ) -> LoginResult:
        md5_bytes = hashlib.md5(username.lower().encode("utf-8")).digest()
        u = uuid_lib.UUID(bytes=md5_bytes)
        uuid = u.hex

        account = self.account_service.create_legacy_account(
            username=username,
            skin_type=skin_type,
            skin_name=skin_name or username,
        )
        self.account_service.set_last_account(account.account_id)

        return account.to_login_result()

    def microsoft_login(self, force_refresh: bool = False) -> LoginResult:
        uuid, username, auth_data = oauth_microsoft_login()

        mc_token = auth_data["mc_token"]
        refresh_token = auth_data.get("refresh_token", "")
        profile_json = auth_data.get("profile", {})
        expires_at = time.time() + 86400

        account = self.account_service.create_microsoft_account(
            uuid=uuid,
            username=username,
            access_token=mc_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            profile_json=profile_json,
        )
        self.account_service.set_last_account(account.account_id)

        return account.to_login_result()

    def refresh_microsoft_token(self, account: Account) -> LoginResult:
        if not account.refresh_token:
            raise Exception("No refresh token available")

        token_data = refresh_ms_token(account.refresh_token)
        access_token = token_data.get("access_token")
        new_refresh_token = token_data.get("refresh_token", account.refresh_token)

        if not access_token:
            raise Exception("Failed to refresh token")

        xbl = access_token_to_xbl(access_token)
        xsts = xbl_to_xsts(xbl)
        mc_token = xsts_to_mc_token(xsts)

        profile_json = get_mc_profile(mc_token)
        expires_at = time.time() + 86400

        account.access_token = mc_token
        account.refresh_token = new_refresh_token
        account.expires_at = expires_at
        account.profile_json = profile_json
        account.uuid = profile_json.get("id", account.uuid)
        account.username = profile_json.get("name", account.username)

        self.account_service.update_account(account)

        return account.to_login_result()

    def server_login(
        self,
        username: str,
        password: str,
        base_url: str,
        server_id: str = "",
        login_type: int = LOGIN_NIDE,
    ) -> LoginResult:
        if login_type == LOGIN_NIDE:
            auth_url = f"{base_url}/authserver"
        else:
            auth_url = f"{base_url}/authlib/inject"

        validate_url = f"{auth_url}/validate"
        authenticate_url = f"{auth_url}/authenticate"

        client_token = hashlib.md5(str(time.time()).encode()).hexdigest()

        auth_data = {
            "agent": {"name": "Minecraft", "version": 1},
            "username": username,
            "password": password,
            "clientToken": client_token,
        }

        response = requests.post(authenticate_url, json=auth_data, timeout=30)

        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get(
                "errorMessage", error_data.get("error", "Unknown error")
            )
            raise Exception(f"Authentication failed: {error_msg}")

        result = response.json()
        access_token = result["accessToken"]
        selected_profile = result["selectedProfile"]
        profile_id = selected_profile["id"].replace("-", "")
        profile_name = selected_profile["name"]

        account = Account(
            account_id="",
            login_type=LoginType(login_type),
            username=profile_name,
            uuid=profile_id,
            access_token=access_token,
            refresh_token="",
            expires_at=0,
            profile_json={"id": profile_id, "name": profile_name},
            base_url=base_url,
            server_id=server_id,
            client_token=client_token,
        )
        self.account_service.add_account(account)
        self.account_service.set_last_account(account.account_id)

        return account.to_login_result()

    def validate_token(self, account: Account) -> bool:
        if account.type == LOGIN_LEGACY:
            return True

        if account.type == LOGIN_MICROSOFT:
            if account.is_expired():
                return False
            return True

        if account.type in (LOGIN_NIDE, LOGIN_AUTHLIB):
            base_url = account.base_url
            if account.type == LOGIN_NIDE:
                validate_url = f"{base_url}/authserver/validate"
            else:
                validate_url = f"{base_url}/authlib/inject/validate"

            validate_data = {
                "accessToken": account.access_token,
                "clientToken": account.client_token,
            }

            try:
                response = requests.post(validate_url, json=validate_data, timeout=10)
                return response.status_code == 204
            except Exception:
                return False

        return False

    def login_with_account(self, account: Account) -> LoginResult:
        if account.type == LOGIN_LEGACY:
            return self.legacy_login(
                account.username, account.skin_type, account.skin_name
            )

        if account.type == LOGIN_MICROSOFT:
            if account.is_expired():
                return self.refresh_microsoft_token(account)
            return account.to_login_result()

        if account.type in (LOGIN_NIDE, LOGIN_AUTHLIB):
            if not self.validate_token(account):
                raise Exception("Token expired, please re-login")
            return account.to_login_result()

        raise ValueError(f"Unknown login type: {account.type}")

    def get_login_result(
        self, account_id: Optional[str] = None
    ) -> Optional[LoginResult]:
        if account_id:
            account = self.account_service.get_account(account_id)
        else:
            account = self.account_service.get_last_account()

        if not account:
            return None

        return self.login_with_account(account)

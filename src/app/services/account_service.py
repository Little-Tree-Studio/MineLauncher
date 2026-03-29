from __future__ import annotations
import rtoml
from pathlib import Path
from typing import Any, Dict, List, Optional
import hashlib
import time
from enum import IntEnum


class LoginType(IntEnum):
    LEGACY = 0
    NIDE = 2
    AUTHLIB = 3
    MICROSOFT = 5


LOGIN_LEGACY = LoginType.LEGACY
LOGIN_NIDE = LoginType.NIDE
LOGIN_AUTHLIB = LoginType.AUTHLIB
LOGIN_MICROSOFT = LoginType.MICROSOFT


class LoginResult:
    def __init__(
        self,
        uuid: str,
        username: str,
        access_token: str,
        login_type: LoginType,
        client_token: Optional[str] = None,
        profile_json: Optional[dict] = None,
    ):
        self.uuid = uuid
        self.username = username
        self.access_token = access_token
        self.type = login_type
        self.client_token = client_token
        self.profile_json = profile_json or {}

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "username": self.username,
            "accessToken": self.access_token,
            "type": int(self.type),
            "clientToken": self.client_token,
            "profileJson": self.profile_json,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LoginResult":
        return cls(
            uuid=data["uuid"],
            username=data["username"],
            access_token=data["accessToken"],
            login_type=LoginType(data["type"]),
            client_token=data.get("clientToken"),
            profile_json=data.get("profileJson"),
        )


class Account:
    def __init__(
        self,
        account_id: str,
        login_type: LoginType,
        username: str,
        uuid: str,
        access_token: str = "",
        refresh_token: str = "",
        expires_at: float = 0,
        profile_json: Optional[dict] = None,
        skin_type: str = "classic",
        skin_name: str = "",
        base_url: str = "",
        server_id: str = "",
        client_token: Optional[str] = None,
    ):
        self.account_id = account_id
        self.type = login_type
        self.username = username
        self.uuid = uuid
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.profile_json = profile_json or {}
        self.skin_type = skin_type
        self.skin_name = skin_name
        self.base_url = base_url
        self.server_id = server_id
        self.client_token = client_token

    @staticmethod
    def generate_legacy_uuid(username: str) -> str:
        name_bytes = username.encode("utf-8")
        name_hash = 0
        for byte in name_bytes:
            name_hash = ((name_hash << 8) - name_hash) & 0xFFFFFFFFFFFFFFFF
            name_hash ^= byte
            name_hash &= 0xFFFFFFFFFFFFFFFF

        hash_str = format(name_hash & 0xFFFFFFFFFFFFFFFF, "016x")
        full_uuid = f"{len(username):02x}{hash_str}"

        uuid_chars = list(full_uuid)
        uuid_chars[12] = "3"
        uuid_chars[16] = "9"

        return "".join(uuid_chars)[:32]

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "type": int(self.type),
            "username": self.username,
            "uuid": self.uuid,
            "accessToken": self.access_token,
            "refreshToken": self.refresh_token,
            "expiresAt": self.expires_at,
            "profileJson": self.profile_json,
            "skinType": self.skin_type,
            "skinName": self.skin_name,
            "baseUrl": self.base_url,
            "serverId": self.server_id,
            "clientToken": self.client_token,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Account":
        return cls(
            account_id=data["account_id"],
            login_type=LoginType(data["type"]),
            username=data["username"],
            uuid=data["uuid"],
            access_token=data.get("accessToken", ""),
            refresh_token=data.get("refreshToken", ""),
            expires_at=data.get("expiresAt", 0),
            profile_json=data.get("profileJson"),
            skin_type=data.get("skinType", "classic"),
            skin_name=data.get("skinName", ""),
            base_url=data.get("baseUrl", ""),
            server_id=data.get("serverId", ""),
            client_token=data.get("clientToken"),
        )

    def is_expired(self) -> bool:
        if self.type != LOGIN_MICROSOFT:
            return False
        if not self.expires_at:
            return False
        return time.time() > self.expires_at - 300

    def to_login_result(self) -> LoginResult:
        return LoginResult(
            uuid=self.uuid,
            username=self.username,
            access_token=self.access_token,
            login_type=self.type,
            client_token=self.client_token,
            profile_json=self.profile_json,
        )


class AccountService:
    DEFAULT_CONFIG = {
        "Accounts": [],
        "LastAccountId": None,
    }

    def __init__(self) -> None:
        self.path = Path("MineLauncher/config/accounts.toml")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cfg: Dict[str, Any] | None = None

    def load(self) -> Dict[str, Any]:
        if self._cfg is None:
            try:
                self._cfg = rtoml.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._cfg = self.DEFAULT_CONFIG.copy()
            self._cfg = self._merge_defaults(self._cfg, self.DEFAULT_CONFIG)
        return self._cfg

    def _merge_defaults(self, cfg: Dict, defaults: Dict) -> Dict:
        result = defaults.copy()
        for key, value in cfg.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._merge_defaults(value, result[key])
            else:
                result[key] = value
        return result

    def save(self, cfg: Dict[str, Any]) -> None:
        self._cfg = cfg
        self.path.write_text(rtoml.dumps(cfg), encoding="utf-8")

    def _generate_account_id(self) -> str:
        return hashlib.md5(str(time.time()).encode()).hexdigest()[:16]

    def get_accounts(self) -> List[Account]:
        cfg = self.load()
        accounts = []
        for account_data in cfg.get("Accounts", []):
            try:
                accounts.append(Account.from_dict(account_data))
            except Exception:
                continue
        return accounts

    def get_account(self, account_id: str) -> Optional[Account]:
        accounts = self.get_accounts()
        for account in accounts:
            if account.account_id == account_id:
                return account
        return None

    def add_account(self, account: Account) -> None:
        cfg = self.load()
        if account.account_id is None:
            account.account_id = self._generate_account_id()
        accounts = cfg.get("Accounts", [])
        accounts.append(account.to_dict())
        cfg["Accounts"] = accounts
        self.save(cfg)

    def update_account(self, account: Account) -> None:
        cfg = self.load()
        accounts = cfg.get("Accounts", [])
        for i, acc_data in enumerate(accounts):
            if acc_data.get("account_id") == account.account_id:
                accounts[i] = account.to_dict()
                break
        cfg["Accounts"] = accounts
        self.save(cfg)

    def remove_account(self, account_id: str) -> None:
        cfg = self.load()
        accounts = cfg.get("Accounts", [])
        accounts = [a for a in accounts if a.get("account_id") != account_id]
        cfg["Accounts"] = accounts
        if cfg.get("LastAccountId") == account_id:
            cfg["LastAccountId"] = accounts[0]["account_id"] if accounts else None
        self.save(cfg)

    def set_last_account(self, account_id: str) -> None:
        cfg = self.load()
        cfg["LastAccountId"] = account_id
        self.save(cfg)

    def get_last_account(self) -> Optional[Account]:
        cfg = self.load()
        last_id = cfg.get("LastAccountId")
        if last_id:
            return self.get_account(last_id)
        accounts = self.get_accounts()
        return accounts[0] if accounts else None

    def create_legacy_account(
        self, username: str, skin_type: str = "classic", skin_name: str = ""
    ) -> Account:
        import hashlib
        import uuid as uuid_lib

        md5_bytes = hashlib.md5(username.lower().encode("utf-8")).digest()
        u = uuid_lib.UUID(bytes=md5_bytes)
        uuid = u.hex

        account = Account(
            account_id=self._generate_account_id(),
            login_type=LOGIN_LEGACY,
            username=username,
            uuid=uuid,
            access_token="0",
            skin_type=skin_type,
            skin_name=skin_name or username,
        )
        self.add_account(account)
        return account

    def create_microsoft_account(
        self,
        uuid: str,
        username: str,
        access_token: str,
        refresh_token: str,
        expires_at: float,
        profile_json: dict,
    ) -> Account:
        account = Account(
            account_id=self._generate_account_id(),
            login_type=LOGIN_MICROSOFT,
            username=username,
            uuid=uuid,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            profile_json=profile_json,
        )
        self.add_account(account)
        return account

    def create_server_account(
        self,
        username: str,
        password: str,
        base_url: str,
        server_id: str = "",
        login_type: LoginType = LOGIN_NIDE,
    ) -> Account:
        account = Account(
            account_id=self._generate_account_id(),
            login_type=login_type,
            username=username,
            uuid="",
            base_url=base_url,
            server_id=server_id,
        )
        self.add_account(account)
        return account

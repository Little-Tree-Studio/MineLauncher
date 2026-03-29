import requests
import json
import hashlib
import uuid as uuid_lib
from typing import Optional
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import webbrowser
import time

CLIENT_ID = "4dedb5d8-d8b4-4d1c-87dd-5ebb9b65aa7c"
REDIRECT_URI = "http://localhost:8080/callback"

auth_code: Optional[str] = None


def code_to_token(auth_code: str, redirect_uri: str = REDIRECT_URI) -> dict:
    token_url = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
    token_data = {
        "client_id": CLIENT_ID,
        "code": auth_code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "scope": "service::user.auth.xboxlive.com::MBI_SSL",
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    response = requests.post(token_url, data=token_data, headers=headers)
    return response.json()


def refresh_ms_token(refresh_token: str) -> dict:
    url = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
    token_data = {
        "client_id": CLIENT_ID,
        "scope": "service::user.auth.xboxlive.com::MBI_SSL",
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    response = requests.post(url, data=token_data)
    return response.json()


def get_device_code() -> dict:
    url = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
    data = {
        "client_id": CLIENT_ID,
        "scope": "service::user.auth.xboxlive.com::MBI_SSL",
    }
    response = requests.post(url, data=data)
    result = response.json()

    if "error" in result:
        raise Exception(
            f"Device code error: {result.get('error_description', result.get('error', 'Unknown'))}"
        )

    if "device_code" not in result:
        raise Exception(f"No device_code in response: {result}")

    return result


def poll_for_token(device_code: str, interval: int = 5, timeout: int = 900) -> dict:
    url = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
    start_time = time.time()

    while time.time() - start_time < timeout:
        token_data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": CLIENT_ID,
            "code": device_code,
        }
        response = requests.post(url, data=token_data)
        result = response.json()

        if "access_token" in result:
            return result
        elif result.get("error") == "authorization_pending":
            time.sleep(interval)
        elif result.get("error") == "slow_down":
            interval += 5
            time.sleep(interval)
        elif result.get("error") == "expired_token":
            raise Exception("Device code expired")
        elif result.get("error") == "authorization_declined":
            raise Exception("Authorization declined by user")
        else:
            raise Exception(
                f"Auth failed: {result.get('error_description', 'Unknown error')}"
            )

    raise TimeoutError("Authentication timeout")


def access_token_to_xbl(access_token: str) -> dict:
    url = "https://user.auth.xboxlive.com/user/authenticate"
    data = {
        "Properties": {
            "AuthMethod": "RPS",
            "SiteName": "user.auth.xboxlive.com",
            "RpsTicket": f"d={access_token}",
        },
        "RelyingParty": "http://auth.xboxlive.com",
        "TokenType": "JWT",
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    response = requests.post(url, json=data, headers=headers, timeout=30)

    if response.status_code != 200:
        raise Exception(f"XBL auth failed: {response.status_code} - {response.text}")

    response_data = response.json()

    if "Token" not in response_data:
        raise KeyError("Token not found in XBL response")

    return {
        "token": response_data["Token"],
        "uhs": response_data["DisplayClaims"]["xui"][0]["uhs"],
    }


def xbl_to_xsts(xbl_return: dict) -> dict:
    url = "https://xsts.auth.xboxlive.com/xsts/authorize"
    xbl = xbl_return["token"]
    data = {
        "Properties": {
            "SandboxId": "RETAIL",
            "UserTokens": [xbl],
        },
        "RelyingParty": "rp://api.minecraftservices.com/",
        "TokenType": "JWT",
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    response = requests.post(url, json=data, headers=headers, timeout=30)

    if response.status_code != 200:
        raise Exception(f"XSTS auth failed: {response.status_code} - {response.text}")

    response_data = response.json()

    return {
        "uhs": response_data["DisplayClaims"]["xui"][0]["uhs"],
        "xsts_token": response_data["Token"],
    }


def xsts_to_mc_token(xsts_return: dict) -> str:
    url = "https://api.minecraftservices.com/authentication/login_with_xbox"
    uhs = xsts_return["uhs"]
    xsts_token = xsts_return["xsts_token"]
    data = {
        "identityToken": f"XBL3.0 x={uhs};{xsts_token}",
        "titleId": "26934a88-3faf-4c7c-bf3b-9d88d5b2f82f",
        "generation": 2,
    }

    response = requests.post(url, json=data, timeout=30)

    if response.status_code != 200:
        raise Exception(
            f"Minecraft auth failed: {response.status_code} - {response.text}"
        )

    response_data = response.json()

    if "access_token" not in response_data:
        raise KeyError("access_token not found in Minecraft auth response")

    return response_data["access_token"]


def get_mc_profile(access_token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    url = "https://api.minecraftservices.com/minecraft/profile"
    response = requests.get(url, headers=headers)

    if response.status_code == 404:
        raise Exception("No Minecraft profile found (game not purchased)")
    elif response.status_code != 200:
        raise Exception(f"Profile API error: {response.status_code}")

    return response.json()


def check_minecraft_ownership(access_token: str) -> tuple[bool, dict]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    entitlements_url = "https://api.minecraftservices.com/entitlements/mcstore"
    try:
        entitlements_response = requests.get(entitlements_url, headers=headers)
        entitlements_response.raise_for_status()
        entitlements_data = entitlements_response.json()
        items = entitlements_data.get("items", [])

        profile_url = "https://api.minecraftservices.com/minecraft/profile"
        profile_response = requests.get(profile_url, headers=headers)
        profile_data = (
            profile_response.json() if profile_response.status_code == 200 else {}
        )

        has_minecraft = (
            len(items) > 0
            and profile_response.status_code == 200
            and "error" not in profile_data
        )
        return has_minecraft, profile_data
    except Exception:
        return False, {}


def gen_legacy_uuid(username: str) -> str:
    md5_bytes = hashlib.md5(username.lower().encode("utf-8")).digest()
    u = uuid_lib.UUID(bytes=md5_bytes)
    return u.hex


class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        if self.path.startswith("/callback"):
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()

            query = urlparse(self.path).query
            params = parse_qs(query)

            if "code" in params:
                auth_code = params["code"][0]
                self.wfile.write(
                    b"<h1>Authentication Successful!</h1><p>You can close this window.</p>"
                )
            elif "error" in params:
                error = params["error"][0]
                error_desc = params.get("error_description", [""])[0]
                self.wfile.write(f"<h1>Error: {error}</h1><p>{error_desc}</p>".encode())
            else:
                self.wfile.write(b"<h1>No code or error received</h1>")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_oauth_server() -> HTTPServer:
    server = HTTPServer(("localhost", 8080), OAuthHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server


def authorize_with_device_code() -> dict:
    device_code_data = get_device_code()
    device_code = device_code_data["device_code"]
    user_code = device_code_data["user_code"]
    verification_uri = device_code_data["verification_uri"]
    interval = device_code_data.get("interval", 5)
    expires_in = device_code_data.get("expires_in", 900)

    webbrowser.open(verification_uri)

    return poll_for_token(device_code, interval, expires_in)


def microsoft_login() -> tuple[str, str, dict]:
    token_data = authorize_with_device_code()
    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token", "")

    xbl = access_token_to_xbl(access_token)
    xsts = xbl_to_xsts(xbl)
    mc_token = xsts_to_mc_token(xsts)

    has_minecraft, profile_data = check_minecraft_ownership(mc_token)
    if not has_minecraft:
        raise Exception("No Minecraft license found")

    uuid = profile_data.get("id", "")
    username = profile_data.get("name", "")

    return (
        uuid,
        username,
        {"mc_token": mc_token, "refresh_token": refresh_token, "profile": profile_data},
    )


if __name__ == "__main__":
    print(microsoft_login())

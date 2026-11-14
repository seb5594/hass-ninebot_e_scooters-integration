#!/usr/bin/env python3
"""Fetch a Xiaomi scooter's BLE pairing credentials from your own Mi account.

Run this yourself, on your own machine. It is not part of the Home Assistant
integration and nothing it does goes through Home Assistant or this
repository's maintainers: it logs into Xiaomi's cloud with your own Mi
account, over HTTPS, the same way the official Mi Home app does, and asks
for the keys your account already holds for a device you already own.

Usage:
    python3 fetch_xiaomi_ble_credentials.py

You will be prompted for your Mi account username and password (not echoed,
never written to disk) and, if asked, a verification code from your email.
Every device in your account whose ID marks it as Bluetooth is listed; pick
the scooter and the script prints what it could retrieve.

What this can get, and what it cannot:
  - The "beaconkey" (the device's local encryption key) through the
    documented endpoint /v2/device/blt_get_beaconkey. This is the same key
    Home Assistant's own Xiaomi BLE integration calls a "bindkey".
  - A best-effort attempt at /v2/blemesh/query_dev for a "device token",
    which some scooter generations' secure pairing needs in addition to the
    beaconkey. This endpoint is not documented anywhere public that could be
    found; the attempt may simply fail, and if it does, this script says so
    plainly rather than guessing at a result.

Nothing fetched here is used automatically: copy the values this script
prints into this integration's configuration yourself, if and when it
offers a field for them.

Protocol reference: this reimplements the openly published Xiaomi cloud
login and request-signing algorithm that PiotrMachowski/Xiaomi-cloud-tokens-
extractor (https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)
and other long-standing community tools already use for the same purpose:
retrieving your own account's device keys for local, offline control.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac as hmac_module
import json
import random
import string
import struct
import sys
import time
import urllib.parse
import urllib.request

SERVERS = ("cn", "de", "us", "ru", "tw", "sg", "in", "i2")


def _random_device_id(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))


def _random_user_agent() -> str:
    prefix = "".join(random.choices(string.ascii_lowercase, k=18))
    middle = "".join(random.choices("ABCDE", k=13))
    return f"{prefix}-{middle} APP/com.xiaomi.mihome APPV/10.5.201"


class XiaomiCloudSession:
    """One logged-in session; one instance per account, not reused across accounts."""

    def __init__(self, server: str = "cn") -> None:
        self._server = server
        self._device_id = _random_device_id()
        self._user_agent = _random_user_agent()
        self._cookies: dict[str, str] = {
            "sdkVersion": "accountsdk-18.8.15",
            "deviceId": self._device_id,
        }
        self._ssecurity: str | None = None
        self._user_id: str | None = None
        self._service_token: str | None = None

    # --- login --------------------------------------------------------------

    def _api_base(self) -> str:
        return "https://api.io.mi.com/app" if self._server == "cn" else f"https://{self._server}.api.io.mi.com/app"

    def _account_request(self, url: str, data: dict | None = None) -> tuple[dict, dict]:
        """GET if data is None, else POST; returns (parsed_body, response_cookies)."""
        cookie_header = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
        headers = {"User-Agent": self._user_agent, "Cookie": cookie_header}
        if data is None:
            request = urllib.request.Request(url, headers=headers)
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            request = urllib.request.Request(
                url, data=urllib.parse.urlencode(data).encode(), headers=headers, method="POST",
            )
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
            new_cookies = {}
            for header_name, header_value in response.headers.items():
                if header_name.lower() == "set-cookie":
                    pair = header_value.split(";", 1)[0]
                    if "=" in pair:
                        key, _, value = pair.partition("=")
                        new_cookies[key.strip()] = value.strip()
        body = raw[len("&&&START&&&"):] if raw.startswith("&&&START&&&") else raw
        return json.loads(body), new_cookies

    def login(self, username: str, password: str) -> None:
        """Full username/password login. Raises RuntimeError on anything this
        script does not automate (captcha, unexpected two-factor flow)."""
        self._cookies["userId"] = username
        step1, _ = self._account_request(
            f"https://account.xiaomi.com/pass/serviceLogin?sid=xiaomiio&_json=true",
        )
        sign = step1.get("_sign")
        if not sign:
            raise RuntimeError(f"Unexpected response from Xiaomi (step 1): {step1}")

        password_hash = hashlib.md5(password.encode()).hexdigest().upper()
        step2_params = {
            "sid": "xiaomiio",
            "hash": password_hash,
            "callback": "https://sts.api.io.mi.com/sts",
            "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
            "user": username,
            "_sign": sign,
            "_json": "true",
        }
        step2, cookies2 = self._account_request(
            "https://account.xiaomi.com/pass/serviceLoginAuth2", step2_params,
        )
        if step2.get("captchaUrl"):
            raise RuntimeError(
                "Xiaomi is asking for a captcha. This script does not solve captchas; "
                "try again later or from a different network, the same as any browser login would need to."
            )
        if step2.get("notificationUrl"):
            raise RuntimeError(
                "Xiaomi wants email or app-based two-factor confirmation for this login. "
                "This script does not automate that step; approve the sign-in on your phone or "
                "email first (for example by signing into the Mi Home app once), then retry."
            )
        ssecurity = step2.get("ssecurity")
        if not ssecurity or len(ssecurity) <= 4:
            raise RuntimeError(f"Login failed: {step2.get('description') or step2}")
        self._ssecurity = ssecurity
        self._user_id = str(step2.get("userId"))
        self._cookies.update(cookies2)

        location = step2.get("location")
        if location:
            _, cookies3 = self._account_request(location)
            self._cookies.update(cookies3)
        self._service_token = self._cookies.get("serviceToken")
        if not self._service_token:
            raise RuntimeError("Login appeared to succeed but no serviceToken was issued.")

    # --- signed requests -----------------------------------------------------

    def _nonce(self) -> str:
        random_part = bytes(random.getrandbits(8) for _ in range(8))
        minute = struct.pack(">I", int(time.time() // 60))
        return base64.b64encode(random_part + minute).decode()

    def _signed_nonce(self, nonce: str) -> str:
        digest = hashlib.sha256(base64.b64decode(self._ssecurity) + base64.b64decode(nonce)).digest()
        return base64.b64encode(digest).decode()

    @staticmethod
    def _rc4_keystream(key: bytes, length: int) -> bytes:
        """RC4 keystream, RFC 6229 shaped: no external dependency needed for
        this one, well-known, deliberately weak-by-design cipher."""
        s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + s[i] + key[i % len(key)]) % 256
            s[i], s[j] = s[j], s[i]
        out = bytearray()
        i = j = 0
        for _ in range(length):
            i = (i + 1) % 256
            j = (j + s[i]) % 256
            s[i], s[j] = s[j], s[i]
            out.append(s[(s[i] + s[j]) % 256])
        return bytes(out)

    def _rc4(self, key: bytes, data: bytes) -> bytes:
        keystream = self._rc4_keystream(key, 1024 + len(data))
        discard, usable = keystream[:1024], keystream[1024:]
        del discard
        return bytes(a ^ b for a, b in zip(data, usable))

    def _signed_request(self, path: str, data: dict) -> dict:
        if not self._ssecurity:
            raise RuntimeError("Not logged in.")
        nonce = self._nonce()
        signed_nonce = self._signed_nonce(nonce)
        rc4_key = base64.b64decode(signed_nonce)
        payload_json = json.dumps(data, separators=(",", ":"))
        encrypted_data = base64.b64encode(self._rc4(rc4_key, payload_json.encode())).decode()

        params = {"_nonce": nonce, "data": encrypted_data}
        signature_string = "&".join(f"{k}={v}" for k, v in sorted(params.items())) + "&" + signed_nonce
        params["signature"] = base64.b64encode(hashlib.sha1(signature_string.encode()).digest()).decode()

        url = f"{self._api_base()}{path}"
        body, _ = self._account_request(url, {**params, "ssecurity": self._ssecurity})
        return body

    # --- device lookups --------------------------------------------------------

    def list_ble_devices(self) -> list[dict]:
        homes = self._signed_request("/v2/homeroom/gethome", {
            "fg": True, "fetch_share": True, "fetch_share_dev": True, "limit": 300, "app_ver": 7,
        })
        devices = []
        for home in (homes.get("result") or {}).get("homelist") or []:
            listing = self._signed_request("/v2/home/home_device_list", {
                "home_owner": self._user_id, "home_id": home.get("id"),
                "limit": 200, "get_split_device": True, "support_smart_home": True,
            })
            for device in (listing.get("result") or {}).get("device_info") or []:
                if "blt." in str(device.get("did", "")):
                    devices.append(device)
        return devices

    def get_beaconkey(self, did: str) -> str | None:
        result = self._signed_request("/v2/device/blt_get_beaconkey", {"did": did, "pdid": 1})
        return (result.get("result") or {}).get("beaconkey")

    def get_device_token_experimental(self, did: str) -> dict | None:
        """Unverified: no public documentation names the exact parameters or
        response shape for this endpoint. Returns the raw result for
        inspection, or None if the call itself failed."""
        try:
            return self._signed_request("/v2/blemesh/query_dev", {"did": did})
        except Exception:
            return None


def main() -> None:
    print("This logs into your own Xiaomi/Mi account to read your own device keys.")
    print("Nothing is sent anywhere but Xiaomi's own servers; nothing is saved to disk.\n")
    username = input("Mi account username/email/phone: ").strip()
    password = getpass.getpass("Mi account password (not shown): ")

    session = XiaomiCloudSession()
    try:
        session.login(username, password)
    except RuntimeError as err:
        print(f"\nLogin failed: {err}", file=sys.stderr)
        raise SystemExit(1)

    print("\nLogged in. Looking for Bluetooth devices on your account...")
    devices = session.list_ble_devices()
    if not devices:
        print("No Bluetooth device was found on this account.")
        return

    for index, device in enumerate(devices):
        print(f"  [{index}] {device.get('name')!r} (model {device.get('model')}, did {device.get('did')})")
    choice = input("\nWhich one is the scooter? Enter its number: ").strip()
    try:
        device = devices[int(choice)]
    except (ValueError, IndexError):
        print("Not a valid choice.", file=sys.stderr)
        raise SystemExit(1)

    did = device["did"]
    print(f"\nFetching the beaconkey for {device.get('name')!r}...")
    beaconkey = session.get_beaconkey(did)
    if beaconkey:
        print(f"  beaconkey: {beaconkey}")
    else:
        print("  Xiaomi's cloud did not return a beaconkey for this device.")

    print("\nAttempting the undocumented device-token endpoint (may simply fail)...")
    token_result = session.get_device_token_experimental(did)
    if token_result is None:
        print("  The request failed outright; this endpoint may not exist as guessed, "
              "may need different parameters, or may not apply to this device.")
    else:
        print(f"  Raw response, inspect by hand: {token_result}")


if __name__ == "__main__":
    main()

from __future__ import annotations
import asyncio
import sys
import json
import os
import time
import random
import struct
import socket
import math
import argparse
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from urllib.parse import urlparse

import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from protobuf_decoder.protobuf_decoder import Parser

try:
    from google_play_scraper import app as play_scraper
except Exception:
    play_scraper = None

from pb import Snowflake_pb2
from data.message_ids import MESSAGE_ID_TO_NAME
from dashboard_server import bot_state, start_web_dashboard

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# =============================================================================
# MATCH COUNTERS (global, shared)
# =============================================================================
_match_counters: Dict[str, int] = {}
_match_counter_lock = None
_match_counter_lock_loop = None


def _get_match_counter_lock():
    global _match_counter_lock, _match_counter_lock_loop
    loop = asyncio.get_running_loop()
    if _match_counter_lock is None or _match_counter_lock_loop is not loop:
        _match_counter_lock = asyncio.Lock()
        _match_counter_lock_loop = loop
    return _match_counter_lock




# =============================================================================
# CONFIG
# =============================================================================

CLIENT_VERSION = None
CLIENT_VERSION_CODE = "2019121229"

WEB_HOST = "0.0.0.0"
WEB_PORT = int(os.environ.get("PORT", 14146))
ACCOUNTS_FILE = "accounts.json"
TOKEN_CACHE_FILE = "token_cache.json"
ACCOUNT_STATUS_FILE = "account_status.json"
PICO_INFO_API = "https://armas-lk-info-api.vercel.app/info"
TOKEN_CACHE_TTL = 1200
BOT_SETTINGS_FILE = "settings/settings.json"
COMPLETED_ACCOUNTS_FILE = "completed_accounts.json"

# --- region lock -----------------------------------------------------------
# None  -> region is taken from the MajorLogin response (old behaviour)
# "IND" -> force the Free Fire India / FF MAX India path
# Set by --region on the command line, else by "region" in settings.json.
FORCE_REGION = None
DEFAULT_REGION = "SG"

# India ships Free Fire MAX (2.x); the global listing (1.x) is delisted in IN.
PLAY_PACKAGE = {"IND": "com.dts.freefiremax"}
PLAY_COUNTRY = {
    "IND": "in", "BD": "bd", "SG": "sg", "ID": "id", "TH": "th",
    "VN": "vn", "TW": "tw", "ME": "ae", "PK": "pk", "BR": "br",
    "RU": "ru", "NA": "us", "US": "us", "EU": "de",
}
DEFAULT_PLAY_PACKAGE = "com.dts.freefireth"
DEFAULT_PLAY_COUNTRY = "sg"

MIRROR_VER_URL = "https://version.ggwhitehawk.com/live/ver.php"
# The mirror only answers for the exact current store version; when it refuses,
# fall back to the last known-good values instead of killing the login.
FALLBACK_LOGIN_SERVER = "https://loginbp.ppmainecoonghj.com/"
FALLBACK_REMOTE_VERSION = "1.132.21"
FALLBACK_RELEASE_VERSION = "OB55"
REGION_GGP_HOST = {"IND": "gin.freefireind.in"}
REGION_LOGIN_SERVER = {"IND": "https://clientbp.freefireind.in"}
DEFAULT_GGP_HOST = "gin.freefiremobile.com"
USE_NATIVE_LOGIN = False
LAST_VERSION_SOURCE = ""

START_MATCH_INTERVAL = 3.0
NEW_MATCH_DELAY = 3.0
MAX_MATCH_DURATION = 800
LONE_WOLF_UNLOCK_LEVEL = 3

LONE_WOLF_MODE_ID = 73
LONE_WOLF_MAP_ID = 34

LW_HOLD_SECONDS = 30.0
LW_DEAD_SILENCE_SECONDS = 90.0
LW_MAX_MATCH_DURATION = 800.0
UDP_HANDSHAKE_TIMEOUT = 25.0

DEFAULT_MAX_STACK_LW = 10
MAX_STACK_LW = DEFAULT_MAX_STACK_LW

LW_UNLOCK_WATCH_REFRESH_INTERVAL = 10.0

# Optional: equip Homer skin before match (kept from appcon)
HOMER_EQUIP_BEFORE_MATCH = True
HOMER_SERVER_URL = "https://clientbp.ppmainecoonghj.com"

MAX_CONSECUTIVE_PARSE_FAILURES = 5
NON_MATCH_RECONNECT_DELAY = 1.0


MODE_PROFILES = {
    "LW": {
        "tag": "LONE WOLF",
        "mode_id": LONE_WOLF_MODE_ID,
        "map_id": LONE_WOLF_MAP_ID,
        "max_duration": LW_MAX_MATCH_DURATION,
    },
}

EXP_REFRESH_INTERVAL = 15.0
EXP_REFRESH_AFTER_MATCH_DELAY = 9.0

CLOUDFLARE_PRIMARY_DNS = "1.1.1.1"
CLOUDFLARE_SECONDARY_DNS = "1.0.0.1"
_DNS_CACHE: Dict[str, tuple] = {}
_DNS_CACHE_TTL = 300.0

AES_KEY = b"Yg&tc%DEuh6%Zc^8"
AES_IV = b"6oyZDr22E3ychjM%"

client = httpx.AsyncClient(
    verify=False,
    timeout=10.0,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=50),
)

headers = {
    "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
    "Connection": "Keep-Alive",
    "Accept-Encoding": "gzip",
    "Content-Type": "application/x-www-form-urlencoded",
    "Expect": "100-continue",
    "X-Unity-Version": "2018.4.12f1",
    "X-GA-SV": str(int(time.time())),
    "X-GA": "v1 1",
    "ReleaseVersion": "OB55",
}

class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    MAGENTA = '\033[95m'
    RESET = "\033[0m"

def _log(level: str, text: str, color: str):
    try:
        print(f"{color}{text}{Colors.RESET}")
    except Exception:
        try:
            print(text.encode("ascii", errors="replace").decode("ascii"))
        except Exception:
            pass
    try:
        from dashboard.bridge import bot_state
        bot_state.log(text, level)
    except Exception:
        pass

def _log_normal(text: str, color: str):
    # Console only (no dashboard fan-out).
    try:
        print(f"{color}{text}{Colors.RESET}")
    except Exception:
        try:
            print(text.encode("ascii", errors="replace").decode("ascii"))
        except Exception:
            pass

print_colored = _log_normal

def log_ok(text: str):
    _log("success", text, Colors.GREEN)

def log_err(text: str):
    _log("error", text, Colors.RED)

async def get_randomized_interval(range_min: float, range_max: float) -> float:
    """Return a randomized delay in seconds, normalizing reversed bounds."""
    low = float(range_min)
    high = float(range_max)
    if low > high:
        low, high = high, low
    return random.uniform(low, high)
    
def log_warn(text: str):
    _log("warning", text, Colors.YELLOW)

def log_info(text: str):
    _log("info", text, Colors.CYAN)

def load_bot_settings() -> dict:
    defaults = {
        "max_stack_lw": DEFAULT_MAX_STACK_LW,
        "start_match_interval": START_MATCH_INTERVAL,
        "new_match_delay": NEW_MATCH_DELAY,
        "lw_hold_seconds": LW_HOLD_SECONDS,
        "exp_refresh_interval": EXP_REFRESH_INTERVAL,
        "token_cache_ttl": TOKEN_CACHE_TTL,
        "homer_equip_before_match": True,
    }
    path = BOT_SETTINGS_FILE
    if not os.path.exists(path):
        path = "bot_settings.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                defaults.update(data)
        except Exception:
            pass
    return defaults

def apply_bot_settings(settings=None):
    global MAX_STACK_LW, START_MATCH_INTERVAL, NEW_MATCH_DELAY
    global LW_HOLD_SECONDS, EXP_REFRESH_INTERVAL
    global TOKEN_CACHE_TTL, HOMER_EQUIP_BEFORE_MATCH
    s = settings if settings is not None else load_bot_settings()
    try:
        MAX_STACK_LW = max(1, int(s.get("max_stack_lw", DEFAULT_MAX_STACK_LW)))
    except Exception:
        MAX_STACK_LW = DEFAULT_MAX_STACK_LW
    try:
        START_MATCH_INTERVAL = float(s.get("start_match_interval", START_MATCH_INTERVAL))
    except Exception:
        pass
    try:
        NEW_MATCH_DELAY = float(s.get("new_match_delay", NEW_MATCH_DELAY))
    except Exception:
        pass
    try:
        LW_HOLD_SECONDS = max(30.0, float(s.get("lw_hold_seconds", LW_HOLD_SECONDS)))
    except Exception:
        pass
    try:
        EXP_REFRESH_INTERVAL = float(s.get("exp_refresh_interval", 15.0))
    except Exception:
        pass
    try:
        TOKEN_CACHE_TTL = int(s.get("token_cache_ttl", TOKEN_CACHE_TTL))
    except Exception:
        pass
    HOMER_EQUIP_BEFORE_MATCH = bool(s.get("homer_equip_before_match", True))

_settings_last_reload = 0.0


def max_stack_lw() -> int:
    # Throttled settings reload: dashboard tuning applies live without
    # re-reading the settings file on every call.
    global _settings_last_reload
    now = time.time()
    if now - _settings_last_reload > 5.0:
        _settings_last_reload = now
        try:
            apply_bot_settings()
        except Exception:
            pass
    return MAX_STACK_LW

def resolve_region(*candidates):
    for r in candidates:
        if r is None:
            continue
        s = str(r).strip().upper()
        if s:
            return s
    return ""


REGION_TO_COUNTRY = {
    "IND": "IN",
    "BR": "BR",
    "SG": "SG",
    "BD": "BD",
    "TH": "TH",
    "VN": "VN",
    "ID": "ID",
    "TW": "TW",
    "ME": "AE",
    "SAC": "CO",
    "NA": "US",
    "US": "US",
    "RU": "RU",
    "EU": "DE",
    "PK": "PK",
}

def region_to_country(region) -> str:
    reg = resolve_region(region)
    if not reg:
        return ""
    if reg in REGION_TO_COUNTRY:
        return REGION_TO_COUNTRY[reg]
    if len(reg) == 2:
        return reg
    return reg[:2]

def region_ka_prefix(region):
    reg = resolve_region(region)
    if reg == "BD":
        return "0219"
    if reg == "IND":
        return "0214"
    if reg == "SG":
        return "0207"
    return "0215"

def region_startmatch_prefix(region):
    reg = resolve_region(region)
    if reg == "IND":
        return "031400"
    if reg == "BD":
        return "031900"
    return "031500"

def region_tcp_online_prefix(region):
    reg = resolve_region(region)
    if reg == "BD":
        return "7119"
    if reg == "IND":
        return "7114"
    if reg == "SG":
        return "7107"
    return "7115"

def region_tcp_other_prefix(region):
    reg = resolve_region(region)
    if reg == "BD":
        return "9219"
    if reg == "IND":
        return "9214"
    if reg == "SG":
        return "9207"
    return "9215"


def gateway_region(addrs, account_region=""):
    """Pick the transport region from the gateway we were actually handed.

    The matchmaking backend can hand an IND account a global gateway (or the
    other way round); the TCP/UDP frame prefixes are a property of the
    gateway, not of the account, so trust the address first.
    """
    host = str(addrs or "").split(":")[0].strip().lower()
    if host:
        ip = None
        try:
            socket.inet_aton(host)
            ip = host
        except OSError:
            pass
        if "freefireind" in host or (ip and (ip.startswith("148.222.") or ip.startswith("202.81."))):
            return "IND"
    return resolve_region(account_region)

async def resolve_host_cloudflare(hostname: str) -> str:
    if not hostname:
        return hostname

    parts = hostname.split('.')
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return hostname

    now = time.time()
    if hostname in _DNS_CACHE:
        ip, exp = _DNS_CACHE[hostname]
        if now < exp:
            return ip

    def _query_cloudflare(server_ip: str) -> Optional[str]:
        s = None
        try:
            tx_id = random.randint(1000, 65535)
            header = struct.pack(">HHHHHH", tx_id, 0x0100, 1, 0, 0, 0)
            qname = b"".join(bytes([len(part)]) + part.encode('ascii') for part in hostname.split('.')) + b"\x00"
            query_pkt = header + qname + struct.pack(">HH", 1, 1)

            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1.2)
            s.sendto(query_pkt, (server_ip, 53))
            resp, _ = s.recvfrom(1024)

            if len(resp) >= 12:
                ancount = struct.unpack(">H", resp[6:8])[0]
                if ancount > 0:
                    offset = 12 + len(qname) + 4
                    for _ in range(ancount):
                        if offset >= len(resp):
                            break
                        if (resp[offset] & 0xC0) == 0xC0:
                            offset += 2
                        else:
                            while offset < len(resp) and resp[offset] != 0:
                                offset += 1 + resp[offset]
                            offset += 1
                        if offset + 10 > len(resp):
                            break
                        rtype, rclass, ttl, rdlen = struct.unpack(">HHIH", resp[offset:offset+10])
                        offset += 10
                        if rtype == 1 and rdlen == 4 and offset + 4 <= len(resp):
                            return socket.inet_ntoa(resp[offset:offset+4])
                        offset += rdlen
        except Exception:
            pass
        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        return None

    loop = asyncio.get_running_loop()
    ip = await loop.run_in_executor(None, _query_cloudflare, CLOUDFLARE_PRIMARY_DNS)
    if not ip:
        ip = await loop.run_in_executor(None, _query_cloudflare, CLOUDFLARE_SECONDARY_DNS)
    if not ip:
        try:
            ip_info = await loop.getaddrinfo(hostname, None, family=socket.AF_INET)
            if ip_info:
                ip = ip_info[0][4][0]
        except Exception:
            ip = hostname

    if ip:
        _DNS_CACHE[hostname] = (ip, now + _DNS_CACHE_TTL)
    return ip or hostname


async def host_pinned_url(url: str) -> str:
    """Rewrite a URL's host to a Cloudflare-resolved IP.

    Some ISPs/resolvers poison Garena hostnames with dead addresses
    (e.g. 100067.connect.garena.com -> 49.44.79.236, TCP 443 refused).
    `client` runs with verify=False and every caller sets the Host header,
    so connecting to the resolved IP is equivalent and bypasses the resolver.
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if not host:
            return url
        ip = await resolve_host_cloudflare(host)
        if ip and ip != host:
            return url.replace(f"//{host}", f"//{ip}", 1)
    except Exception:
        pass
    return url




def optimize_tcp_socket(sock: socket.socket):
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
    except Exception:
        pass




def optimize_udp_socket(sock: socket.socket):
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 131072)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 131072)
        if hasattr(socket, 'SIO_UDP_CONNRESET') and os.name == 'nt':
            try:
                sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except Exception:
                pass
    except Exception:
        pass




async def get_playstore_version(package=DEFAULT_PLAY_PACKAGE, country=DEFAULT_PLAY_COUNTRY):
    if play_scraper is None:
        return None
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: play_scraper(package, lang='en', country=country)
    )
    return result.get("version")



async def version_config(region=None):
    global LAST_VERSION_SOURCE
    LAST_VERSION_SOURCE = "mirror"

    reg = resolve_region(region, FORCE_REGION) or DEFAULT_REGION
    pkg = PLAY_PACKAGE.get(reg, DEFAULT_PLAY_PACKAGE)
    country = PLAY_COUNTRY.get(reg, DEFAULT_PLAY_COUNTRY)

    # Regional listing first, then the global one, then IN MAX.
    candidates = [(pkg, country), (DEFAULT_PLAY_PACKAGE, DEFAULT_PLAY_COUNTRY), ("com.dts.freefiremax", "in")]
    seen = set()
    for c_pkg, c_country in candidates:
        if (c_pkg, c_country) in seen:
            continue
        seen.add((c_pkg, c_country))
        try:
            app_version = await get_playstore_version(c_pkg, c_country)
        except Exception:
            app_version = None
        if not app_version:
            continue

        api_url = (
            f"{MIRROR_VER_URL}?version={app_version}"
            "&lang=hi&device=android&channel=android"
            f"&appstore=googleplay&region={reg}"
            "&whitelist_version=1.3.0&whitelist_sp_version=1.0.0"
        )
        try:
            response = await client.get(api_url)
            response.raise_for_status()
            data = response.json()
            server_url = data.get("server_url")
            remote_version = data.get("remote_version")
            latest_release_version = data.get("latest_release_version")
            if server_url and remote_version and latest_release_version:
                if USE_NATIVE_LOGIN and reg in REGION_LOGIN_SERVER:
                    server_url = REGION_LOGIN_SERVER[reg]
                return latest_release_version, remote_version, server_url
            log_warn(
                f"[VERSION] mirror refused {c_pkg}/{c_country} "
                f"(version={app_version} code={data.get('code')})"
            )
        except Exception as e:
            log_warn(f"[VERSION] mirror error for {c_pkg}/{c_country}: {e}")

    LAST_VERSION_SOURCE = "fallback"
    log_warn(
        f"[VERSION] using fallback config for region {reg} "
        f"({FALLBACK_RELEASE_VERSION}/{FALLBACK_REMOTE_VERSION})"
    )
    server_url = REGION_LOGIN_SERVER[reg] if (USE_NATIVE_LOGIN and reg in REGION_LOGIN_SERVER) else FALLBACK_LOGIN_SERVER
    return FALLBACK_RELEASE_VERSION, FALLBACK_REMOTE_VERSION, server_url



# =============================================================================
# CRYPTO
# =============================================================================

async def aes_encrypt(payload, key=None, iv=None):
    key = key or AES_KEY
    iv = iv or AES_IV
    cipher = AES.new(key, AES.MODE_CBC, iv)
    if isinstance(payload, str):
        try:
            if all(c in "0123456789abcdefABCDEF" for c in payload) and len(payload) % 2 == 0:
                payload = bytes.fromhex(payload)
            else:
                payload = payload.encode()
        except Exception:
            payload = payload.encode() if isinstance(payload, str) else bytes(payload)
    return cipher.encrypt(pad(payload, AES.block_size))


# =============================================================================
# PROTO UTILS
# =============================================================================

def get_proto_field(d, key, default=None):
    if not d or not isinstance(d, dict):
        return default
    if key in d:
        val = d[key].get('data')
        return val if val is not None else default
    if str(key) in d:
        val = d[str(key)].get('data')
        return val if val is not None else default
    return default




async def parse_results(parsed_results):
    result_dict = {}
    for result in parsed_results:
        field_data = {"wire_type": result.wire_type}
        if result.wire_type == "varint":
            field_data["data"] = result.data
        elif result.wire_type == "string":
            field_data["data"] = result.data
        elif result.wire_type == "bytes":
            field_data["data"] = result.data
        elif result.wire_type == "length_delimited":
            field_data["data"] = await parse_results(result.data.results)
        result_dict[result.field] = field_data
    return result_dict

async def decode_protobuf(data):
    parsed_results = Parser().parse(data)
    parsed_results_dict = await parse_results(parsed_results)
    return json.dumps(parsed_results_dict)

async def encode_varint(number):
    if number < 0:
        raise ValueError("Number must be non-negative")
    EncodedBytes = []
    while True:
        byte = number & 0x7F
        number >>= 7
        if number:
            byte |= 0x80
        EncodedBytes.append(byte)
        if not number:
            break
    return bytes(EncodedBytes)

async def create_varint_field(FieldNumber, Value):
    FieldHeader = (FieldNumber << 3) | 0
    HeaderBytes = await encode_varint(FieldHeader)
    ValueBytes = await encode_varint(Value)
    return HeaderBytes + ValueBytes

async def create_length_delimited_field(FieldNumber, Value):
    FieldHeader = (FieldNumber << 3) | 2
    EncodedValue = Value.encode() if isinstance(Value, str) else Value
    HeaderBytes = await encode_varint(FieldHeader)
    LengthBytes = await encode_varint(len(EncodedValue))
    return HeaderBytes + LengthBytes + EncodedValue


async def create_proto_packet(Fields):
    packet = bytearray()
    for FieldNumber, Value in Fields.items():
        if isinstance(Value, dict):
            NestedPacket = await create_proto_packet(Value)
            FieldBytes = await create_length_delimited_field(FieldNumber, NestedPacket)
            packet.extend(FieldBytes)
        elif isinstance(Value, int):
            FieldBytes = await create_varint_field(FieldNumber, Value)
            packet.extend(FieldBytes)
        elif isinstance(Value, str) or isinstance(Value, bytes):
            FieldBytes = await create_length_delimited_field(FieldNumber, Value)
            packet.extend(FieldBytes)
    return bytes(packet)


def _extract_jwt_from_bytes(content: bytes) -> Optional[str]:
    if b"eyJ" not in content:
        return None
    start = content.find(b"eyJ")
    end = start
    while end < len(content) and content[end] in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.":
        end += 1
    candidate = content[start:end].decode("ascii", errors="ignore")
    if candidate.count(".") >= 2 and len(candidate) > 80:
        return candidate
    return None


def _extract_server_message(content: bytes) -> Optional[str]:
    """Pull the printable reason out of a protobuf error body (ban note, version reject)."""
    if not content:
        return None
    runs, cur = [], bytearray()
    for b in content:
        if 0x20 <= b <= 0x7E:
            cur.append(b)
        else:
            if len(cur) >= 6:
                runs.append(cur.decode("latin-1"))
            cur = bytearray()
    if len(cur) >= 6:
        runs.append(cur.decode("latin-1"))
    if not runs:
        return None
    words = [r for r in runs if " " in r] or runs
    return max(words, key=len)


def _decode_jwt_payload(jwt_token: str) -> dict:
    try:
        import base64
        parts = jwt_token.split(".")
        if len(parts) < 2:
            return {}
        pad = "=" * (-len(parts[1]) % 4)
        raw = base64.urlsafe_b64decode(parts[1] + pad)
        return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return {}


def _bytes_field(val) -> bytes:
    if val is None:
        return b""
    if isinstance(val, (bytes, bytearray)):
        return bytes(val)
    if isinstance(val, str):
        try:
            if all(c in "0123456789abcdefABCDEF" for c in val) and len(val) % 2 == 0:
                return bytes.fromhex(val)
        except Exception:
            pass
        return val.encode("utf-8", errors="replace")
    return b""


async def _generic_proto_dict(content: bytes) -> dict:
    for offset in (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 24, 32, 48, 64, 80, 96, 128):
        if offset >= len(content):
            break
        try:
            parsed = Parser().parse(content[offset:].hex())
            d = await parse_results(parsed)
            if d:
                return d
        except Exception:
            continue
    return {}


def _pick_proto_value(d: dict, *field_nums):
    for n in field_nums:
        v = get_proto_field(d, n, None)
        if v is not None and v != "" and v != 0:
            return v
    return None




# =============================================================================
# UDP HELPERS
# =============================================================================

CRC7_TABLE = bytes([
    0, 9, 18, 27, 36, 45, 54, 63, 72, 65, 90, 83, 108, 101, 126, 119,
    25, 16, 11, 2, 61, 52, 47, 38, 81, 88, 67, 74, 117, 124, 103, 110,
    50, 59, 32, 41, 22, 31, 4, 13, 122, 115, 104, 97, 94, 87, 76, 69,
    43, 34, 57, 48, 15, 6, 29, 20, 99, 106, 113, 120, 71, 78, 85, 92,
    100, 109, 118, 127, 64, 73, 82, 91, 44, 37, 62, 55, 8, 1, 26, 19,
    125, 116, 111, 102, 89, 80, 75, 66, 53, 60, 39, 46, 17, 24, 3, 10,
    86, 95, 68, 77, 114, 123, 96, 105, 30, 23, 12, 5, 58, 51, 40, 33,
    79, 70, 93, 84, 107, 98, 121, 112, 7, 14, 21, 28, 35, 42, 49, 56,
    65, 72, 83, 90, 101, 108, 119, 126, 9, 0, 27, 18, 45, 36, 63, 54,
    88, 81, 74, 67, 124, 117, 110, 103, 16, 25, 2, 11, 52, 61, 38, 47,
    115, 122, 97, 104, 87, 94, 69, 76, 59, 50, 41, 32, 31, 22, 13, 4,
    106, 99, 120, 113, 78, 71, 92, 85, 34, 43, 48, 57, 6, 15, 20, 29,
    37, 44, 55, 62, 1, 8, 19, 26, 109, 100, 127, 118, 73, 64, 91, 82,
    60, 53, 46, 39, 24, 17, 10, 3, 116, 125, 102, 111, 80, 89, 66, 75,
    23, 30, 5, 12, 51, 58, 33, 40, 95, 86, 77, 68, 123, 114, 105, 96,
    14, 7, 28, 21, 42, 35, 56, 49, 70, 79, 84, 93, 98, 107, 112, 121,
])

_DELTA = 0x9E3779B9
_ROUNDS = 16
_FIELD_SIZES = {0: 1, 1: 2, 2: 2, 3: 1, 4: 2}
_FIELD_NAMES = {0: "sendOption", 1: "cmd", 2: "orderId", 3: "flags", 4: "length"}



_ROUNDS = 16





async def has_ssan_zig(n):
    z = (n << 1) & 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while z >= 0x80:
        out.append((z & 0x7F) | 0x80)
        z >>= 7
    out.append(z)
    return bytes(out)

async def uleb_encode(n):
    if n < 0:
        n &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            break
    return bytes(out)

async def tea_enc(v0, v1, k0, k1, k2, k3):
    s = 0
    for _ in range(_ROUNDS):
        s = (s + _DELTA) & 0xFFFFFFFF
        v0 = (v0 + (((((v1 << 4) & 0xFFFFFFFF) + k0) & 0xFFFFFFFF ^
                      ((v1 + s) & 0xFFFFFFFF) ^
                      (((v1 >> 5) + k1) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        v1 = (v1 + (((((v0 << 4) & 0xFFFFFFFF) + k2) & 0xFFFFFFFF ^
                      ((v0 + s) & 0xFFFFFFFF) ^
                      (((v0 >> 5) + k3) & 0xFFFFFFFF)))) & 0xFFFFFFFF
    return v0, v1

async def tea_dec(v0, v1, k0, k1, k2, k3):
    s = (_DELTA * _ROUNDS) & 0xFFFFFFFF
    for _ in range(_ROUNDS):
        v1 = (v1 - (((((v0 << 4) & 0xFFFFFFFF) + k2) & 0xFFFFFFFF ^
                      ((v0 + s) & 0xFFFFFFFF) ^
                      (((v0 >> 5) + k3) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        v0 = (v0 - (((((v1 << 4) & 0xFFFFFFFF) + k0) & 0xFFFFFFFF ^
                      ((v1 + s) & 0xFFFFFFFF) ^
                      (((v1 >> 5) + k1) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        s = (s - _DELTA) & 0xFFFFFFFF
    return v0, v1

async def tea_cbc_encrypt(padded, key_bytes):
    k0, k1, k2, k3 = (struct.unpack_from("<I", key_bytes, o)[0] for o in (0, 4, 8, 12))
    out = bytearray(len(padded))
    prev_cipher = bytearray(8)
    prev_intermediate = bytearray(8)
    for i in range(0, len(padded), 8):
        xored = bytearray(8)
        for j in range(8):
            xored[j] = padded[i + j] ^ prev_cipher[j]
        e0, e1 = await tea_enc(
            struct.unpack_from("<I", xored, 0)[0],
            struct.unpack_from("<I", xored, 4)[0],
            k0, k1, k2, k3,
        )
        enc = bytearray(8)
        struct.pack_into("<I", enc, 0, e0)
        struct.pack_into("<I", enc, 4, e1)
        for j in range(8):
            out[i + j] = enc[j] ^ prev_intermediate[j]
        prev_cipher[:] = out[i:i + 8]
        prev_intermediate[:] = xored
    return bytes(out)

async def build_padded(content):
    pad_len = (8 - (len(content) + 10) % 8) % 8
    return bytes([pad_len, 0, 0]) + b"\x00" * pad_len + content + b"\x00" * 7

async def encode_header(layout, send_option, cmd, order_id, flags, length, k, v80):
    out = bytearray()
    for code in layout:
        value = {0: send_option, 1: cmd, 2: order_id, 3: flags, 4: length}[code]
        if _FIELD_SIZES[code] == 1:
            out.append((value & 0xFF) ^ k)
        else:
            v = ((value & 0xFFFF) ^ v80) & 0xFFFF
            out.append(v & 0xFF)
            out.append((v >> 8) & 0xFF)
    return bytes(out)

async def crc7_buff(crc, buf):
    c = crc & 0x7F
    for b in buf:
        c = CRC7_TABLE[((2 * (c & 0xFF)) ^ (b & 0xFF)) & 0xFF] & 0x7F
    return c & 0x7F

async def sv_frame(msg_key, layout, send_option, cmd, order_id, flags, content, key, encrypted=True):
    k = key[0]
    v80 = ((k << 8) | k) & 0xFFFF
    body = await tea_cbc_encrypt(await build_padded(content), key) if encrypted else content
    hdr = bytearray([msg_key, 0]) + await encode_header(layout, send_option, cmd, order_id, flags, len(body), k, v80)
    packet = bytearray(hdr + body)
    packet[1] = await crc7_buff(0, bytes(packet[2:])) & 0x7F
    return bytes(packet)

DOTNET_EPOCH_TICKS = 621355968000000000  # ticks at 1970-01-01 UTC

# Stream A values
CSOVERSEA_HOST_BLOCK = bytes.fromhex(
    "ca0163736f7665727365612e7374726f6e67686f6c642e66726565666972656d6f62696c652e636f6d"
    "3b302e302e302e303b33342e3132362e37362e34353b33342e38372e3137372e31343b33342e38372e"
    "3137302e3233303b33352e3138352e3138332e3537"
)
# 33-byte flag area from stream A (set bytes at offsets 6, 19, 25, 30=03, 31)
CSOVERSEA_FLAGS = bytes([0]*6 + [1] + [0]*12 + [1] + [0]*5 + [1] + [0]*4 + [3, 1, 0])



async def dotnet_ticks_zigzag_uleb():
    """Current UTC time as .NET ticks, zigzag-encoded, then uleb128."""
    ticks = time.time_ns() // 100 + DOTNET_EPOCH_TICKS
    return await uleb_encode(ticks << 1)  # zigzag of a positive int is n << 1


async def build_match_startup_packets(token, udp_key, udp_mask, account_id, block_val,
                                      server_ip="", region="BD", client_version=CLIENT_VERSION,
                                      client_version_code=CLIENT_VERSION_CODE, access_token="",
                                      mode_id=LONE_WOLF_MODE_ID, map_id=LONE_WOLF_MAP_ID):
    token = token.strip()
    udp_key = bytes.fromhex(udp_key)
    udp_mask = [int(ch) for ch in str(udp_mask).strip()]

    prepare_jwt = token[:660] if len(token) > 660 else token
    post_jwt = token[660:] if len(token) > 660 else ""
    encoded_prepare_jwt = prepare_jwt.encode()
    encoded_post_jwt = post_jwt.encode()

    garena420 = await has_ssan_zig(len(encoded_prepare_jwt)) + encoded_prepare_jwt

    reg = str(region).upper() if region else "BD"

    mid = bytes.fromhex('0000000000000102030101')            # fixed (was ...0100010203...)
    mid += await has_ssan_zig(len(reg)) + reg.encode()
    mid += bytes.fromhex('0001010001000004')                  # fixed (was 0001030003000004)
    mid += await has_ssan_zig(len(client_version)) + client_version.encode()
    mid += await has_ssan_zig(len(client_version_code)) + client_version_code.encode()
    mid += CSOVERSEA_HOST_BLOCK + CSOVERSEA_FLAGS
    mid += await dotnet_ticks_zigzag_uleb()                   # live timestamp
    mid += bytes.fromhex('0200')

    clean_ip = server_ip.split(':')[0] if server_ip else "0.0.0.0"
    mid += await has_ssan_zig(len(clean_ip)) + clean_ip.encode()

    clean_acc_tok = access_token.strip() if access_token else ""
    if clean_acc_tok:
        mid += await has_ssan_zig(len(clean_acc_tok)) + clean_acc_tok.encode()

    mid += await has_ssan_zig(len(encoded_post_jwt)) + encoded_post_jwt

    tg_garena420 = (
        await uleb_encode(int(account_id)) +
        await uleb_encode(int(block_val)) +
        await uleb_encode(1) +
        await uleb_encode(int(mode_id)) +
        await uleb_encode(int(block_val)) +
        await uleb_encode(int(map_id)) +
        mid
    )

    prepare = await sv_frame(0x5E, udp_mask, 2, 447, 0, 1, garena420, udp_key)
    post = await sv_frame(0x5A, udp_mask, 2, 448, 1, 1, tg_garena420, udp_key)
    return prepare.hex(), post.hex()

async def produce_xor_key(secret_key):
    k = secret_key[0] if secret_key and len(secret_key) > 0 else 10
    return k, ((k << 8) | k) & 0xFFFF

async def parse_layout(layout):
    if isinstance(layout, str):
        return [int(ch) for ch in layout.strip()]
    return list(layout)

async def tea_cbc_decrypt(body, key_bytes):
    k0, k1, k2, k3 = (struct.unpack_from("<I", key_bytes, o)[0] for o in (0, 4, 8, 12))
    out = bytearray(len(body))
    prev_intermediate = bytearray(8)
    prev_cipher = bytearray(8)
    xored = bytearray(8)
    dec = bytearray(8)
    for i in range(0, len(body), 8):
        for j in range(8):
            xored[j] = body[i + j] ^ prev_intermediate[j]
        d0, d1 = await tea_dec(
            struct.unpack_from("<I", xored, 0)[0],
            struct.unpack_from("<I", xored, 4)[0],
            k0, k1, k2, k3
        )
        struct.pack_into("<I", dec, 0, d0)
        struct.pack_into("<I", dec, 4, d1)
        for j in range(8):
            out[i + j] = dec[j] ^ prev_cipher[j]
        prev_cipher[:] = body[i:i + 8]
        prev_intermediate[:] = dec
    return bytes(out)

async def build_hello_packet(text, key, layout):
    data = text.encode("utf-8")
    if len(data) > 25:
        raise ValueError(f"Text is too long ({len(data)} bytes)")
    content = b"\x10\x00\x00\x00" + data + b"\x00" * (29 - 4 - len(data))
    k, v80 = await produce_xor_key(key)
    layout = await parse_layout(layout)
    padded = await build_padded(content)
    enc_body = await tea_cbc_encrypt(padded, key)
    header_bytes = await encode_header(layout, 1, 1, 0, 1, len(enc_body), k, v80)
    packet = bytearray([0x63, 0x00]) + header_bytes + enc_body
    packet[1] = await crc7_buff(0, packet[2:]) & 0x7F
    return bytes(packet).hex()

async def classify(frame):
    cmd = frame["cmd"]
    msg_name = MESSAGE_ID_TO_NAME.get(cmd, f"UNKNOWN_{cmd}")
    if msg_name == "UDP_HELLO":
        return "HELLO"
    if msg_name == "UDP_ACK":
        return "ACK"
    if msg_name == "UDP_PING":
        return "PING"
    if msg_name == "RUDP_JOIN_MATCH":
        return "JOIN_MATCH"
    if msg_name.startswith("RUDP_"):
        return msg_name
    if msg_name.startswith("UDP_"):
        return msg_name
    return "DATA"

async def build_packet(msg_key, layout, send_option, cmd, order_id, flags, content, key, encrypted=True):
    k = key[0]
    v80 = ((k << 8) | k) & 0xFFFF
    body = await tea_cbc_encrypt(await build_padded(content), key) if encrypted else content
    hdr = bytearray([msg_key, 0])
    for code in layout:
        value = {0: send_option, 1: cmd, 2: order_id, 3: flags, 4: len(body)}[code]
        if _FIELD_SIZES[code] == 1:
            hdr.append((value & 0xFF) ^ k)
        else:
            v = ((value & 0xFFFF) ^ v80) & 0xFFFF
            hdr.append(v & 0xFF)
            hdr.append((v >> 8) & 0xFF)
    packet = bytearray(hdr + body)
    packet[1] = await crc7_buff(0, bytes(packet[2:])) & 0x7F
    return bytes(packet)

async def layouts_from_mask(mask):
    ru = [int(c) for c in str(mask).strip()]
    nr = [c for c in ru if c != 2]
    return ru, nr

async def reply_for(frame, key, mask, ack_key=0x68, ping_key=0x6D, hello_key=0x5B, ack_style="short"):
    ru, nr = await layouts_from_mask(mask)
    typ = await classify(frame)
    if typ == "HELLO":
        if ack_style == "echo":
            content = frame["content"] if frame["content"] else b"\x10\x00\x00\x00"
            return typ, await build_packet(hello_key, nr, 1, 1, None, 1, content, key)
        return typ, await build_packet(ack_key, nr, 0, 2, None, 1, b"\x01\x00", key)
    if typ == "ACK":
        content = frame["content"] if frame["content"] else b"\x01\x00"
        return typ, await build_packet(ack_key, nr, 0, 2, None, 1, content, key)
    if typ == "PING":
        c = frame["content"]
        counter = c[:4] if len(c) >= 4 else c
        return typ, await build_packet(ping_key, nr, 0, 3, None, 0, counter + b"\x00\x00\x00", key, encrypted=False)
    if typ == "JOIN_MATCH":
        return typ, await build_packet(ack_key, nr, 0, 2, None, 1, b"\x02\x00", key)
    return typ, None

async def keepalive_ping(sock, ip, port, key_bytes, mask, stop_event):
    nr = (await layouts_from_mask(mask))[1]
    ping_keys = [0x66, 0x6D, 0x69, 0x6C, 0x6B, 0x6E, 0x6F, 0x70]
    loop = asyncio.get_running_loop()
    i = 0
    while not stop_event.is_set():
        pk = ping_keys[i % len(ping_keys)]
        counter = int(time.time() * 1000) & 0xFFFFFFFF
        pkt = await build_packet(pk, nr, 0, 3, None, 0, struct.pack("<I", counter) + b"\x00\x00\x00", key_bytes, encrypted=False)
        try:
            await loop.sock_sendto(sock, pkt, (ip, port))
        except Exception:
            pass
        i += 1
        interval = await get_randomized_interval(2.5, 3.8)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass

async def try_header(buf, layout, k, v80):
    off = 2
    out = {}
    for code in layout:
        size = _FIELD_SIZES[code]
        if off + size > len(buf):
            return None
        out[_FIELD_NAMES[code]] = (buf[off] ^ k) if size == 1 else ((buf[off] | (buf[off + 1] << 8)) ^ v80) & 0xFFFF
        off += size
    out["headerLen"] = off
    return out

async def oicq_unpad(padded):
    if not padded or len(padded) < 8:
        return None
    if not all(padded[-1 - i] == 0 for i in range(7)):
        return None
    pad_len = padded[0] & 0x07
    s = 3 + pad_len
    e = len(padded) - 7
    return padded[s:e] if s < e else b""

async def decode_packet(packet, key, mask=None):
    data = bytes(packet) if isinstance(packet, bytes) else bytes.fromhex(packet)
    if len(data) < 8:
        return None
    k = key[0]
    v80 = ((k << 8) | k) & 0xFFFF
    crc_ok = (data[1] & 0x7F) == await crc7_buff(0, data[2:])
    candidates = []
    if not mask:
        return None
    ru, nr = await layouts_from_mask(mask)
    layouts = [("RUDP", ru), ("nonRUDP", nr)]
    for kind, layout in layouts:
        f = await try_header(data, layout, k, v80)
        if not f:
            continue
        if f["flags"] > 7 or f["sendOption"] > 7:
            continue
        if f["length"] != len(data) - f["headerLen"]:
            continue
        body = data[f["headerLen"]:f["headerLen"] + f["length"]]
        content = None
        padded = None
        if f["flags"] & 1:
            if len(body) < 8 or len(body) % 8 != 0:
                continue
            padded = await tea_cbc_decrypt(body, key)
            content = await oicq_unpad(padded)
            if content is None:
                continue
        else:
            content = body
        score = (1 if crc_ok else 0) + (1 if content is not None else 0)
        candidates.append({
            "kind": kind, "layout": layout, "headerLen": f["headerLen"],
            "msgKey": data[0], "cmd": f["cmd"], "flags": f["flags"],
            "sendOption": f["sendOption"], "orderId": f.get("orderId"),
            "length": f["length"], "content": content, "crcOk": crc_ok,
            "padded": padded, "score": score, "total": len(data),
        })
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["kind"] == "RUDP" or c["kind"] == "nonRUDP", c["score"]), reverse=True)
    return candidates[0]




# =============================================================================
# LW MOVEMENT (ground only)

DATA_DIR = "data"

DATA_DIR = "data"

# ── Movement constants ──────────────────────────────────────────────────────
DEFAULT_GAME_MODE_ID    = LONE_WOLF_MODE_ID
DEFAULT_GAME_MAP_ID     = LONE_WOLF_MAP_ID
# Ground movement only (LW) — timing aligned with appflow, values from appcon
MOVEMENT_TICK_MS        = 100
MOVEMENT_SPEED_MIN      = 0.96
MOVEMENT_SPEED_MAX      = 1.02
MOVEMENT_UPDATE_SPEED_EVERY = 4.0
PLAYER_STATE_MAP = {"idle": 0, "walk": 1, "run": 1, "sprint": 1, "jump": 2, "crouch": 3, "prone": 4}
MOVE_STATE_MAP   = {"idle": 0, "walk": 1, "run": 2, "sprint": 3, "jump": 4, "crouch": 1, "prone": 1}

# ── Protobuf / ULEB helpers ──────────────────────────────────────────────────
def uleb_encode_sync(n: int) -> bytes:
    try:
        n = int(n)
    except Exception:
        n = 0
    if n < 0:
        n &= 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            break
    return bytes(out)


async def _udp_sendto(loop, sock, data: bytes, addr):
    try:
        return sock.sendto(data, addr)
    except (BlockingIOError, InterruptedError):
        pass
    try:
        return await loop.sock_sendto(sock, data, addr)
    except Exception:
        fut = loop.create_future()
        fd = sock.fileno()

        def _on_writable():
            if fut.done():
                return
            try:
                n = sock.sendto(data, addr)
            except (BlockingIOError, InterruptedError):
                return
            except Exception as exc:
                try:
                    loop.remove_writer(fd)
                except Exception:
                    pass
                fut.set_exception(exc)
            else:
                try:
                    loop.remove_writer(fd)
                except Exception:
                    pass
                fut.set_result(n)

        loop.add_writer(fd, _on_writable)
        try:
            return await fut
        finally:
            try:
                loop.remove_writer(fd)
            except Exception:
                pass


def _f32_bits(val: float) -> int:
    return struct.unpack("<I", struct.pack("<f", float(val)))[0]


async def zigzag_encode_signed(n: int) -> bytes:
    try:
        n = int(n)
    except Exception:
        n = 0
    zz = (n << 1) ^ (n >> 63)
    if zz < 0:
        zz = -zz
    zz &= 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while True:
        b = zz & 0x7F
        zz >>= 7
        if zz:
            b |= 0x80
        out.append(b)
        if not zz:
            break
    return bytes(out)


# ── varint helpers for packet parsing ───────────────────────────────────────
#  movement packet builder (CMD 2001)
# ═══════════════════════════════════════════════════════════════════════════════
async def build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z,
                                     tick, counter, move_state, account_uid,
                                     room_code=None, slot_id=1, phase="arena",
                                     angle=0.0, speed=0.0, vel_y=0.0, s1=0, s2=2,
                                     player_match_id=1):
    if room_code:
        _, nr = await layouts_from_mask(room_code)
    else:
        nr = [0, 1, 4, 3]

    pid_val = int(player_match_id) & 0x7F if player_match_id else 1
    body = bytearray(await uleb_encode((1 << 24) | pid_val))

    body += await zigzag_encode_signed(int(round(x)))
    body += await zigzag_encode_signed(int(round(y)))
    body += await zigzag_encode_signed(int(round(z)))

    ca = math.cos(angle)
    sa = math.sin(angle)
    fx = max(-100, min(100, int(round(100.0 * ca))))
    fy = -24 if s1 == 2 else 0
    fz = max(-100, min(100, int(round(100.0 * sa))))
    body += await zigzag_encode_signed(fx)
    body += await zigzag_encode_signed(fy)
    body += await zigzag_encode_signed(fz)

    if s1 in (4, 2):
        mx, mz = 0, 100
    elif s1 == 1 and s2 == 11:
        mx, mz = 0, 0
    elif s1 == 0 and s2 == 2:
        if speed > 1.0:
            mx, mz = fx, fz
        else:
            mx, mz = 0, 0
    elif speed > 1.0:
        mx, mz = fx, fz
    else:
        mx, mz = 0, 0
    body += await zigzag_encode_signed(mx)
    body += await zigzag_encode_signed(mz)

    vx = int(round((speed * ca) / 10.0))
    vy = int(round(vel_y / 10.0))
    vz = int(round((speed * sa) / 10.0))
    body += await zigzag_encode_signed(vx)
    body += await zigzag_encode_signed(vy)
    body += await zigzag_encode_signed(vz)

    body += await uleb_encode(int(s1))
    body += await uleb_encode(int(s2))

    pitch = -0.15 if (s1 == 0 and s2 == 2) else -0.25
    cp = math.cos(pitch); sp = math.sin(pitch)
    cam_x = ca * cp; cam_y = sp; cam_z = sa * cp
    body += await uleb_encode(_f32_bits(cam_x))
    body += await uleb_encode(_f32_bits(cam_y))
    body += await uleb_encode(_f32_bits(cam_z))

    body += b"\x00\x00"
    body += struct.pack("<I", int(tick))
    body += await uleb_encode(int(counter) & 0xFFFFFFFF)
    return await build_packet(msg_key, nr, 0, 2001, None, 0, bytes(body), key_bytes, encrypted=False)


def _mc_dec_v(b, off):
    res = 0; s = 0; cur = off
    while cur < len(b):
        bt = b[cur]; res |= (bt & 0x7F) << s; cur += 1; s += 7
        if not (bt & 0x80):
            break
    return res, cur


def _mc_dec_zz(n):
    return (n >> 1) ^ -(n & 1)


class MovementController:
    def __init__(
        self,
        account_id,
        udp_sock=None,
        udp_server=None,
        udp_key_bytes=None,
        match_code=None,
        slot_id=None,
        initial_rudp_order_id=2,
    ):
        self.account_id      = int(account_id) if str(account_id).isdigit() else 0
        self.account_id_uleb = uleb_encode_sync(self.account_id)
        self.udp_sock    = udp_sock
        self.udp_server  = udp_server
        self.udp_key     = udp_key_bytes
        self.match_code  = match_code


        # handshake gate: startup beacons only after prepare+post is sent
        self._handshake_done = False

        if slot_id is not None:
            self.slot_id = max(1, min(4, int(slot_id)))
        else:
            self.slot_id = 1

        self.player_match_id = None
        self.phase = "ground"

        self.spawn_x = 5751; self.spawn_y = 1400160; self.spawn_z = 1650
        self.ground_y = 1400160
        self.x = float(self.spawn_x)
        self.y = float(self.spawn_y)
        self.z = float(self.spawn_z)
        self.has_real_coords       = False
        self.has_real_ground_coords = False

        self.tick = 18
        self.angle   = ((self.slot_id - 1) * (math.pi / 2.0)) + random.uniform(-0.3, 0.3)
        self.state   = "sprint"
        self.cur_speed = 0.0; self.vel_y = 0.0
        self.pkt_s1 = 0; self.pkt_s2 = 2
        self.speed_mul = random.uniform(MOVEMENT_SPEED_MIN, MOVEMENT_SPEED_MAX)
        self._msg_keys  = [0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6a, 0x6b, 0x6c]
        self._key_idx   = 0

        self._stop_evt   = asyncio.Event()
        self._clock_stop = asyncio.Event()
        self._task       = None
        self._clock_task = None
        self._last_decision    = 0.0
        self._last_speed_change = 0.0
        self._last_jump_t      = 0.0
        self._jump_start_t     = 0.0
        self._rudp_order_id = int(initial_rudp_order_id)
        self._startup_actions_sent = False
        self._ground_land_t = None
        self._start_time = 0.0
        self._last_clock_echo_t = 0.0
        self._last_echo_spawn_t = 0.0
        self._stuck_ref_pos = None
        self._stuck_ref_t = 0.0

    # ── handshake gate ──────────────────────────────────────────────────────
    def notify_handshake_complete(self):
        """Called once prepare+post is sent."""
        self._handshake_done = True

    async def send_rudp(self, cmd: int, content: bytes, msg_key: int = None, flags: int = 1, send_opt: int = 2):
        if not self.udp_sock or not self.udp_server or not self.udp_key:
            return False
        # CMD 106 / 107 are inbound-only — never send
        if cmd in (106, 107):
            return False
        try:
            loop = asyncio.get_running_loop()
            ru, _ = await layouts_from_mask(self.match_code)
            oid = self._rudp_order_id
            self._rudp_order_id = (self._rudp_order_id + 1) & 0xFFFF
            if msg_key is None or msg_key == 0x68:
                # 106 and 107 intentionally absent
                cmd_keys = {
                    1026: 0x5A, 1079: 0x5F, 899: 0x60,
                    105:  0x61, 108:  0x62, 133:  0x5D, 134: 0x5C,
                    104:  0x5D, 139:  0x68, 953: 0x68,
                    221:  0x68, 335:  0x68, 382:  0x68, 310: 0x68,
                    111:  0x68,
                }
                msg_key = cmd_keys.get(cmd, 0x68)
            pkt = await build_packet(msg_key, ru, send_opt, cmd, oid, flags, content, self.udp_key, encrypted=True)
            await _udp_sendto(loop, self.udp_sock, pkt, self.udp_server)
            return True
        except Exception:
            return False

    async def send_startup_beacons(self):
        """
        Sends 105 and 108 exactly ONCE as match init actions.
        Gated on _handshake_done to prevent sending before prepare+post.
        """
        if self._startup_actions_sent:
            return
        if not self._handshake_done:
            return
        self._startup_actions_sent = True
        try:
            sys_info_path = os.path.join(DATA_DIR, 'gin_1026_startup.bin')
            if os.path.exists(sys_info_path):
                with open(sys_info_path, 'rb') as f:
                    sys_data = f.read()
                await self.send_rudp(1026, sys_data)
                await asyncio.sleep(0.1)

            gin_path = os.path.join(DATA_DIR, 'gin_1079_startup.bin')
            if os.path.exists(gin_path):
                with open(gin_path, 'rb') as f:
                    gin_data = f.read()
                await self.send_rudp(1079, gin_data)
                await asyncio.sleep(0.1)

            # CMD 105 — sent exactly once here
            await self.send_rudp(105, self.account_id_uleb + bytes.fromhex('0eb048796b82b94c8325216a42aa2088784061'))
            await asyncio.sleep(0.1)

            # CMD 108 — sent exactly once here
            await self.send_rudp(108, bytes.fromhex('e112611132abdef8ed0e7e8053c33ca2'))
        except Exception as e:
            log_warn(f"send_startup_beacons error: {e}")

    async def _echo_clock_sync(self, raw_tick_bytes: bytes):
        if not self.udp_sock or not self.udp_server or not self.udp_key:
            return
        try:
            loop = asyncio.get_running_loop()
            _, nr = await layouts_from_mask(self.match_code)
            mk = self._msg_keys[self._key_idx % len(self._msg_keys)]
            pkt = await build_packet(mk, nr, 0, 2000, None, 0, raw_tick_bytes, self.udp_key, encrypted=False)
            await _udp_sendto(loop, self.udp_sock, pkt, self.udp_server)
            self._last_clock_echo_t = time.time()
        except Exception:
            pass

    # ── server frame dispatcher ───────────────────────────────────────────────
    def handle_server_frame(self, frame):
        """
        Feed every incoming UDP frame here.
        Dispatches CMD 2000 (clock sync) and CMD 2001 (own position)
        for LW ground movement.
        """
        cmd     = frame.get("cmd")
        content = frame.get("content")
        if not content:
            return
        try:

            # ── CMD 2000: clock sync ─────────────────────────────────────
            if cmd == 2000 and len(content) >= 1:
                _, end_off = _mc_dec_v(content, 0)
                if end_off >= 1:
                    now = time.time()
                    if now - self._last_echo_spawn_t >= 0.4:
                        self._last_echo_spawn_t = now
                        asyncio.create_task(self._echo_clock_sync(bytes(content[:end_off])))
                return

            # ── CMD 2001: our own position ─────────────────────────────────
            if cmd == 2001 and len(content) >= 15 and content[:2] == b"\x00\x02" and 1 <= content[2] <= 64:
                pid = content[2]
                if self.player_match_id is None:
                    self.player_match_id = pid
                elif pid != self.player_match_id:
                    return

                cur = 3
                vx, cur = _mc_dec_v(content, cur)
                vy, cur = _mc_dec_v(content, cur)
                vz, cur = _mc_dec_v(content, cur)
                zx, zy, zz = _mc_dec_zz(vx), _mc_dec_zz(vy), _mc_dec_zz(vz)

                s1, s2 = 0, 0
                try:
                    for _ in range(8):
                        _, cur = _mc_dec_v(content, cur)
                    s1, cur = _mc_dec_v(content, cur)
                    s2, cur = _mc_dec_v(content, cur)
                except Exception:
                    pass

                now = time.time()

                # lobby
                if zy >= 800000:
                    self.phase = "ground"
                    self.ground_y = zy
                    self.spawn_x  = zx; self.spawn_y = zy; self.spawn_z = zz
                    self.x = float(zx); self.y = float(zy); self.z = float(zz)
                    if not self.has_real_coords:
                        self.has_real_coords = True
                    # startup beacons gated on handshake completion
                    if not self._startup_actions_sent and self._handshake_done:
                        asyncio.create_task(self.send_startup_beacons())
                    return

                # ground
                if zy < 250000:
                    if not self.has_real_ground_coords:
                        self.phase = "ground"
                        self.spawn_x = zx; self.spawn_y = zy; self.spawn_z = zz
                        self.ground_y = zy
                        self.x = float(zx); self.y = float(zy); self.z = float(zz)
                        self.has_real_coords = True
                        self.has_real_ground_coords = True
                        self._ground_land_t = now
                        self._stuck_ref_pos = (zx, zy, zz)
                        self._stuck_ref_t   = now
                        self.angle  = ((self.slot_id - 1) * (math.pi / 2.0)) + random.uniform(-0.3, 0.3)
                        self.state  = "sprint"
                        return

                    self.phase = "ground"
                    is_jumping = (self.state == "jump" and (now - self._jump_start_t) < 0.85)
                    if s1 == 0 and not is_jumping:
                        self.ground_y = zy
                        self.y = float(zy)

                    err_xz = math.hypot(self.x - zx, self.z - zz)
                    if err_xz > 1500.0:
                        self.x = float(zx); self.z = float(zz)
                        if not is_jumping:
                            self.ground_y = zy; self.y = float(zy)

                    if self._stuck_ref_pos is None:
                        self._stuck_ref_pos = (zx, zy, zz)
                        self._stuck_ref_t   = now
                    elif (now - self._stuck_ref_t) >= 0.35:
                        moved_xz = math.hypot(zx - self._stuck_ref_pos[0], zz - self._stuck_ref_pos[2])
                        self._stuck_ref_pos = (zx, zy, zz)
                        self._stuck_ref_t   = now
                        if moved_xz < 120.0 and self.cur_speed > 1000.0:
                            self.x = float(zx); self.z = float(zz)
                            self.ground_y = zy
                            self.angle = (self.angle + random.choice([-1.57, 1.57]) + random.uniform(-0.25, 0.25)) % (2.0 * math.pi)
                            self._jump_start_t = now
                            self._last_jump_t  = now
                            self.state = "jump"
                    return
        except Exception:
            pass

    # ── position step ─────────────────────────────────────────────────────────
    def _pick_state(self) -> str:
        r = random.random()
        if r < 0.50: return "sprint"
        if r < 0.70: return "run"
        if r < 0.85: return "crouch"
        return "walk"

    def _step_position(self, dt: float):
        """LW ground movement: jump arc + walk states + center wander."""
        now = time.time()
        self.tick = 18

        if self.state == "jump":
            j_prog = (now - self._jump_start_t) / 0.85
            if 0.0 <= j_prog < 1.0:
                self.y     = float(self.ground_y) + 698.0 * 4.0 * j_prog * (1.0 - j_prog)
                self.vel_y = 3285.0 * (1.0 - 2.0 * j_prog)
                self.pkt_s1 = 1; self.pkt_s2 = 11; speed = 5550.0
            else:
                self.y = float(self.ground_y); self.vel_y = -3300.0; self.pkt_s1 = 1; self.pkt_s2 = 0; self.state = "sprint"; speed = 5600.0
        else:
            self.y = float(self.ground_y); self.vel_y = 0.0
            if   self.state == "idle":   speed = 0.0;                    self.pkt_s1 = 0; self.pkt_s2 = 0
            elif self.state == "walk":   speed = 3400.0 * self.speed_mul; self.pkt_s1 = 0; self.pkt_s2 = 1
            elif self.state == "crouch": speed = 2600.0 * self.speed_mul; self.pkt_s1 = 0; self.pkt_s2 = 2
            else:                        speed = 5600.0 * self.speed_mul; self.pkt_s1 = 1; self.pkt_s2 = 11; self.state = "sprint"

        self.cur_speed = speed

        if speed > 0.0:
            self.x += math.cos(self.angle) * speed * dt
            self.z += math.sin(self.angle) * speed * dt

            if self.has_real_ground_coords:
                t_ground = (now - self._ground_land_t) if self._ground_land_t else 0.0
                if t_ground < 45.0:
                    cx, cz = 350000.0, 350000.0
                    dist_to_center = math.hypot(cx - self.x, cz - self.z)
                    if dist_to_center > 25000.0:
                        target_angle = math.atan2(cz - self.z, cx - self.x)
                        angle_diff   = (target_angle - self.angle + math.pi) % (2.0 * math.pi) - math.pi
                        self.angle   = (self.angle + angle_diff * (dt * 0.8) + random.uniform(-0.04, 0.04)) % (2.0 * math.pi)
                    else:
                        self.angle = (self.angle + 0.5 * dt + random.uniform(-0.03, 0.03)) % (2.0 * math.pi)
                else:
                    ex, ez = 850000.0, -250000.0
                    target_angle = math.atan2(ez - self.z, ex - self.x)
                    angle_diff   = (target_angle - self.angle + math.pi) % (2.0 * math.pi) - math.pi
                    self.angle   = (self.angle + angle_diff * (dt * 0.8) + random.uniform(-0.04, 0.04)) % (2.0 * math.pi)

    async def _send_udp(self):
        if not self.udp_sock or not self.udp_server or not self.udp_key:
            return False
        try:
            loop = asyncio.get_running_loop()
            time_ms = int((time.time() - self._start_time) * 1000) & 0xFFFFFFFF
            p_state = PLAYER_STATE_MAP.get(self.state, 1)
            m_state = MOVE_STATE_MAP.get(self.state, 2)
            mk = self._msg_keys[self._key_idx % len(self._msg_keys)]
            self._key_idx += 1
            pkt = await build_movement_packet_2001(
                self.udp_key, mk, p_state,
                self.x, self.y, self.z,
                self.tick, time_ms, m_state,
                self.account_id, room_code=self.match_code, slot_id=self.slot_id,
                phase=self.state, angle=self.angle, speed=self.cur_speed,
                vel_y=self.vel_y, s1=self.pkt_s1, s2=self.pkt_s2,
                player_match_id=self.player_match_id or 1,
            )
            await _udp_sendto(loop, self.udp_sock, pkt, self.udp_server)
            return True
        except Exception:
            return False

    async def _clock_sync_loop(self):
        if not self.udp_sock or not self.udp_server or not self.udp_key:
            return
        loop = asyncio.get_running_loop()
        _, nr = await layouts_from_mask(self.match_code)
        tick_val = 60
        try:
            await asyncio.sleep(2.5)
            while not self._clock_stop.is_set():
                try:
                    if (time.time() - self._last_clock_echo_t) > 4.5:
                        body = await uleb_encode(tick_val)
                        pkt  = await build_packet(0x68, nr, 0, 2000, None, 0, body, self.udp_key, encrypted=False)
                        await _udp_sendto(loop, self.udp_sock, pkt, self.udp_server)
                        tick_val = (tick_val + 60) & 0xFFFFFFFF
                    try:
                        await asyncio.wait_for(self._clock_stop.wait(), timeout=2.0)
                        break
                    except asyncio.TimeoutError:
                        pass
                except asyncio.CancelledError:
                    break
                except Exception:
                    await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            pass

    async def _do_jump(self):
        self._jump_start_t = time.time()
        self.state = "jump"
        try:
            await self._send_udp()
        except Exception:
            pass

    # ── main loop ─────────────────────────────────────────────────────────────
    async def _loop(self):
        try:
            self._start_time = time.time()
            # send loading-end beacon
            if self.udp_sock and self.udp_server and self.udp_key:
                try:
                    loop = asyncio.get_running_loop()
                    ru, _ = await layouts_from_mask(self.match_code)
                    loading_end = await build_packet(0x60, ru, 2, 899, 8, 1, b"", self.udp_key)
                    await _udp_sendto(loop, self.udp_sock, loading_end, self.udp_server)
                except Exception:
                    pass

            await asyncio.sleep(1.0)
            interval  = MOVEMENT_TICK_MS / 1000.0
            last_t    = time.time()
            self._last_jump_t      = last_t
            self._last_decision    = last_t
            self._last_speed_change = last_t
            sent = 0

            while not self._stop_evt.is_set():
                now = time.time()
                dt  = now - last_t; last_t = now
                if dt <= 0.0 or dt > 0.25:
                    dt = interval

                if self.phase == "ground":
                    if self.state != "idle":
                        # jump every 3.8-6.2 s
                        if self.state != "jump" and (now - self._last_jump_t) >= random.uniform(3.8, 6.2):
                            self._last_jump_t  = now
                            self._jump_start_t = now
                            self.state = "jump"

                        # random state change every 3-5.5 s
                        if self.state != "jump" and (now - self._last_decision) >= random.uniform(3.0, 5.5):
                            self.state = self._pick_state()
                            self.angle = (self.angle + random.uniform(-0.25, 0.25)) % (2.0 * math.pi)
                            self._last_decision = now

                    if now - self._last_speed_change >= MOVEMENT_UPDATE_SPEED_EVERY:
                        self.speed_mul = random.uniform(MOVEMENT_SPEED_MIN, MOVEMENT_SPEED_MAX)
                        self._last_speed_change = now

                self._step_position(dt)
                if await self._send_udp():
                    sent += 1

                try:
                    await asyncio.wait_for(self._stop_evt.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass

            log_info(f"MovementController STOP uid={self.account_id} sent={sent}")
        except Exception as e:
            log_err(f"MovementController loop error: {e}")

    def start(self):
        if self._task and not self._task.done():
            return
        self._stop_evt.clear()
        self._clock_stop.clear()
        self._task       = asyncio.create_task(self._loop())
        self._clock_task = asyncio.create_task(self._clock_sync_loop())

    async def stop(self):
        self._stop_evt.set()
        self._clock_stop.set()
        for t in (self._task, self._clock_task):
            if t:
                try:
                    await asyncio.wait_for(t, timeout=3.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    t.cancel()


# =============================================================================
# AUTH
# =============================================================================

_token_cache_memo: Dict[str, Any] = {}
_token_cache_memo_time: float = 0.0
_TOKEN_CACHE_MEMO_TTL = 5.0

def _json_serializer(obj):
    if isinstance(obj, (bytes, bytearray)):
        return {"__bytes_hex__": bytes(obj).hex()}
    raise TypeError(f"Type {type(obj)} not serializable")

def _json_deserializer(obj):
    if isinstance(obj, dict):
        if "__bytes_hex__" in obj and len(obj) == 1:
            try:
                return bytes.fromhex(obj["__bytes_hex__"])
            except Exception:
                return b""
        return {k: _json_deserializer(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_deserializer(x) for x in obj]
    return obj

def _load_token_cache() -> Dict[str, Any]:
    global _token_cache_memo, _token_cache_memo_time
    now = time.time()
    if _token_cache_memo and (now - _token_cache_memo_time) < _TOKEN_CACHE_MEMO_TTL:
        return _token_cache_memo

    if not os.path.exists(TOKEN_CACHE_FILE):
        return {}
    try:
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return {}
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("Cache root must be dict")
        parsed = _json_deserializer(data)
        _token_cache_memo = parsed
        _token_cache_memo_time = now
        return parsed
    except Exception as e:
        log_err(f"Token cache corrupt → deleting: {e}")
        try:
            os.remove(TOKEN_CACHE_FILE)
        except Exception:
            pass
        return {}

def _save_token_cache(cache: Dict[str, Any]):
    global _token_cache_memo, _token_cache_memo_time
    try:
        tmp_file = TOKEN_CACHE_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, default=_json_serializer)
        os.replace(tmp_file, TOKEN_CACHE_FILE)
        _token_cache_memo = cache
        _token_cache_memo_time = time.time()
    except Exception as e:
        log_err(f"Token cache save error: {e}")

def cache_get(uid: str) -> Optional[Dict]:
    cache = _load_token_cache()
    entry = cache.get(str(uid))
    if not entry:
        return None
    if time.time() - entry.get("cached_at", 0) > TOKEN_CACHE_TTL:
        log_info(f"UID {uid} expired. Re-login needed.")
        cache_invalidate(uid)
        return None
    if str(entry.get("account_id", "")).isdigit():
        entry["account_id"] = int(entry["account_id"])
    if not isinstance(entry.get("login_payload_data"), (bytes, bytearray)):
        log_warn(f"UID {uid} missing payload → invalidating")
        cache_invalidate(uid)
        return None
    return entry

def cache_set(uid: str, account_data: Dict):
    cache = _load_token_cache()
    entry = dict(account_data)
    entry["cached_at"] = time.time()
    cache[str(uid)] = entry
    _save_token_cache(cache)
    log_ok(f"Saved credentials for UID {uid}")

def cache_invalidate(uid: str):
    cache = _load_token_cache()
    if str(uid) in cache:
        del cache[str(uid)]
        _save_token_cache(cache)
        log_warn(f"Invalidated: {uid}")


def _status_auth_key(auth_type: str, auth_id: str) -> str:
    if auth_type == "token":
        return f"token:{str(auth_id)[:10]}"
    return f"guest:{auth_id}"


def load_account_status_raw() -> Dict[str, Any]:
    if not os.path.exists(ACCOUNT_STATUS_FILE):
        return {}
    try:
        with open(ACCOUNT_STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        log_err(f"Could not load {ACCOUNT_STATUS_FILE}: {e}")
    return {}


def load_account_status() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in load_account_status_raw().items():
        if isinstance(v, dict):
            c = v.get("control")
            if c in ("run", "pause", "stop"):
                out[str(k)] = c
        elif v in ("run", "pause", "stop"):
            out[str(k)] = v
    return out


def save_account_status(status_map: Dict[str, Any]):
    try:
        tmp = ACCOUNT_STATUS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(status_map, f, indent=2)
        os.replace(tmp, ACCOUNT_STATUS_FILE)
    except Exception as e:
        log_err(f"Could not save {ACCOUNT_STATUS_FILE}: {e}")


def get_saved_control(*keys: str) -> str:
    data = load_account_status_raw()
    for k in keys:
        if not k or k not in data:
            continue
        v = data[k]
        if isinstance(v, dict):
            c = v.get("control")
            if c in ("run", "pause", "stop"):
                return c
        elif v in ("run", "pause", "stop"):
            return v
    return "run"


def get_saved_status_meta(*keys: str) -> Dict[str, Any]:
    data = load_account_status_raw()
    for k in keys:
        if not k or k not in data:
            continue
        v = data[k]
        if isinstance(v, dict):
            return dict(v)
        if v in ("run", "pause", "stop"):
            return {"control": v}
    return {}


def set_saved_control(control: str, *keys: str, nickname: Optional[str] = None, account_id: Optional[str] = None, target_level=None, keep_target: bool = True):
    if control not in ("run", "pause", "stop"):
        return
    data = load_account_status_raw()
    for k in keys:
        if not k:
            continue
        prev = data.get(str(k))
        entry: Dict[str, Any] = {}
        if isinstance(prev, dict):
            entry = dict(prev)
        elif prev in ("run", "pause", "stop"):
            entry = {"control": prev}
        entry["control"] = control
        if nickname:
            entry["nickname"] = str(nickname)
        if account_id is not None:
            entry["account_id"] = str(account_id)
        if target_level is not None:
            if target_level == "" or target_level is False:
                entry.pop("target_level", None)
            else:
                try:
                    entry["target_level"] = int(target_level)
                except Exception:
                    pass
        elif not keep_target:
            entry.pop("target_level", None)
        data[str(k)] = entry
    save_account_status(data)


def remove_saved_control(*keys: str):
    data = load_account_status_raw()
    changed = False
    for k in keys:
        if k and k in data:
            del data[k]
            changed = True
    if changed:
        save_account_status(data)


# ── uid-primary account state helpers ────────────────────────────────────────
# The canonical key is always the raw uid (numeric string), never "guest:uid"
# or "acc:account_id".  Extra keys are tolerated for read-back compat but all
# writes go under the uid key only.

def _canon_uid(uid: str) -> str:
    """Strip auth-type prefix if present — 'guest:12345' → '12345'."""
    s = str(uid or "").strip()
    for pfx in ("guest:", "token:", "acc:"):
        if s.startswith(pfx):
            s = s[len(pfx):]
            break
    return s


def set_account_state(uid: str, **fields) -> None:
    """
    Merge `fields` into the uid-primary entry in account_status.json.
    Supported keys: control, nickname, account_id, target_level, homer_equipped,
                    region, level, exp.
    Old 'guest:...' / 'acc:...' shadow keys are cleaned up on first write.
    """
    uid = _canon_uid(uid)
    if not uid:
        return
    data = load_account_status_raw()

    # migrate any existing shadow keys into the uid entry
    for pfx in (f"guest:{uid}", f"acc:{uid}"):
        if pfx in data and pfx != uid:
            existing = data.pop(pfx)
            if isinstance(existing, dict):
                entry = data.get(uid, {})
                if not isinstance(entry, dict):
                    entry = {}
                for k, v in existing.items():
                    entry.setdefault(k, v)
                data[uid] = entry

    entry = data.get(uid, {})
    if not isinstance(entry, dict):
        entry = {"control": entry} if entry in ("run", "pause", "stop") else {}
    entry.update({k: v for k, v in fields.items() if v is not None})
    data[uid] = entry
    save_account_status(data)


def get_account_state(uid: str) -> Dict[str, Any]:
    uid = _canon_uid(uid)
    data = load_account_status_raw()
    v = data.get(uid, {})
    if not isinstance(v, dict):
        return {"control": v} if v in ("run", "pause", "stop") else {}
    return dict(v)


def get_homer_equipped(uid: str) -> bool:
    return bool(get_account_state(uid).get("homer_equipped", False))


def set_homer_equipped(uid: str, equipped: bool) -> None:
    set_account_state(uid, homer_equipped=bool(equipped))


async def get_access_token(uid, password):
    url = "https://100067.connect.garena.com/oauth/guest/token/grant"
    hdrs = {
        "Host": "100067.connect.garena.com",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; SM-G998B Build/SP1A.210812.016)",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "close"
    }
    data = {
        "uid": uid,
        "password": password,
        "response_type": "token",
        "client_type": "2",
        "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_id": "100067"
    }
    for attempt in range(5):
        try:
            await asyncio.sleep(0.2)
            target = await host_pinned_url(url) if attempt >= 1 else url
            response = await client.post(target, headers=hdrs, data=data)
            if response.status_code == 200:
                response_data = response.json()
                open_id = response_data.get("open_id")
                access_token = response_data.get("access_token")
                platform = response_data.get("platform", 4)
                if open_id and access_token:
                    return open_id, access_token, platform
            if response.status_code == 429:
                await asyncio.sleep(random.uniform(1.0, 2.0))
                continue
        except Exception:
            pass
        await asyncio.sleep(random.uniform(0.4, 0.8))
    return None


async def build_majorlogin_payload(open_id, access_token, platform, client_version):
    try:
        
        fields = {
            3: str(datetime.now())[:-7],
            4: "free fire",
            5: 1 if str(platform) in ["1", "4"] else int(platform),
            7: str(client_version),
            8: "Android OS 16 / API-36 (BP2A.250605.031.A3_CSNN_V000L1/compiler260909194330)",
            9: "Handheld",
            11: "WIFI",
            12: 1608,
            13: 720,
            14: "270",
            15: "ARM64 FP ASIMD AES | 5606 | 8",
            16: 7597,
            17: "Adreno (TM) 610",
            18: "OpenGL ES 3.2 V@0615.100 (GIT@b82916be04, I507ba793b7, 1754480107) (Date:08/06/25)",
            19: "Google|010624fb-a876-4d46-85e6-89c094ce2004",
            20: f"{random.randint(103, 223)}.{random.randint(10, 250)}.{random.randint(10, 250)}.{random.randint(10, 250)}",
            21: "en",
            22: str(open_id),
            23: str(platform),
            24: "Handheld",
            25: "vivo V2434",
            29: str(access_token),
            30: 1,
            42: "WIFI",
            57: "7428b253defc164018c604a1ebbfebdf",
            60: 223252,
            61: 128736,
            62: 4510,
            64: 128864,
            65: 223252,
            66: 128864,
            67: 223252,
            73: 3,
            74: "/data/app/~~qTPtxsVH5kRQHc-NlwZjSQ==/com.dts.freefireth-0M38ZBv2eA3G777MEba-KA==/lib/arm64",
            76: 1,
            77: "b8e0cd5e295eee42f5860d3c86e483dd|/data/app/~~qTPtxsVH5kRQHc-NlwZjSQ==/com.dts.freefireth-0M38ZBv2eA3G777MEba-KA==/base.apk",
            78: 3,
            79: 2,
            81: "64",
            83: str(CLIENT_VERSION_CODE),
            86: "OpenGLES2",
            87: 4095,
            88: int(platform),
            92: random.randint(10000, 13000),
            93: "android",
            94: "KqsHT7r/6smkUzPLzZ9M2DKUP1xUZLW8igS0UpobKbM8fY1z6GKLtkafwGFHdFTNqf3LexWOwKqQl9YjHfWm7h1o/7fWXWHHxk4cLGdP5QIZnAxj",
            95: 111207,
            96: "{\"cur_rate\":[60,90,120],\"support_etc2\":false}",
            99: str(platform),
            100: str(platform),
            102: "JP\u0017\u0017T\u000e\\\u00049",
            104: 81114,
            105: 1,
            106: "https://dl.gmc.freefiremobile.com/live/ABHotUpdates/|https://core-gmc.freefiremobile.com/live/ABHotUpdates/|a4332cb1c1a84e51dd77441e4856ed5a",
            107: "1.70833924799a92b3"
        }

        final = await create_proto_packet(fields)

        return await aes_encrypt(final, AES_KEY, AES_IV)
    except Exception as e:
        print(f"MajorLogin Payload Error: {e}")
        return None



class MajorLoginResult:
    def __init__(self):
        self.token = ""
        self.region = ""
        self.account_id = 0
        self.server_time = int(time.time())
        self.aes_ak = b""
        self.iv_i = b""
        self.url = ""
        self.lockRegion = ""


async def send_majorlogin(data, release_version, server_url):
    try:
        url = f"{server_url.rstrip('/')}/MajorLogin"
        netloc = urlparse(server_url).netloc

        req_headers = {
            "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Content-Type": "application/x-www-form-urlencoded",
            "Expect": "100-continue",
            "X-Unity-Version": "2018.4.12f1",
            "X-GA": "v1 1",
            "X-GA-SV": str(int(time.time())),
            "ReleaseVersion": release_version,
            "Host": netloc,
            "Content-Length": str(len(data)),
            "Authorization": "Bearer",
        }

        print(f"\nMajorLogin POST {url}")
        log_info(f"MajorLogin Host={netloc}  ReleaseVersion={release_version}  Payload={len(data)} bytes")

        response = await client.post(await host_pinned_url(url), headers=req_headers, data=data, timeout=15.0)

        content = response.content or b""
        log_info(f"MajorLogin HTTP {response.status_code}")
        log_info(f"MajorLogin Content-Length: {len(content)}")
        log_info(f"MajorLogin Headers: {dict(response.headers)}")

        try:
            text = content.decode("utf-8", errors="replace")
            log_info(f"MajorLogin Body (text):\n{text[:800]}")
        except Exception:
            text = ""
        pass  # login body

        if response.status_code != 200:
            log_info("MajorLogin Non-200 response → abort")
            return None

        if len(content) < 20:
            log_info("MajorLogin Body too short")
            return None

        jwt_token = _extract_jwt_from_bytes(content)
        if jwt_token:
            log_info(f"MajorLogin Found embedded JWT (len={len(jwt_token)})")

        res_proto = None

        for offset in (0, 4, 8, 16, 32, 64, 80, 96, 128):
            if offset >= len(content):
                break
            try:
                p = Snowflake_pb2.MajorLoginRes()
                p.ParseFromString(content[offset:])
                if (getattr(p, "token", None) or getattr(p, "region", None) or
                    getattr(p, "lockRegion", None) or getattr(p, "serverUrl", None)):
                    res_proto = p
                    log_info(f"MajorLogin Parsed successfully (offset {offset})")
                    break
            except Exception as e:
                if offset == 0:
                    log_info(f"MajorLogin Direct parse failed: {e}")
                continue

        result = MajorLoginResult()
        result.url = server_url

        if res_proto is not None:
            result.token = getattr(res_proto, "token", None) or getattr(res_proto, "Token", None) or ""
            result.region = resolve_region(getattr(res_proto, "region", None), getattr(res_proto, "lockRegion", None), getattr(res_proto, "lock_region", None))
            result.lockRegion = getattr(res_proto, "lockRegion", None) or result.region
            result.account_id = int(getattr(res_proto, "account_id", 0) or getattr(res_proto, "accountId", 0) or 0)
            result.server_time = int(getattr(res_proto, "server_time", 0) or getattr(res_proto, "serverTime", 0) or time.time())
            result.aes_ak = _bytes_field(getattr(res_proto, "aes_ak", None) or getattr(res_proto, "aesAk", None) or getattr(res_proto, "key", None))
            result.iv_i = _bytes_field(getattr(res_proto, "iv_i", None) or getattr(res_proto, "ivI", None) or getattr(res_proto, "iv", None))
            su = getattr(res_proto, "serverUrl", None) or getattr(res_proto, "server_url", None) or getattr(res_proto, "url", None)
            if su:
                result.url = su if isinstance(su, str) else str(su)
        else:
            log_info("MajorLogin Typed parse failed — trying generic protobuf decode")
            gdict = await _generic_proto_dict(content)
            if gdict:
                tok = _pick_proto_value(gdict, 1, 2, 3, 5, 7, 8, 10) or jwt_token
                if isinstance(tok, bytes):
                    tok = tok.decode("utf-8", errors="ignore")
                if isinstance(tok, str) and "eyJ" in tok:
                    result.token = tok[tok.find("eyJ"):] if "eyJ" in tok else tok
                elif jwt_token:
                    result.token = jwt_token
                elif isinstance(tok, str) and len(tok) > 40:
                    result.token = tok

                reg = _pick_proto_value(gdict, 3, 4, 6, 9, 11, 15)
                if isinstance(reg, str) and 1 < len(reg) <= 8:
                    result.region = reg.upper()

                aid = _pick_proto_value(gdict, 1, 2, 4, 5)
                if isinstance(aid, int) and aid > 1000:
                    result.account_id = aid

                for n in (12, 13, 14, 16, 17, 18, 20, 21, 22, 25, 30):
                    v = get_proto_field(gdict, n, None)
                    if isinstance(v, (bytes, bytearray)) and 8 <= len(v) <= 64:
                        if not result.aes_ak:
                            result.aes_ak = bytes(v)
                        elif not result.iv_i:
                            result.iv_i = bytes(v)
                    if isinstance(v, str) and v.startswith("http"):
                        result.url = v

                st = _pick_proto_value(gdict, 6, 7, 8, 9)
                if isinstance(st, int) and st > 1_600_000_000:
                    result.server_time = st

            if not result.token and jwt_token:
                result.token = jwt_token

        if result.token:
            claims = _decode_jwt_payload(result.token)
            if claims:
                log_info(f"MajorLogin JWT claims keys: {list(claims.keys())[:12]}")
                for k in ("account_id", "accountId", "uid", "user_id", "sub"):
                    if k in claims and not result.account_id:
                        try:
                            result.account_id = int(claims[k])
                        except Exception:
                            pass
                for k in ("region", "lock_region", "lockRegion", "server_region"):
                    if k in claims and claims[k]:
                        result.region = str(claims[k]).upper()
                for k in ("server_url", "serverUrl", "url", "bp_url"):
                    if k in claims and str(claims[k]).startswith("http"):
                        result.url = str(claims[k])

        if not result.token:
            server_msg = _extract_server_message(content)
            if server_msg:
                log_err(f"MajorLogin ✗ server refused: \"{server_msg}\"")
            log_info("MajorLogin ✗ No token / JWT found — payload, version or device mismatch")
            return None

        if "version" in (result.url or "").lower() or not result.url:
            result.url = server_url

        print(
            f"MajorLogin ✓ SUCCESS  region={result.region}  "
            f"account_id={result.account_id}  token_len={len(result.token)}  "
            f"aes={len(result.aes_ak)} iv={len(result.iv_i)}  url={result.url}"
        )
        return result

    except Exception as e:
        log_err(f"MajorLogin Exception: {type(e).__name__}: {e}")
        return None


async def _parse_getlogin_body(response_content: bytes):
    """Parse a GetLoginData body. Returns (res_proto, dict_res) or None. Silent."""
    res_proto = Snowflake_pb2.GetLoginDataRes()
    parsed_successfully = False
    try:
        res_proto.ParseFromString(response_content)
        if getattr(res_proto, "functional_addrs", None) or getattr(res_proto, "informational_addrs", None):
            parsed_successfully = True
    except Exception:
        pass

    if not parsed_successfully:
        for offset in range(0, min(160, len(response_content))):
            try:
                candidate = Snowflake_pb2.GetLoginDataRes()
                candidate.ParseFromString(response_content[offset:])
                if getattr(candidate, "functional_addrs", None) or getattr(candidate, "informational_addrs", None):
                    res_proto = candidate
                    parsed_successfully = True
                    break
            except Exception:
                pass

    dict_res = {}
    try:
        dict_res = await _generic_proto_dict(response_content)
    except Exception:
        pass

    if not parsed_successfully:
        fa = get_proto_field(dict_res, 14, None) or get_proto_field(dict_res, 15, None)
        ia = get_proto_field(dict_res, 32, None) or get_proto_field(dict_res, 33, None)
        if fa or ia:
            class FakeLogin:
                pass
            fake = FakeLogin()
            fake.functional_addrs = fa if isinstance(fa, str) else (fa.decode() if isinstance(fa, bytes) else "")
            fake.informational_addrs = ia if isinstance(ia, str) else (ia.decode() if isinstance(ia, bytes) else "")
            fake.nickname = get_proto_field(dict_res, 4, "") or ""
            res_proto = fake
            parsed_successfully = True

    if not parsed_successfully and not dict_res:
        return None
    return res_proto, dict_res


async def send_getlogin(data, base_url, token, release_version, attempts: int = 3):
    """POST GetLoginData with retries. Silent on success, one line on failure."""
    if not base_url:
        log_warn("GetLoginData missing base_url")
        return None

    url = f"{base_url.rstrip('/')}/GetLoginData"
    netloc = urlparse(base_url).netloc or "clientbp.ppmainecoonghj.com"

    req_headers = headers.copy()
    req_headers["ReleaseVersion"] = release_version
    req_headers["Authorization"] = f"Bearer {token}"
    req_headers["Host"] = netloc
    req_headers["Content-Length"] = str(len(data)) if data else "0"

    last_err = "unknown"
    for attempt in range(1, attempts + 1):
        try:
            await asyncio.sleep(0.1)
            target = await host_pinned_url(url)
            response = await client.post(target, headers=req_headers, data=data, timeout=15.0)
            response_content = response.content or b""
            if response.status_code != 200:
                last_err = f"HTTP {response.status_code}"
            elif len(response_content) < 8:
                last_err = "body too short"
            else:
                parsed = await _parse_getlogin_body(response_content)
                if parsed is not None:
                    return parsed
                last_err = "unparseable body"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        if attempt < attempts:
            await asyncio.sleep(0.7 * attempt)
    log_warn(f"GetLoginData failed after {attempts} attempts ({netloc}): {last_err}")
    return None


def _register_credentials(account_data: Dict):
    try:
        acc_id = str(account_data['account_id'])
        bot_state.account_credentials[acc_id] = account_data
        if account_data.get('auth_uid'):
            bot_state.account_credentials[str(account_data['auth_uid'])] = account_data
        if account_data.get('auth_token'):
            bot_state.account_credentials[f"tok_{account_data['auth_token'][:20]}"] = account_data
        if acc_id in bot_state.accounts:
            bot_state.accounts[acc_id]["auth_type"] = account_data.get("auth_type", "guest")
            bot_state.accounts[acc_id]["auth_uid"] = account_data.get("auth_uid")
            bot_state.accounts[acc_id]["auth_token"] = account_data.get("auth_token")
            if account_data.get("auth_type") == "token" and account_data.get("auth_token"):
                bot_state.accounts[acc_id]["worker_key"] = account_data["auth_token"][:10]
            elif account_data.get("auth_uid"):
                bot_state.accounts[acc_id]["worker_key"] = str(account_data["auth_uid"])
    except Exception:
        pass


async def fetch_profile_card(account_id, region) -> Optional[str]:
    try:
        import base64
        acc_id = str(int(account_id))
        reg = (region or "").strip() or ""
        url = f"{PICO_INFO_API}?uid={acc_id}&region={reg}"
        log_info(f"[PROFILE] Fetching card for {acc_id} ({reg})…")
        try:
            resp = await client.get(url, timeout=12.0)
        except Exception:
            async with httpx.AsyncClient(timeout=12.0, verify=False) as http:
                resp = await http.get(url)
        if resp.status_code != 200:
            log_warn(f"[PROFILE] API HTTP {resp.status_code} for {acc_id}")
            return None
        data = resp.json()
        b64 = data.get("profile_card") or data.get("profileCard") or ""
        if not b64:
            log_warn(f"[PROFILE] No profile_card for {acc_id}")
            return None
        if "," in b64 and b64.strip().startswith("data:"):
            b64 = b64.split(",", 1)[1]
        raw = base64.b64decode(b64)
        try:
            bot_state.profile_images[acc_id] = raw
        except Exception:
            pass
        path = f"/api/account/image/{acc_id}"
        log_ok(f"[PROFILE] Loaded into memory for {acc_id} ({len(raw)} bytes)")
        return path
    except Exception as e:
        log_err(f"[PROFILE] {e}")
        return None


def delete_account_image(account_id):
    try:
        bot_state.profile_images.pop(str(int(account_id)), None)
        bot_state.profile_images.pop(str(account_id), None)
    except Exception:
        pass


_completing_targets = set()


async def complete_target_level(acc_id: str, level: int):
    acc_id = str(acc_id)
    if acc_id in _completing_targets:
        return
    _completing_targets.add(acc_id)
    try:
        await _complete_target_level_impl(acc_id, level)
    finally:
        _completing_targets.discard(acc_id)


async def _complete_target_level_impl(acc_id: str, level: int):
    acc_id = str(acc_id)
    acc = bot_state.accounts.get(acc_id) or {}
    log_ok(f"[TARGET] {acc.get('nickname', acc_id)} reached Lv{level} — archiving")
    try:
        if acc_id in bot_state.accounts:
            bot_state.accounts[acc_id]["control"] = "stop"
            bot_state.accounts[acc_id]["status"] = "STOPPED"
            bot_state.accounts[acc_id]["target_level"] = None
        bot_state.set_control(acc_id, "stop")
    except Exception:
        pass
    out_file = f"{int(level)}_level_accounts.json"
    entry = { }
    try:
        if os.path.exists(ACCOUNTS_FILE):
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                rows = json.load(f)
            for row in rows:
                if acc.get("auth_uid") and str(row.get("uid")) == str(acc.get("auth_uid")):
                    entry["uid"] = row.get("uid")
                    entry["password"] = row.get("password")
                    break
                if acc.get("auth_token") and row.get("token") == acc.get("auth_token"):
                    entry["token"] = row.get("token")
                    break
    except Exception:
        pass
    if not entry.get("password") and acc.get("auth_uid"):
        try:
            cred = bot_state.account_credentials.get(str(acc_id)) or {}
            if cred.get("auth_password"):
                entry["uid"] = entry.get("uid") or acc.get("auth_uid")
                entry["password"] = cred.get("auth_password")
        except Exception:
            pass
    if not entry and acc.get("auth_uid"):
        entry = {"uid": acc.get("auth_uid"), "password": ""}
        try:
            cred = bot_state.account_credentials.get(str(acc_id)) or {}
            if cred.get("auth_password"):
                entry["password"] = cred["auth_password"]
        except Exception:
            pass
    if not entry and acc.get("auth_token"):
        entry = {"token": acc.get("auth_token")}
    entry["account_id"] = acc_id
    entry["level"] = int(level)
    entry["nickname"] = acc.get("nickname") or ""
    entry["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    existing = []
    if os.path.exists(out_file):
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    existing = [e for e in existing if str(e.get("account_id")) != acc_id]
    existing.append(entry)
    try:
        tmp = out_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp, out_file)
    except Exception as e:
        log_err(f"[TARGET] write {out_file}: {e}")
    try:
        cred_entry = {}
        if entry.get("uid") is not None:
            cred_entry["uid"] = entry.get("uid")
            cred_entry["password"] = entry.get("password", "")
        if entry.get("token"):
            cred_entry["token"] = entry.get("token")
        completed = []
        if os.path.exists(COMPLETED_ACCOUNTS_FILE):
            try:
                with open(COMPLETED_ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    completed = json.load(f)
                if not isinstance(completed, list):
                    completed = []
            except Exception:
                completed = []
        def _same(a, b):
            if a.get("uid") and b.get("uid") and str(a["uid"]) == str(b["uid"]):
                return True
            if a.get("token") and b.get("token") and a["token"] == b["token"]:
                return True
            return False
        completed = [c for c in completed if not _same(c, cred_entry)]
        if cred_entry:
            completed.append(cred_entry)
        tmp = COMPLETED_ACCOUNTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(completed, f, indent=2)
        os.replace(tmp, COMPLETED_ACCOUNTS_FILE)
    except Exception as e:
        log_err(f"[TARGET] completed_accounts.json: {e}")

    try:
        bot_state.set_control(acc_id, "stop")
    except Exception:
        pass
    auth_uid = acc.get("auth_uid")
    auth_token = acc.get("auth_token")
    worker_key = acc.get("worker_key")
    try:
        if os.path.exists(ACCOUNTS_FILE):
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                rows = json.load(f)
            filtered = []
            for row in rows:
                if auth_uid and str(row.get("uid")) == str(auth_uid):
                    continue
                if auth_token and row.get("token") == auth_token:
                    continue
                if str(row.get("uid")) == acc_id:
                    continue
                filtered.append(row)
            with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                json.dump(filtered, f, indent=2)
    except Exception as e:
        log_err(f"[TARGET] accounts.json: {e}")
    try:
        if auth_uid:
            cache_invalidate(str(auth_uid))
        if auth_token:
            cache_invalidate(f"tok_{auth_token[:20]}")
        cache_invalidate(acc_id)
    except Exception:
        pass
    delete_account_image(acc_id)
    for k in {acc_id, str(worker_key or ""), str(auth_uid or ""), str(auth_token or "")[:10]}:
        if not k:
            continue
        task = bot_state.account_workers.pop(k, None)
        if task and not task.done():
            task.cancel()
    bot_state.accounts.pop(acc_id, None)
    bot_state._exp_samples.pop(acc_id, None)
    bot_state.account_credentials.pop(acc_id, None)
    bot_state.recalc_totals()
    bot_state.log(f"Target Lv{level} reached — archived → {out_file}", "success", acc_id)


def _resolve_target_for_account(acc_id: str, acc=None):
    acc_id = str(acc_id)
    if acc is None:
        acc = bot_state.accounts.get(acc_id)
    if acc and acc.get("target_level") is not None and acc.get("target_level") != "":
        try:
            return int(acc["target_level"])
        except Exception:
            pass
    keys = [f"acc:{acc_id}"]
    if acc:
        if acc.get("auth_uid"):
            keys.append(f"guest:{acc['auth_uid']}")
        if acc.get("auth_token"):
            keys.append(f"token:{str(acc['auth_token'])[:10]}")
        if acc.get("worker_key"):
            wk = str(acc["worker_key"])
            keys.append(f"guest:{wk}")
            keys.append(f"token:{wk}")
    try:
        cred = bot_state.account_credentials.get(acc_id) or {}
        if cred.get("auth_uid"):
            keys.append(f"guest:{cred['auth_uid']}")
        if cred.get("auth_token"):
            keys.append(f"token:{str(cred['auth_token'])[:10]}")
    except Exception:
        pass
    seen = set()
    ordered = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            ordered.append(k)
    try:
        data = load_account_status_raw()
        for k in ordered:
            v = data.get(k)
            if isinstance(v, dict) and v.get("target_level") is not None and v.get("target_level") != "":
                try:
                    tl = int(v["target_level"])
                    if acc is not None:
                        acc["target_level"] = tl
                    return tl
                except Exception:
                    continue
        for k, v in data.items():
            if not isinstance(v, dict):
                continue
            if str(v.get("account_id") or "") != acc_id:
                continue
            if v.get("target_level") is not None and v.get("target_level") != "":
                try:
                    tl = int(v["target_level"])
                    if acc is not None:
                        acc["target_level"] = tl
                    return tl
                except Exception:
                    continue
    except Exception:
        pass
    return None


async def maybe_check_target_level(acc_id: str, level: int):
    acc_id = str(acc_id)
    acc = bot_state.accounts.get(acc_id)
    target = _resolve_target_for_account(acc_id, acc)
    if target is None:
        return
    try:
        target = int(target)
        level = int(level)
    except Exception:
        return
    if target > 0 and level >= target:
        log_ok(
            f"[TARGET] UID {acc_id} level {level} >= target {target} — stopping & archiving"
        )
        await complete_target_level(acc_id, level)


def _update_cache_profile(account_data: Dict, level: int, exp: int):
    try:
        auth_uid = account_data.get('auth_uid')
        auth_token = account_data.get('auth_token')
        keys = []
        if auth_uid:
            keys.append(str(auth_uid))
        if auth_token:
            keys.append(f"tok_{auth_token[:20]}")
        if not keys:
            return
        cache = _load_token_cache()
        changed = False
        for k in keys:
            if k in cache and isinstance(cache[k], dict):
                cache[k]['level'] = level
                cache[k]['exp'] = exp
                changed = True
        if changed:
            _save_token_cache(cache)
    except Exception as e:
        log_warn(f"[EXP-REFRESH] cache update failed: {e}")


_refresh_locks: Dict[str, asyncio.Lock] = {}


def _get_refresh_lock(uid: str) -> asyncio.Lock:
    lock = _refresh_locks.get(uid)
    if lock is None:
        lock = asyncio.Lock()
        _refresh_locks[uid] = lock
    return lock


async def refresh_account_profile(account_data_or_uid: Any):
    """Serialize profile refreshes per account.

    The 15 s periodic loop and post-match triggers overlap constantly while
    stacking; without this they stampede GetLoginData and race the cache
    file. If a refresh is already in flight, skip — it delivers fresh data.
    """
    try:
        if isinstance(account_data_or_uid, str):
            uid = str(account_data_or_uid)
        elif account_data_or_uid:
            uid = str(account_data_or_uid.get("account_id", "?"))
        else:
            uid = "?"
    except Exception:
        uid = "?"
    lock = _get_refresh_lock(uid)
    if lock.locked():
        return
    async with lock:
        await _refresh_account_profile_impl(account_data_or_uid)


async def _refresh_account_profile_impl(account_data_or_uid: Any):
    try:
        if isinstance(account_data_or_uid, str):
            uid = str(account_data_or_uid)
            account_data = bot_state.account_credentials.get(uid)
        else:
            account_data = account_data_or_uid
            uid = str(account_data.get('account_id')) if account_data else "?"
        if not account_data:
            log_warn(f"[EXP-REFRESH] No credentials for UID {uid}")
            return
        url = account_data.get('server_url')
        token = account_data.get('token')
        release_version = account_data.get('release_version')
        payload = account_data.get('login_payload_data')
        if not (url and token and release_version and payload):
            log_warn(f"[EXP-REFRESH] Missing fields for {uid}")
            return
        res = None
        try:
            res = await send_getlogin(payload, url, token, release_version)
        except Exception as e:
            log_err(f"[EXP-REFRESH] send_getlogin exception for {uid}: {e}")
            return
        if not res:
            log_warn(f"[EXP-REFRESH] GetLoginData returned None for {uid}")
            return
        res_proto, dict_res = res

        def _safe_int(v, default):
            try:
                if v is None or v == "":
                    return default
                return int(v)
            except Exception:
                return default

        level = _safe_int(get_proto_field(dict_res, 6, None), None)
        exp = _safe_int(get_proto_field(dict_res, 7, None), None)
        likes = _safe_int(get_proto_field(dict_res, 8, None), None)
        nickname = ""
        try:
            nickname = res_proto.nickname or get_proto_field(dict_res, 4, "") or ""
        except Exception:
            nickname = ""
        if level is None and exp is None:
            log_warn(f"[EXP-REFRESH] No level/exp field parsed for {uid}")
            return
        level = level if level is not None else 1
        exp = exp if exp is not None else 0
        likes = likes if likes is not None else 0
        acc_id = str(account_data['account_id'])
        old_level = 0
        old_exp = 0
        try:
            if acc_id in bot_state.accounts:
                old_level = int(bot_state.accounts[acc_id].get('level', 0) or 0)
                old_exp = int(bot_state.accounts[acc_id].get('current_exp', 0) or 0)
        except Exception:
            pass
        try:
            bot_state.update_exp(acc_id, exp, level)
        except Exception as e:
            log_err(f"[EXP-REFRESH] update_exp failed for {acc_id}: {e}")
        if likes > 0 and acc_id in bot_state.accounts:
            try:
                bot_state.accounts[acc_id]["likes"] = likes
            except Exception:
                pass
        if nickname and acc_id in bot_state.accounts:
            try:
                bot_state.accounts[acc_id]["nickname"] = nickname
            except Exception:
                pass
        _update_cache_profile(account_data, level, exp)
        account_data['level'] = level
        account_data['exp'] = exp
        if likes > 0:
            account_data['likes'] = likes
        if nickname:
            account_data['nickname'] = nickname
        if old_level > 0 and level > old_level:
            log_ok(f"[LEVEL UP] UID {acc_id} : Lvl {old_level} -> {level} (EXP {old_exp} -> {exp})")
            if level >= LONE_WOLF_UNLOCK_LEVEL and old_level < LONE_WOLF_UNLOCK_LEVEL:
                log_ok(f"[MODE LOCK] UID {acc_id} reached Lvl {level} -> next search will be LONE WOLF")
        elif old_exp != exp:
            log_ok(f"[EXP] UID {acc_id} Lvl {level} | EXP {old_exp} -> {exp} (+{exp - old_exp})")
        else:
            log_info(f"[EXP-REFRESH] UID {acc_id} -> Level: {level}, EXP: {exp}")
        if level > old_level:
            await maybe_check_target_level(acc_id, level)
    except Exception as e:
        log_err(f"refresh_account_profile error: {e}")


async def process_account_uid_pass(uid: str, password: str) -> Optional[Dict]:
    cached = cache_get(uid)
    if cached:
        log_ok(f"[CACHE HIT] UID {uid} loaded from token_cache.json (no login)")
        acc_id = str(cached['account_id'])
        img = await fetch_profile_card(
            cached.get('account_id'),
            cached.get('lock_region') or cached.get('region') or "",
        )
        bot_state.register_account(
            uid=acc_id,
            nickname=cached.get('nickname', f"Player_{acc_id}"),
            region=cached.get('region', ""),
            level=cached.get('level', 1),
            exp=cached.get('exp', 0),
            likes=cached.get('likes', 0)
        )
        if img and acc_id in bot_state.accounts:
            bot_state.accounts[acc_id]['profile_image'] = img
        _register_credentials(cached)
        return cached

    log_info(f"Full login for UID {uid}...")
    try:
        verconfig_res = await version_config(FORCE_REGION)
        if verconfig_res is None:
            print("Version Config Failed")
            return None
        release_version, client_version, server_url = verconfig_res

        tokengrant_response = await get_access_token(uid, password)
        if tokengrant_response is None:
            print("Token Grant Attempt Failed")
            return None
        open_id, access_token, platform = tokengrant_response

        login_payload_data = await build_majorlogin_payload(open_id, access_token, platform, client_version)
        """
        print(login_payload_data.hex())

        print("Access:", access_token)
        print("Release:", release_version)
        print("Server:", server_url)
        print("Client:", client_version)
        """
        majorlogin_response = await send_majorlogin(login_payload_data, release_version, server_url)
        if majorlogin_response is None:
            log_info("MajorLogin Response is empty")
            return None
        getlogin_result = await send_getlogin(login_payload_data, majorlogin_response.url, majorlogin_response.token, release_version)
        if getlogin_result is None:
            log_info("GetLoginData Response is empty")
            return None
        res_proto, dict_res = getlogin_result

        game_account_id = int(getattr(majorlogin_response, "account_id", 0) or 0)
        lock_region = resolve_region(getattr(majorlogin_response, "lockRegion", None), getattr(majorlogin_response, "region", None), FORCE_REGION)
        profile_image = await fetch_profile_card(game_account_id, lock_region)

        acc_id = str(game_account_id or majorlogin_response.account_id)
        level = int(get_proto_field(dict_res, 6, 1))
        exp = int(get_proto_field(dict_res, 7, 0))
        likes = int(get_proto_field(dict_res, 8, 0))
        nickname = res_proto.nickname or get_proto_field(dict_res, 4, f"Player_{acc_id}")
        region = resolve_region(majorlogin_response.region, get_proto_field(dict_res, 3, None), FORCE_REGION)

        bot_state.register_account(uid=acc_id, nickname=nickname, region=region, level=level, exp=exp, likes=likes)
        if profile_image and acc_id in bot_state.accounts:
            bot_state.accounts[acc_id]["profile_image"] = profile_image

        account_data = {
            'account_id': majorlogin_response.account_id,
            'nickname': nickname,
            'region': region,
            'lock_region': lock_region,
            'level': level,
            'exp': exp,
            'likes': likes,
            'open_id': open_id,
            'access_token': access_token,
            'platform': str(platform),
            'token': majorlogin_response.token,
            'server_time': majorlogin_response.server_time,
            'aes_ak': majorlogin_response.aes_ak,
            'iv_i': majorlogin_response.iv_i,
            'functional_addrs': res_proto.functional_addrs or get_proto_field(dict_res, 14),
            'informational_addrs': res_proto.informational_addrs or get_proto_field(dict_res, 32),
            'release_version': release_version,
            'client_version': client_version,
            'server_url': majorlogin_response.url,
            'login_payload_data': login_payload_data,
            'auth_type': 'guest',
            'auth_uid': uid,
            'auth_password': password,
            'profile_image': profile_image,
        }
        _register_credentials(account_data)
        cache_set(uid, account_data)
        try:
            aid = str(account_data['account_id'])
            tl = _resolve_target_for_account(aid, bot_state.accounts.get(aid))
            if tl is not None and aid in bot_state.accounts:
                bot_state.accounts[aid]["target_level"] = tl
            await maybe_check_target_level(aid, int(level))
        except Exception as e:
            log_warn(f"[TARGET] post-login check: {e}")
        return account_data
    except Exception as e:
        log_err(f"process_account_uid_pass error: {e}")
        return None

async def process_account_token(access_token: str) -> Optional[Dict]:
    cache_key = f"tok_{access_token[:20]}"
    cached = cache_get(cache_key)
    if cached:
        print_success(f"[CACHE HIT] Token {access_token[:10]}... loaded from cache")
        acc_id = str(cached['account_id'])
        img = await fetch_profile_card(
            cached.get('account_id'),
            cached.get('lock_region') or cached.get('region'),
        )
        bot_state.register_account(
            uid=acc_id,
            nickname=cached.get('nickname', f"Player_{acc_id}"),
            region=cached.get('region', ""),
            level=cached.get('level', 1),
            exp=cached.get('exp', 0),
            likes=cached.get('likes', 0)
        )
        if img and acc_id in bot_state.accounts:
            bot_state.accounts[acc_id]['profile_image'] = img
        _register_credentials(cached)
        return cached

    print_info("[LOGIN] Full login with Access Token...")
    try:
        verconfig_res = await version_config(FORCE_REGION)
        if verconfig_res is None:
            return None
        release_version, client_version, server_url = verconfig_res

        import requests
        url = f"https://100067.connect.garena.com/oauth/token/inspect?token={access_token}"
        hdrs = {
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "close",
            "Content-Type": "application/x-www-form-urlencoded",
            "Host": "100067.connect.garena.com",
            "User-Agent": "GarenaMSDK/4.0.19P4(G011A ;Android 9;en;US;)"
        }
        await asyncio.sleep(0.2)
        target = await host_pinned_url(url)
        resp = await asyncio.to_thread(requests.get, target, headers=hdrs, timeout=10, verify=False)
        data = resp.json()

        if 'error' in data:
            return None

        open_id = data.get('open_id')
        platform = data.get('platform', 4)

        if not open_id:
            return None

        login_payload_data = await build_majorlogin_payload(open_id, access_token, str(platform), client_version)
        if not login_payload_data:
            return None

        majorlogin_response = await send_majorlogin(login_payload_data, release_version, server_url)
        if majorlogin_response is None:
            return None

        getlogin_result = await send_getlogin(
            login_payload_data,
            majorlogin_response.url,
            majorlogin_response.token,
            release_version
        )
        if getlogin_result is None:
            return None

        res_proto, dict_res = getlogin_result
        game_account_id = int(getattr(majorlogin_response, "account_id", 0) or 0)
        lock_region = (
            getattr(majorlogin_response, "lockRegion", None)
            or getattr(majorlogin_response, "region", None)
            or FORCE_REGION
        )
        profile_image = await fetch_profile_card(game_account_id, lock_region)

        acc_id = str(game_account_id or majorlogin_response.account_id)
        level = int(get_proto_field(dict_res, 6, 1))
        exp = int(get_proto_field(dict_res, 7, 0))
        likes = int(get_proto_field(dict_res, 8, 0))
        nickname = res_proto.nickname or get_proto_field(dict_res, 4, f"Player_{acc_id}")
        region = majorlogin_response.region or get_proto_field(dict_res, 3, None) or FORCE_REGION

        bot_state.register_account(uid=acc_id, nickname=nickname, region=region, level=level, exp=exp, likes=likes)
        if profile_image and acc_id in bot_state.accounts:
            bot_state.accounts[acc_id]["profile_image"] = profile_image

        account_data = {
            'account_id': majorlogin_response.account_id,
            'nickname': nickname,
            'region': region,
            'lock_region': lock_region,
            'level': level,
            'exp': exp,
            'likes': likes,
            'open_id': open_id,
            'access_token': access_token,
            'platform': str(platform),
            'token': majorlogin_response.token,
            'server_time': majorlogin_response.server_time,
            'aes_ak': majorlogin_response.aes_ak,
            'iv_i': majorlogin_response.iv_i,
            'functional_addrs': res_proto.functional_addrs or get_proto_field(dict_res, 14),
            'informational_addrs': res_proto.informational_addrs or get_proto_field(dict_res, 32),
            'release_version': release_version,
            'client_version': client_version,
            'server_url': majorlogin_response.url,
            'login_payload_data': login_payload_data,
            'auth_type': 'token',
            'auth_token': access_token,
            'profile_image': profile_image,
        }
        _register_credentials(account_data)
        cache_set(cache_key, account_data)
        try:
            aid = str(account_data['account_id'])
            tl = _resolve_target_for_account(aid, bot_state.accounts.get(aid))
            if tl is not None and aid in bot_state.accounts:
                bot_state.accounts[aid]["target_level"] = tl
            await maybe_check_target_level(aid, int(level))
        except Exception as e:
            print_warning(f"[TARGET] post-login check: {e}")
        return account_data
    except Exception as e:
        print_error(f"process_account_token error: {e}")
        return None


# =============================================================================
# HOMER EQUIP
# =============================================================================

# -*- coding: utf-8 -*-
"""
Homer character equip module — ported from homer/main.py (RG RIFAT 07)
Equips Homer + 3 passives on both presets (1 and 50) via SelectPresetLoadout RPC.
Called once per account before any match; result cached in account_status.
"""

# ── Homer character constants ──────────────────────────────────────────────
HOMER_CHARACTER_ID  = 102000037
HOMER_ACTIVE_SKILL  = 5506          # Senses Shockwave
HOMER_PASSIVES      = [706, 4806, 4106]  # Kelly, Chrono, D-Bee

UNLOCK_GROUPS       = [1, 2, 3, 4, 7, 8, 9, 10]
DEFAULT_RELEASE_VER = "OB55"

_HEADERS_BASE = {
    "User-Agent":       "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
    "Connection":       "Keep-Alive",
    "Accept-Encoding":  "deflate, gzip",
    "Content-Type":     "application/x-www-form-urlencoded",
    "Expect":           "100-continue",
    "X-Unity-Version":  "2018.4.12f1",
    "X-GA":             "v1 1",
    "Accept":           "*/*",
}

# ── Protobuf helpers (no external library) ───────────────────────────────
def _enc_vi(n: int) -> bytes:
    if n < 0:
        n = (1 << 64) + n
    r = bytearray()
    while n > 0x7F:
        r.append((n & 0x7F) | 0x80)
        n >>= 7
    r.append(n & 0x7F)
    return bytes(r)

def pb_v(field: int, value: int) -> bytes:
    return _enc_vi((field << 3) | 0) + _enc_vi(value)

def pb_l(field: int, value: bytes | str) -> bytes:
    if isinstance(value, str):
        value = value.encode()
    return _enc_vi((field << 3) | 2) + _enc_vi(len(value)) + value

def build_equip_wire(
    char_id: int,
    act_id: int = 0,
    passives: Optional[List[int]] = None,
    preset_id: int = 1,
    name: str = "SFUDP",
) -> bytes:
    ps = [x for x in (passives or []) if x > 0][:3]

    f1 = pb_v(1, char_id)

    f2 = bytearray()
    f2 += pb_v(1, char_id)
    f2 += pb_l(2, b"".join(_enc_vi(i) for i in range(4)))
    sk = ([act_id] if act_id > 0 else [0]) + ps
    while len(sk) < 4:
        sk.append(0)
    f2 += pb_l(3, b"".join(_enc_vi(s) for s in sk))
    f2 += pb_l(4, b"".join(_enc_vi(0) for _ in range(4)))

    en = bytearray()
    en += pb_v(1, preset_id)
    en += pb_v(2, char_id)
    s0 = bytearray()
    if act_id > 0:
        s0 += pb_v(2, act_id)
    en += pb_l(3, bytes(s0))
    for idx, s in enumerate(ps, 1):
        sl = bytearray()
        sl += pb_v(1, idx)
        if s > 0:
            sl += pb_v(2, s)
        en += pb_l(3, bytes(sl))
    en += pb_l(6, name)

    root = bytearray()
    root += pb_l(1, bytes(f1))
    root += pb_l(2, bytes(f2))
    root += pb_l(6, pb_l(1, bytes(en)))
    root += pb_v(11, 1)
    return bytes(root)

# ── Crypto (same keys as the main project) ────────────────────────────────
def _aes_enc(data: bytes) -> bytes:
    return AES.new(AES_KEY, AES.MODE_CBC, AES_IV).encrypt(pad(data, 16))

# ── HTTP POST helper ───────────────────────────────────────────────────────
async def _post_rpc(
    client: httpx.AsyncClient,
    server_url: str,
    path: str,
    jwt_token: str,
    raw_payload: bytes,
    release_version: str = DEFAULT_RELEASE_VER,
) -> Tuple[int, bytes]:
    url = f"{server_url.rstrip('/')}/{path}"
    host = server_url.replace("https://", "").replace("http://", "").split("/")[0]
    headers = dict(_HEADERS_BASE)
    headers.update({
        "Authorization":  f"Bearer {jwt_token.strip()}",
        "Host":           host,
        "ReleaseVersion": release_version,
        "X-GA-SV":        str(int(time.time())),
    })
    try:
        r = await client.post(url, headers=headers, content=_aes_enc(raw_payload))
        return r.status_code, r.content
    except Exception as exc:
        log_warn(f"[HOMER-EQUIP] RPC {path} error: {exc}")
        return 0, b""

# ── Character unlock ──────────────────────────────────────────────────────
async def _unlock_characters(
    client: httpx.AsyncClient,
    server_url: str,
    jwt_token: str,
    release_version: str = DEFAULT_RELEASE_VER,
) -> bool:
    # Trigger newbie guide first (best-effort)
    await _post_rpc(client, server_url, "GetNewbieGuideDesc",
                    jwt_token, pb_v(1, 2), release_version)
    ok_count = 0
    for group_id in UNLOCK_GROUPS:
        code, _ = await _post_rpc(
            client, server_url, "GiveAccountNewbieRoles",
            jwt_token, pb_v(1, group_id), release_version,
        )
        if code in (200, 400):
            ok_count += 1
    return ok_count >= len(UNLOCK_GROUPS) // 2

# ── Equip Homer on both presets ───────────────────────────────────────────
async def equip_homer(
    jwt_token: str,
    server_url: str,
    release_version: str = DEFAULT_RELEASE_VER,
    char_id: int = HOMER_CHARACTER_ID,
    act_id: int = HOMER_ACTIVE_SKILL,
    passives: Optional[List[int]] = None,
) -> bool:
    """
    Equip Homer + 3 passives on preset 1 and preset 50.
    Returns True if both presets returned HTTP 200.
    """
    if passives is None:
        passives = list(HOMER_PASSIVES)

    async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
        await _unlock_characters(client, server_url, jwt_token, release_version)

        results = {}
        for preset_id in (1, 50):
            wire = build_equip_wire(char_id, act_id, passives, preset_id)
            code, _ = await _post_rpc(
                client, server_url, "SelectPresetLoadout",
                jwt_token, wire, release_version,
            )
            results[preset_id] = code

    p1, p50 = results.get(1), results.get(50)
    success = (p1 == 200 and p50 == 200)
    if success:
        log_ok(f"[HOMER-EQUIP] Homer equipped (preset 1 HTTP {p1}, preset 50 HTTP {p50})")
    else:
        log_warn(f"[HOMER-EQUIP] Partial — preset 1 HTTP {p1}, preset 50 HTTP {p50}")
    return success

# ── High-level helper: equip if not already equipped ─────────────────────
async def ensure_homer_equipped(
    uid: str,
    jwt_token: str,
    server_url: str,
    release_version: str = DEFAULT_RELEASE_VER,
    force: bool = False,
) -> bool:
    """
    Check account_status to see if homer was already equipped for this uid.
    If not (or force=True), call equip_homer() and persist the result.
    Returns True if homer is equipped (or was already).
    """
    if not force and get_homer_equipped(str(uid)):
        log_info(f"[HOMER-EQUIP] UID {uid} already equipped — skip")
        return True
    log_info(f"[HOMER-EQUIP] Equipping homer on UID {uid}...")
    success = await equip_homer(jwt_token, server_url, release_version)
    if success:
        set_homer_equipped(str(uid), True)
    return success


# =============================================================================
# GAMEPLAY (LEVEL MODE)
# =============================================================================


async def _inc_match(uid: str) -> int:
    async with _get_match_counter_lock():
        _match_counters[uid] = _match_counters.get(uid, 0) + 1
        return _match_counters[uid]

async def _dec_match(uid: str) -> int:
    async with _get_match_counter_lock():
        cur = max(0, _match_counters.get(uid, 0) - 1)
        _match_counters[uid] = cur
        return cur

async def _get_match_count(uid: str) -> int:
    return _match_counters.get(uid, 0)

async def _get_total_match_count() -> int:
    return sum(_match_counters.values())

def dashboard_status_for(uid: str, active_matches: int) -> str:
    if active_matches and active_matches > 0:
        return "IN_MATCH"
    return "ONLINE"

def publish_status(uid, active_matches: int):
    try:
        st = dashboard_status_for(uid, active_matches)
        bot_state.update_status(str(uid), st, active_matches)
    except Exception:
        pass


async def build_tcp_startup_packet(account_id, token, server_time, key, iv, region="", typ="OnLine"):
    uid_hex = f"{int(account_id):016x}"
    timestamp_hex = f"{int(server_time):08x}"
    encode_token = token.encode()
    encrypted_packet = (await aes_encrypt(encode_token, key, iv)).hex()
    encrypted_packet_length = f"{len(encrypted_packet) // 2:08x}"
    if typ == "OnLine":
        prefix = region_tcp_online_prefix(region)
        return f"{prefix}{uid_hex}{timestamp_hex}00000000{encrypted_packet_length}{encrypted_packet}"
    prefix = region_tcp_other_prefix(region)
    return f"{prefix}{uid_hex}{timestamp_hex}{encrypted_packet_length}{encrypted_packet}"

async def send_keep_alive(region=""):
    try:
        return bytes.fromhex(region_ka_prefix(region))
    except Exception:
        return bytes.fromhex("0215")


async def start_game_lone_wolf(region, client_version, writer, key, iv, guard=None):
    packet = bytes.fromhex("080112f40a0a012210493a0d0a044944433310f6011a02504b3a0c0a0449444331102a1a0253473a0c0a044944433210201a02545740014a0901090a121920222729580162fe090a8001303830363830383737354243374542353032303130303030303030303030303430303035303030313030303030303030384544333238304430463030303030303436373632353134303030303030303030303030303030303030303030303030303030303030303030303030303066663030303030303030636163666131366410181ab9037f585c571100084d0602570955090a54000a010c0c050c06040051550a055301545b07005353040d1204044d7c5c40464b19081d041c1208034c02547f7a025a6d40637e7a604b477a675b7c750f7708677903717c081600457b5d6053775b7c4f7a657e7656537677415a7b545e5b5b515361460512535a5f4d1e637a1f7648410749695477786558604e695c655d5150005354590f587a00007105067b0f120902495f704d6065425672425d6f505d097a644619076d7a416f437776690f1109444502651e5262621d68087c426f5f42524379594b1a761a5a4d42780c13004e757953715f4941537b5e1d084a7062067c4e40487558565f0660780c1a084c0558644d57464c657b427a7455690e404479626f437d6a7e507264081600014d7848787b4b660550090159027a48577e5c41616860425663605d080c16064d711a015661620975431e035f05586407504d1a5a067612771b65020c1b054953487e5047786b7009606c00436868760761455b1e464f067e74750f1103084d447207125059407c5674435e60654b43450305497602405c7e4e700d11074d5747465c795f5f5b7340534d5c1e61765141537863461708616f460422047b5a5f5c300c3a0916500870697860151d4208312e3133322e3231480350025a99050362625351363863485177346d416456324b796f566c546c6865587274756f63644b54726a36474b4736323946636a4b4234704a646c76524e342b3639692f3276443031717675704f6d4e4d614533476c327649476e357765584371495362496e73336a4448366f674f4744416c64686137744f644d304a4670664130416a444b326f43646b4539644f766b477437475842304943556b4a51764a7532536443554332504630646a5a58304b30655574757174624d775a334769494b382f377648712b4f442f5578634a6e495767616566784d786b4835786c76744f537a444b53592b5662467450476b7968575855625749655565696e59686c59614a63524d72424e7a323177472f466155373974395350486e464a2f5a767a6f446d7566456a4a7650367a4a677a4e524c513870383168617255596b4832586c79506370544e682b43336d7a462b4c7a4638324a4574724d70342b6c79696e7351756e474d4833776c74396a6f6f42466372456a5863304a6c324579676737456859766778597237616c69797842487255324d6d512b59526f6d584d703272666c496844507a46696c455373703179384d424f4c5a4e62476a38664b48546a6557547a65576b536b4768324e4a7a765232444d533168673852494c4d2f5a396f446a57584165443657624a463839464c47724833336a44373246434a4761766a5333646545386e4b43737938596974657857386e4752727264573638724b396252633352524c545736533561586f41334e4f64624378706c6b752f47734a5a4e6e5a463335316c303964787173716f513241525a5971536f2f2b6b612f386e63612f59584d4a493052634b43584c616f4b4a773550733277514b506a3471465a4849686c6451687472714c54327131782f4e367a504b54656f5775586970a201050803108a03a201050804108703a20105080510c001a20105081d10cc01a2010408161078a20105080e10af01a201020815")
    proto = Snowflake_pb2.StartMatch()
    proto.ParseFromString(packet)
    if hasattr(proto.main, 'region_list') and len(proto.main.region_list) > 0:
        proto.main.region_list[0].region = region
        if len(proto.main.region_list) > 1:
            proto.main.region_list[1].region = region
    if hasattr(proto.main, 'client_version'):
        proto.main.client_version.remote_version = client_version
    packet = proto.SerializeToString()
    encrypted_packet = (await aes_encrypt(packet, key, iv)).hex()
    packet_length = len(encrypted_packet) // 2
    hex_length = hex(packet_length)[2:]
    hex_length = hex_length if len(hex_length) > 1 else "0" + hex_length
    cmd_prefix = region_startmatch_prefix(region)
    final_packet = cmd_prefix + "0" * (6 - len(hex_length)) + hex_length + encrypted_packet
    await asyncio.sleep(0.1)
    if guard is not None and not guard():
        return False
    writer.write(bytes.fromhex(final_packet))
    await writer.drain()
    return True


async def _stop_aux_task(task, stop_event=None, grace: float = 2.0):
    """Signal an aux task to stop and await it; cancel only if it hangs."""
    if stop_event is not None:
        stop_event.set()
    if not task:
        return
    try:
        await asyncio.wait_for(task, timeout=grace)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    except (asyncio.CancelledError, Exception):
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


async def _play_udp_match(mode: str, server_ip_port, prepare, post, udp_key, udp_mask,
                          account_id, match_index: int, on_match_complete=None,
                          player_region="", key=None, iv=None, mode_id=None, map_id=None):
    profile = MODE_PROFILES[mode]
    if mode_id is None:
        mode_id = profile.get("mode_id")
    if map_id is None:
        map_id = profile.get("map_id")
    match_max_duration = float(profile.get("max_duration") or MAX_MATCH_DURATION)
    lbl = f"[MATCH #{match_index}] [{mode}]"
    match_start_time = time.time()
    last_activity = match_start_time

    ping_task = None
    movement_task = None
    sock = None
    ping_stop = asyncio.Event()
    movement_stop = asyncio.Event()
    uid_str = str(account_id)
    completed_cleanly = False
    try:
        ip, port = server_ip_port.split(":")
        port = int(port)
        resolved_ip = await resolve_host_cloudflare(ip)
        server_addr = (resolved_ip, port)

        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("0.0.0.0", 0))
        except Exception:
            pass
        optimize_udp_socket(sock)
        sock.setblocking(False)
        udp_key_bytes = bytes.fromhex(udp_key)

        await asyncio.sleep(0.1)

        hello_identity = f"{account_id}_2585"
        # HELLO must use the allocation-provided UDP mask; do not substitute a fixed layout.
        hello_packet = await build_hello_packet(hello_identity, udp_key_bytes, udp_mask)
        hello_bytes = bytes.fromhex(hello_packet)
        await loop.sock_sendto(sock, hello_bytes, server_addr)

        ack_state = "waiting_for_hello_reply"
        prepare_sent = False
        post_sent = False
        join_match_received = False
        local_closed = False
        send_lock = asyncio.Lock()
        MAX_IDLE_BEFORE_HELLO_RESEND = 7.0

        ping_task = asyncio.create_task(
            keepalive_ping(sock, resolved_ip, port, udp_key_bytes, udp_mask, ping_stop)
        )
        print_colored(
            f"{lbl} UDP Match Connected → {server_ip_port}",
            Colors.MAGENTA
        )

        movement_ctrl = None

        async def movement_simulator():
            nonlocal movement_ctrl
            try:
                movement_ctrl = MovementController(
                    account_id=account_id,
                    udp_sock=sock,
                    udp_server=server_addr,
                    udp_key_bytes=udp_key_bytes,
                    match_code=udp_mask,
                )
                movement_ctrl.start()
                # Simulator only ever starts after prepare+post was sent,
                # so the handshake gate can be released immediately.
                movement_ctrl.notify_handshake_complete()
                while not movement_stop.is_set():
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log_err(f"{lbl} movement error: {e}")
            finally:
                try:
                    if movement_ctrl:
                        await movement_ctrl.stop()
                except Exception:
                    pass

        def feed_movement_frame(frame):
            if movement_ctrl is None or not frame:
                return
            try:
                movement_ctrl.handle_server_frame(frame)
            except Exception:
                pass

        async def send_prepare_post_inline():
            nonlocal ack_state, prepare_sent, post_sent, movement_task
            if post_sent:
                return
            async with send_lock:
                if post_sent:
                    return
                try:
                    if not prepare_sent:
                        prepare_bytes = bytes.fromhex(prepare)
                        await loop.sock_sendto(sock, prepare_bytes, server_addr)
                        prepare_sent = True
                        await asyncio.sleep(random.uniform(0.05, 0.1))
                        prepare_ack = await build_packet(
                            0x68, (await layouts_from_mask(udp_mask))[1],
                            0, 2, None, 1, b"\x01\x00", udp_key_bytes
                        )
                        await loop.sock_sendto(sock, prepare_ack, server_addr)
                        await asyncio.sleep(random.uniform(0.05, 0.2))
                    post_bytes = bytes.fromhex(post)
                    await loop.sock_sendto(sock, post_bytes, server_addr)
                    post_sent = True
                    ack_state = "prepare_post_sent"
                    if movement_task is None and not movement_stop.is_set():
                        movement_task = asyncio.create_task(movement_simulator())
                    if movement_ctrl is not None:
                        movement_ctrl.notify_handshake_complete()
                except Exception:
                    pass


        while not local_closed:
            elapsed = time.time() - match_start_time
            if elapsed > match_max_duration:
                log_info(f"{lbl} max duration reached ({int(elapsed)}s)")
                completed_cleanly = True
                break

            if ack_state == "prepare_post_sent":
                time_in_match = time.time() - match_start_time
                idle_time = time.time() - last_activity
                if time_in_match > LW_HOLD_SECONDS or idle_time > LW_DEAD_SILENCE_SECONDS:
                    log_ok(f"{lbl} Finished naturally")
                    completed_cleanly = True
                    break

            try:
                response, from_addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 65535), timeout=1.5
                )
                if response:
                    last_activity = time.time()
                    frame = await decode_packet(response, udp_key_bytes, udp_mask)
                    if not frame:
                        pass  # undecodable datagram — ignore silently
                    else:
                        feed_movement_frame(frame)
                        ptype = await classify(frame)

                        if frame['cmd'] in (103, 107):
                            log_ok(f"{lbl} Finished naturally")
                            completed_cleanly = True
                            local_closed = True
                            break

                        if frame['cmd'] == 101:
                            try:
                                ack_pkt = await build_packet(
                                    0x68, (await layouts_from_mask(udp_mask))[1],
                                    0, 2, None, 1, b"\x01\x00", udp_key_bytes
                                )
                                await loop.sock_sendto(sock, ack_pkt, server_addr)
                            except Exception:
                                pass
                            continue

                        if frame['cmd'] == 2000:
                            content = frame.get('content', b'')
                            reply_content = content[:-1] if len(content) > 1 else content
                            _, nr_layout_sync = await layouts_from_mask(udp_mask)
                            sync_reply = await build_packet(
                                0x64, nr_layout_sync, 0, 2000, None, 0, reply_content, udp_key_bytes, encrypted=False
                            )
                            await loop.sock_sendto(sock, sync_reply, server_addr)
                            continue

                        if frame['cmd'] == 768:
                            content = frame.get('content', b'')
                            _, nr_layout_sync = await layouts_from_mask(udp_mask)
                            hb_reply = await build_packet(
                                random.choice([0x68, 0x6A, 0x6B, 0x6C]),
                                nr_layout_sync, 0, 768, None, 0,
                                content + b"\x00\x00\x00",
                                udp_key_bytes, encrypted=False
                            )
                            await loop.sock_sendto(sock, hb_reply, server_addr)
                            continue

                        if frame['cmd'] == 513:
                            content = frame.get('content', b'')
                            if content:
                                _, nr_layout_sync = await layouts_from_mask(udp_mask)
                                sync_reply = await build_packet(
                                    random.choice([0x68, 0x6A, 0x6B, 0x6C]),
                                    nr_layout_sync, 0, 513, None, 0,
                                    content, udp_key_bytes, encrypted=False
                                )
                                await loop.sock_sendto(sock, sync_reply, server_addr)
                            continue

                        if frame['cmd'] in [258, 261, 984, 1005]:
                            continue

                        if ptype in ["ACK", "PING", "HELLO", "JOIN_MATCH"]:
                            if ptype == "HELLO" and ack_state == "waiting_for_hello_reply":
                                typ, reply = await reply_for(
                                    frame, udp_key_bytes, udp_mask, ack_style="short"
                                )
                                if reply:
                                    await loop.sock_sendto(sock, reply, from_addr)
                                ack_state = "ack_sent_waiting"
                            elif ptype == "ACK":
                                if ack_state == "waiting_for_hello_reply":
                                    typ, reply = await reply_for(
                                        frame, udp_key_bytes, udp_mask, ack_key=0x68
                                    )
                                    if reply:
                                        await loop.sock_sendto(sock, reply, from_addr)
                                    ack_state = "ready_to_send_prepare"
                                elif ack_state == "ack_sent_waiting":
                                    ack_state = "ready_to_send_prepare"
                                else:
                                    typ, reply = await reply_for(frame, udp_key_bytes, udp_mask)
                                    if reply:
                                        await loop.sock_sendto(sock, reply, from_addr)
                            elif ptype == "PING":
                                typ, reply = await reply_for(frame, udp_key_bytes, udp_mask)
                                if reply:
                                    await loop.sock_sendto(sock, reply, from_addr)
                            elif ptype == "JOIN_MATCH" and not join_match_received:
                                typ, reply = await reply_for(frame, udp_key_bytes, udp_mask)
                                if reply:
                                    await loop.sock_sendto(sock, reply, from_addr)
                                    join_match_received = True

            except asyncio.TimeoutError:
                _now = time.time()
                if ack_state == "ready_to_send_prepare" and not prepare_sent:
                    await send_prepare_post_inline()
                elif ack_state == "waiting_for_hello_reply":
                    if (_now - last_activity) > MAX_IDLE_BEFORE_HELLO_RESEND:
                        try:
                            await loop.sock_sendto(sock, hello_bytes, server_addr)
                        except Exception:
                            pass
                        last_activity = _now
                    if (_now - match_start_time) > UDP_HANDSHAKE_TIMEOUT:
                        break
                elif ack_state == "prepare_post_sent":
                    time_in_match = _now - match_start_time
                    idle_time = _now - last_activity
                    if time_in_match > LW_HOLD_SECONDS or idle_time > LW_DEAD_SILENCE_SECONDS:
                        log_ok(f"{lbl} Finished naturally")
                        completed_cleanly = True
                        break
                continue
            except BlockingIOError:
                await asyncio.sleep(0.05)
            except OSError:
                await asyncio.sleep(0.5)
                continue
            except Exception:
                await asyncio.sleep(0.5)
                continue

            if ack_state == "ready_to_send_prepare" and not post_sent:
                await send_prepare_post_inline()


        # appflow rule: if we successfully sent POST (joined session), count as played
        if not completed_cleanly and post_sent:
            completed_cleanly = True
            log_ok(f"{lbl} Counted as played (joined match)")

        return f"match #{match_index} finished"
    except asyncio.CancelledError:
        log_warn(f"{lbl} cancelled")
        raise
    except Exception as e:
        log_err(f"{lbl} error: {e}")
        return f"match #{match_index} error"
    finally:
        # Count the finished match first (UDP conversation is over at this
        # point), then tear down aux tasks and the socket — appflow order.
        if completed_cleanly:
            try:
                bot_state.increment_match(uid_str)
            except Exception as e:
                log_err(f"{lbl} increment_match failed: {e}")
            if on_match_complete:
                try:
                    asyncio.create_task(on_match_complete())
                except Exception as e:
                    log_warn(f"[EXP-REFRESH] post-match trigger failed: {e}")

        await _stop_aux_task(ping_task, ping_stop)
        await _stop_aux_task(movement_task, movement_stop)
        if sock:
            try:
                sock.close()
            except Exception:
                pass

        remaining = await _dec_match(uid_str)
        total = await _get_total_match_count()
        log_info(f"{lbl} Closed. UID active: {remaining} | Total active: {total}")
        try:
            bot_state.update_status(uid_str, "IN_MATCH" if remaining > 0 else "ONLINE", remaining)
        except Exception:
            pass


async def play_game_lw(server_ip_port, prepare, post, udp_key, udp_mask,
                       account_id, player_region, client_version, key, iv,
                       match_index: int, on_match_complete=None):
    return await _play_udp_match(
        "LW", server_ip_port, prepare, post, udp_key, udp_mask,
        account_id, match_index, on_match_complete,
        player_region=player_region, key=key, iv=iv,
        mode_id=MODE_PROFILES["LW"]["mode_id"], map_id=MODE_PROFILES["LW"]["map_id"],
    )


async def functional_lone_wolf(addrs, starter_packet, account_region, client_version,
                                key, iv, account_id="", account_data=None,
                                account_level: int = 2, max_reconnects=10):
    reconnects = 0
    ip, port = addrs.split(":")
    play_matches: List[asyncio.Task] = []
    no_response_count = 0
    search_attempts = 0
    current_level = int(account_level or 2)
    last_start_time = 0.0
    uid_str = str(account_id)

    consecutive_parse_failures = 0

    current_token = starter_packet
    current_key = key
    current_iv = iv
    current_account_data = account_data

    async def trigger_post_match_refresh():
        await asyncio.sleep(EXP_REFRESH_AFTER_MATCH_DELAY)
        try:
            cd = bot_state.account_credentials.get(uid_str)
            if cd:
                await refresh_account_profile(cd)
        except Exception as e:
            log_warn(f"[EXP-REFRESH] post-match refresh error: {e}")

    def _resolve_current_level() -> int:
        lvl = int(account_level or 2)
        try:
            if current_account_data and current_account_data.get('level') is not None:
                lvl = max(lvl, int(current_account_data['level']))
        except Exception:
            pass
        try:
            live = bot_state.accounts.get(uid_str, {}).get('level')
            if live is not None:
                lvl = max(lvl, int(live))
        except Exception:
            pass
        try:
            cred = bot_state.account_credentials.get(uid_str)
            if cred and cred.get('level') is not None:
                lvl = max(lvl, int(cred['level']))
        except Exception:
            pass
        return lvl

    def _control_state() -> str:
        try:
            acc = bot_state.accounts.get(uid_str)
            if not acc:
                return "run"
            if acc.get("control") == "stop":
                return "stop"
            if acc.get("control") == "pause":
                return "pause"
        except Exception:
            pass
        return "run"

    def _refresh_level() -> None:
        nonlocal current_level
        lvl = _resolve_current_level()
        if lvl != current_level:
            log_info(f"[LEVEL] UID {uid_str}: {current_level} -> {lvl}")
            current_level = lvl
            try:
                asyncio.create_task(maybe_check_target_level(uid_str, lvl))
            except Exception:
                pass

    try:
        while True:
            ctrl = _control_state()
            if ctrl == "stop":
                log_warn(f"[FUNCTIONAL] Stop requested for {uid_str} — exiting worker")
                for m in play_matches:
                    if not m.done():
                        m.cancel()
                if play_matches:
                    await asyncio.gather(*play_matches, return_exceptions=True)
                play_matches.clear()
                try:
                    bot_state.update_status(uid_str, "STOPPED", 0)
                except Exception:
                    pass
                return
            if ctrl == "pause":
                try:
                    bot_state.update_status(uid_str, "PAUSED", await _get_match_count(uid_str))
                except Exception:
                    pass
                await asyncio.sleep(1.5)
                continue

            writer = None
            try:
                if current_account_data:
                    fresh = None
                    if current_account_data.get('auth_type') == 'guest' and current_account_data.get('auth_uid'):
                        fresh = cache_get(str(current_account_data['auth_uid']))
                    elif current_account_data.get('auth_type') == 'token' and current_account_data.get('auth_token'):
                        fresh = cache_get(f"tok_{current_account_data['auth_token'][:20]}")

                    if fresh:
                        current_account_data = fresh
                        current_key = fresh['aes_ak']
                        current_iv = fresh['iv_i']
                        current_token = await build_tcp_startup_packet(
                            fresh['account_id'],
                            fresh['token'],
                            fresh['server_time'],
                            current_key,
                            current_iv,
                            region=fresh.get('region', account_region),
                            typ='OnLine'
                        )
                    else:
                        log_warn(f"[FUNCTIONAL] Cache miss for {uid_str} → re-login needed")
                        try:
                            if current_account_data.get('auth_uid'):
                                cache_invalidate(str(current_account_data['auth_uid']))
                            if current_account_data.get('auth_token'):
                                cache_invalidate(f"tok_{current_account_data['auth_token'][:20]}")
                        except Exception:
                            pass
                        raise ConnectionError("Cache expired, triggering fresh login")

                _refresh_level()

                gateway_ka_task = None
                gateway_ka_stop = asyncio.Event()

                resolved_ip = await resolve_host_cloudflare(ip)
                reader, writer = await asyncio.open_connection(resolved_ip, int(port))

                raw_sock = writer.get_extra_info('socket')
                if raw_sock:
                    optimize_tcp_socket(raw_sock)

                writer.write(bytes.fromhex(current_token))
                await writer.drain()

                try:
                    init_ka = await send_keep_alive(account_region)
                    if init_ka and writer and not writer.is_closing():
                        writer.write(init_ka)
                        await asyncio.wait_for(writer.drain(), timeout=3)
                except Exception:
                    pass

                log_ok(f"[FUNCTIONAL] TCP Gateway Connected for UID: {uid_str} (DNS: {resolved_ip})")
                reconnects = 0
                no_response_count = 0
                last_start_time = 0.0

                async def gateway_keepalive_loop():
                    try:
                        ka_bytes = await send_keep_alive(account_region)
                    except Exception:
                        ka_bytes = None
                    while not gateway_ka_stop.is_set():
                        try:
                            await asyncio.sleep(5.0)
                            if gateway_ka_stop.is_set():
                                break
                            if writer and not writer.is_closing() and ka_bytes:
                                writer.write(ka_bytes)
                                await writer.drain()
                        except Exception:
                            break

                gateway_ka_task = asyncio.create_task(gateway_keepalive_loop())


                async def live_stack() -> int:
                    play_matches[:] = [m for m in play_matches if not m.done()]
                    cnt = await _get_match_count(uid_str)
                    return max(int(cnt), len(play_matches))

                async def send_start_match():
                    nonlocal search_attempts, last_start_time
                    if _control_state() != "run":
                        return False
                    profile = MODE_PROFILES["LW"]
                    mode_tag = profile["tag"]
                    stack_cap = max_stack_lw()
                    active = await live_stack()
                    if active >= stack_cap:
                        log_info(
                            f"{mode_tag} at cap {active}/{stack_cap} "
                            f"— withholding StartMatch"
                        )
                        try:
                            publish_status(uid_str, active)
                        except Exception:
                            pass
                        return False
                    current_region = resolve_region(account_region)
                    search_attempts += 1

                    log_info(
                        f"[{mode_tag}] Sending StartMatch #{search_attempts} "
                        f"region: {current_region} (Lvl {current_level}) "
                        f"[stack {active}/{stack_cap}] mode_id={profile['mode_id']} map_id={profile['map_id']}"
                    )
                    try:
                        await asyncio.sleep(random.uniform(0.15, 0.4))
                        active2 = await live_stack()
                        if active2 >= stack_cap or _control_state() != "run":
                            log_info(
                                f"Cap hit during delay ({active2}/{stack_cap}) — abort StartMatch"
                            )
                            return False
                        sent = await start_game_lone_wolf(
                            current_region, client_version, writer, current_key, current_iv,
                            guard=lambda: _control_state() == "run",
                        )
                        if sent is False:
                            return False
                        log_ok(
                            f"[{mode_tag}] StartMatch packet sent "
                            f"(active {active2}/{stack_cap})"
                        )
                        publish_status(uid_str, active2)
                    except Exception as e:
                        log_err(f"start_game_lone_wolf error: {e}")
                        return False
                    last_start_time = asyncio.get_running_loop().time()
                    return True

                await send_start_match()
                while True:
                    ctrl = _control_state()
                    if ctrl == "stop":
                        raise ConnectionError("Stop requested")
                    if ctrl == "pause":
                        try:
                            bot_state.update_status(uid_str, "PAUSED", await _get_match_count(uid_str))
                        except Exception:
                            pass
                        await asyncio.sleep(1.0)
                        continue

                    play_matches[:] = [m for m in play_matches if not m.done()]

                    _refresh_level()

                    active_count = await live_stack()
                    try:
                        publish_status(uid_str, active_count)
                    except Exception:
                        pass

                    now = asyncio.get_running_loop().time()
                    random_interval = START_MATCH_INTERVAL + random.uniform(-0.5, 1.0)
                    stack_cap = max_stack_lw()
                    if active_count >= stack_cap:
                        pass
                    elif now - last_start_time >= max(1.5, random_interval):
                        await send_start_match()

                    try:
                        data = await asyncio.wait_for(reader.read(8192), timeout=2.0)
                    except asyncio.TimeoutError:
                        no_response_count += 1
                        active_now = 0
                        try:
                            active_now = await live_stack()
                        except Exception:
                            pass
                        if no_response_count > 45 and active_now <= 0:
                            log_warn(f"[FUNCTIONAL] Gateway silent ({uid_str}). Reconnecting...")
                            raise ConnectionError("Gateway idle timeout")
                        continue

                    if not data:
                        raise ConnectionError("Connection closed by server")

                    hex_data = data.hex()
                    packet_length = len(data)
                    no_response_count = 0

                    if hex_data.startswith("0300") and 10 < packet_length < 30:
                        pass  # progress ack (silent)
                        continue

                    if hex_data.startswith("0300") and packet_length >= 300:
                        pass  # allocation received
                        print_colored("=" * 60, Colors.GREEN)
                        print_colored("MATCH FOUND! Loading...", Colors.GREEN)
                        print_colored("=" * 60, Colors.GREEN)

                        try:
                            res = json.loads(await decode_protobuf(hex_data[10:]))
                            token = None
                            udp_key = None
                            udp_mask = None
                            server_ip_port = None
                            match_account_id = None
                            block_val = None

                            if '42' in res and 'data' in res['42']:
                                udp_mask = res['42']['data']
                            if '5' in res and 'data' in res['5']:
                                res_field5 = res['5']['data']
                                server_ip_port = res_field5.get('2', {}).get('data')
                                udp_key = res_field5.get('3', {}).get('data')
                                token = res_field5.get('4', {}).get('data')
                                if '42' in res_field5:
                                    udp_mask = res_field5['42']['data']
                            if '1' in res and 'data' in res['1']:
                                match_account_id = res['1']['data']
                            if '5' in res and 'data' in res['5']:
                                block_val = res['5']['data'].get('1', {}).get('data')

                            effective_acc_id = match_account_id or account_id or "BD_BOT"
                            pass  # allocation parsed

                            if token and udp_key and udp_mask and server_ip_port:
                                pass  # fields present
                                acc_tok = ""
                                if current_account_data:
                                    acc_tok = current_account_data.get('access_token', '') or ""
                                match_profile = MODE_PROFILES["LW"]
                                selected_mode_id = match_profile["mode_id"]
                                selected_map_id = match_profile["map_id"]
                                mode_tag = match_profile["tag"].replace(" ", "_")
                                log_info(
                                    f"[TARGET] Mode: {mode_tag} | mode_id={selected_mode_id} | "
                                    f"map_id={selected_map_id} | UID: {uid_str}"
                                )
                                pass  # building payloads
                                prepare, post = await build_match_startup_packets(
                                    token, udp_key, udp_mask, effective_acc_id, block_val or 0,
                                    server_ip=server_ip_port,
                                    region=account_region,
                                    client_version=client_version,
                                    access_token=acc_tok,
                                    mode_id=selected_mode_id,
                                    map_id=selected_map_id
                                )

                                pass  # payloads built
                                match_index = await _inc_match(uid_str)
                                pass  # UDP connect message printed inside _play_udp_match (magenta)

                                try:
                                    gateway_ka_stop.set()
                                    if gateway_ka_task and not gateway_ka_task.done():
                                        gateway_ka_task.cancel()
                                except Exception:
                                    pass

                                in_match_ka_stop = asyncio.Event()

                                async def gateway_in_match_keepalive():
                                    try:
                                        ka_pulse = await send_keep_alive(account_region)
                                    except Exception:
                                        ka_pulse = None
                                    while not in_match_ka_stop.is_set():
                                        try:
                                            if writer and not writer.is_closing() and ka_pulse:
                                                writer.write(ka_pulse)
                                                await writer.drain()
                                        except Exception:
                                            break
                                        try:
                                            try:
                                                await asyncio.wait_for(reader.read(4096), timeout=4.0)
                                            except asyncio.TimeoutError:
                                                pass
                                        except Exception:
                                            break

                                gateway_in_match_task = asyncio.create_task(gateway_in_match_keepalive())
                                try:
                                    publish_status(uid_str, 1)
                                except Exception:
                                    pass

                                async def _lw_bg_match():
                                    try:
                                        await play_game_lw(
                                            server_ip_port,
                                            prepare,
                                            post,
                                            udp_key,
                                            udp_mask,
                                            effective_acc_id,
                                            "",
                                            client_version,
                                            current_key,
                                            current_iv,
                                            match_index=match_index,
                                            on_match_complete=trigger_post_match_refresh,
                                        )
                                    except Exception as e:
                                        log_warn(f"[MATCH #{match_index}] LW bg error: {e}")
                                    finally:
                                        try:
                                            in_match_ka_stop.set()
                                        except Exception:
                                            pass

                                bg = asyncio.create_task(_lw_bg_match())
                                play_matches.append(bg)
                                log_ok(
                                    f"[LW STACK] Match #{match_index} running in background "
                                    f"(UDP ground only) — dropping TCP to queue next"
                                )


                                try:
                                    in_match_ka_stop.set()
                                    if gateway_in_match_task and not gateway_in_match_task.done():
                                        gateway_in_match_task.cancel()
                                        try:
                                            await gateway_in_match_task
                                        except (asyncio.CancelledError, Exception):
                                            pass
                                except Exception:
                                    pass

                                try:
                                    writer.close()
                                    await writer.wait_closed()
                                except Exception:
                                    pass

                                consecutive_parse_failures = 0
                                active_now = await live_stack()
                                try:
                                    publish_status(uid_str, active_now)
                                except Exception:
                                    pass

                                stack_cap = max_stack_lw()
                                if active_now >= stack_cap:
                                    log_info(
                                        f"[LW STACK] Cap reached {active_now}/{stack_cap} — "
                                        f"wait for a free slot before next StartMatch"
                                    )
                                    await asyncio.sleep(max(0.3, NEW_MATCH_DELAY * 0.5))
                                else:
                                    log_info(
                                        f"[LW STACK] Slot free {active_now}/{stack_cap} — "
                                        f"reopen TCP + StartMatch"
                                    )
                                    await asyncio.sleep(max(0.2, min(1.0, NEW_MATCH_DELAY * 0.4)))

                                reconnects = 0
                                break

                            else:
                                consecutive_parse_failures += 1
                                log_warn(
                                    f"[FUNCTIONAL] Non-match big packet "
                                    f"(#{consecutive_parse_failures}/{MAX_CONSECUTIVE_PARSE_FAILURES}) "
                                    f"→ reconnecting"
                                )

                                if consecutive_parse_failures >= MAX_CONSECUTIVE_PARSE_FAILURES:
                                    log_err(
                                        f"[FUNCTIONAL] {MAX_CONSECUTIVE_PARSE_FAILURES}x parse failures "
                                        f"→ invalidating cache for fresh login"
                                    )
                                    if current_account_data:
                                        try:
                                            if current_account_data.get('auth_uid'):
                                                cache_invalidate(str(current_account_data['auth_uid']))
                                            if current_account_data.get('auth_token'):
                                                cache_invalidate(f"tok_{current_account_data['auth_token'][:20]}")
                                        except Exception:
                                            pass
                                    consecutive_parse_failures = 0

                                try:
                                    writer.close()
                                    await writer.wait_closed()
                                except Exception:
                                    pass
                                await asyncio.sleep(NON_MATCH_RECONNECT_DELAY)
                                break

                        except Exception as e:
                            log_err(f"[FUNCTIONAL] Match packet error: {e}")
                            consecutive_parse_failures += 1
                            if consecutive_parse_failures >= MAX_CONSECUTIVE_PARSE_FAILURES:
                                if current_account_data:
                                    try:
                                        if current_account_data.get('auth_uid'):
                                            cache_invalidate(str(current_account_data['auth_uid']))
                                        if current_account_data.get('auth_token'):
                                            cache_invalidate(f"tok_{current_account_data['auth_token'][:20]}")
                                    except Exception:
                                        pass
                                consecutive_parse_failures = 0
                            try:
                                writer.close()
                                await writer.wait_closed()
                            except Exception:
                                pass
                            await asyncio.sleep(NON_MATCH_RECONNECT_DELAY)
                            break

                    if 30 <= packet_length <= 40:
                        continue

            except asyncio.CancelledError:
                log_warn(f"[FUNCTIONAL] Cancelled — cancelling {len(play_matches)} UDP matches")
                for m in play_matches:
                    if not m.done():
                        m.cancel()
                if play_matches:
                    await asyncio.gather(*play_matches, return_exceptions=True)
                play_matches.clear()
                raise
            except Exception as e:
                log_err(f"[FUNCTIONAL] TCP state ({uid_str}): {e}")

                play_matches[:] = [m for m in play_matches if not m.done()]

                try:
                    gateway_ka_stop.set()
                    if gateway_ka_task and not gateway_ka_task.done():
                        gateway_ka_task.cancel()
                except Exception:
                    pass

                if writer:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass

                if "Cache expired" in str(e):
                    log_warn(f"[FUNCTIONAL] Triggering re-login for {uid_str}")
                    break

                reconnects += 1
                if reconnects > max_reconnects:
                    log_err("[FUNCTIONAL] Max reconnects reached, retrying...")
                    reconnects = 0
                    await asyncio.sleep(3)
                    continue

                await asyncio.sleep(min(reconnects, 2))

    except asyncio.CancelledError:
        log_warn(f"[FUNCTIONAL] Outer cancelled. {len(play_matches)} UDP matches still running.")
        for m in play_matches:
            if not m.done():
                m.cancel()
        if play_matches:
            await asyncio.gather(*play_matches, return_exceptions=True)
        play_matches.clear()
        raise


async def informational(addrs, starter_packet, key, iv, region="", max_reconnects=3):
    reconnects = 0
    ip, port = addrs.split(":")
    while True:
        writer = None
        ping_task = None
        try:
            resolved_ip = await resolve_host_cloudflare(ip)
            reader, writer = await asyncio.open_connection(resolved_ip, int(port))

            raw_sock = writer.get_extra_info('socket')
            if raw_sock:
                optimize_tcp_socket(raw_sock)

            writer.write(bytes.fromhex(starter_packet))
            await writer.drain()
            reconnects = 0

            try:
                init_ka = await send_keep_alive(region)
                if init_ka and writer and not writer.is_closing():
                    writer.write(init_ka)
                    await asyncio.wait_for(writer.drain(), timeout=3)
            except Exception:
                pass

            async def info_keepalive():
                ka_bytes = await send_keep_alive(region)
                while True:
                    interval = await get_randomized_interval(4.0, 6.5)
                    await asyncio.sleep(interval)
                    try:
                        if writer and not writer.is_closing():
                            writer.write(ka_bytes)
                            await writer.drain()
                    except Exception:
                        break

            ping_task = asyncio.create_task(info_keepalive())

            while True:
                data = await reader.read(8192)
                if not data:
                    raise ConnectionError("Connection closed")
        except asyncio.CancelledError:
            if ping_task and not ping_task.done():
                ping_task.cancel()
                try:
                    await ping_task
                except (asyncio.CancelledError, Exception):
                    pass
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
            raise
        except Exception:
            if ping_task and not ping_task.done():
                ping_task.cancel()
                try:
                    await ping_task
                except (asyncio.CancelledError, Exception):
                    pass
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
            reconnects += 1
            if reconnects > max_reconnects:
                await asyncio.sleep(3)
                reconnects = 0
            else:
                await asyncio.sleep(random.uniform(0.8, 1.5))


# =============================================================================
# ENGINE (LEVEL MODE)
# =============================================================================

print_success = log_ok
print_error = log_err
print_warning = log_warn
print_info = log_info













async def run_account_worker(account_data: Dict, label: str):
    acc_id = str(account_data['account_id'])
    informational_task = None
    exp_task = None
    try:
        reg = gateway_region(account_data.get('functional_addrs'), account_data.get('region', ""))
        if reg != resolve_region(account_data.get('region', "")):
            log_info(
                f"[REGION] gateway region {reg} overrides account region "
                f"{resolve_region(account_data.get('region', '')) or '?'} for UID {acc_id}"
            )
        info_reg = gateway_region(account_data.get('informational_addrs'), reg)
        tcp_packet_online = await build_tcp_startup_packet(
            account_data['account_id'],
            account_data['token'],
            account_data['server_time'],
            account_data['aes_ak'],
            account_data['iv_i'],
            region=reg,
            typ='OnLine'
        )

        tcp_packet_chat = await build_tcp_startup_packet(
            account_data['account_id'],
            account_data['token'],
            account_data['server_time'],
            account_data['aes_ak'],
            account_data['iv_i'],
            region=info_reg,
            typ='ChaT'
        )

        informational_task = asyncio.create_task(
            informational(
                account_data['informational_addrs'],
                tcp_packet_chat,
                account_data['aes_ak'],
                account_data['iv_i'],
                region=info_reg
            )
        )

        async def exp_refresher():
            await asyncio.sleep(random.uniform(0.0, 2.0))
            try:
                fresh = bot_state.account_credentials.get(acc_id)
                if fresh:
                    await refresh_account_profile(fresh)
            except Exception as e:
                log_warn(f"[EXP-REFRESH] initial refresh error ({acc_id}): {e}")
            while True:
                _interval = EXP_REFRESH_INTERVAL
                try:
                    _lvl = bot_state.accounts.get(acc_id, {}).get("level")
                    if _lvl is not None and int(_lvl) == LONE_WOLF_UNLOCK_LEVEL - 1:
                        _interval = LW_UNLOCK_WATCH_REFRESH_INTERVAL
                except Exception:
                    pass
                _spread = 3.0 if _interval == EXP_REFRESH_INTERVAL else 1.0
                await asyncio.sleep(_interval + random.uniform(-_spread, _spread))
                try:
                    fresh = bot_state.account_credentials.get(acc_id)
                    if fresh:
                        await refresh_account_profile(fresh)
                except Exception as e:
                    log_warn(f"[EXP-REFRESH] periodic refresh error ({acc_id}): {e}")

        exp_task = asyncio.create_task(exp_refresher())

        functional_task = asyncio.create_task(
            functional_lone_wolf(
                account_data['functional_addrs'],
                tcp_packet_online,
                reg,
                account_data['client_version'],
                account_data['aes_ak'],
                account_data['iv_i'],
                account_id=acc_id,
                account_data=account_data,
                account_level=int(account_data.get('level', 2) or 2)
            )
        )

        await functional_task

    except asyncio.CancelledError:
        raise
    except Exception as e:
        log_err(f"run_account_worker error for {label}: {e}")
    finally:
        for t in (informational_task, exp_task):
            if t and not t.done():
                t.cancel()
        for t in (informational_task, exp_task):
            if t:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass


def _ensure_dashboard_placeholder(
    display_uid: str,
    *,
    auth_type: str,
    auth_uid: Optional[str] = None,
    auth_token: Optional[str] = None,
    worker_key: Optional[str] = None,
    control: str = "stop",
):
    display_uid = str(display_uid)
    nick = f"Player_{display_uid[:6]}"
    region = ""
    level, exp = 1, 0
    try:
        meta_keys = []
        if auth_type == "guest" and auth_uid:
            meta_keys.append(f"guest:{auth_uid}")
        if auth_type == "token" and auth_token:
            meta_keys.append(f"token:{str(auth_token)[:10]}")
        meta_keys.append(f"acc:{display_uid}")
        meta = get_saved_status_meta(*meta_keys)
        if meta.get("nickname"):
            nick = str(meta["nickname"])
        if meta.get("account_id") and str(meta["account_id"]) != display_uid:
            pass
    except Exception:
        pass
    try:
        cache_key = display_uid if auth_type == "guest" else f"tok_{(auth_token or '')[:20]}"
        cached = cache_get(cache_key) if cache_key else None
        if cached:
            nick = cached.get("nickname") or nick
            region = cached.get("region") or region
            level = int(cached.get("level") or level)
            exp = int(cached.get("exp") or exp)
    except Exception:
        pass

    bot_state.register_account(
        uid=display_uid, nickname=nick, region=region, level=level, exp=exp, likes=0
    )
    acc = bot_state.accounts.get(display_uid)
    if not acc:
        return
    acc["auth_type"] = auth_type
    if auth_uid:
        acc["auth_uid"] = str(auth_uid)
    if auth_token:
        acc["auth_token"] = auth_token
    if worker_key:
        acc["worker_key"] = worker_key
    if control in ("run", "pause", "stop"):
        acc["control"] = control
        acc["status"] = {"run": "ONLINE", "pause": "PAUSED", "stop": "STOPPED"}[control]
    try:
        meta_keys = []
        if auth_type == "guest" and auth_uid:
            meta_keys.append(f"guest:{auth_uid}")
        if auth_type == "token" and auth_token:
            meta_keys.append(f"token:{str(auth_token)[:10]}")
        meta_keys.append(f"acc:{display_uid}")
        meta = get_saved_status_meta(*meta_keys)
        if meta.get("target_level") is not None:
            try:
                acc["target_level"] = int(meta["target_level"])
            except Exception:
                pass
    except Exception:
        pass
    acc["last_updated"] = time.strftime("%H:%M:%S")
    try:
        keys = [f"acc:{display_uid}"]
        if auth_uid:
            keys.append(f"guest:{auth_uid}")
        if auth_token:
            keys.append(f"token:{str(auth_token)[:10]}")
        set_saved_control(control, *keys, nickname=nick)
    except Exception:
        pass


def _dashboard_control(uid: str) -> Optional[str]:
    acc = bot_state.accounts.get(str(uid))
    if acc:
        return acc.get("control")
    return None


def _remove_placeholder_if_different(placeholder_uid: str, real_acc_id: str):
    p, r = str(placeholder_uid), str(real_acc_id)
    if p != r and p in bot_state.accounts and r in bot_state.accounts:
        try:
            del bot_state.accounts[p]
        except Exception:
            pass
        try:
            if p in bot_state._exp_samples:
                del bot_state._exp_samples[p]
        except Exception:
            pass
        bot_state.recalc_totals()


async def account_loop_guest(uid: str, password: str):
    auth_key = _status_auth_key("guest", uid)
    while True:
        try:
            while True:
                saved = get_saved_control(auth_key)
                live = _dashboard_control(uid)
                if saved != "stop" and live != "stop":
                    break
                if live == "run" or saved == "run":
                    set_saved_control("run", auth_key)
                    if uid in bot_state.accounts:
                        bot_state.accounts[uid]["control"] = "run"
                        bot_state.accounts[uid]["status"] = "CONNECTING"
                    break
                _ensure_dashboard_placeholder(
                    uid, auth_type="guest", auth_uid=uid, worker_key=uid, control="stop"
                )
                log_info(f"Guest {uid} is STOPPED — waiting for Start")
                await asyncio.sleep(1.5)

            log_info(f"Starting login for Guest UID: {uid}...")
            try:
                if uid in bot_state.accounts:
                    bot_state.accounts[uid]["status"] = "CONNECTING"
                    bot_state.accounts[uid]["control"] = "run"
                else:
                    bot_state.update_status(str(uid), "CONNECTING")
            except Exception:
                pass
            account_data = await process_account_uid_pass(uid, password)
            if not account_data:
                log_err(f"Login failed for UID: {uid}. Retrying in 15 seconds...")
                try:
                    bot_state.update_status(str(uid), "ERROR")
                except Exception:
                    pass
                await asyncio.sleep(random.uniform(12.0, 18.0))
                continue

            acc_id = str(account_data['account_id'])
            acc_key = f"acc:{acc_id}"
            task = asyncio.current_task()
            if task is not None:
                bot_state.account_workers[uid] = task
                bot_state.account_workers[acc_id] = task

            saved = get_saved_control(auth_key, acc_key)
            if acc_id in bot_state.accounts:
                bot_state.accounts[acc_id]["worker_key"] = uid
                bot_state.accounts[acc_id]["auth_uid"] = uid
                bot_state.accounts[acc_id]["auth_type"] = "guest"
                bot_state.accounts[acc_id]["control"] = saved if saved in ("run", "pause", "stop") else "run"
                if saved == "pause":
                    bot_state.accounts[acc_id]["status"] = "PAUSED"
                elif saved == "stop":
                    bot_state.accounts[acc_id]["status"] = "STOPPED"
                else:
                    bot_state.accounts[acc_id]["status"] = "ONLINE"
                try:
                    meta = get_saved_status_meta(auth_key, acc_key)
                    if meta.get("target_level") is not None:
                        bot_state.accounts[acc_id]["target_level"] = int(meta["target_level"])
                    tl = _resolve_target_for_account(acc_id, bot_state.accounts.get(acc_id))
                    if tl is not None:
                        bot_state.accounts[acc_id]["target_level"] = tl
                except Exception:
                    pass
            _remove_placeholder_if_different(uid, acc_id)
            _nick = bot_state.accounts.get(acc_id, {}).get("nickname") or account_data.get("nickname")
            set_saved_control(
                bot_state.accounts.get(acc_id, {}).get("control", "run"),
                auth_key, acc_key,
                nickname=_nick,
                account_id=acc_id,
            )
            # uid-primary write — merges all info under the uid key
            set_account_state(uid,
                 control=bot_state.accounts.get(acc_id, {}).get("control", "run"),
                 nickname=_nick,
                 account_id=acc_id,
                 region=account_data.get("region", ""))

            # Homer equip — once per uid, cached in account_status
            if HOMER_EQUIP_BEFORE_MATCH:
                _jwt_for_equip = account_data.get("token") or account_data.get("jwt") or ""
                if _jwt_for_equip:
                    try:
                        await ensure_homer_equipped(uid, _jwt_for_equip, HOMER_SERVER_URL)
                    except Exception as _he:
                        log_warn(f"[HOMER-EQUIP] uid={uid} failed: {_he}")

            await run_account_worker(account_data, uid)

            if bot_state.accounts.get(acc_id, {}).get("control") == "stop":
                log_warn(f"Account {acc_id} stopped — waiting for Start")
                set_saved_control(
                    "stop", auth_key, acc_key,
                    nickname=bot_state.accounts.get(acc_id, {}).get("nickname"),
                    account_id=acc_id,
                )
                try:
                    bot_state.update_status(acc_id, "STOPPED", 0)
                except Exception:
                    pass
                while bot_state.accounts.get(acc_id, {}).get("control") == "stop":
                    await asyncio.sleep(1.5)
                cache_invalidate(str(uid))
                set_saved_control(
                    "run", auth_key, acc_key,
                    nickname=bot_state.accounts.get(acc_id, {}).get("nickname"),
                    account_id=acc_id,
                )
                continue

            log_warn(f"Session finished for {uid}. Reconnecting in 3s...")
            await asyncio.sleep(random.uniform(2.5, 4.5))
        except asyncio.CancelledError:
            log_warn(f"Worker for {uid} stopped.")
            try:
                bot_state.update_status(str(uid), "OFFLINE")
            except Exception:
                pass
            break
        except Exception as e:
            log_err(f"Error for UID {uid}: {e}. Retrying in 10s...")
            await asyncio.sleep(random.uniform(8.0, 12.0))


async def account_loop_token(token: str):
    token_label = token[:10]
    auth_key = _status_auth_key("token", token)
    while True:
        try:
            while True:
                saved = get_saved_control(auth_key)
                live = _dashboard_control(token_label)
                if saved != "stop" and live != "stop":
                    break
                if live == "run" or saved == "run":
                    set_saved_control("run", auth_key)
                    if token_label in bot_state.accounts:
                        bot_state.accounts[token_label]["control"] = "run"
                        bot_state.accounts[token_label]["status"] = "CONNECTING"
                    break
                _ensure_dashboard_placeholder(
                    token_label,
                    auth_type="token",
                    auth_token=token,
                    worker_key=token_label,
                    control="stop",
                )
                log_info(f"Token {token_label} is STOPPED — waiting for Start")
                await asyncio.sleep(1.5)

            log_info("Starting login with Access Token...")
            account_data = await process_account_token(token)
            if not account_data:
                log_err("Login failed for Token. Retrying in 15 seconds...")
                await asyncio.sleep(random.uniform(12.0, 18.0))
                continue

            acc_id = str(account_data['account_id'])
            acc_key = f"acc:{acc_id}"
            task = asyncio.current_task()
            if task is not None:
                bot_state.account_workers[token_label] = task
                bot_state.account_workers[acc_id] = task

            saved = get_saved_control(auth_key, acc_key)
            if acc_id in bot_state.accounts:
                bot_state.accounts[acc_id]["worker_key"] = token_label
                bot_state.accounts[acc_id]["auth_token"] = token
                bot_state.accounts[acc_id]["auth_type"] = "token"
                bot_state.accounts[acc_id]["control"] = saved if saved in ("run", "pause", "stop") else "run"
                if saved == "pause":
                    bot_state.accounts[acc_id]["status"] = "PAUSED"
                elif saved == "stop":
                    bot_state.accounts[acc_id]["status"] = "STOPPED"
                else:
                    bot_state.accounts[acc_id]["status"] = "ONLINE"
                try:
                    meta = get_saved_status_meta(auth_key, acc_key)
                    if meta.get("target_level") is not None:
                        bot_state.accounts[acc_id]["target_level"] = int(meta["target_level"])
                    tl = _resolve_target_for_account(acc_id, bot_state.accounts.get(acc_id))
                    if tl is not None:
                        bot_state.accounts[acc_id]["target_level"] = tl
                except Exception:
                    pass
            _remove_placeholder_if_different(token_label, acc_id)
            _nick = bot_state.accounts.get(acc_id, {}).get("nickname") or account_data.get("nickname")
            set_saved_control(
                bot_state.accounts.get(acc_id, {}).get("control", "run"),
                auth_key, acc_key,
                nickname=_nick,
                account_id=acc_id,
            )

            await run_account_worker(account_data, acc_id)

            if bot_state.accounts.get(acc_id, {}).get("control") == "stop":
                log_warn(f"Account {acc_id} stopped — waiting for Start")
                set_saved_control(
                    "stop", auth_key, acc_key,
                    nickname=bot_state.accounts.get(acc_id, {}).get("nickname"),
                    account_id=acc_id,
                )
                try:
                    bot_state.update_status(acc_id, "STOPPED", 0)
                except Exception:
                    pass
                while bot_state.accounts.get(acc_id, {}).get("control") == "stop":
                    await asyncio.sleep(1.5)
                cache_invalidate(f"tok_{token[:20]}")
                set_saved_control(
                    "run", auth_key, acc_key,
                    nickname=bot_state.accounts.get(acc_id, {}).get("nickname"),
                    account_id=acc_id,
                )
                continue

            log_warn("Token session finished. Reconnecting in 3s...")
            await asyncio.sleep(random.uniform(2.5, 4.5))
        except asyncio.CancelledError:
            log_warn(f"Worker for token {token_label} stopped.")
            break
        except Exception as e:
            log_err(f"Token error: {e}. Retrying in 10s...")
            await asyncio.sleep(random.uniform(8.0, 12.0))


def load_accounts():
    accounts = []
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    accounts = data
        except Exception as e:
            log_err(f"Could not load {ACCOUNTS_FILE}: {e}")


    return accounts


def _parse_args():
    p = argparse.ArgumentParser(description="SFUDP — FreeFire LW Level-Up Bot")
    p.add_argument("-l", "--level", action="store_true",
                   help="Level-up mode: LW exp farming (default, only mode)")
    p.add_argument("-r", "--region", default=None,
                   help="Force a region (e.g. IND for Free Fire India / FF MAX India)")
    p.add_argument("-c", "--check", action="store_true",
                   help="Diagnose the login chain for the selected region and exit")
    p.add_argument("--native-login", action="store_true",
                   help="Login through the region's own BP host instead of the mirror proxy")
    return p.parse_args()


async def run_check(region=None):
    """Region diagnostic: store version -> mirror -> login host -> DNS. No account needed."""
    reg = resolve_region(region, FORCE_REGION) or DEFAULT_REGION
    pkg = PLAY_PACKAGE.get(reg, DEFAULT_PLAY_PACKAGE)
    country = PLAY_COUNTRY.get(reg, DEFAULT_PLAY_COUNTRY)
    log_info(f"[CHECK] region        = {reg}")
    log_info(f"[CHECK] store listing = {pkg} ({country})")
    try:
        app_version = await get_playstore_version(pkg, country)
    except Exception as e:
        app_version = None
        log_err(f"[CHECK] store scrape failed: {e}")
    log_info(f"[CHECK] store version = {app_version}")

    cfg = await version_config(reg)
    release_version, client_version, server_url = cfg
    log_info(f"[CHECK] source        = {LAST_VERSION_SOURCE}")
    log_info(f"[CHECK] release       = {release_version}")
    log_info(f"[CHECK] client version= {client_version}")
    log_info(f"[CHECK] login server  = {server_url}")

    host = urlparse(server_url).hostname or ""
    ggp = REGION_GGP_HOST.get(reg, DEFAULT_GGP_HOST)
    for h in (host, ggp):
        try:
            ip = await resolve_host_cloudflare(h)
            log_info(f"[CHECK] {h} -> {ip}")
        except Exception as e:
            log_err(f"[CHECK] {h} -> resolve failed: {e}")
    if reg == "IND" and "freefireind" not in server_url:
        log_warn("[CHECK] IND selected but the login host is not an *.freefireind.in endpoint; "
                 "GetLoginData will hand out global match servers.")

    native = REGION_LOGIN_SERVER.get(reg)
    if native:
        try:
            probe = await client.get(native.rstrip("/") + "/", timeout=8.0)
            log_info(f"[CHECK] native BP   {native} -> HTTP {probe.status_code} (live host)")
        except Exception as e:
            log_warn(f"[CHECK] native BP   {native} -> {type(e).__name__}")
    return cfg



async def main():
    global FORCE_REGION, USE_NATIVE_LOGIN
    _args = _parse_args()

    USE_NATIVE_LOGIN = bool(_args.native_login)
    if _args.region:
        FORCE_REGION = resolve_region(_args.region) or None
    else:
        try:
            FORCE_REGION = resolve_region(load_bot_settings().get("region")) or None
        except Exception:
            FORCE_REGION = None
    if FORCE_REGION:
        log_info(f"[REGION] locked to {FORCE_REGION}")

    if _args.check:
        await run_check(FORCE_REGION)
        return

    # Never carry asyncio.Task objects across asyncio.run() event loops.
    current_loop = asyncio.get_running_loop()
    for key, task in list(bot_state.account_workers.items()):
        try:
            if not isinstance(task, asyncio.Task) or task.get_loop() is not current_loop or task.done():
                bot_state.account_workers.pop(key, None)
        except Exception:
            bot_state.account_workers.pop(key, None)

    apply_bot_settings()

    print_colored("=" * 60, Colors.CYAN)
    # ── LEVEL mode (original flow) ──────────────────────────────────────────
    try:
        await start_web_dashboard(host=WEB_HOST, port=WEB_PORT)
        log_ok(f"Web Dashboard live at http://localhost:{WEB_PORT}")
    except OSError as e:
        if getattr(e, "errno", None) == 98 or "address already in use" in str(e).lower():
            log_warn(
                f"Dashboard port {WEB_PORT} is already in use; "
                "the existing listener was left untouched. Account workers will continue."
            )
        else:
            log_err(f"Could not start web dashboard: {e}")
    except Exception as e:
        log_err(f"Could not start web dashboard: {e}")

    async def on_account_added_handler(data):
        if "token" in data and data["token"]:
            t = str(data["token"]).strip()
            task = asyncio.create_task(account_loop_token(t))
            bot_state.account_workers[t[:10]] = task
        elif "uid" in data and "password" in data:
            u = str(data["uid"]).strip()
            p = str(data["password"]).strip()
            task = asyncio.create_task(account_loop_guest(u, p))
            bot_state.account_workers[u] = task

    async def on_refresh_account_handler(uid):
        await refresh_account_profile(uid)

    bot_state.refresh_callbacks["on_account_added"] = on_account_added_handler
    bot_state.refresh_callbacks["on_refresh_account"] = on_refresh_account_handler

    accounts = load_accounts()

    if not accounts:
        log_warn(f"No accounts found in {ACCOUNTS_FILE}! Add accounts from Web Dashboard.")
        log_warn(f"Open: http://localhost:{WEB_PORT}")

    for acc in accounts:
        if "token" in acc and acc["token"]:
            t = asyncio.create_task(account_loop_token(acc["token"]))
            bot_state.account_workers[acc["token"][:10]] = t
        elif "uid" in acc and "password" in acc and acc["uid"]:
            u = str(acc["uid"])
            t = asyncio.create_task(account_loop_guest(u, acc["password"]))
            bot_state.account_workers[u] = t

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        log_warn("\nShutting down all accounts...")
        current_loop = asyncio.get_running_loop()
        workers = {
            t for t in list(bot_state.account_workers.values())
            if isinstance(t, asyncio.Task)
            and t.get_loop() is current_loop
            and not t.done()
        }
        for task in workers:
            task.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        bot_state.account_workers.clear()
        log_ok("All sessions cleanly closed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log_warn("\nProgram stopped by user.")

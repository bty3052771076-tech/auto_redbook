from __future__ import annotations

import ctypes
import hashlib
import hmac
import ipaddress
import os
import re
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


class PlatformError(ValueError):
    def __init__(self, code: str, action: str, *, status: int = 400, retryable: bool = False):
        super().__init__(f'{code}: {action}')
        self.code, self.action, self.status, self.retryable = code, action, status, retryable

    def public(self):
        return {'error': str(self), 'code': self.code, 'action': self.action, 'retryable': self.retryable}


@contextmanager
def file_lock(path: Path, *, timeout: float = 10):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as file:
        if file.tell() == 0:
            file.write(b'0')
            file.flush()
        deadline = time.monotonic() + timeout
        while True:
            file.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise PlatformError('CONFIG_BUSY', '连接正在被使用，请稍后重试', retryable=True) from None
                time.sleep(.02)
        try:
            yield
        finally:
            file.seek(0)
            if os.name == 'nt':
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file, fcntl.LOCK_UN)


def validate_address(base: str, network: str) -> str:
    parsed = urlsplit(base)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or '\\' in base or any(ord(c) < 33 for c in base)):
        raise PlatformError('UNSAFE_ADDRESS', '请填写不含凭据、查询参数和片段的 API 基址')
    try:
        port = parsed.port
    except ValueError:
        raise PlatformError('UNSAFE_ADDRESS', 'API 端口无效') from None
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if network == 'local':
        if not (parsed.hostname == 'localhost' or address and address.is_loopback) or not port or port < 1024:
            raise PlatformError('UNSAFE_LOCAL_ADDRESS', '本机服务只允许明确的 loopback 地址及 1024 以上端口')
    elif network == 'public':
        if parsed.scheme != 'https' or (address and not address.is_global) or parsed.hostname == 'localhost':
            raise PlatformError('UNSAFE_PUBLIC_ADDRESS', '公网接口必须使用 HTTPS，不能指向内网或 metadata')
    else:
        raise PlatformError('UNSAFE_NETWORK_POLICY', '网络模式只能是 public 或 local')
    return base.rstrip('/')


def relative_path(value: str) -> str:
    from urllib.parse import unquote
    decoded = unquote(value)
    if not value or decoded.startswith('/') or '\\' in decoded or urlsplit(decoded).scheme or any(
        part in {'.', '..'} for part in decoded.split('/')
    ) or '?' in decoded or '#' in decoded or any(ord(c) < 33 for c in decoded):
        raise PlatformError('UNSAFE_ENDPOINT', '端点必须是同 API 基址下的安全相对路径')
    return value


def pinned_address(base: str, network: str) -> str:
    parsed = urlsplit(validate_address(base, network))
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except OSError:
        raise PlatformError('CONNECTION_FAILED', 'DNS 解析失败，请检查网络或代理', retryable=True) from None
    if not addresses or any(not (ipaddress.ip_address(ip).is_loopback if network == 'local' else ipaddress.ip_address(ip).is_global) for ip in addresses):
        raise PlatformError('UNSAFE_DNS_TARGET', 'DNS 指向禁止访问的目标，已阻止发送凭据')
    return sorted(addresses)[0]


class CredentialStore:
    def __init__(self, directory: Path, env: dict | None = None):
        self.directory, self.env = directory, env

    def save(self, secret: str) -> str:
        if os.name != 'nt':
            raise PlatformError('ENCRYPTION_UNAVAILABLE', '此部署请使用环境变量凭据引用；禁止明文存储')
        from uuid import uuid4
        ref = 'dpapi:' + uuid4().hex
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (ref.split(':', 1)[1] + '.bin')
        path.write_bytes(self._crypt(secret.encode(), decrypt=False))
        if self.read(ref) != secret:
            path.unlink(missing_ok=True)
            raise PlatformError('CREDENTIAL_WRITE_FAILED', '凭据加密验证失败，旧配置未更改')
        return ref

    def read(self, ref: str) -> str:
        if ref.startswith('env:') and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', ref[4:]):
            value = (self.env if self.env is not None else os.environ).get(ref[4:], '')
            if value:
                return str(value)
        if ref.startswith('dpapi:') and re.fullmatch(r'[a-f0-9]{32}', ref[6:]) and os.name == 'nt':
            try:
                return self._crypt((self.directory / (ref[6:] + '.bin')).read_bytes(), decrypt=True).decode()
            except (OSError, UnicodeError):
                pass
        raise PlatformError('CREDENTIAL_UNAVAILABLE', '凭据无法读取，请在连接管理中重新配置')

    def fingerprint(self, ref: str) -> str:
        if not ref:
            return ''
        secret = self.read(ref)
        with file_lock(self.directory / 'fingerprint.lock'):
            path = self.directory / 'fingerprint.key'
            if not path.exists():
                with path.open('xb') as file:
                    file.write(os.urandom(32))
                    file.flush()
                    os.fsync(file.fileno())
            salt = path.read_bytes()
        if len(salt) != 32:
            raise PlatformError('CREDENTIAL_UNAVAILABLE', '凭据校验文件损坏，请重新配置连接')
        return hmac.new(salt, (ref + '\0' + secret).encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _crypt(data: bytes, *, decrypt: bool) -> bytes:
        class Blob(ctypes.Structure):
            _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]
        buffer = ctypes.create_string_buffer(data)
        source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        dest = Blob()
        api = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
        ok = api(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(dest))
        if not ok:
            raise PlatformError('CREDENTIAL_UNAVAILABLE', 'Windows 凭据加解密失败，请在当前账户重新配置')
        try:
            return ctypes.string_at(dest.data, dest.size)
        finally:
            ctypes.windll.kernel32.LocalFree(dest.data)

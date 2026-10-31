"""Loopback-only HTTP/TLS allocation probe; no FUB access or real credentials.

Run in separate processes with the old and proposed Python runtimes, with
httpx, cryptography and psutil installed. A temporary self-signed certificate
and synthetic HTTPS server exercise actual TLS allocation and teardown.
No forced GC during the run. Temporary keys are never printed or committed.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import ipaddress
import json
import platform
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import certifi
import httpx
import psutil
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


async def synthetic_response(reader, writer):
    try:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{"ok":true}')
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


def sample(completed: int, phase: str = "automatic_gc") -> None:
    print(
        json.dumps(
            {
                "python": platform.python_version(),
                "completed": completed,
                "phase": phase,
                "rss_mib": round(psutil.Process().memory_info().rss / 2**20, 2),
                "ssl_contexts": sum(isinstance(obj, ssl.SSLContext) for obj in gc.get_objects()),
            }
        ),
        flush=True,
    )


async def one_request(url: str, ca_path: Path, shared_context: ssl.SSLContext | None) -> None:
    # HTTPX's ordinary client constructor makes a fresh SSLContext per call.
    context = shared_context or ssl.create_default_context(cafile=str(ca_path))
    async with httpx.AsyncClient(verify=context, trust_env=False) as client:
        response = await client.get(url)
        assert response.json() == {"ok": True}


async def main(reuse_context: bool) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
        .sign(key, hashes.SHA256())
    )
    with TemporaryDirectory(prefix="fub-memory-probe-") as directory:
        folder = Path(directory)
        cert_path, key_path, ca_path = folder / "cert.pem", folder / "key.pem", folder / "ca.pem"
        cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        ca_path.write_bytes(Path(certifi.where()).read_bytes() + cert_path.read_bytes())
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(cert_path, key_path)
        shared_context = ssl.create_default_context(cafile=str(ca_path)) if reuse_context else None
        async with await asyncio.start_server(synthetic_response, "127.0.0.1", 0, ssl=server_context) as server:
            url = f"https://127.0.0.1:{server.sockets[0].getsockname()[1]}/record"
            sample(0)
            for batch in range(100):
                await asyncio.gather(*(one_request(url, ca_path, shared_context) for _ in range(8)))
                if (batch + 1) % 25 == 0:
                    sample((batch + 1) * 8)
            gc.collect()
            sample(800, "after_forced_gc")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-context", action="store_true")
    asyncio.run(main(parser.parse_args().reuse_context))

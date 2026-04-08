from __future__ import annotations

from base64 import b64encode
import hashlib
import hmac
import json
from typing import Mapping, Sequence
from urllib.parse import quote
from uuid import uuid4


QueryPairs = Sequence[tuple[str, str]]


def build_query_string(query_pairs: QueryPairs) -> str:
    return "&".join(
        f"{quote(key, safe='[]')}={quote(value, safe='[]')}"
        for key, value in query_pairs
    )


def build_query_hash(query_string: str) -> str:
    digest = hashlib.sha512()
    digest.update(query_string.encode("utf-8"))
    return digest.hexdigest()


def create_upbit_jwt_token(
    access_key: str,
    secret_key: str,
    *,
    query_string: str | None = None,
    nonce: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "access_key": access_key,
        "nonce": nonce or str(uuid4()),
    }
    if query_string:
        payload["query_hash"] = build_query_hash(query_string)
        payload["query_hash_alg"] = "SHA512"
    return _encode_jwt(payload, secret_key, algorithm="HS512")


def create_bithumb_jwt_token(
    access_key: str,
    secret_key: str,
    *,
    query_string: str | None = None,
    nonce: str | None = None,
    timestamp_ms: int | None = None,
) -> str:
    payload: dict[str, object] = {
        "access_key": access_key,
        "nonce": nonce or str(uuid4()),
        "timestamp": int(timestamp_ms if timestamp_ms is not None else _now_ms()),
    }
    if query_string:
        payload["query_hash"] = build_query_hash(query_string)
        payload["query_hash_alg"] = "SHA512"
    return _encode_jwt(payload, secret_key, algorithm="HS256")


def build_bearer_authorization(token: str) -> str:
    return f"Bearer {token}"


def encode_coinone_payload(
    payload: Mapping[str, object],
    *,
    access_key: str,
    nonce: str | None = None,
) -> tuple[dict[str, object], str]:
    body = dict(payload)
    body["access_token"] = access_key
    body["nonce"] = nonce or str(uuid4())
    dumped = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    encoded = b64encode(dumped.encode("utf-8")).decode("ascii")
    return body, encoded


def sign_coinone_payload(encoded_payload: str, secret_key: str) -> str:
    return hmac.new(
        secret_key.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest()


def build_coinone_private_headers(
    payload: Mapping[str, object],
    *,
    access_key: str,
    secret_key: str,
    nonce: str | None = None,
) -> tuple[dict[str, str], dict[str, object], str]:
    body, encoded_payload = encode_coinone_payload(
        payload,
        access_key=access_key,
        nonce=nonce,
    )
    headers = {
        "Content-Type": "application/json",
        "X-COINONE-PAYLOAD": encoded_payload,
        "X-COINONE-SIGNATURE": sign_coinone_payload(encoded_payload, secret_key),
    }
    return headers, body, encoded_payload


def _encode_jwt(payload: Mapping[str, object], secret_key: str, *, algorithm: str) -> str:
    header = {"alg": algorithm, "typ": "JWT"}
    encoded_header = _urlsafe_b64json(header)
    encoded_payload = _urlsafe_b64json(payload)
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    digest_name = _jwt_digest_name(algorithm)
    signature = hmac.new(
        secret_key.encode("utf-8"),
        signing_input,
        getattr(hashlib, digest_name),
    ).digest()
    encoded_signature = _urlsafe_b64(signature)
    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


def _jwt_digest_name(algorithm: str) -> str:
    digest_names = {
        "HS256": "sha256",
        "HS384": "sha384",
        "HS512": "sha512",
    }
    try:
        return digest_names[algorithm]
    except KeyError as exc:
        raise ValueError(f"unsupported jwt algorithm: {algorithm}") from exc


def _urlsafe_b64json(value: Mapping[str, object]) -> str:
    dumped = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _urlsafe_b64(dumped)


def _urlsafe_b64(raw: bytes) -> str:
    return b64encode(raw).decode("ascii").replace("+", "-").replace("/", "_").rstrip("=")


def _now_ms() -> int:
    from time import time

    return round(time() * 1000)

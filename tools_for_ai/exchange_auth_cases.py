from __future__ import annotations

from base64 import urlsafe_b64decode
import hashlib
import hmac
import json

from trading_platform.strategy import (
    build_bearer_authorization,
    build_coinone_private_headers,
    build_query_hash,
    build_query_string,
    create_bithumb_jwt_token,
    create_upbit_jwt_token,
    encode_coinone_payload,
    sign_coinone_payload,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _decode_jwt_segment(token: str, index: int) -> dict[str, object]:
    segment = token.split(".")[index]
    padding = "=" * (-len(segment) % 4)
    return json.loads(urlsafe_b64decode(segment + padding).decode("utf-8"))


def _test_query_string_and_hash() -> None:
    query_string = build_query_string(
        (
            ("states[]", "wait"),
            ("states[]", "watch"),
            ("market", "KRW-BTC"),
        )
    )
    _assert(
        query_string == "states[]=wait&states[]=watch&market=KRW-BTC",
        "query string should preserve repeated key order",
    )
    _assert(
        build_query_hash(query_string) == hashlib.sha512(query_string.encode("utf-8")).hexdigest(),
        "query hash mismatch",
    )


def _test_upbit_jwt() -> None:
    query_string = "market=KRW-BTC&states[]=wait&states[]=watch"
    token = create_upbit_jwt_token(
        "upbit-access",
        "upbit-secret",
        query_string=query_string,
        nonce="nonce-upbit",
    )
    header = _decode_jwt_segment(token, 0)
    payload = _decode_jwt_segment(token, 1)
    _assert(header == {"alg": "HS512", "typ": "JWT"}, "upbit jwt header mismatch")
    _assert(payload["access_key"] == "upbit-access", "upbit access_key mismatch")
    _assert(payload["nonce"] == "nonce-upbit", "upbit nonce mismatch")
    _assert(payload["query_hash_alg"] == "SHA512", "upbit query hash alg mismatch")
    _assert(
        payload["query_hash"] == hashlib.sha512(query_string.encode("utf-8")).hexdigest(),
        "upbit query hash mismatch",
    )
    _assert(
        build_bearer_authorization(token).startswith("Bearer "),
        "bearer authorization prefix mismatch",
    )


def _test_bithumb_jwt() -> None:
    query_string = "market=KRW-BTC&limit=1"
    token = create_bithumb_jwt_token(
        "bithumb-access",
        "bithumb-secret",
        query_string=query_string,
        nonce="nonce-bithumb",
        timestamp_ms=1712550000123,
    )
    header = _decode_jwt_segment(token, 0)
    payload = _decode_jwt_segment(token, 1)
    _assert(header == {"alg": "HS256", "typ": "JWT"}, "bithumb jwt header mismatch")
    _assert(payload["access_key"] == "bithumb-access", "bithumb access_key mismatch")
    _assert(payload["nonce"] == "nonce-bithumb", "bithumb nonce mismatch")
    _assert(payload["timestamp"] == 1712550000123, "bithumb timestamp mismatch")
    _assert(payload["query_hash_alg"] == "SHA512", "bithumb query hash alg mismatch")
    signing_input = ".".join(token.split(".")[:2]).encode("ascii")
    expected_signature = hmac.new(
        b"bithumb-secret",
        signing_input,
        hashlib.sha256,
    ).digest()
    signature_segment = token.split(".")[2]
    padding = "=" * (-len(signature_segment) % 4)
    actual_signature = urlsafe_b64decode(signature_segment + padding)
    _assert(actual_signature == expected_signature, "bithumb jwt signature mismatch")


def _test_coinone_payload_and_signature() -> None:
    body, encoded_payload = encode_coinone_payload(
        {"price": "1000", "qty": "0.1"},
        access_key="coinone-access",
        nonce="coinone-nonce",
    )
    _assert(body["access_token"] == "coinone-access", "coinone access token mismatch")
    _assert(body["nonce"] == "coinone-nonce", "coinone nonce mismatch")
    signature = sign_coinone_payload(encoded_payload, "coinone-secret")
    expected_signature = hmac.new(
        b"coinone-secret",
        encoded_payload.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest()
    _assert(signature == expected_signature, "coinone payload signature mismatch")

    headers, request_body, encoded = build_coinone_private_headers(
        {"price": "1000", "qty": "0.1"},
        access_key="coinone-access",
        secret_key="coinone-secret",
        nonce="coinone-nonce",
    )
    _assert(
        headers["Content-Type"] == "application/json",
        "coinone content-type mismatch",
    )
    _assert(
        headers["X-COINONE-PAYLOAD"] == encoded,
        "coinone payload header mismatch",
    )
    _assert(
        headers["X-COINONE-SIGNATURE"] == signature,
        "coinone signature header mismatch",
    )
    _assert(request_body == body, "coinone request body mismatch")


def main() -> None:
    _test_query_string_and_hash()
    _test_upbit_jwt()
    _test_bithumb_jwt()
    _test_coinone_payload_and_signature()
    print("PASS exchange auth helpers build deterministic signed payloads")


if __name__ == "__main__":
    main()

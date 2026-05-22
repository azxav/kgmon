from __future__ import annotations

import os
import sys
from pathlib import Path

from kgmon_kaggle.doctor import (
    DependencyCheck,
    build_doctor_report,
    check_dependencies,
    detect_kaggle_credentials,
)
from kgmon_kaggle.redaction import redact_mapping, redact_secret


def test_redacts_secret_values_without_exposing_raw_text() -> None:
    secret = "abc123-super-secret-token"

    assert redact_secret(secret) == "ab********************en"
    redacted = redact_mapping({"KAGGLE_API_TOKEN": secret})["KAGGLE_API_TOKEN"]
    assert secret not in redacted


def test_detects_api_token_without_returning_secret(monkeypatch) -> None:
    monkeypatch.setenv("KAGGLE_API_TOKEN", "kg-token-value")
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)

    credentials = detect_kaggle_credentials(access_token_path=Path("missing-token"))

    assert credentials.mode == "KAGGLE_API_TOKEN"
    assert credentials.available is True
    assert credentials.redacted_values == {"KAGGLE_API_TOKEN": "kg**********ue"}
    assert "kg-token-value" not in repr(credentials)


def test_detects_legacy_credentials_only_when_pair_is_present(monkeypatch) -> None:
    monkeypatch.delenv("KAGGLE_API_TOKEN", raising=False)
    monkeypatch.setenv("KAGGLE_USERNAME", "aziz")
    monkeypatch.delenv("KAGGLE_KEY", raising=False)

    missing_pair = detect_kaggle_credentials(access_token_path=Path("missing-token"))

    assert missing_pair.available is False
    assert missing_pair.mode == "missing"

    monkeypatch.setenv("KAGGLE_KEY", "legacy-key")

    credentials = detect_kaggle_credentials(access_token_path=Path("missing-token"))

    assert credentials.available is True
    assert credentials.mode == "legacy"
    assert credentials.redacted_values == {
        "KAGGLE_KEY": "le******ey",
        "KAGGLE_USERNAME": "az**iz",
    }


def test_detects_access_token_file_with_unicode_bom_without_leaking_secret(
    monkeypatch,
) -> None:
    monkeypatch.delenv("KAGGLE_API_TOKEN", raising=False)
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    token_dir = Path("test-output") / "doctor"
    token_dir.mkdir(parents=True, exist_ok=True)
    token_path = token_dir / "access_token"
    token_path.write_bytes("\ufeffkg-file-token\x00\n".encode("utf-16"))

    credentials = detect_kaggle_credentials(access_token_path=token_path)

    assert credentials.available is True
    assert credentials.mode == "access_token"
    assert credentials.redacted_values == {"KAGGLE_API_TOKEN": "kg*********en"}
    assert credentials.redacted_values["KAGGLE_API_TOKEN"] != "kg-file-token"
    assert os.environ["KAGGLE_API_TOKEN"] == "kg-file-token"
    assert "kg-file-token" not in repr(credentials)


def test_dependency_checks_report_python_and_modules() -> None:
    checks = check_dependencies(
        ["sys", "definitely_missing_kgmon_dependency"],
        sys.version_info,
    )

    assert checks == [
        DependencyCheck(name="python", installed=True, detail=sys.version.split()[0]),
        DependencyCheck(name="sys", installed=True, detail="available"),
        DependencyCheck(
            name="definitely_missing_kgmon_dependency",
            installed=False,
            detail="not installed",
        ),
    ]


def test_doctor_report_is_secret_safe(monkeypatch) -> None:
    monkeypatch.setenv("KAGGLE_API_TOKEN", "kg-token-value")

    report = build_doctor_report(["sys"], sys.version_info)

    assert report.credentials.available is True
    assert report.credentials.mode == "KAGGLE_API_TOKEN"
    assert "kg-token-value" not in report.to_text()
    assert "kg**********ue" in report.to_text()

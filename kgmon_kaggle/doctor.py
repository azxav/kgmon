from __future__ import annotations

import importlib.util
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from kgmon_kaggle.redaction import redact_mapping


@dataclass(frozen=True)
class DependencyCheck:
    name: str
    installed: bool
    detail: str


@dataclass(frozen=True)
class CredentialStatus:
    available: bool
    mode: str
    redacted_values: dict[str, str]


@dataclass(frozen=True)
class DoctorReport:
    dependencies: list[DependencyCheck]
    credentials: CredentialStatus
    vendor_available: bool

    def to_text(self) -> str:
        lines = ["KGMON Kaggle doctor", "", "Dependencies:"]
        for dependency in self.dependencies:
            marker = "ok" if dependency.installed else "missing"
            lines.append(f"- {dependency.name}: {marker} ({dependency.detail})")

        credential_marker = "ok" if self.credentials.available else "missing"
        lines.extend(
            [
                "",
                "Credentials:",
                f"- mode: {self.credentials.mode}",
                f"- status: {credential_marker}",
            ]
        )
        for key, value in self.credentials.redacted_values.items():
            lines.append(f"- {key}: {value}")

        vendor_marker = "ok" if self.vendor_available else "missing"
        lines.extend(["", "Vendor:", f"- shepsci/kaggle-skill: {vendor_marker}"])
        return "\n".join(lines)


class VersionInfo(Protocol):
    @property
    def major(self) -> int: ...

    @property
    def minor(self) -> int: ...

    @property
    def micro(self) -> int: ...


MODULE_IMPORT_NAMES = {
    "python-dotenv": "dotenv",
}


def check_dependencies(
    module_names: Sequence[str],
    version_info: VersionInfo,
) -> list[DependencyCheck]:
    python_version = f"{version_info.major}.{version_info.minor}.{version_info.micro}"
    checks = [
        DependencyCheck(
            name="python",
            installed=(version_info.major, version_info.minor) >= (3, 11),
            detail=python_version,
        )
    ]

    for module_name in module_names:
        import_name = MODULE_IMPORT_NAMES.get(module_name, module_name)
        installed = importlib.util.find_spec(import_name) is not None
        checks.append(
            DependencyCheck(
                name=module_name,
                installed=installed,
                detail="available" if installed else "not installed",
            )
        )
    return checks


def detect_kaggle_credentials(
    environ: dict[str, str] | None = None,
    access_token_path: Path | None = None,
) -> CredentialStatus:
    env = os.environ if environ is None else environ
    api_token = env.get("KAGGLE_API_TOKEN")
    if api_token:
        return CredentialStatus(
            available=True,
            mode="KAGGLE_API_TOKEN",
            redacted_values=redact_mapping({"KAGGLE_API_TOKEN": api_token}),
        )

    access_token = _read_access_token(
        access_token_path or Path.home() / ".kaggle" / "access_token"
    )
    if access_token:
        if environ is None:
            os.environ["KAGGLE_API_TOKEN"] = access_token
        return CredentialStatus(
            available=True,
            mode="access_token",
            redacted_values=redact_mapping({"KAGGLE_API_TOKEN": access_token}),
        )

    username = env.get("KAGGLE_USERNAME")
    key = env.get("KAGGLE_KEY")
    if username and key:
        return CredentialStatus(
            available=True,
            mode="legacy",
            redacted_values=redact_mapping(
                {"KAGGLE_KEY": key, "KAGGLE_USERNAME": username}
            ),
        )

    return CredentialStatus(available=False, mode="missing", redacted_values={})


def _read_access_token(path: Path) -> str | None:
    if not path.exists():
        return None

    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            token = _clean_token(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
        if token:
            return token
    return None


def _clean_token(text: str) -> str:
    return text.replace("\ufeff", "").replace("\x00", "").strip()


def build_doctor_report(
    module_names: Sequence[str],
    version_info: VersionInfo,
    vendor_available: bool = False,
) -> DoctorReport:
    return DoctorReport(
        dependencies=check_dependencies(module_names, version_info),
        credentials=detect_kaggle_credentials(),
        vendor_available=vendor_available,
    )

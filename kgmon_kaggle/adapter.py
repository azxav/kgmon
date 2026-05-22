from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from kgmon_kaggle.doctor import CredentialStatus, detect_kaggle_credentials


@dataclass(frozen=True)
class CompetitionManifest:
    slug: str
    url: str
    files: list[dict[str, Any]]


@dataclass(frozen=True)
class CompetitionPage:
    name: str
    content: str


@dataclass(frozen=True)
class DownloadedFile:
    path: Path
    size: int


class KaggleAccessError(RuntimeError):
    """Raised when the wrapped Kaggle access layer fails."""


Runner = Callable[
    [list[str]],
    subprocess.CompletedProcess[str],
]


def _default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


class KaggleAccessAdapter:
    """Adapter around the vendored `shepsci/kaggle-skill` access layer."""

    def __init__(
        self,
        vendor_root: Path | None = None,
        runner: Runner = _default_runner,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        self.vendor_root = vendor_root or repo_root / "vendor" / "kaggle-skill"
        self.runner = runner

    def check_credentials(self) -> CredentialStatus:
        script = (
            self.vendor_root
            / "skills"
            / "kaggle"
            / "modules"
            / "kllm"
            / "scripts"
            / "check_credentials.py"
        )
        if script.exists():
            result = self.runner([sys.executable, str(script)])
            if result.returncode != 0:
                credentials = detect_kaggle_credentials()
                return CredentialStatus(
                    available=False,
                    mode=credentials.mode,
                    redacted_values=credentials.redacted_values,
                )
        return detect_kaggle_credentials()

    def get_competition_manifest(self, slug: str) -> CompetitionManifest:
        script = (
            self.vendor_root
            / "skills"
            / "kaggle"
            / "modules"
            / "comp-report"
            / "scripts"
            / "competition_details.py"
        )
        result = self._run([sys.executable, str(script), "--slug", slug])
        payload = _extract_json_object(result.stdout)
        return CompetitionManifest(
            slug=payload.get("slug", slug),
            url=payload.get("url", f"https://www.kaggle.com/competitions/{slug}"),
            files=list(payload.get("files") or []),
        )

    def fetch_competition_pages(
        self,
        slug: str,
        pages: list[str] | None = None,
    ) -> list[CompetitionPage]:
        script = (
            self.vendor_root
            / "skills"
            / "kaggle"
            / "modules"
            / "kllm"
            / "scripts"
            / "list_competition_pages.py"
        )
        command = [sys.executable, str(script), "--competition", slug, "--pretty"]
        result = self._run(command)
        payload = _extract_json_object(result.stdout)
        raw_pages = ((payload.get("data") or {}).get("pages") or [])

        selected_pages = []
        wanted = {page.lower() for page in pages or []}
        for raw_page in raw_pages:
            name = str(raw_page.get("name") or "unnamed")
            if wanted and not any(needle in name.lower() for needle in wanted):
                continue
            selected_pages.append(
                CompetitionPage(name=name, content=str(raw_page.get("content") or ""))
            )
        return selected_pages

    def download_competition_data(
        self,
        slug: str,
        output_dir: Path,
    ) -> list[DownloadedFile]:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                "kaggle",
                "competitions",
                "download",
                slug,
                "--path",
                str(output_dir),
            ]
        )
        _extract_download_archives(output_dir)
        return [
            DownloadedFile(path=path, size=path.stat().st_size)
            for path in sorted(output_dir.rglob("*"))
            if path.is_file()
        ]

    def push_notebook(self, notebook_path: Path, metadata: dict[str, object]) -> str:
        metadata_path = notebook_path.with_name("kernel-metadata.json")
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        result = self._run(
            [
                "kaggle",
                "kernels",
                "push",
                "--path",
                str(notebook_path.parent),
            ]
        )
        output = (result.stdout or result.stderr).strip()
        return output.splitlines()[-1] if output else notebook_path.stem

    def run_notebook(self, notebook_ref: str) -> str:
        result = self._run(["kaggle", "kernels", "status", notebook_ref])
        output = (result.stdout or result.stderr).strip()
        return output or notebook_ref

    def download_notebook_output(self, notebook_ref: str, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                "kaggle",
                "kernels",
                "output",
                notebook_ref,
                "--path",
                str(output_dir),
            ]
        )
        outputs = sorted(path for path in output_dir.rglob("*") if path.is_file())
        if not outputs:
            raise KaggleAccessError("notebook output download returned no files")
        return outputs[0]

    def submit_predictions(
        self,
        slug: str,
        submission_path: Path,
        message: str,
    ) -> str:
        result = self._run(
            [
                "kaggle",
                "competitions",
                "submit",
                slug,
                "--file",
                str(submission_path),
                "--message",
                message,
            ]
        )
        return (result.stdout or result.stderr).strip() or "submitted"

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        result = self.runner(command)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            detail = _add_network_hint(detail)
            raise KaggleAccessError(detail or f"command failed: {' '.join(command)}")
        return result


def _extract_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start == -1:
        raise KaggleAccessError("Kaggle access output did not contain JSON.")

    depth = 0
    in_string = False
    escaped = False
    for index, character in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return cast(dict[str, Any], json.loads(text[start : index + 1]))

    raise KaggleAccessError("Kaggle access output contained incomplete JSON.")


def _add_network_hint(detail: str) -> str:
    lowered = detail.lower()
    if "127.0.0.1:9" not in lowered:
        return detail
    return (
        f"{detail}\n\n"
        "Codex sandbox network access appears blocked. Live Kaggle CLI/MCP "
        "calls need escalated network approval."
    )


def _extract_download_archives(output_dir: Path) -> None:
    for archive in output_dir.glob("*.zip"):
        with zipfile.ZipFile(archive) as zip_file:
            for member in zip_file.infolist():
                destination = (output_dir / member.filename).resolve()
                if not destination.is_relative_to(output_dir.resolve()):
                    raise KaggleAccessError(
                        f"refusing to extract unsafe archive member: {member.filename}"
                    )
            zip_file.extractall(output_dir)

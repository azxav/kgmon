from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentRole:
    id: str
    lane: str
    title: str
    permitted_tools: tuple[str, ...]
    input_artifact_types: tuple[str, ...]
    output_artifact_types: tuple[str, ...]
    verification_obligations: tuple[str, ...]
    may_write_final_artifacts: bool = False

    @property
    def key(self) -> str:
        return self.id.removeprefix("kgmon:")

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "lane": self.lane,
            "title": self.title,
            "permitted_tools": list(self.permitted_tools),
            "input_artifact_types": list(self.input_artifact_types),
            "output_artifact_types": list(self.output_artifact_types),
            "verification_obligations": list(self.verification_obligations),
            "may_write_final_artifacts": self.may_write_final_artifacts,
        }


class AgentRegistry:
    def __init__(self, roles: list[AgentRole]) -> None:
        self._roles = {role.id: role for role in roles}
        self._aliases: dict[str, str] = {}
        for role in roles:
            self._aliases[role.key] = role.id
            self._aliases[role.key.replace("-", "_")] = role.id
        self._aliases["tabular"] = "kgmon:tabular-specialist"
        self._aliases["cv"] = "kgmon:cv-specialist"
        self._aliases["nlp"] = "kgmon:nlp-specialist"
        self._aliases["time-series"] = "kgmon:timeseries-specialist"
        self._aliases["time_series"] = "kgmon:timeseries-specialist"
        self._aliases["timeseries"] = "kgmon:timeseries-specialist"
        self._aliases["gpu"] = "kgmon:gpu-engineer"

    @classmethod
    def default(cls) -> AgentRegistry:
        return cls(
            [
                *_build_ml_roles(),
                *_review_roles(),
                *_domain_roles(),
                *_coordination_roles(),
            ]
        )

    def all(self) -> list[AgentRole]:
        return sorted(self._roles.values(), key=lambda role: role.id)

    def get(self, role: str) -> AgentRole:
        role_id = role if role.startswith("kgmon:") else self._aliases.get(role)
        if role_id is None or role_id not in self._roles:
            raise KeyError(f"unknown KGMON role: {role}")
        return self._roles[role_id]

    def allocate(self, spec: str) -> list[AgentRole]:
        count_text, _, role_text = spec.partition(":")
        if not role_text:
            count = 1
            role_name = count_text
        else:
            count = int(count_text)
            role_name = role_text
        if count < 1:
            raise ValueError("worker count must be at least 1")
        if count > 8:
            raise ValueError("worker count must not exceed 8")
        role = self.get(role_name)
        return [role for _ in range(count)]


def _build_ml_roles() -> list[AgentRole]:
    return [
        _role(
            "scout",
            "build_ml",
            "Competition Scout",
            ("kgmon.bootstrap", "kgmon.artifacts.list"),
            ("competition_manifest", "kaggle_pages"),
            ("mission_brief",),
            ("KAGGLE_RULES_AUDITED",),
        ),
        _role(
            "profiler",
            "build_ml",
            "Data Profiler",
            ("kgmon.data.profile", "kgmon.artifacts.list"),
            ("raw_data",),
            ("data_profile",),
            ("DATA_PROFILE_EXISTS",),
        ),
        _role(
            "validator",
            "build_ml",
            "Validation Engineer",
            ("kgmon.validation.plan", "kgmon.artifacts.list"),
            ("data_profile", "competition_manifest"),
            ("validation_plan",),
            ("VALIDATION_FIXED", "LEAKAGE_CHECK_PASS"),
        ),
        _role(
            "feature-engineer",
            "build_ml",
            "Feature Engineer",
            ("kgmon.experiment.plan", "kgmon.artifacts.list"),
            ("validation_plan", "raw_data"),
            ("feature_report",),
            ("NO_UNAPPROVED_EXTERNAL_DATA",),
        ),
        _role(
            "modeler",
            "build_ml",
            "Modeler",
            ("kgmon.experiment.plan", "kgmon.experiment.run", "kgmon.artifacts.list"),
            ("validation_plan", "feature_report"),
            ("model_report", "oof_predictions", "test_predictions"),
            ("OOF_CONTRACT_PASS", "TEST_PRED_CONTRACT_PASS"),
        ),
        _role(
            "ensembler",
            "build_ml",
            "Ensembler",
            ("kgmon.ensemble.search", "kgmon.artifacts.list"),
            ("oof_predictions", "test_predictions"),
            ("ensemble_report", "submission_candidate"),
            ("ENSEMBLE_REPRODUCIBLE",),
        ),
        _role(
            "error-analyst",
            "build_ml",
            "Error Analyst",
            ("kgmon.artifacts.list",),
            ("oof_predictions", "model_report", "ensemble_report"),
            ("error_analysis_report", "postprocess_report"),
            ("ERROR_ANALYSIS_BACKED_BY_OOF",),
        ),
        _role(
            "external-data-governor",
            "build_ml",
            "External Data Governor",
            ("kgmon.artifacts.list",),
            ("competition_manifest", "candidate_external_data"),
            ("external_data_audit",),
            ("EXTERNAL_DATA_RULE_APPROVED",),
        ),
        _role(
            "packager",
            "build_ml",
            "Packager",
            ("kgmon.package.final", "kgmon.artifacts.list"),
            ("submission_candidate", "ensemble_report"),
            ("package_plan",),
            ("PACKAGE_REPRODUCIBLE",),
        ),
        _role(
            "verifier",
            "build_ml",
            "Verifier",
            ("kgmon.verify.all", "kgmon.artifacts.list"),
            ("package_plan", "verification_evidence"),
            ("verification_report",),
            ("SUBMISSION_SCHEMA_PASS", "NO_SECRET_LEAK"),
        ),
    ]


def _review_roles() -> list[AgentRole]:
    return [
        _role(
            "critic",
            "review",
            "Critic",
            ("kgmon.artifacts.list",),
            ("plan_bundle",),
            ("critique_report",),
            ("CONFIG_VALID",),
        ),
        _role(
            "security-reviewer",
            "review",
            "Security Reviewer",
            ("kgmon.verify.all",),
            ("artifact_descriptor",),
            ("security_review",),
            ("NO_SECRET_LEAK", "NO_UNAPPROVED_AUTOSUBMIT"),
        ),
        _role(
            "leakage-auditor",
            "review",
            "Leakage Auditor",
            ("kgmon.validation.plan",),
            ("validation_plan", "data_profile"),
            ("leakage_audit",),
            ("LEAKAGE_CHECK_PASS",),
        ),
        _role(
            "reproducibility-reviewer",
            "review",
            "Reproducibility Reviewer",
            ("kgmon.verify.all",),
            ("run_report", "package_plan"),
            ("reproducibility_review",),
            ("PACKAGE_REPRODUCIBLE",),
        ),
    ]


def _domain_roles() -> list[AgentRole]:
    return [
        _role(
            key,
            "domain",
            title,
            ("kgmon.experiment.plan", "kgmon.artifacts.list"),
            ("competition_manifest", "data_profile"),
            ("domain_recommendations",),
            ("KAGGLE_RULES_AUDITED",),
        )
        for key, title in (
            ("tabular-specialist", "Tabular Specialist"),
            ("cv-specialist", "CV Specialist"),
            ("nlp-specialist", "NLP Specialist"),
            ("timeseries-specialist", "Timeseries Specialist"),
            ("recommendation-specialist", "Recommendation Specialist"),
            ("optimization-specialist", "Optimization Specialist"),
            ("gpu-engineer", "GPU Engineer"),
            ("documenter", "Documenter"),
        )
    ]


def _coordination_roles() -> list[AgentRole]:
    return [
        _role(
            key,
            "coordination",
            title,
            ("kgmon.ralplan", "kgmon.team.run", "kgmon.artifacts.list"),
            ("mission_brief", "artifact_descriptor"),
            ("coordination_report",),
            ("CONFIG_VALID",),
        )
        for key, title in (
            ("planner", "Planner"),
            ("architect", "Architect"),
            ("team-lead", "Team Lead"),
            ("git-master", "Git Master"),
        )
    ]


def _role(
    key: str,
    lane: str,
    title: str,
    permitted_tools: tuple[str, ...],
    input_artifact_types: tuple[str, ...],
    output_artifact_types: tuple[str, ...],
    verification_obligations: tuple[str, ...],
) -> AgentRole:
    return AgentRole(
        id=f"kgmon:{key}",
        lane=lane,
        title=title,
        permitted_tools=permitted_tools,
        input_artifact_types=input_artifact_types,
        output_artifact_types=output_artifact_types,
        verification_obligations=verification_obligations,
    )

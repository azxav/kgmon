from __future__ import annotations

PROMPT_ID_MAP: dict[str, str] = {
    "kgmon_dsml_master": "master-dsml-operating",
    "kgmon_competition_deep_interview": "kaggle-competition-deep-interview",
    "kgmon_ralplan_ml_consensus": "ml-consensus-ralplan",
    "kgmon_team_ds_workflow": "dsml-team-workflow",
    "kgmon_ralph_ml_verification_loop": "ralph-ml-verification-loop",
    "kgmon_ultrawork_experiment_burst": "ultrawork-experiment-burst",
    "kgmon_validation_design": "validation-design",
    "kgmon_leakage_audit": "leakage-audit",
    "kgmon_feature_generation": "feature-generation",
    "kgmon_modeling_plan": "modeling-plan",
    "kgmon_ensemble_search": "ensemble-search",
    "kgmon_error_analysis_postprocess": "error-analysis-postprocessing",
    "kgmon_final_package": "final-kaggle-package-verification",
    "kgmon_writeup_research": "kaggle-writeup-research",
}


def internal_prompt_id(public_prompt_id: str) -> str:
    return PROMPT_ID_MAP.get(public_prompt_id, public_prompt_id)

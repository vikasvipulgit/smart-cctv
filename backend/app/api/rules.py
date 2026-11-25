"""Create, edit, enable/disable and delete rules. Changes are saved to rules.yaml and applied live."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..config_store import RuleConfig, load_rules, save_rules
from ..pipeline.manager import pipeline

router = APIRouter(prefix="/api/rules", tags=["rules"])


def _apply(rules: list[RuleConfig]) -> list[RuleConfig]:
    save_rules(rules)
    pipeline.reload_rules(rules)
    return rules


@router.get("", response_model=list[RuleConfig])
def list_rules():
    return load_rules()


@router.post("", response_model=RuleConfig)
def create_rule(rule: RuleConfig):
    rules = load_rules()
    if any(r.id == rule.id for r in rules):
        raise HTTPException(409, f"Rule id {rule.id!r} already exists")
    _apply([*rules, rule])
    return rule


@router.put("/{rule_id}", response_model=RuleConfig)
def update_rule(rule_id: str, rule: RuleConfig):
    rules = load_rules()
    for i, r in enumerate(rules):
        if r.id == rule_id:
            rules[i] = rule
            _apply(rules)
            return rule
    raise HTTPException(404, "Rule not found")


@router.patch("/{rule_id}/enabled", response_model=RuleConfig)
def set_enabled(rule_id: str, enabled: bool):
    rules = load_rules()
    for r in rules:
        if r.id == rule_id:
            r.enabled = enabled
            _apply(rules)
            return r
    raise HTTPException(404, "Rule not found")


@router.delete("/{rule_id}")
def delete_rule(rule_id: str):
    rules = load_rules()
    remaining = [r for r in rules if r.id != rule_id]
    if len(remaining) == len(rules):
        raise HTTPException(404, "Rule not found")
    _apply(remaining)
    return {"ok": True}

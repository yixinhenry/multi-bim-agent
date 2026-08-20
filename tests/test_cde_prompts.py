from __future__ import annotations

from bim_multi.domain import MOD_ROLE_DETAILS, ROLE_PERMISSION_CODES, CDEState, ProjectRole
from bim_multi.prompts import role_can_access_state, system_prompt_for_role


def test_all_role_permissions_match_the_cde_reference() -> None:
    assert len(ROLE_PERMISSION_CODES) == 26
    common = ("P01", "P07", "P10", "P11", "P15", "P17")
    for role, (_, _, query, property_edit, geometry_edit) in MOD_ROLE_DETAILS.items():
        assert ROLE_PERMISSION_CODES[role] == common + (
            query,
            property_edit,
            geometry_edit,
        )


def test_state_prompt_combines_role_and_current_cde_permissions() -> None:
    shared = system_prompt_for_role("Base", ProjectRole.PM_BIM, CDEState.SHARED)
    assert "P14" in shared
    assert "Current CDE state: Shared" in shared
    assert "Shared access requires P02 and is read-only" in shared
    assert "has state access" in shared

    denied = system_prompt_for_role("Base", ProjectRole.CL_REP, CDEState.WIP)
    assert "Current CDE state: WIP" in denied
    assert "has no access to this CDE state" in denied
    assert "B01 always applies" in denied


def test_role_state_access_is_prompt_only_and_follows_permission_codes() -> None:
    assert role_can_access_state(ProjectRole.ARC_MOD_SHELL, CDEState.WIP)
    assert not role_can_access_state(ProjectRole.ARC_MOD_SHELL, CDEState.SHARED)
    assert not role_can_access_state(ProjectRole.ARC_MOD_SHELL, CDEState.PUBLISHED)
    assert role_can_access_state(ProjectRole.ARC_CHK, CDEState.WIP)
    assert not role_can_access_state(ProjectRole.ARC_CHK, CDEState.SHARED)
    assert role_can_access_state(ProjectRole.CL_APP, CDEState.PUBLISHED)
    assert role_can_access_state(ProjectRole.PM_BIM, CDEState.ARCHIVED)

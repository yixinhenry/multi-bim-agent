from __future__ import annotations

from bim_multi.domain import ROLE_PERMISSION_CODES, CDEState, ProjectRole
from bim_multi.prompts import role_can_access_state, system_prompt_for_role


def test_all_role_permissions_match_the_cde_reference() -> None:
    expected = {
        ProjectRole.CL_REP: ("P04", "P05", "P06", "P15"),
        ProjectRole.CL_APP: ("P04", "P05", "P06", "P15", "P20"),
        ProjectRole.PM_BIM: (
            "P02", "P03", "P04", "P05", "P06", "P14", "P15", "P16", "P17", "P21"
        ),
        ProjectRole.PM_CTL: ("P02", "P03", "P04", "P05", "P15", "P18"),
        ProjectRole.PM_MGR: (
            "P02", "P03", "P04", "P05", "P06", "P15", "P16", "P17", "P19"
        ),
        ProjectRole.ARC_MOD: (
            "P01", "P02", "P05", "P07", "P08", "P09", "P10", "P11", "P15", "P17"
        ),
        ProjectRole.ARC_CHK: ("P01", "P02", "P05", "P12", "P15", "P17"),
        ProjectRole.ARC_LEAD: (
            "P01", "P02", "P03", "P04", "P05", "P06", "P13", "P15", "P16", "P17"
        ),
        ProjectRole.STR_MOD: (
            "P01", "P02", "P05", "P07", "P08", "P09", "P10", "P11", "P15", "P17"
        ),
        ProjectRole.STR_CHK: ("P01", "P02", "P05", "P12", "P15", "P17"),
        ProjectRole.STR_LEAD: (
            "P01", "P02", "P03", "P04", "P05", "P06", "P13", "P15", "P16", "P17"
        ),
        ProjectRole.MEP_MOD: (
            "P01", "P02", "P05", "P07", "P08", "P09", "P10", "P11", "P15", "P17"
        ),
        ProjectRole.MEP_CHK: ("P01", "P02", "P05", "P12", "P15", "P17"),
        ProjectRole.MEP_LEAD: (
            "P01", "P02", "P03", "P04", "P05", "P06", "P13", "P15", "P16", "P17"
        ),
    }
    assert ROLE_PERMISSION_CODES == expected


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
    assert role_can_access_state(ProjectRole.ARC_MOD, CDEState.WIP)
    assert role_can_access_state(ProjectRole.ARC_MOD, CDEState.SHARED)
    assert not role_can_access_state(ProjectRole.ARC_MOD, CDEState.PUBLISHED)
    assert role_can_access_state(ProjectRole.CL_APP, CDEState.PUBLISHED)
    assert role_can_access_state(ProjectRole.PM_BIM, CDEState.ARCHIVED)


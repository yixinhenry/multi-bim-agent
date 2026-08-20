from __future__ import annotations

from bim_multi.domain import CDEState, ProjectRole, viewer_model_choices


ALL_SLOTS = {
    (discipline, state)
    for discipline in ("ARC", "STR", "MEP")
    for state in CDEState
}


def test_mod_and_checker_only_receive_their_discipline_wip() -> None:
    expected = ((('ARC', CDEState.WIP),),)
    assert viewer_model_choices(ProjectRole.ARC_MOD_SHELL, ALL_SLOTS) == expected
    assert viewer_model_choices(ProjectRole.ARC_CHK, ALL_SLOTS) == expected


def test_lead_shared_federations_always_include_own_discipline() -> None:
    choices = viewer_model_choices(ProjectRole.ARC_LEAD, ALL_SLOTS)
    assert (("ARC", CDEState.WIP),) in choices
    assert (("ARC", CDEState.SHARED),) in choices
    assert (("STR", CDEState.SHARED),) not in choices
    federations = [choice for choice in choices if len(choice) > 1]
    assert len(federations) == 3
    assert all(("ARC", CDEState.SHARED) in choice for choice in federations)


def test_pm_and_client_choices_do_not_mix_cde_states() -> None:
    pm_bim = viewer_model_choices(ProjectRole.PM_BIM, ALL_SLOTS)
    pm_ctl = viewer_model_choices(ProjectRole.PM_CTL, ALL_SLOTS)
    client = viewer_model_choices(ProjectRole.CL_REP, ALL_SLOTS)

    assert len(pm_bim) == 13
    assert len(pm_ctl) == 10
    assert len(client) == 3
    assert all(len({state for _, state in choice}) == 1 for choice in pm_bim)
    assert all(choice[0][1] is CDEState.PUBLISHED for choice in client)

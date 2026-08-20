from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations


class Identity(StrEnum):
    CLIENT = "CLIENT"
    PROJECT_MANAGER = "PROJECT_MANAGER"
    ARC = "ARC"
    STR = "STR"
    MEP = "MEP"


class ProjectRole(StrEnum):
    CL_REP = "CL-REP"
    CL_APP = "CL-APP"
    PM_BIM = "PM-BIM"
    PM_CTL = "PM-CTL"
    PM_MGR = "PM-MGR"
    ARC_MOD_SHELL = "ARC-MOD-SHELL"
    ARC_MOD_INTERIOR = "ARC-MOD-INTERIOR"
    ARC_MOD_FACADE = "ARC-MOD-FACADE"
    ARC_MOD_FIRE = "ARC-MOD-FIRE"
    ARC_MOD_SITE = "ARC-MOD-SITE"
    ARC_CHK = "ARC-CHK"
    ARC_LEAD = "ARC-LEAD"
    STR_MOD_FOUNDATION = "STR-MOD-FOUNDATION"
    STR_MOD_CONCRETE = "STR-MOD-CONCRETE"
    STR_MOD_STEEL = "STR-MOD-STEEL"
    STR_MOD_REBAR = "STR-MOD-REBAR"
    STR_CHK = "STR-CHK"
    STR_LEAD = "STR-LEAD"
    MEP_MOD_HVAC = "MEP-MOD-HVAC"
    MEP_MOD_PLUMBING = "MEP-MOD-PLUMBING"
    MEP_MOD_FIRE = "MEP-MOD-FIRE"
    MEP_MOD_ELECTRICAL = "MEP-MOD-ELECTRICAL"
    MEP_MOD_ELV = "MEP-MOD-ELV"
    MEP_MOD_BMS = "MEP-MOD-BMS"
    MEP_CHK = "MEP-CHK"
    MEP_LEAD = "MEP-LEAD"


class CDEState(StrEnum):
    WIP = "WIP"
    SHARED = "Shared"
    PUBLISHED = "Published"
    ARCHIVED = "Archived"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class IdentityProfile:
    identity: Identity
    label: str
    agent_id: str
    declared_role: str
    expected_files: frozenset[str]


@dataclass(frozen=True)
class ProjectRoleProfile:
    role: ProjectRole
    identity: Identity
    label: str
    responsibility: str
    prompt_policy: str


PROFILES = {
    Identity.CLIENT: IdentityProfile(
        Identity.CLIENT,
        "Client",
        "project-manager-agent",
        "Client-facing Project Manager Agent",
        frozenset({"ARC.ifc", "STR.ifc", "MEP.ifc"}),
    ),
    Identity.PROJECT_MANAGER: IdentityProfile(
        Identity.PROJECT_MANAGER,
        "Project Management",
        "project-manager-agent",
        "Project Manager Agent",
        frozenset({"ARC.ifc", "STR.ifc", "MEP.ifc"}),
    ),
    Identity.ARC: IdentityProfile(
        Identity.ARC, "ARC", "arc-agent", "ARC Agent", frozenset({"ARC.ifc"})
    ),
    Identity.STR: IdentityProfile(
        Identity.STR, "STR", "str-agent", "STR Agent", frozenset({"STR.ifc"})
    ),
    Identity.MEP: IdentityProfile(
        Identity.MEP, "MEP", "mep-agent", "MEP Agent", frozenset({"MEP.ifc"})
    ),
}


MOD_ROLE_DETAILS = {
    ProjectRole.ARC_MOD_SHELL: (Identity.ARC, "Shell", "P0501", "P0801", "P0901"),
    ProjectRole.ARC_MOD_INTERIOR: (Identity.ARC, "Interior", "P0502", "P0802", "P0902"),
    ProjectRole.ARC_MOD_FACADE: (Identity.ARC, "Facade", "P0503", "P0803", "P0903"),
    ProjectRole.ARC_MOD_FIRE: (Identity.ARC, "Fire", "P0504", "P0804", "P0904"),
    ProjectRole.ARC_MOD_SITE: (Identity.ARC, "Site", "P0505", "P0805", "P0905"),
    ProjectRole.STR_MOD_FOUNDATION: (Identity.STR, "Foundation", "P0511", "P0811", "P0911"),
    ProjectRole.STR_MOD_CONCRETE: (Identity.STR, "Concrete", "P0512", "P0812", "P0912"),
    ProjectRole.STR_MOD_STEEL: (Identity.STR, "Steel", "P0513", "P0813", "P0913"),
    ProjectRole.STR_MOD_REBAR: (Identity.STR, "Rebar", "P0514", "P0814", "P0914"),
    ProjectRole.MEP_MOD_HVAC: (Identity.MEP, "HVAC", "P0521", "P0821", "P0921"),
    ProjectRole.MEP_MOD_PLUMBING: (Identity.MEP, "Plumbing", "P0522", "P0822", "P0922"),
    ProjectRole.MEP_MOD_FIRE: (Identity.MEP, "Fire", "P0523", "P0823", "P0923"),
    ProjectRole.MEP_MOD_ELECTRICAL: (Identity.MEP, "Electrical", "P0524", "P0824", "P0924"),
    ProjectRole.MEP_MOD_ELV: (Identity.MEP, "ELV", "P0525", "P0825", "P0925"),
    ProjectRole.MEP_MOD_BMS: (Identity.MEP, "BMS", "P0526", "P0826", "P0926"),
}

MOD_ROLES_BY_IDENTITY = {
    identity: tuple(
        role for role, details in MOD_ROLE_DETAILS.items() if details[0] is identity
    )
    for identity in (Identity.ARC, Identity.STR, Identity.MEP)
}
MOD_ROLES = frozenset(MOD_ROLE_DETAILS)
CHECKER_ROLES = frozenset(
    {ProjectRole.ARC_CHK, ProjectRole.STR_CHK, ProjectRole.MEP_CHK}
)
DISCIPLINE_LEADS = frozenset(
    {ProjectRole.ARC_LEAD, ProjectRole.STR_LEAD, ProjectRole.MEP_LEAD}
)


ROLE_PERMISSION_CODES = {
    ProjectRole.CL_REP: ("P04", "P05", "P06", "P15"),
    ProjectRole.CL_APP: ("P04", "P05", "P06", "P15", "P20"),
    ProjectRole.PM_BIM: (
        "P02", "P03", "P04", "P05", "P06", "P14", "P15", "P16", "P17", "P21"
    ),
    ProjectRole.PM_CTL: ("P02", "P03", "P04", "P05", "P15", "P18"),
    ProjectRole.PM_MGR: (
        "P02", "P03", "P04", "P05", "P06", "P15", "P16", "P17", "P19"
    ),
    ProjectRole.ARC_CHK: ("P01", "P05", "P12", "P15", "P17"),
    ProjectRole.ARC_LEAD: (
        "P01", "P02", "P03", "P04", "P05", "P06", "P13", "P15", "P16", "P17"
    ),
    ProjectRole.STR_CHK: ("P01", "P05", "P12", "P15", "P17"),
    ProjectRole.STR_LEAD: (
        "P01", "P02", "P03", "P04", "P05", "P06", "P13", "P15", "P16", "P17"
    ),
    ProjectRole.MEP_CHK: ("P01", "P05", "P12", "P15", "P17"),
    ProjectRole.MEP_LEAD: (
        "P01", "P02", "P03", "P04", "P05", "P06", "P13", "P15", "P16", "P17"
    ),
}
for _role, (_, _, _query, _property, _geometry) in MOD_ROLE_DETAILS.items():
    ROLE_PERMISSION_CODES[_role] = (
        "P01", "P07", "P10", "P11", "P15", "P17", _query, _property, _geometry
    )


def _policy(role: ProjectRole, allowed: str, forbidden: str) -> str:
    codes = ", ".join(ROLE_PERMISSION_CODES[role])
    return (
        f"Granted permission codes: {codes}. Allowed: {allowed} "
        f"Forbidden: {forbidden} B01 always applies: never modify another "
        "discipline, an unassigned element, or a non-WIP IFC. Any permission "
        "not explicitly granted is denied."
    )


def _modeler_policy(role: ProjectRole) -> str:
    identity, category, query, property_edit, geometry_edit = MOD_ROLE_DETAILS[role]
    discipline = identity.value
    return _policy(
        role,
        f"Access only the {discipline} WIP model. Query {category} elements under "
        f"{query}; modify assigned {category} properties under {property_edit} and "
        f"geometry under {geometry_edit}; upload or replace {discipline} WIP; create "
        "Issues and update assigned remediation results.",
        f"Do not access Shared or federated models; modify other {discipline} "
        "categories or another discipline; review, publish, archive, assign Issues, "
        "or run clash detection.",
    )


def _checker_policy(role: ProjectRole, discipline: str) -> str:
    return _policy(
        role,
        f"View and query only the {discipline} WIP model and view Issues assigned "
        f"to {discipline}.",
        "Do not access Shared or federated models; edit a model; submit Shared; "
        "publish, archive, assign Issues, or run clash detection.",
    )


def _lead_policy(role: ProjectRole, discipline: str) -> str:
    return _policy(
        role,
        f"View {discipline} WIP, {discipline} Shared, and authorized Shared federated "
        f"combinations containing {discipline}; copy {discipline} WIP to Shared; view "
        "Issues involving the discipline and assign responsibility by discipline.",
        "Do not edit a model directly; replace a checker; publish or archive IFCs; "
        "approve ordinary or major changes.",
    )


ROLE_PROMPT_POLICIES = {
    ProjectRole.CL_REP: _policy(
        ProjectRole.CL_REP,
        "View, query, and download authorized Published IFC deliverables and create Issues.",
        "Do not access WIP or Shared; edit, review, publish, archive, or run clash detection.",
    ),
    ProjectRole.CL_APP: _policy(
        ProjectRole.CL_APP,
        "View authorized Published IFCs, create Issues, approve major changes, and accept deliverables.",
        "Do not access WIP or Shared; edit, review, publish, archive, or run clash detection.",
    ),
    ProjectRole.PM_BIM: _policy(
        ProjectRole.PM_BIM,
        "View Shared discipline and federated models and Published models; run clash "
        "detection on the submitted Viewer Shared combination; manage coordination "
        "Issues; copy any discipline Shared to Published and Published to Archived.",
        "Do not edit discipline IFCs or require clash runs, closed Issues, or review "
        "gates before publishing.",
    ),
    ProjectRole.PM_CTL: _policy(
        ProjectRole.PM_CTL,
        "View relevant Shared, federated, and Published models and assess cost or schedule impacts.",
        "Do not access WIP; edit, review, publish, archive, or run clash detection.",
    ),
    ProjectRole.PM_MGR: _policy(
        ProjectRole.PM_MGR,
        "View Shared, federated, and Published models and manage project Issues and ordinary changes.",
        "Do not access WIP; edit, perform discipline review, publish, or archive.",
    ),
    ProjectRole.ARC_CHK: _checker_policy(ProjectRole.ARC_CHK, "ARC"),
    ProjectRole.ARC_LEAD: _lead_policy(ProjectRole.ARC_LEAD, "ARC"),
    ProjectRole.STR_CHK: _checker_policy(ProjectRole.STR_CHK, "STR"),
    ProjectRole.STR_LEAD: _lead_policy(ProjectRole.STR_LEAD, "STR"),
    ProjectRole.MEP_CHK: _checker_policy(ProjectRole.MEP_CHK, "MEP"),
    ProjectRole.MEP_LEAD: _lead_policy(ProjectRole.MEP_LEAD, "MEP"),
}
ROLE_PROMPT_POLICIES.update({role: _modeler_policy(role) for role in MOD_ROLE_DETAILS})


_BASE_ROLE_PROFILES = {
    ProjectRole.CL_REP: (Identity.CLIENT, "Client Representative", "View project information and raise requests."),
    ProjectRole.CL_APP: (Identity.CLIENT, "Client Approver", "Approve major changes and formal deliverables."),
    ProjectRole.PM_BIM: (Identity.PROJECT_MANAGER, "BIM/CDE Coordinator", "Coordinate Shared models, clashes, Issues, publishing, and archiving."),
    ProjectRole.PM_CTL: (Identity.PROJECT_MANAGER, "Project Controls Engineer", "Manage cost and schedule information."),
    ProjectRole.PM_MGR: (Identity.PROJECT_MANAGER, "Project Manager", "Resolve project matters and approve ordinary changes."),
    ProjectRole.ARC_CHK: (Identity.ARC, "ARC Checker", "View ARC WIP and discipline Issues."),
    ProjectRole.ARC_LEAD: (Identity.ARC, "ARC Lead", "Submit ARC WIP to Shared and coordinate ARC Issues."),
    ProjectRole.STR_CHK: (Identity.STR, "STR Checker", "View STR WIP and discipline Issues."),
    ProjectRole.STR_LEAD: (Identity.STR, "STR Lead", "Submit STR WIP to Shared and coordinate STR Issues."),
    ProjectRole.MEP_CHK: (Identity.MEP, "MEP Checker", "View MEP WIP and discipline Issues."),
    ProjectRole.MEP_LEAD: (Identity.MEP, "MEP Lead", "Submit MEP WIP to Shared and coordinate MEP Issues."),
}

ROLE_PROFILES = {
    role: ProjectRoleProfile(role, identity, label, responsibility, ROLE_PROMPT_POLICIES[role])
    for role, (identity, label, responsibility) in _BASE_ROLE_PROFILES.items()
}
for _role, (_identity, _category, _, _, _) in MOD_ROLE_DETAILS.items():
    ROLE_PROFILES[_role] = ProjectRoleProfile(
        _role,
        _identity,
        _role.value,
        f"Create and modify assigned {_category} elements in {_identity.value} WIP.",
        ROLE_PROMPT_POLICIES[_role],
    )


ROLES_BY_IDENTITY = {
    identity: tuple(role for role in ProjectRole if ROLE_PROFILES[role].identity is identity)
    for identity in Identity
}

DEFAULT_ROLE_BY_IDENTITY = {
    Identity.CLIENT: ProjectRole.CL_REP,
    Identity.PROJECT_MANAGER: ProjectRole.PM_MGR,
    Identity.ARC: ProjectRole.ARC_MOD_SHELL,
    Identity.STR: ProjectRole.STR_MOD_FOUNDATION,
    Identity.MEP: ProjectRole.MEP_MOD_HVAC,
}

SCHEDULE_VISIBLE_ROLES = frozenset(
    {
        ProjectRole.CL_REP,
        ProjectRole.CL_APP,
        ProjectRole.PM_BIM,
        ProjectRole.PM_CTL,
        ProjectRole.PM_MGR,
        *DISCIPLINE_LEADS,
    }
)


def role_discipline(role: ProjectRole) -> str | None:
    identity = ROLE_PROFILES[role].identity
    return identity.value if identity in {Identity.ARC, Identity.STR, Identity.MEP} else None


def viewer_model_choices(
    role: ProjectRole,
    available: set[tuple[str, CDEState]],
) -> tuple[tuple[tuple[str, CDEState], ...], ...]:
    """Return UI-visible single slots and Shared federations for one role."""
    discipline = role_discipline(role)
    if role in MOD_ROLES or role in CHECKER_ROLES:
        choice = ((discipline, CDEState.WIP),)
        return (choice,) if choice[0] in available else ()

    choices: list[tuple[tuple[str, CDEState], ...]] = []
    shared = [
        item
        for item in ((kind, CDEState.SHARED) for kind in ("ARC", "STR", "MEP"))
        if item in available
    ]
    if role in DISCIPLINE_LEADS:
        for state in (CDEState.WIP, CDEState.SHARED):
            item = (discipline, state)
            if item in available:
                choices.append((item,))
        for size in range(2, len(shared) + 1):
            choices.extend(
                combo
                for combo in combinations(shared, size)
                if any(kind == discipline for kind, _ in combo)
            )
        return tuple(choices)

    if ROLE_PROFILES[role].identity is Identity.PROJECT_MANAGER:
        for size in range(1, len(shared) + 1):
            choices.extend(combinations(shared, size))
        choices.extend(
            ((kind, CDEState.PUBLISHED),)
            for kind in ("ARC", "STR", "MEP")
            if (kind, CDEState.PUBLISHED) in available
        )
        if role is ProjectRole.PM_BIM:
            choices.extend(
                ((kind, CDEState.ARCHIVED),)
                for kind in ("ARC", "STR", "MEP")
                if (kind, CDEState.ARCHIVED) in available
            )
        return tuple(choices)

    return tuple(
        ((kind, CDEState.PUBLISHED),)
        for kind in ("ARC", "STR", "MEP")
        if (kind, CDEState.PUBLISHED) in available
    )


def can_view_clash_issue(
    role: ProjectRole,
    model_a: str,
    model_b: str,
    assigned_to: str | None,
) -> bool:
    if role is ProjectRole.PM_BIM:
        return True
    discipline = role_discipline(role)
    if role in DISCIPLINE_LEADS:
        return discipline in {model_a, model_b}
    if role in MOD_ROLES or role in CHECKER_ROLES:
        return assigned_to == discipline
    return False


def notification_recipient_key(role: ProjectRole) -> str | None:
    discipline = role_discipline(role)
    if role in MOD_ROLES:
        return f"{discipline}-MOD-GROUP"
    if role in CHECKER_ROLES or role in DISCIPLINE_LEADS or role is ProjectRole.PM_BIM:
        return role.value
    return None


def can_view_schedule(role: ProjectRole) -> bool:
    return role in SCHEDULE_VISIBLE_ROLES


def visible_context_roles(viewer_role: ProjectRole) -> tuple[ProjectRole, ...]:
    """Return role memories visible to a user at the application boundary."""
    if viewer_role in DISCIPLINE_LEADS:
        return ROLES_BY_IDENTITY[ROLE_PROFILES[viewer_role].identity]
    return (viewer_role,)


def can_view_role_context(viewer_role: ProjectRole, target_role: ProjectRole) -> bool:
    return target_role in visible_context_roles(viewer_role)


def role_conversation_key(role: ProjectRole) -> str:
    """Use stable per-role conversations; legacy main conversations remain stored."""
    return f"role:{role.value}"


def expected_access(identity: Identity, file_name: str, operation: str = "read_ifc") -> bool:
    """Return the existing low-level IFC boundary for an executing Agent identity."""
    if file_name not in PROFILES[identity].expected_files:
        return False
    if operation == "edit_ifc" and identity in {Identity.CLIENT, Identity.PROJECT_MANAGER}:
        return False
    return True

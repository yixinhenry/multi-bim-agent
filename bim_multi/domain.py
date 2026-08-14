from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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
    ARC_MOD = "ARC-MOD"
    ARC_CHK = "ARC-CHK"
    ARC_LEAD = "ARC-LEAD"
    STR_MOD = "STR-MOD"
    STR_CHK = "STR-CHK"
    STR_LEAD = "STR-LEAD"
    MEP_MOD = "MEP-MOD"
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
        "Project Manager",
        "project-manager-agent",
        "Project Manager Agent",
        frozenset({"ARC.ifc", "STR.ifc", "MEP.ifc"}),
    ),
    Identity.ARC: IdentityProfile(
        Identity.ARC,
        "ARC Engineer",
        "arc-agent",
        "ARC Agent",
        frozenset({"ARC.ifc"}),
    ),
    Identity.STR: IdentityProfile(
        Identity.STR,
        "STR Engineer",
        "str-agent",
        "STR Agent",
        frozenset({"STR.ifc"}),
    ),
    Identity.MEP: IdentityProfile(
        Identity.MEP,
        "MEP Engineer",
        "mep-agent",
        "MEP Agent",
        frozenset({"MEP.ifc"}),
    ),
}


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


def _policy(role: ProjectRole, allowed: str, forbidden: str) -> str:
    codes = ", ".join(ROLE_PERMISSION_CODES[role])
    return (
        f"Granted permission codes: {codes}. Allowed: {allowed} "
        f"Forbidden: {forbidden} B01 always applies: never modify another "
        "discipline, an unassigned element, or a non-WIP IFC. Any permission "
        "not explicitly granted is denied."
    )


def _modeler_policy(role: ProjectRole, discipline: str, others: str) -> str:
    return _policy(
        role,
        f"Access authorized {discipline} WIP and task-required Shared IFCs; query "
        f"accessible elements; upload {discipline} WIP; edit only assigned "
        f"{discipline} WIP elements; save a new revision and submit it for review; "
        "create Issues and update assigned remediation results.",
        f"Do not modify {others}, unassigned {discipline}, Shared, Published, or "
        "Archived content; review or approve your own work; run clash detection; "
        "approve design changes; publish or archive IFCs.",
    )


def _checker_policy(role: ProjectRole, discipline: str) -> str:
    return _policy(
        role,
        f"View submitted {discipline} WIP and review-required Shared IFCs; query "
        f"accessible elements; review {discipline} WIP, record conclusions, return "
        "nonconforming work, and update responsible review Issues.",
        f"Do not edit any discipline model; approve {discipline} for Shared; review "
        "another discipline; approve design changes; publish or archive IFCs.",
    )


def _lead_policy(role: ProjectRole, discipline: str) -> str:
    return _policy(
        role,
        f"View {discipline} WIP awaiting approval, Shared discipline and federated "
        "IFCs, and authorized Published IFCs; approve or reject the discipline IFC "
        "for Shared; create, assign, and update discipline Issues; confirm remediation "
        "and participate in cross-discipline coordination.",
        f"Do not directly edit {discipline} or another discipline model; replace the "
        f"{discipline} checker; approve ordinary or major design changes; publish or archive IFCs.",
    )


ROLE_PROMPT_POLICIES = {
    ProjectRole.CL_REP: _policy(
        ProjectRole.CL_REP,
        "View, query, and download authorized Published IFC deliverables and create "
        "Issues or change requests against accessible elements.",
        "Do not access WIP or unsigned Shared IFCs; upload, edit, revise, or submit "
        "IFCs; perform technical review, discipline approval, clash detection, "
        "publishing, archiving, change approval, or delivery acceptance.",
    ),
    ProjectRole.CL_APP: _policy(
        ProjectRole.CL_APP,
        "View, query, and download authorized Published IFCs; create Issues; approve "
        "or reject major changes; accept or reject formal IFC deliverables.",
        "Do not access or edit WIP; directly edit Shared or Published IFCs; perform "
        "technical review, ordinary change approval, clash detection, publishing, or archiving.",
    ),
    ProjectRole.PM_BIM: _policy(
        ProjectRole.PM_BIM,
        "View Shared discipline, Shared federated, and Published IFCs; query model, "
        "version, and coordination data; run Shared clash detection; create, assign, "
        "update, verify, and close coordination Issues; publish approved IFCs and "
        "archive superseded revisions after required gates pass.",
        "Do not directly edit discipline IFCs; replace a checker or discipline lead; "
        "approve ordinary or major changes; bypass review or approval gates.",
    ),
    ProjectRole.PM_CTL: _policy(
        ProjectRole.PM_CTL,
        "View relevant Shared discipline, Shared federated, and Published IFCs; query "
        "element, quantity, task, cost, and schedule links; create Issues; assess and "
        "update cost or schedule impacts.",
        "Do not access WIP; upload, edit, review, or approve IFCs; edit geometry or "
        "technical properties; approve changes; publish IFCs; download complete "
        "Published files without separate authorization.",
    ),
    ProjectRole.PM_MGR: _policy(
        ProjectRole.PM_MGR,
        "View Shared discipline, Shared federated, and Published IFCs; query project "
        "information; create, assign, update, and close management Issues; review "
        "technical, cost, and schedule impacts; approve ordinary design changes.",
        "Do not directly edit discipline IFCs; perform discipline technical review or "
        "Shared approval; replace the client for major changes or formal acceptance; publish or archive.",
    ),
    ProjectRole.ARC_MOD: _modeler_policy(ProjectRole.ARC_MOD, "ARC", "STR or MEP"),
    ProjectRole.ARC_CHK: _checker_policy(ProjectRole.ARC_CHK, "ARC"),
    ProjectRole.ARC_LEAD: _lead_policy(ProjectRole.ARC_LEAD, "ARC"),
    ProjectRole.STR_MOD: _modeler_policy(ProjectRole.STR_MOD, "STR", "ARC or MEP"),
    ProjectRole.STR_CHK: _checker_policy(ProjectRole.STR_CHK, "STR"),
    ProjectRole.STR_LEAD: _lead_policy(ProjectRole.STR_LEAD, "STR"),
    ProjectRole.MEP_MOD: _modeler_policy(ProjectRole.MEP_MOD, "MEP", "ARC or STR"),
    ProjectRole.MEP_CHK: _checker_policy(ProjectRole.MEP_CHK, "MEP"),
    ProjectRole.MEP_LEAD: _lead_policy(ProjectRole.MEP_LEAD, "MEP"),
}


ROLE_PROFILES = {
    ProjectRole.CL_REP: ProjectRoleProfile(
        ProjectRole.CL_REP,
        Identity.CLIENT,
        "Client Representative",
        "View project information and raise requirements, issues, or change requests.",
        ROLE_PROMPT_POLICIES[ProjectRole.CL_REP],
    ),
    ProjectRole.CL_APP: ProjectRoleProfile(
        ProjectRole.CL_APP,
        Identity.CLIENT,
        "Client Approver",
        "Approve major changes and accept or reject formal project deliverables.",
        ROLE_PROMPT_POLICIES[ProjectRole.CL_APP],
    ),
    ProjectRole.PM_BIM: ProjectRoleProfile(
        ProjectRole.PM_BIM,
        Identity.PROJECT_MANAGER,
        "BIM/CDE Coordinator",
        "Coordinate federated models, clashes, tasks, CDE checks, versions, and publishing.",
        ROLE_PROMPT_POLICIES[ProjectRole.PM_BIM],
    ),
    ProjectRole.PM_CTL: ProjectRoleProfile(
        ProjectRole.PM_CTL,
        Identity.PROJECT_MANAGER,
        "Project Controls Engineer",
        "Manage cost and schedule information and assess change impacts.",
        ROLE_PROMPT_POLICIES[ProjectRole.PM_CTL],
    ),
    ProjectRole.PM_MGR: ProjectRoleProfile(
        ProjectRole.PM_MGR,
        Identity.PROJECT_MANAGER,
        "Project Manager",
        "Resolve cross-discipline matters, approve ordinary changes, and authorize delivery.",
        ROLE_PROMPT_POLICIES[ProjectRole.PM_MGR],
    ),
    ProjectRole.ARC_MOD: ProjectRoleProfile(
        ProjectRole.ARC_MOD,
        Identity.ARC,
        "ARC Modeler",
        "Create and modify ARC components in WIP and submit them for review.",
        ROLE_PROMPT_POLICIES[ProjectRole.ARC_MOD],
    ),
    ProjectRole.ARC_CHK: ProjectRoleProfile(
        ProjectRole.ARC_CHK,
        Identity.ARC,
        "ARC Checker",
        "Review ARC models and return nonconforming work for revision.",
        ROLE_PROMPT_POLICIES[ProjectRole.ARC_CHK],
    ),
    ProjectRole.ARC_LEAD: ProjectRoleProfile(
        ProjectRole.ARC_LEAD,
        Identity.ARC,
        "ARC Lead",
        "Approve ARC information for sharing and participate in coordination.",
        ROLE_PROMPT_POLICIES[ProjectRole.ARC_LEAD],
    ),
    ProjectRole.STR_MOD: ProjectRoleProfile(
        ProjectRole.STR_MOD,
        Identity.STR,
        "STR Modeler",
        "Create and modify STR components in WIP and submit them for review.",
        ROLE_PROMPT_POLICIES[ProjectRole.STR_MOD],
    ),
    ProjectRole.STR_CHK: ProjectRoleProfile(
        ProjectRole.STR_CHK,
        Identity.STR,
        "STR Checker",
        "Review STR models and return nonconforming work for revision.",
        ROLE_PROMPT_POLICIES[ProjectRole.STR_CHK],
    ),
    ProjectRole.STR_LEAD: ProjectRoleProfile(
        ProjectRole.STR_LEAD,
        Identity.STR,
        "STR Lead",
        "Approve STR information for sharing and participate in coordination.",
        ROLE_PROMPT_POLICIES[ProjectRole.STR_LEAD],
    ),
    ProjectRole.MEP_MOD: ProjectRoleProfile(
        ProjectRole.MEP_MOD,
        Identity.MEP,
        "MEP Modeler",
        "Create and modify MEP components in WIP and submit them for review.",
        ROLE_PROMPT_POLICIES[ProjectRole.MEP_MOD],
    ),
    ProjectRole.MEP_CHK: ProjectRoleProfile(
        ProjectRole.MEP_CHK,
        Identity.MEP,
        "MEP Checker",
        "Review MEP models and return nonconforming work for revision.",
        ROLE_PROMPT_POLICIES[ProjectRole.MEP_CHK],
    ),
    ProjectRole.MEP_LEAD: ProjectRoleProfile(
        ProjectRole.MEP_LEAD,
        Identity.MEP,
        "MEP Lead",
        "Approve MEP information for sharing and participate in coordination.",
        ROLE_PROMPT_POLICIES[ProjectRole.MEP_LEAD],
    ),
}


ROLES_BY_IDENTITY = {
    identity: tuple(
        role for role, profile in ROLE_PROFILES.items() if profile.identity is identity
    )
    for identity in Identity
}

DEFAULT_ROLE_BY_IDENTITY = {
    Identity.CLIENT: ProjectRole.CL_REP,
    Identity.PROJECT_MANAGER: ProjectRole.PM_MGR,
    Identity.ARC: ProjectRole.ARC_MOD,
    Identity.STR: ProjectRole.STR_MOD,
    Identity.MEP: ProjectRole.MEP_MOD,
}

DISCIPLINE_LEADS = frozenset(
    {ProjectRole.ARC_LEAD, ProjectRole.STR_LEAD, ProjectRole.MEP_LEAD}
)

SCHEDULE_VISIBLE_ROLES = frozenset(
    {
        ProjectRole.CL_REP,
        ProjectRole.CL_APP,
        ProjectRole.PM_BIM,
        ProjectRole.PM_CTL,
        ProjectRole.PM_MGR,
        ProjectRole.ARC_LEAD,
        ProjectRole.STR_LEAD,
        ProjectRole.MEP_LEAD,
    }
)


def can_view_schedule(role: ProjectRole) -> bool:
    return role in SCHEDULE_VISIBLE_ROLES


def visible_context_roles(viewer_role: ProjectRole) -> tuple[ProjectRole, ...]:
    """Return role memories visible to a user at the application boundary."""
    if viewer_role in DISCIPLINE_LEADS:
        return ROLES_BY_IDENTITY[ROLE_PROFILES[viewer_role].identity]
    return (viewer_role,)


def can_view_role_context(
    viewer_role: ProjectRole,
    target_role: ProjectRole,
) -> bool:
    return target_role in visible_context_roles(viewer_role)


def role_conversation_key(role: ProjectRole) -> str:
    """Keep each detailed role isolated while preserving legacy main histories."""
    identity = ROLE_PROFILES[role].identity
    if DEFAULT_ROLE_BY_IDENTITY[identity] is role:
        return "main"
    return f"role:{role.value}"


def expected_access(
    identity: Identity,
    file_name: str,
    operation: str = "read_ifc",
) -> bool:
    """Return the low-level IFC boundary for an executing Agent identity."""
    if file_name not in PROFILES[identity].expected_files:
        return False
    if operation == "edit_ifc" and identity in {
        Identity.CLIENT,
        Identity.PROJECT_MANAGER,
    }:
        return False
    return True

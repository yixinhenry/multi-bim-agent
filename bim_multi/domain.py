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


ROLE_PROFILES = {
    ProjectRole.CL_REP: ProjectRoleProfile(
        ProjectRole.CL_REP,
        Identity.CLIENT,
        "Client Representative",
        "View project information and raise requirements, issues, or change requests.",
        "You may request authorized model, cost, and schedule information and create "
        "issues or change requests. Do not request direct model edits or approvals.",
    ),
    ProjectRole.CL_APP: ProjectRoleProfile(
        ProjectRole.CL_APP,
        Identity.CLIENT,
        "Client Approver",
        "Approve major changes and accept or reject formal project deliverables.",
        "Focus on major-change approval and formal deliverable acceptance. Do not "
        "perform technical review or request direct model edits.",
    ),
    ProjectRole.PM_BIM: ProjectRoleProfile(
        ProjectRole.PM_BIM,
        Identity.PROJECT_MANAGER,
        "BIM/CDE Coordinator",
        "Coordinate federated models, clashes, tasks, CDE checks, versions, and publishing.",
        "You may coordinate disciplines, run federated clash detection, assign issues, "
        "check CDE compliance, and manage publishing or archiving. Do not directly edit "
        "discipline models or approve discipline technical content.",
    ),
    ProjectRole.PM_CTL: ProjectRoleProfile(
        ProjectRole.PM_CTL,
        Identity.PROJECT_MANAGER,
        "Project Controls Engineer",
        "Manage cost and schedule information and assess change impacts.",
        "Limit work to cost, schedule, progress, and change-impact analysis. Do not "
        "directly edit discipline models or approve design proposals.",
    ),
    ProjectRole.PM_MGR: ProjectRoleProfile(
        ProjectRole.PM_MGR,
        Identity.PROJECT_MANAGER,
        "Project Manager",
        "Resolve cross-discipline matters, approve ordinary changes, and authorize delivery.",
        "You may coordinate cross-discipline decisions, approve ordinary design changes, "
        "and authorize formal delivery. Do not directly edit or technically review "
        "discipline models.",
    ),
    ProjectRole.ARC_MOD: ProjectRoleProfile(
        ProjectRole.ARC_MOD,
        Identity.ARC,
        "ARC Modeler",
        "Create and modify ARC components in WIP and submit them for review.",
        "Limit model changes to ARC.ifc in WIP and submit completed work for review. "
        "Do not review or approve your own changes.",
    ),
    ProjectRole.ARC_CHK: ProjectRoleProfile(
        ProjectRole.ARC_CHK,
        Identity.ARC,
        "ARC Checker",
        "Review ARC models and return nonconforming work for revision.",
        "Perform technical review of ARC work and return issues for revision. Do not "
        "edit the model or approve information for sharing.",
    ),
    ProjectRole.ARC_LEAD: ProjectRoleProfile(
        ProjectRole.ARC_LEAD,
        Identity.ARC,
        "ARC Lead",
        "Approve ARC information for sharing and participate in coordination.",
        "Approve reviewed ARC information for sharing and perform cross-discipline "
        "coordination. Do not directly edit the model.",
    ),
    ProjectRole.STR_MOD: ProjectRoleProfile(
        ProjectRole.STR_MOD,
        Identity.STR,
        "STR Modeler",
        "Create and modify STR components in WIP and submit them for review.",
        "Limit model changes to STR.ifc in WIP and submit completed work for review. "
        "Do not review or approve your own changes.",
    ),
    ProjectRole.STR_CHK: ProjectRoleProfile(
        ProjectRole.STR_CHK,
        Identity.STR,
        "STR Checker",
        "Review STR models and return nonconforming work for revision.",
        "Perform technical review of STR work and return issues for revision. Do not "
        "edit the model or approve information for sharing.",
    ),
    ProjectRole.STR_LEAD: ProjectRoleProfile(
        ProjectRole.STR_LEAD,
        Identity.STR,
        "STR Lead",
        "Approve STR information for sharing and participate in coordination.",
        "Approve reviewed STR information for sharing and perform cross-discipline "
        "coordination. Do not directly edit the model.",
    ),
    ProjectRole.MEP_MOD: ProjectRoleProfile(
        ProjectRole.MEP_MOD,
        Identity.MEP,
        "MEP Modeler",
        "Create and modify MEP components in WIP and submit them for review.",
        "Limit model changes to MEP.ifc in WIP and submit completed work for review. "
        "Do not review or approve your own changes.",
    ),
    ProjectRole.MEP_CHK: ProjectRoleProfile(
        ProjectRole.MEP_CHK,
        Identity.MEP,
        "MEP Checker",
        "Review MEP models and return nonconforming work for revision.",
        "Perform technical review of MEP work and return issues for revision. Do not "
        "edit the model or approve information for sharing.",
    ),
    ProjectRole.MEP_LEAD: ProjectRoleProfile(
        ProjectRole.MEP_LEAD,
        Identity.MEP,
        "MEP Lead",
        "Approve MEP information for sharing and participate in coordination.",
        "Approve reviewed MEP information for sharing and perform cross-discipline "
        "coordination. Do not directly edit the model.",
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

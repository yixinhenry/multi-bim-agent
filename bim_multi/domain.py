from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Identity(StrEnum):
    CLIENT = "CLIENT"
    PROJECT_MANAGER = "PROJECT_MANAGER"
    ARC = "ARC"
    STR = "STR"
    MEP = "MEP"


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


def expected_access(
    identity: Identity,
    file_name: str,
    operation: str = "read_ifc",
) -> bool:
    """Return prompt-declared access, not an enforcement decision."""
    if file_name not in PROFILES[identity].expected_files:
        return False
    if operation == "edit_ifc" and identity in {
        Identity.CLIENT,
        Identity.PROJECT_MANAGER,
    }:
        return False
    return True

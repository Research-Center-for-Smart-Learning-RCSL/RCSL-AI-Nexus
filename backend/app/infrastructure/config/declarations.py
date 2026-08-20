"""Composition of flat setting declaration groups."""

from .core import CoreSettings
from .identity_security import IdentitySecuritySettings
from .knowledge import KnowledgeSettings
from .operations import OperationsSettings
from .runtime import RuntimeSettings
from .secrets import SecretsSettings


class SettingDeclarations(
    CoreSettings,
    RuntimeSettings,
    IdentitySecuritySettings,
    KnowledgeSettings,
    OperationsSettings,
    SecretsSettings,
):
    pass

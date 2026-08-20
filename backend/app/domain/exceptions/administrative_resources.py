"""Administrative Resources domain errors."""

from __future__ import annotations

from .base import DomainError, StateConflictError


class PromptTemplateStateConflictError(StateConflictError):
    code = "prompt_template_state_conflict"
    public_message = "That change to the template is not allowed."


class RoutingPolicyStateConflictError(StateConflictError):
    code = "routing_policy_state_conflict"
    public_message = "That routing policy cannot be saved as written."


class NodeStateConflictError(StateConflictError):
    code = "node_state_conflict"
    public_message = "The node is not in a state that allows this operation."


class TenantStateConflictError(StateConflictError):
    code = "tenant_state_conflict"
    public_message = "That change to the tenant is not allowed."


class UserStateConflictError(StateConflictError):
    code = "user_state_conflict"
    public_message = "That change to the account is not allowed."


class NodeNotFoundError(DomainError):
    code = "node_not_found"
    public_message = "The requested node does not exist."


class InvalidNodeAddressError(DomainError):
    code = "invalid_node_address"
    public_message = "Node address must be inside the tailnet range."


class PromptTemplateNotFoundError(DomainError):
    code = "prompt_template_not_found"
    public_message = "That prompt template does not exist."

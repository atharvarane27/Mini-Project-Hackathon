"""P13 rule validation endpoint returning tokens, typed AST, or diagnostics."""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping
from uuid import uuid4

from fastapi import APIRouter, Header, status
from fastapi.responses import JSONResponse

from app.engines.rules.ast_nodes import ast_to_dict
from app.engines.rules.lexer import LexerError, tokenize
from app.engines.rules.parser import ParserError, parse_tokens
from app.engines.rules.service import (
    RuleActor,
    RuleAuthorizationError,
    RuleIdempotencyConflict,
    RuleNotFoundError,
    RuleService,
    RuleStateError,
)
from app.engines.rules.tokens import Token
from app.engines.rules.types import DEFAULT_FIELD_TYPES, RuleValueType
from app.schemas.rules import RuleCreateRequest, RuleValidationRequest


def _request_id(value: str | None) -> str:
    return value.strip() if value and value.strip() else str(uuid4())


def _token_literal(token: Token) -> int | bool | str | None:
    if isinstance(token.literal, Decimal):
        return str(token.literal)
    return token.literal


def _token_dict(token: Token) -> dict[str, object]:
    return {
        "kind": token.kind.value,
        "lexeme": token.lexeme,
        "literal": _token_literal(token),
        "start_offset": token.start_offset,
        "end_offset": token.end_offset,
        "line": token.line,
        "column": token.column,
    }


def _diagnostic_response(
    error: LexerError | ParserError,
    phase: str,
    request_id: str,
) -> JSONResponse:
    diagnostic = error.diagnostic
    details = {**diagnostic.as_dict(), "phase": phase}
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": diagnostic.code.value,
                "message": diagnostic.message,
                "details": details,
            },
            "request_id": request_id,
        },
    )


def _error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message, "details": {}},
            "request_id": request_id,
        },
    )


def _actor(actor_id: str | None, roles_header: str | None) -> RuleActor | None:
    if actor_id is None or not actor_id.strip():
        return None
    roles = frozenset(
        role.strip() for role in (roles_header or "").split(",") if role.strip()
    )
    return RuleActor(actor_id.strip(), roles)


def create_rules_router(
    field_types: Mapping[str, RuleValueType] | None = None,
    service: RuleService | None = None,
) -> APIRouter:
    registry = dict(DEFAULT_FIELD_TYPES if field_types is None else field_types)
    router = APIRouter()

    @router.post("/rules/validate", response_model=None)
    def validate_rule(
        request: RuleValidationRequest,
        request_id_header: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object] | JSONResponse:
        request_id = _request_id(request_id_header)
        try:
            tokens = tokenize(request.expression)
        except LexerError as error:
            return _diagnostic_response(error, "LEXER", request_id)
        try:
            ast = parse_tokens(tokens, registry)
        except ParserError as error:
            return _diagnostic_response(error, "PARSER", request_id)

        return {
            "data": {
                "valid": True,
                "tokens": [_token_dict(token) for token in tokens],
                "ast": ast_to_dict(ast),
                "result_type": ast.value_type.value,
            },
            "meta": {"field_registry_size": len(registry)},
            "request_id": request_id,
        }

    if service is not None:

        @router.post("/rules", status_code=status.HTTP_201_CREATED, response_model=None)
        def create_rule(
            request: RuleCreateRequest,
            request_id_header: str | None = Header(default=None, alias="X-Request-ID"),
            actor_id: str | None = Header(default=None, alias="X-Actor-ID"),
            roles_header: str | None = Header(default=None, alias="X-Roles"),
            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ) -> dict[str, object] | JSONResponse:
            request_id = _request_id(request_id_header)
            actor = _actor(actor_id, roles_header)
            if actor is None:
                return _error_response(401, "UNAUTHENTICATED", "actor is required", request_id)
            try:
                rule = service.create_draft(
                    request.name,
                    request.expression,
                    actor,
                    idempotency_key,
                )
            except RuleAuthorizationError as error:
                return _error_response(403, "FORBIDDEN", str(error), request_id)
            except LexerError as error:
                return _diagnostic_response(error, "LEXER", request_id)
            except ParserError as error:
                return _diagnostic_response(error, "PARSER", request_id)
            except RuleIdempotencyConflict as error:
                return _error_response(409, "IDEMPOTENCY_CONFLICT", str(error), request_id)
            except ValueError as error:
                return _error_response(422, "INVALID_RULE", str(error), request_id)
            return {"data": rule.as_dict(), "meta": {}, "request_id": request_id}

        @router.post("/rules/{rule_id}/activate", response_model=None)
        def activate_rule(
            rule_id: str,
            request_id_header: str | None = Header(default=None, alias="X-Request-ID"),
            actor_id: str | None = Header(default=None, alias="X-Actor-ID"),
            roles_header: str | None = Header(default=None, alias="X-Roles"),
        ) -> dict[str, object] | JSONResponse:
            request_id = _request_id(request_id_header)
            actor = _actor(actor_id, roles_header)
            if actor is None:
                return _error_response(401, "UNAUTHENTICATED", "actor is required", request_id)
            try:
                rule = service.activate(rule_id, actor)
            except RuleAuthorizationError as error:
                return _error_response(403, "FORBIDDEN", str(error), request_id)
            except RuleNotFoundError as error:
                return _error_response(404, "RULE_NOT_FOUND", str(error), request_id)
            except RuleStateError as error:
                return _error_response(409, "INVALID_RULE_STATE", str(error), request_id)
            except LexerError as error:
                return _diagnostic_response(error, "LEXER", request_id)
            except ParserError as error:
                return _diagnostic_response(error, "PARSER", request_id)
            return {"data": rule.as_dict(), "meta": {}, "request_id": request_id}

    return router


router = create_rules_router()

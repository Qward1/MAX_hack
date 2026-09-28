"""Caller-owned transactions. Lock order: house (shared), chat, request.

The MAX platform proves chat administration; AccessPolicy independently proves
authority over the current management. A correlation token proves neither.
"""

import hashlib
import re
import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.bot.chat_provider import ChatInfo, MaxChatProvider, MaxProviderError
from domsignal.contracts.chat_connections import ConnectionCreate, ConnectionView
from domsignal.core.chat_connections import (
    TERMINAL,
    ConnectionStatus,
    binding_transition,
    connection_transition,
)
from domsignal.db.models.chat_connections import ChatBinding, ConnectionRequest, MAXChat
from domsignal.db.repositories.access import AccessRepository
from domsignal.db.repositories.chat_connections import ChatRepository
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.services.chat_quota import (
    QUOTA_EXCEEDED,
    activation_slot_error,
    company_of_management,
    quota_state,
)
from domsignal.services.context import OperationContext, ScopeState, ScopeValue
from domsignal.services.errors import ResourceNotFound, ServiceError
from domsignal.services.membership import MembershipService


class ChatConnectionError(ServiceError):
    def __init__(self, code: str, *, status: int = 409, detail: str | None = None) -> None:
        super().__init__(detail or "Chat connection could not be completed")
        self.code = code
        self.status = status
        self.retryable = status == 503


def typed_connect_token(text: str | None) -> str | None:
    """Команда `/start connect_…`, набранная в личке вручную, → токен подключения.

    Равнозначна ссылке запуска бота с тем же токеном (A-07). Формат токена
    проверяет `claim`: неполный токен получает ответ «код не подошёл».
    """
    match = re.fullmatch(r"/start(?:@[A-Za-z0-9_]{1,100})?\s+(connect_\S*)", (text or "").strip())
    return match[1] if match else None


class ChatConnectionService:
    def __init__(
        self,
        provider: MaxChatProvider,
        *,
        ttl_seconds: int = 900,
        required_permissions: frozenset[str] = frozenset({"read_all_messages"}),
    ) -> None:
        self.provider = provider
        self.ttl_seconds = ttl_seconds
        self.required_permissions = required_permissions
        self.memberships = MembershipService()

    @staticmethod
    def token_digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def transition(request: ConnectionRequest, target: str) -> None:
        request.status = connection_transition(request.status, target)
        now = datetime.now(UTC)
        if target == "completed":
            request.completed_at = now
        elif target == "cancelled":
            request.cancelled_at = now
        elif target == "rejected":
            request.rejected_at = now

    def expire(self, request: ConnectionRequest) -> bool:
        if request.status not in TERMINAL and request.expires_at <= datetime.now(UTC):
            self.transition(request, "expired")
        return request.status == "expired"

    async def initiate(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        house_id: UUID,
        scope: ConnectionCreate,
    ) -> tuple[ConnectionRequest, str | None]:
        context = await self.memberships.require_house(
            session,
            user_id=actor_id,
            house_id=house_id,
            for_write=True,
        )
        self.memberships.require_permission(context, "chat.connect")
        management_id = cast(UUID, context.management_id.value)
        # Квота (D2): при исчерпанных слотах новый запрос не создаётся —
        # администратор не проходит шаги в MAX впустую. Окончательная проверка
        # под блокировкой строки УК — при активации.
        company_id = await company_of_management(session, management_id)
        if company_id is not None:
            state = await quota_state(session, company_id)
            if state.exhausted:
                raise ChatConnectionError(QUOTA_EXCEEDED, detail=state.exceeded_detail())
        repo = ChatRepository(session)
        await repo.lock(f"initiate:{actor_id}:{management_id}")
        for previous in await repo.open_for_initiator(actor_id, management_id):
            if not self.expire(previous) and (previous.scope_type, previous.scope_value) == (
                scope.scope_type,
                scope.scope_value,
            ):
                return previous, None
        await repo.lock(f"initiate-house:{house_id}")
        if any(
            not self.expire(item)
            and (item.scope_type, item.scope_value) == (scope.scope_type, scope.scope_value)
            for item in await repo.open_for_house(house_id)
        ):
            # U-01: у дома уже идёт подключение — второй запрос не создаётся.
            raise ChatConnectionError(
                "house_connection_in_progress",
                detail="Для этого дома уже идёт подключение чата — продолжите или отмените его",
            )
        token = "connect_" + secrets.token_urlsafe(32)
        request = ConnectionRequest(
            management_id=management_id,
            house_id=house_id,
            initiated_by_user_id=actor_id,
            token_hash=self.token_digest(token),
            expires_at=datetime.now(UTC) + timedelta(seconds=self.ttl_seconds),
            scope_type=scope.scope_type,
            scope_value=scope.scope_value,
        )
        await repo.add(request)
        return request, token

    async def reissue(
        self, session: AsyncSession, *, request_id: UUID, actor_id: UUID
    ) -> tuple[ConnectionRequest, str]:
        """Новый код для незавершённого запроса: в базе хранится только хэш кода.

        U-01: после перезагрузки страницы код не показать — его можно выдать
        заново, пока бот его не получил (`created`). Прежний код перестаёт
        действовать; срок запроса продлевается.
        """
        request = await self.locked_request(session, request_id)
        await self.require_authority(session, request, actor_id)
        if self.expire(request) or request.status != "created":
            raise ChatConnectionError("connection_code_used")
        token = "connect_" + secrets.token_urlsafe(32)
        request.token_hash = self.token_digest(token)
        request.expires_at = datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)
        return request, token

    async def claim(
        self,
        session: AsyncSession,
        *,
        token: str,
        connector: str,
        occurred_at: datetime,
    ) -> ConnectionRequest | None:
        if not re.fullmatch(r"connect_[A-Za-z0-9_-]{43}", token):
            return None
        repo = ChatRepository(session)
        await repo.lock(f"connector:{connector}")
        request = await repo.by_token(self.token_digest(token))
        if request is None:
            return None
        request = await repo.request(request.id, lock=True)
        assert request is not None
        if self.expire(request) or request.status in TERMINAL:
            return request
        if request.connector_max_user_id is not None:
            # Same actor replay is harmless; another actor cannot steal the request.
            return request
        open_requests = await repo.open_for_connector(connector)
        if any(not self.expire(item) for item in open_requests):
            request.last_error_code = "connector_connection_in_progress"
            return request
        if occurred_at < request.created_at:
            return request
        request.connector_max_user_id = connector
        request.claimed_at = occurred_at
        request.last_error_code = None
        self.transition(request, "connector_claimed")
        return request

    async def bot_added(
        self,
        session: AsyncSession,
        *,
        chat_id: str,
        actor: str,
        occurred_at: datetime,
        is_channel: bool,
    ) -> ConnectionRequest | None:
        repo = ChatRepository(session)
        await repo.lock(f"chat:{chat_id}")
        chat = await repo.chat(chat_id)
        if chat is None:
            chat = MAXChat(
                max_chat_id=chat_id,
                type="channel" if is_channel else "chat",
                is_channel=is_channel,
                last_seen_at=occurred_at,
            )
            await repo.add(chat)
        if chat.lifecycle_at is not None and occurred_at <= chat.lifecycle_at:
            return None
        chat.lifecycle_at = occurred_at
        chat.last_seen_at = max(chat.last_seen_at, occurred_at)
        chat.bot_present = True
        requests = [
            item
            for item in await repo.open_for_connector(actor)
            if not self.expire(item)
            and item.claimed_at is not None
            and item.claimed_at <= occurred_at
            and item.status == "connector_claimed"
        ]
        if len(requests) != 1 or is_channel:
            return None
        request = requests[0]
        request.candidate_max_chat_id = chat_id
        self.transition(request, "chat_detected")
        await ReliabilityRepository(session).add_job(
            kind="max.connection.verify",
            payload={"connection_request_id": str(request.id)},
            priority=40,
        )
        return request

    async def _check_max(self, chat_id: str, connector: str | None = None) -> ChatInfo:
        info = await self.provider.get_chat_info(chat_id)
        if info.chat_id != chat_id or info.type != "chat":
            raise MaxProviderError("chat_type_unsupported")
        if not info.bot_present:
            raise MaxProviderError("bot_permission_missing")
        bot = await self.provider.get_bot_membership(chat_id)
        if (
            not bot.is_bot
            or not bot.is_admin
            or not self.required_permissions.issubset(bot.permissions)
        ):
            raise MaxProviderError("bot_permission_missing")
        if connector is not None:
            admins = await self.provider.get_chat_admins(chat_id)
            if not any(
                member.user_id == connector
                and not member.is_bot
                and (member.is_admin or member.is_owner)
                for member in admins
            ):
                raise MaxProviderError("connector_not_chat_admin")
        return info

    async def locked_request(
        self,
        session: AsyncSession,
        request_id: UUID,
    ) -> ConnectionRequest:
        repo = ChatRepository(session)
        routing = await repo.request(request_id)
        if routing is None:
            raise ResourceNotFound("Resource was not found")
        candidate = routing.candidate_max_chat_id
        await AccessRepository(session).lock_house(routing.house_id)
        if candidate is not None:
            await repo.lock(f"chat:{candidate}")
        result = await repo.request(request_id, lock=True)
        assert result is not None
        if result.candidate_max_chat_id != candidate:
            # Detection raced the routing read. Retry without reversing chat/request locks.
            raise ChatConnectionError("connection_changed_retry")
        return result

    async def require_authority(
        self,
        session: AsyncSession,
        request: ConnectionRequest,
        actor_id: UUID,
    ) -> OperationContext:
        context = await self.memberships.require_house(
            session,
            user_id=actor_id,
            house_id=request.house_id,
            for_write=True,
        )
        if context.management_id.value != request.management_id:
            raise ResourceNotFound("Resource was not found")
        self.memberships.require_permission(context, "chat.connect")
        return context

    async def verify(
        self,
        session: AsyncSession,
        request_id: UUID,
    ) -> ConnectionRequest:
        request = await self.locked_request(session, request_id)
        if self.expire(request) or request.status in TERMINAL:
            return request
        if request.status not in {"chat_detected", "max_verified", "awaiting_approval"}:
            raise ChatConnectionError("connection_not_detected")
        repo = ChatRepository(session)
        error = await repo.management_state(request.management_id, datetime.now(UTC))
        if error:
            request.last_error_code = error
            return request
        assert request.candidate_max_chat_id and request.connector_max_user_id
        try:
            info = await self._check_max(
                request.candidate_max_chat_id,
                request.connector_max_user_id,
            )
        except MaxProviderError as exc:
            request.verified_at = None
            request.last_error_code = exc.code
            return request
        # A late/stale verification must not outlive the request's TTL.
        if self.expire(request):
            return request
        chat = await repo.chat(info.chat_id)
        assert chat is not None
        if not chat.bot_present:
            request.last_error_code = "bot_removed"
            return request
        chat.title, chat.owner_max_user_id = info.title, info.owner_id
        chat.type, chat.is_channel = info.type, False
        chat.last_seen_at = datetime.now(UTC)
        request.verified_at = datetime.now(UTC)
        request.last_error_code = None
        if request.status == "chat_detected":
            self.transition(request, "max_verified")
        # Case A is resolved by the same identity + existing policy, without grants.
        connector = await AccessRepository(session).user_by_max_id(request.connector_max_user_id)
        can_confirm = False
        if connector:
            try:
                await self.require_authority(session, request, connector.id)
                can_confirm = True
            except ServiceError:
                pass
        if not can_confirm and request.status == "max_verified":
            self.transition(request, "awaiting_approval")
        return request

    async def approve(
        self,
        session: AsyncSession,
        *,
        request_id: UUID,
        actor_id: UUID,
    ) -> ChatBinding:
        request = await self.locked_request(session, request_id)
        await self.require_authority(session, request, actor_id)
        repo = ChatRepository(session)
        if request.status == "completed":
            binding = await repo.completed_binding(request.id)
            assert binding is not None
            if binding.status != "active":
                raise ChatConnectionError("binding_not_active")
            return binding
        if self.expire(request):
            raise ChatConnectionError("connection_expired")
        request = await self.verify(session, request.id)
        if request.status == "expired":
            raise ChatConnectionError("connection_expired")
        if request.last_error_code:
            raise ChatConnectionError(
                request.last_error_code,
                status=(503 if request.last_error_code.startswith("max_") else 409),
            )
        if request.status not in {"max_verified", "awaiting_approval"}:
            raise ChatConnectionError("connection_not_verified")
        assert request.candidate_max_chat_id
        # Recheck management/actor after network calls and before any effect.
        await self.require_authority(session, request, actor_id)
        if await repo.active_binding(request.candidate_max_chat_id):
            raise ChatConnectionError("chat_already_bound")
        # Квота УК (CHAT-QUOTA-2026-09-26): последняя проверка в транзакции
        # активации под блокировкой строки УК. Отказ сохраняется в запросе
        # (маршрут фиксирует транзакцию и при ошибке) — после расширения квоты
        # то же подключение подтверждается повторно.
        slot_error = await activation_slot_error(session, request.management_id)
        if slot_error is not None:
            code, detail = slot_error
            request.last_error_code = code
            raise ChatConnectionError(code, detail=detail)
        chat = await repo.chat(request.candidate_max_chat_id)
        assert chat is not None
        chat.binding_version += 1
        binding = ChatBinding(
            max_chat_id=chat.max_chat_id,
            connection_request_id=request.id,
            house_id=request.house_id,
            management_id=request.management_id,
            scope_type=request.scope_type,
            scope_value=request.scope_value,
            status=binding_transition("pending", "active"),
            verified_at=request.verified_at,
            verified_by_user_id=actor_id,
            binding_version=chat.binding_version,
            activated_at=datetime.now(UTC),
        )
        await repo.add(binding)
        self.transition(request, "completed")
        self.audit(session, binding, "activated")
        return binding

    async def finish(
        self,
        session: AsyncSession,
        *,
        request_id: UUID,
        actor_id: UUID,
        target: str,
    ) -> ConnectionRequest:
        request = await self.locked_request(session, request_id)
        await self.require_authority(session, request, actor_id)
        if self.expire(request):
            return request
        try:
            self.transition(request, target)
        except ValueError:
            raise ChatConnectionError("connection_invalid_transition") from None
        return request

    @staticmethod
    def audit(session: AsyncSession, binding: ChatBinding, action: str) -> None:
        ReliabilityRepository(session).add_outbox(
            kind=f"chat_binding.{action}",
            aggregate_id=binding.id,
            payload={
                "chat_binding_id": str(binding.id),
                "binding_version": binding.binding_version,
            },
        )

    async def revoke(
        self,
        session: AsyncSession,
        *,
        binding_id: UUID,
        actor_id: UUID,
    ) -> ChatBinding:
        repo = ChatRepository(session)
        binding = await repo.binding(binding_id)
        if binding is None:
            raise ResourceNotFound("Resource was not found")
        request = await self.locked_request(session, binding.connection_request_id)
        await self.require_authority(session, request, actor_id)
        binding = await repo.binding(binding_id)
        assert binding is not None
        if binding.status != "revoked":
            binding.status = binding_transition(binding.status, "revoked")
            binding.revoked_at = datetime.now(UTC)
            self.audit(session, binding, "revoked")
        return binding

    def suspend(self, session: AsyncSession, binding: ChatBinding, reason: str) -> None:
        if binding.status != "active":
            return
        binding.status = binding_transition(binding.status, "suspended")
        binding.suspended_at = datetime.now(UTC)
        binding.suspension_reason = reason
        self.audit(session, binding, "suspended")

    async def bot_removed(
        self,
        session: AsyncSession,
        *,
        chat_id: str,
        occurred_at: datetime,
    ) -> None:
        repo = ChatRepository(session)
        await repo.lock(f"chat:{chat_id}")
        chat = await repo.chat(chat_id)
        if chat is None:
            chat = MAXChat(max_chat_id=chat_id, type="unknown", last_seen_at=occurred_at)
            await repo.add(chat)
        if chat.lifecycle_at is not None and occurred_at < chat.lifecycle_at:
            return
        chat.lifecycle_at = occurred_at
        chat.last_seen_at = max(chat.last_seen_at, occurred_at)
        chat.bot_present = False
        binding = await repo.active_binding(chat_id)
        if binding:
            self.suspend(session, binding, "BOT_REMOVED")

    async def verify_binding_health(self, session: AsyncSession, binding_id: UUID) -> None:
        repo = ChatRepository(session)
        binding = await repo.binding(binding_id)
        if binding is None:
            return
        await AccessRepository(session).lock_house(binding.house_id)
        await repo.lock(f"chat:{binding.max_chat_id}")
        binding = await repo.binding(binding_id)
        assert binding is not None
        if binding.status != "active":
            return
        reason = await repo.management_state(binding.management_id, datetime.now(UTC))
        if reason:
            self.suspend(
                session,
                binding,
                "MANAGEMENT_ENDED" if reason == "management_not_active" else "TENANT_SUSPENDED",
            )
            return
        try:
            info = await self._check_max(binding.max_chat_id)
        except MaxProviderError as exc:
            # Unknown permission state also fails closed; recovery needs a new flow.
            self.suspend(session, binding, exc.code.upper())
            return
        chat = await repo.chat(binding.max_chat_id)
        assert chat is not None
        chat.title, chat.owner_max_user_id = info.title, info.owner_id
        chat.last_seen_at = datetime.now(UTC)

    async def resolve_context(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        chat_id: str,
        binding_id: UUID,
        version: int,
        occurred_at: datetime,
    ) -> OperationContext:
        repo = ChatRepository(session)
        binding = await repo.binding(binding_id)
        if binding is None or binding.max_chat_id != chat_id:
            raise ChatConnectionError("binding_not_active")
        await AccessRepository(session).lock_house(binding.house_id)
        await repo.lock(f"chat:{chat_id}")
        binding = await repo.binding(binding_id)
        assert binding is not None
        if binding.binding_version != version:
            raise ChatConnectionError("stale_binding_version")
        if binding.status != "active":
            raise ChatConnectionError("binding_not_active")
        if binding.activated_at is None or occurred_at < binding.activated_at:
            raise ChatConnectionError("stale_binding_version")
        chat = await repo.chat(chat_id)
        if chat is None or not chat.bot_present or chat.binding_version != version:
            raise ChatConnectionError("stale_binding_version")
        context = await self.memberships.require_house(
            session,
            user_id=actor_id,
            house_id=binding.house_id,
            source="max_group",
            for_write=True,
        )
        if context.management_id.value != binding.management_id:
            raise ChatConnectionError("management_not_active")
        return replace(
            context,
            chat_binding_id=ScopeValue(ScopeState.KNOWN, binding.id),
            binding_version=ScopeValue(ScopeState.KNOWN, version),
            source_chat_id=ScopeValue(ScopeState.KNOWN, chat_id),
            entrance=binding.scope_value if binding.scope_type == "entrance" else None,
        )

    async def view(
        self,
        session: AsyncSession,
        request: ConnectionRequest,
        token: str | None = None,
    ) -> ConnectionView:
        binding = await ChatRepository(session).completed_binding(request.id)
        company_id = await company_of_management(session, request.management_id)
        quota = (await quota_state(session, company_id)).view() if company_id else None
        return ConnectionView(
            id=request.id,
            house_id=request.house_id,
            status=ConnectionStatus(request.status),
            expires_at=request.expires_at,
            candidate_max_chat_id=request.candidate_max_chat_id,
            scope_type=request.scope_type,  # validated by model + DB
            scope_value=request.scope_value,
            last_error_code=request.last_error_code,
            binding_id=binding.id if binding else None,
            binding_version=binding.binding_version if binding else None,
            correlation_token=token,
            quota=quota,
        )

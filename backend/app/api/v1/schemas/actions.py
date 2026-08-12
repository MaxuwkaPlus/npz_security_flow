from pydantic import BaseModel, Field

from app.application.actions import ActionReceipt


class SubmitActionRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=36)
    action_type: str = Field(min_length=1, max_length=64)
    target_code: str = Field(min_length=1, max_length=64)
    value: dict[str, float] = Field(default_factory=dict)
    # Клиентское время используется только для аудита рассинхронизации.
    client_sim_time_ms: int | None = Field(default=None, ge=0)


class ActionResponse(BaseModel):
    """Подтверждение приёма. Правильность команды оценивается позже, после окна эффекта."""

    id: str
    request_id: str
    session_id: str
    sequence_no: int
    sim_time_ms: int
    action_type: str
    target_code: str
    value: dict[str, float]
    status: str
    rejection_reason: str | None

    @classmethod
    def from_receipt(cls, receipt: ActionReceipt) -> "ActionResponse":
        return cls(
            id=receipt.id,
            request_id=receipt.request_id,
            session_id=receipt.session_id,
            sequence_no=receipt.sequence_no,
            sim_time_ms=receipt.sim_time_ms,
            action_type=receipt.action_type,
            target_code=receipt.target_code,
            value=receipt.value,
            status=receipt.status.value,
            rejection_reason=receipt.rejection_reason,
        )

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    first_name: Mapped[str]
    middle_name: Mapped[str | None]
    last_name: Mapped[str | None]
    phone_number: Mapped[str]
    date_of_birth: Mapped[date | None]
    gender: Mapped[str | None]
    email: Mapped[str | None]
    address: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    @property
    def full_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.middle_name, self.last_name) if part)


class Test(Base):
    __tablename__ = "tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    aliases: Mapped[list] = mapped_column(JSONB, default=list)
    description: Mapped[str | None]
    category: Mapped[str | None]
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    sample_type: Mapped[str | None]
    home_collection_available: Mapped[bool] = mapped_column(default=True)
    turnaround_time_hours: Mapped[int | None]
    fasting_required: Mapped[bool] = mapped_column(default=False)
    fasting_instructions: Mapped[str | None]
    active: Mapped[bool] = mapped_column(default=True)


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(unique=True)
    name: Mapped[str]
    category: Mapped[str | None]
    description: Mapped[str | None]
    value_proposition: Mapped[str | None]
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    fasting_required: Mapped[bool] = mapped_column(default=False)
    fasting_instructions: Mapped[str | None]
    active: Mapped[bool] = mapped_column(default=True)


class PackageTest(Base):
    __tablename__ = "package_tests"

    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id", ondelete="CASCADE"), primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id", ondelete="CASCADE"), primary_key=True)


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    description: Mapped[str | None]
    discount_type: Mapped[str] = mapped_column(CheckConstraint("discount_type IN ('percent', 'flat', 'other')"))
    discount_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    format_note: Mapped[str | None]
    eligibility_note: Mapped[str | None]
    applies_to_type: Mapped[str] = mapped_column(CheckConstraint("applies_to_type IN ('test', 'package', 'all')"))
    applies_to_id: Mapped[int | None]
    start_date: Mapped[date]
    end_date: Mapped[date]
    active: Mapped[bool] = mapped_column(default=True)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    test_id: Mapped[int | None] = mapped_column(ForeignKey("tests.id"))
    package_id: Mapped[int | None] = mapped_column(ForeignKey("packages.id"))
    status: Mapped[str] = mapped_column(
        CheckConstraint("status IN ('pending', 'processing', 'ready', 'delivered')"), default="pending"
    )
    sample_collected_at: Mapped[datetime | None]
    ready_at: Mapped[datetime | None]
    report_url: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    patient: Mapped["Patient"] = relationship()
    test: Mapped["Test | None"] = relationship()
    package: Mapped["Package | None"] = relationship()


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    reference_code: Mapped[str] = mapped_column(unique=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(CheckConstraint("type IN ('lab_visit', 'home_collection')"))
    status: Mapped[str] = mapped_column(
        CheckConstraint("status IN ('booked', 'rescheduled', 'cancelled', 'completed')"), default="booked"
    )
    scheduled_at: Mapped[datetime]
    address: Mapped[str | None]
    home_collection_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    notes: Mapped[str | None]
    previous_appointment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("appointments.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    patient: Mapped["Patient"] = relationship()
    items: Mapped[list["AppointmentItem"]] = relationship()


class AppointmentItem(Base):
    __tablename__ = "appointment_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"))
    test_id: Mapped[int | None] = mapped_column(ForeignKey("tests.id"))
    package_id: Mapped[int | None] = mapped_column(ForeignKey("packages.id"))

    test: Mapped["Test | None"] = relationship()
    package: Mapped["Package | None"] = relationship()


class LabInfo(Base):
    __tablename__ = "lab_info"
    __table_args__ = (CheckConstraint("id = 1"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    name: Mapped[str]
    address: Mapped[str]
    phone_number: Mapped[str]
    hours: Mapped[dict] = mapped_column(JSONB)
    email: Mapped[str | None]
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    operational_rules: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SymptomRoute(Base):
    __tablename__ = "symptom_routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    condition_keyword: Mapped[str]
    symptoms: Mapped[list] = mapped_column(JSONB, default=list)
    recommended_test_codes: Mapped[list] = mapped_column(JSONB, default=list)
    recommended_package_codes: Mapped[list] = mapped_column(JSONB, default=list)
    voice_script_hint: Mapped[str | None]


class CallEvent(Base):
    __tablename__ = "call_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    call_session_id: Mapped[str]
    event_type: Mapped[str] = mapped_column(
        CheckConstraint("event_type IN ('usage', 'latency', 'error', 'close', 'tool_call')")
    )
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PendingAction(Base):
    __tablename__ = "pending_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    call_session_id: Mapped[str]
    action_type: Mapped[str] = mapped_column(
        CheckConstraint(
            "action_type IN ('register_patient', 'book_appointment', "
            "'reschedule_appointment', 'cancel_appointment')"
        )
    )
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        CheckConstraint("status IN ('proposed', 'confirmed', 'rejected', 'expired')"), default="proposed"
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(server_default=text("now() + interval '10 minutes'"))
    resolved_at: Mapped[datetime | None]

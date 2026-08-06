from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

# Import Activity definitions via string names to preserve workflow determinism
with workflow.unsafe.imports_passed_through():
    from activities.booking_activities import (
        cancel_supplier_reservation_activity,
        create_supplier_reservation_activity,
        persist_booking_record_activity,
        poll_supplier_confirmation_activity,
        revalidate_offer_activity,
    )


@dataclass
class BookingRequest:
    """Input payload for BookingWorkflow."""
    offer_id: str
    supplier_id: str
    property_id: str
    check_in_date: str
    check_out_date: str
    quoted_price: float
    currency: str
    guest_details: Dict[str, Any]
    idempotency_key: str


TERMINAL_STATES = {"CONFIRMED", "FAILED", "CANCELLED", "PRICE_CHANGED", "REQUIRES_MANUAL_REVIEW"}


@workflow.defn
class BookingWorkflow:
    """
    Temporal workflow orchestrating the complete hotel booking lifecycle.
    """

    def __init__(self):
        self._status: str = "PENDING"
        self._current_step: str = "INITIALIZED"
        self._supplier_reservation_id: Optional[str] = None
        self._cancel_requested: bool = False
        self._idempotency_key: str = ""
        self._supplier_id: str = ""

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        """Query current workflow state and reservation details."""
        return {
            "status": self._status,
            "current_step": self._current_step,
            "supplier_reservation_id": self._supplier_reservation_id,
            "idempotency_key": self._idempotency_key,
            "supplier_id": self._supplier_id,
            "cancel_requested": self._cancel_requested,
        }

    @workflow.signal
    def cancel_booking(self) -> None:
        """Signal workflow to initiate cancellation."""
        if self._status in TERMINAL_STATES:
            # Signal received after terminal state reached -> no-op
            workflow.logger.info("cancel_booking signal received post-terminal state; ignoring.")
            return

        workflow.logger.info("cancel_booking signal received mid-workflow.")
        self._cancel_requested = True

    @workflow.run
    async def run(self, request: BookingRequest) -> Dict[str, Any]:
        self._idempotency_key = request.idempotency_key
        self._supplier_id = request.supplier_id
        self._status = "PROCESSING"
        workflow_id = workflow.info().workflow_id

        # -------------------------------------------------------------------------
        # Step 1: Revalidate offer pricing & availability
        # -------------------------------------------------------------------------
        self._current_step = "REVALIDATING_OFFER"
        if self._cancel_requested:
            self._status = "CANCELLED"
            self._current_step = "COMPLETED"
            return self.get_status()

        reval_payload = {
            "supplier_id": request.supplier_id,
            "property_id": request.property_id,
            "check_in_date": request.check_in_date,
            "check_out_date": request.check_out_date,
            "quoted_price": request.quoted_price,
            "currency": request.currency,
        }

        reval_res = await workflow.execute_activity(
            revalidate_offer_activity,
            reval_payload,
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                backoff_coefficient=2.0,
                maximum_attempts=5,
            ),
        )

        if reval_res.get("price_changed_exceeded"):
            self._status = "PRICE_CHANGED"
            self._current_step = "COMPLETED"
            return self.get_status()

        # -------------------------------------------------------------------------
        # Step 2: Create supplier reservation using idempotency token
        # -------------------------------------------------------------------------
        self._current_step = "CREATING_SUPPLIER_RESERVATION"

        create_payload = {
            "supplier_id": request.supplier_id,
            "property_id": request.property_id,
            "check_in_date": request.check_in_date,
            "check_out_date": request.check_out_date,
            "total_price": reval_res.get("new_price", request.quoted_price),
            "currency": request.currency,
            "guest_details": request.guest_details,
            "idempotency_key": request.idempotency_key,
        }

        booking_res = await workflow.execute_activity(
            create_supplier_reservation_activity,
            create_payload,
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_attempts=2,
            ),
        )

        self._supplier_reservation_id = booking_res["reservation_id"]

        # Check if cancellation signal arrived right after supplier reservation creation
        if self._cancel_requested:
            self._current_step = "COMPENSATING_SUPPLIER_RESERVATION"
            if self._supplier_reservation_id:
                await workflow.execute_activity(
                    cancel_supplier_reservation_activity,
                    {
                        "supplier_id": request.supplier_id,
                        "supplier_reservation_id": self._supplier_reservation_id,
                    },
                    start_to_close_timeout=timedelta(seconds=15),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=1),
                        backoff_coefficient=2.0,
                        maximum_attempts=3,
                    ),
                )
            self._status = "CANCELLED"
            self._current_step = "COMPLETED"
            return self.get_status()

        # -------------------------------------------------------------------------
        # Step 3: Persist booking record to DB with Saga Compensation on failure
        # -------------------------------------------------------------------------
        self._current_step = "PERSISTING_DB_RECORD"
        persist_payload = {
            "workflow_id": workflow_id,
            "idempotency_key": request.idempotency_key,
            "supplier_id": request.supplier_id,
            "property_id": request.property_id,
            "status": "PROCESSING",
            "supplier_reservation_id": self._supplier_reservation_id,
            "total_price": reval_res.get("new_price", request.quoted_price),
            "currency": request.currency,
            "guest_name": request.guest_details.get("name", "Guest"),
        }

        try:
            await workflow.execute_activity(
                persist_booking_record_activity,
                persist_payload,
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    backoff_coefficient=2.0,
                    maximum_attempts=3,
                ),
            )
        except Exception as e:
            # Saga Compensation: DB write failed permanently after retries
            workflow.logger.error(f"Persist DB failed: {e}. Initiating Saga compensation...")
            self._current_step = "COMPENSATING_SUPPLIER_RESERVATION"
            try:
                await workflow.execute_activity(
                    cancel_supplier_reservation_activity,
                    {
                        "supplier_id": request.supplier_id,
                        "supplier_reservation_id": self._supplier_reservation_id,
                    },
                    start_to_close_timeout=timedelta(seconds=15),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=1),
                        backoff_coefficient=2.0,
                        maximum_attempts=3,
                    ),
                )
                self._status = "FAILED"
            except Exception as comp_err:
                # Compensation ALSO failed!
                workflow.logger.error(f"Saga compensation failed: {comp_err}. Moving to REQUIRES_MANUAL_REVIEW.")
                self._status = "REQUIRES_MANUAL_REVIEW"

            self._current_step = "COMPLETED"
            return self.get_status()

        # -------------------------------------------------------------------------
        # Step 4: Poll supplier confirmation status (with explicit cancel checks)
        # -------------------------------------------------------------------------
        self._current_step = "POLLING_SUPPLIER_CONFIRMATION"
        max_poll_attempts = 5
        confirmed = False

        for attempt in range(max_poll_attempts):
            # Explicit cancellation check during polling loop
            if self._cancel_requested:
                self._current_step = "COMPENSATING_SUPPLIER_RESERVATION"
                if self._supplier_reservation_id:
                    await workflow.execute_activity(
                        cancel_supplier_reservation_activity,
                        {
                            "supplier_id": request.supplier_id,
                            "supplier_reservation_id": self._supplier_reservation_id,
                        },
                        start_to_close_timeout=timedelta(seconds=15),
                        retry_policy=RetryPolicy(
                            initial_interval=timedelta(seconds=1),
                            backoff_coefficient=2.0,
                            maximum_attempts=3,
                        ),
                    )
                self._status = "CANCELLED"
                self._current_step = "COMPLETED"

                # Update DB record
                persist_payload["status"] = "CANCELLED"
                try:
                    await workflow.execute_activity(
                        persist_booking_record_activity,
                        persist_payload,
                        start_to_close_timeout=timedelta(seconds=10),
                        retry_policy=RetryPolicy(
                            initial_interval=timedelta(seconds=1),
                            maximum_attempts=2,
                        ),
                    )
                except Exception:
                    pass
                return self.get_status()

            poll_res = await workflow.execute_activity(
                poll_supplier_confirmation_activity,
                {
                    "supplier_id": request.supplier_id,
                    "supplier_reservation_id": self._supplier_reservation_id,
                },
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    backoff_coefficient=2.0,
                    maximum_attempts=3,
                ),
            )

            status_val = poll_res.get("status", "").lower()
            if status_val == "confirmed":
                self._status = "CONFIRMED"
                confirmed = True
                break
            elif status_val in ("cancelled", "failed"):
                self._status = "FAILED"
                break

            await workflow.sleep(timedelta(seconds=2))

        # Strict Resolution Rule: If max attempts exhausted without explicit CONFIRMED or FAILED status
        if not confirmed and self._status not in ("CONFIRMED", "FAILED", "CANCELLED"):
            self._status = "REQUIRES_MANUAL_REVIEW"

        # Final DB status update
        self._current_step = "COMPLETED"
        persist_payload["status"] = self._status
        try:
            await workflow.execute_activity(
                persist_booking_record_activity,
                persist_payload,
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_attempts=2,
                ),
            )
        except Exception:
            pass

        return self.get_status()

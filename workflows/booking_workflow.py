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
        record_failure_log_activity,
        record_status_change_activity,
        record_supplier_reference_activity,
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
    Includes Step 4 structured status history audit tracking across all state transitions.
    """

    def __init__(self):
        self._status: str = "PENDING"
        self._current_step: str = "INITIALIZED"
        self._supplier_reservation_id: Optional[str] = None
        self._cancel_requested: bool = False
        self._idempotency_key: str = ""
        self._supplier_id: str = ""
        self._booking_id: str = ""

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        """Query current workflow state and reservation details."""
        return {
            "booking_id": self._booking_id,
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
            workflow.logger.info("cancel_booking signal received post-terminal state; ignoring.")
            return

        workflow.logger.info("cancel_booking signal received mid-workflow.")
        self._cancel_requested = True

    async def _transition_status(
        self,
        new_status: str,
        reason: str,
        current_step: Optional[str] = None
    ) -> None:
        """
        Record a status transition into self._status and persist a row to booking_status_history.
        Best-Effort Policy: Audit history failure does NOT fail the workflow execution.
        """
        previous = self._status
        self._status = new_status
        if current_step:
            self._current_step = current_step

        try:
            await workflow.execute_activity(
                record_status_change_activity,
                {
                    "booking_id": self._booking_id,
                    "previous_status": previous,
                    "new_status": new_status,
                    "reason": reason,
                },
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception as e:
            workflow.logger.warning(f"Failed to record status transition audit: {e}")

    @workflow.run
    async def run(self, request: BookingRequest) -> Dict[str, Any]:
        self._idempotency_key = request.idempotency_key
        self._supplier_id = request.supplier_id
        self._booking_id = f"BK-{request.idempotency_key[:12]}"
        workflow_id = workflow.info().workflow_id

        # Record initial status transition: PENDING -> PROCESSING
        await self._transition_status(
            new_status="PROCESSING",
            reason="Booking request initiated",
            current_step="INITIALIZED"
        )

        # -------------------------------------------------------------------------
        # Step 1: Revalidate offer pricing & availability
        # -------------------------------------------------------------------------
        self._current_step = "REVALIDATING_OFFER"
        if self._cancel_requested:
            await self._transition_status("CANCELLED", "Cancelled prior to revalidation", "COMPLETED")
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
            drift_pct = round(reval_res.get("price_drift", 0.0) * 100, 2)
            await self._transition_status(
                new_status="PRICE_CHANGED",
                reason=f"Price drift exceeded threshold: {drift_pct}% change",
                current_step="COMPLETED"
            )
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

        # Persist raw supplier reference response payload for audit trail
        try:
            await workflow.execute_activity(
                record_supplier_reference_activity,
                {
                    "booking_id": self._booking_id,
                    "supplier_id": request.supplier_id,
                    "supplier_reservation_id": self._supplier_reservation_id,
                    "raw_supplier_response": booking_res,
                },
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception as ref_err:
            workflow.logger.warning(f"Failed to record supplier reference audit: {ref_err}")

        # Check if cancellation signal arrived post-reservation creation
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
            await self._transition_status("CANCELLED", "User cancelled mid-polling", "COMPLETED")
            return self.get_status()

        # -------------------------------------------------------------------------
        # Step 3: Persist booking record to DB with Saga Compensation on failure
        # -------------------------------------------------------------------------
        self._current_step = "PERSISTING_DB_RECORD"
        persist_payload = {
            "booking_id": self._booking_id,
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
            
            # Record transition: PROCESSING -> COMPENSATING_SUPPLIER_RESERVATION
            await self._transition_status(
                new_status="COMPENSATING",
                reason=f"Persist DB record failed permanently after retries: {e}",
                current_step="COMPENSATING_SUPPLIER_RESERVATION"
            )

            # Record failure log
            try:
                await workflow.execute_activity(
                    record_failure_log_activity,
                    {
                        "context": "booking_workflow",
                        "booking_id": self._booking_id,
                        "supplier_id": request.supplier_id,
                        "error_type": "DatabasePersistError",
                        "error_message": str(e),
                        "retry_attempt_number": 3,
                    },
                    start_to_close_timeout=timedelta(seconds=5),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
            except Exception:
                pass

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
                # Saga compensation succeeded -> FAILED
                await self._transition_status(
                    new_status="FAILED",
                    reason="DB persist failed; supplier reservation successfully cancelled via Saga compensation",
                    current_step="COMPLETED"
                )
            except Exception as comp_err:
                # Compensation ALSO failed! -> REQUIRES_MANUAL_REVIEW
                workflow.logger.error(f"Saga compensation failed: {comp_err}. Moving to REQUIRES_MANUAL_REVIEW.")
                await self._transition_status(
                    new_status="REQUIRES_MANUAL_REVIEW",
                    reason=f"DB persist failed AND supplier cancellation compensation failed: {comp_err}",
                    current_step="COMPLETED"
                )

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
                await self._transition_status("CANCELLED", "User cancelled mid-polling", "COMPLETED")
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
                await self._transition_status("CONFIRMED", "Supplier confirmed reservation", "COMPLETED")
                confirmed = True
                break
            elif status_val in ("cancelled", "failed"):
                await self._transition_status("FAILED", f"Supplier returned failure status: {status_val}", "COMPLETED")
                break

            await workflow.sleep(timedelta(seconds=2))

        # Strict Resolution Rule: If max attempts exhausted without explicit CONFIRMED or FAILED status
        if not confirmed and self._status not in ("CONFIRMED", "FAILED", "CANCELLED"):
            await self._transition_status(
                new_status="REQUIRES_MANUAL_REVIEW",
                reason="Supplier status polling exhausted 5 attempts without explicit confirmed/failed status",
                current_step="COMPLETED"
            )

        # Final DB status update
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

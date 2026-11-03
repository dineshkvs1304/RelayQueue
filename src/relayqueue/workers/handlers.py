import logging

logger = logging.getLogger(__name__)


def send_email(payload: dict) -> None:
    recipient = payload.get("recipient")
    subject = payload.get("subject")

    if not recipient or not subject:
        raise ValueError("Recipient and subject are required")

    # Simulated email execution for development.
    logger.info(
        "Email task executed | recipient=%s | subject=%s",
        recipient,
        subject,
    )


def echo(payload: dict) -> None:
    """Log the supplied message. Useful for testing job execution."""
    message = payload.get("message")

    if not message:
        raise ValueError("Message is required")

    logger.info("Echo task executed | message=%s", message)


TASK_HANDLERS = {
    "send_email": send_email,
    "echo": echo,
}


def execute_task(task_type: str, payload: dict) -> None:
    handler = TASK_HANDLERS.get(task_type)

    if handler is None:
        raise ValueError(f"Unsupported task type: {task_type}")

    handler(payload)

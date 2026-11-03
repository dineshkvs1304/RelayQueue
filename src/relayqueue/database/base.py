from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all RelayQueue database models."""


from relayqueue import models  # noqa: E402, F401

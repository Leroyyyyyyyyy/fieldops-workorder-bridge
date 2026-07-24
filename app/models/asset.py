from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Asset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A piece of equipment at a client site that work orders are raised against.

    `external_id` is the vendor's stable identifier and is unique, so incoming
    vendor events can resolve the asset without exposing our internal UUID.
    """

    __tablename__ = "assets"

    external_id: Mapped[str] = mapped_column(unique=True, index=True)
    site: Mapped[str]
    name: Mapped[str]
    asset_type: Mapped[str]
    status: Mapped[str] = mapped_column(default="ACTIVE")

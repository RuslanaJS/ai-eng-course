"""Pydantic extraction schema v5 (like a zod / TypeScript interface: describes and validates data).

One record = one apartment. Area, rooms and floor are single numbers. Price per m2 is a
{min, max} range: an exact price gives min = max, an investment-wide range gives its bounds.
There is no total price field: it must not be taken from the investment-wide range.
Rule for every field: if the text does not say it, return null ("not_stated" for enums),
never invent it.
"""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Finish(StrEnum):
    DEVELOPER_STANDARD = "developer_standard"  # developer standard: walls and installations, buyer finishes the interior
    TURNKEY = "turnkey"  # fully finished, ready to move in
    TO_RENOVATE = "to_renovate"  # needs renovation
    NOT_STATED = "not_stated"


class Parking(StrEnum):
    UNDERGROUND = "underground"  # underground garage or car park
    SURFACE = "surface"  # open-air or ground-level spots
    BOTH = "both"  # both underground and surface
    NONE = "none"  # explicitly no parking
    NOT_STATED = "not_stated"


# YYYY (2026), YYYY-MM (2026-03) or YYYY-QN (2026-Q3)
CompletionDate = Annotated[
    str,
    Field(pattern=r"^\d{4}(-(0[1-9]|1[0-2]|Q[1-4]))?$"),
]


class PriceRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: float | None = Field(None, gt=0)
    max: float | None = Field(None, gt=0)

    @model_validator(mode="after")
    def _min_not_above_max(self) -> Self:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not exceed max")
        return self


class Address(BaseModel):
    model_config = ConfigDict(extra="forbid")

    street: str | None = Field(
        None, description="Street and building number, as written in the text"
    )
    district: str | None = Field(
        None, description="District of the city (first element after the city in the address line)"
    )
    city: str | None = Field(None, description="City in Polish spelling: Warszawa, not Warsaw")


class OfferRecord(BaseModel):
    """Extracted data about one apartment"""

    model_config = ConfigDict(extra="forbid")

    project_name: str | None = Field(None, description="Name of the development (investment)")
    developer: str | None = Field(
        None, description="Developer company name, as written in the text"
    )
    address: Address = Field(default_factory=Address)
    # TODO(project): add an explicit completion status (completed / under construction) so a
    # ready building does not only carry a past date here; see data/golden/LABELING.md.
    completion_date: CompletionDate | None = Field(
        None,
        description="Completion or handover date: YYYY, YYYY-MM or YYYY-QN, e.g. 2026-Q3. "
        "If the building is already completed, use the quarter it was completed in.",
    )
    area_m2: float | None = Field(
        None, gt=0, description="Area of THIS apartment in square metres (a single number)"
    )
    rooms: int | None = Field(
        None, ge=0, description="Number of rooms of THIS apartment (a single number)"
    )
    # Stored and shown as written in the source (parter = 0, '1 piętro' = 1); nothing is
    # converted anywhere in the project.
    floor: int | None = Field(
        None,
        description="Floor of THIS apartment as in the Polish text: parter = 0, '1 piętro' = 1, underground = -1",
    )
    price_per_m2_pln: PriceRange | None = Field(
        None,
        description="Price per square metre in PLN. Exact price: min = max. If only an "
        "investment-wide range is given: its bounds. Normalise '9 850 zł/m²', 'PLN 9,850', "
        "'ok. 10 tys.' to numbers.",
    )
    finish: Finish = Field(Finish.NOT_STATED, description="Finish standard of the apartment")
    parking: Parking = Field(
        Parking.NOT_STATED, description="Parking type offered with the development"
    )
    amenities: list[str] = Field(
        default_factory=list,
        description="Amenities and extras as listed in the text (balcony, storage room, lift, ...)",
    )

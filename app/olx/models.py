from pydantic import BaseModel, Field
from datetime import datetime

class RawListing(BaseModel):
    olx_id: str
    title: str
    price: float
    url: str
    location: str | None = None
    image_url: str | None = None
    published_date_str: str | None = None

class ListingDetails(BaseModel):
    description: str
    image_url: str | None = None
    images: list[str] = Field(default_factory=list)
    parameters: dict[str, str] = Field(default_factory=dict)

# Aliases/helpers for codebase compatibility
class ScrapedAd(RawListing):
    pass

class ScrapedAdDetails(BaseModel):
    olx_id: str
    title: str
    price: int
    url: str
    location: str | None = None
    description: str | None = None
    image_url: str | None = None
    published_at: datetime | None = None

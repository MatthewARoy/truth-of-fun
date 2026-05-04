"""Event ingestion pipelines package."""

from app.ingestion.base import BaseSource
from app.ingestion.input_agent import InputAgentSource
from app.ingestion.registry import SourceRegistry
from app.ingestion.sources.eventbrite import EventbriteSource
from app.ingestion.sources.funcheap_sf import FuncheapSFSource
from app.ingestion.sources.meetup import MeetupSource
from app.ingestion.sources.nineteen_hz import NineteenHzSource
from app.ingestion.sources.reddit import RedditSource
from app.ingestion.sources.dothebay import DoTheBaySource
from app.ingestion.sources.eddies_list import EddiesListSource
from app.ingestion.sources.luma import LumaSource
from app.ingestion.sources.minnesotastreet import MinnesotaStreetSource
from app.ingestion.sources.sfstation import SFStationSource
from app.ingestion.ticketmaster import TicketmasterSource

registry = SourceRegistry()
registry.register(TicketmasterSource.source_name, TicketmasterSource)
registry.register(EventbriteSource.source_name, EventbriteSource)
registry.register(MeetupSource.source_name, MeetupSource)
registry.register(FuncheapSFSource.source_name, FuncheapSFSource)
registry.register(NineteenHzSource.source_name, NineteenHzSource)
registry.register(LumaSource.source_name, LumaSource)
registry.register(DoTheBaySource.source_name, DoTheBaySource)
registry.register(SFStationSource.source_name, SFStationSource)
registry.register(MinnesotaStreetSource.source_name, MinnesotaStreetSource)
registry.register(RedditSource.source_name, RedditSource)
registry.register(EddiesListSource.source_name, EddiesListSource)

__all__ = [
    "BaseSource",
    "InputAgentSource",
    "DoTheBaySource",
    "EddiesListSource",
    "EventbriteSource",
    "FuncheapSFSource",
    "LumaSource",
    "MeetupSource",
    "MinnesotaStreetSource",
    "NineteenHzSource",
    "RedditSource",
    "SFStationSource",
    "SourceRegistry",
    "TicketmasterSource",
    "registry",
]

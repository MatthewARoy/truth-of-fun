"""Event ingestion pipelines package."""

from app.ingestion.base import BaseSource
from app.ingestion.input_agent import InputAgentSource
from app.ingestion.registry import SourceRegistry
from app.ingestion.sources.bibliocommons import BiblioCommonsSource
from app.ingestion.sources.bibliocommons import OaklandLibrarySource
from app.ingestion.sources.bibliocommons import SanJoseLibrarySource
from app.ingestion.sources.eventbrite import EventbriteSource
from app.ingestion.sources.funcheap_sf import FuncheapSFSource
from app.ingestion.sources.meetup import MeetupSource
from app.ingestion.sources.nineteen_hz import NineteenHzSource
from app.ingestion.sources.reddit import RedditSource
from app.ingestion.sources.dothebay import DoTheBaySource
from app.ingestion.sources.eddies_list import EddiesListSource
from app.ingestion.sources.localist import LocalistSource
from app.ingestion.sources.localist import SJSUEventsSource
from app.ingestion.sources.localist import StanfordEventsSource
from app.ingestion.sources.luma import LumaSource
from app.ingestion.sources.minnesotastreet import MinnesotaStreetSource
from app.ingestion.sources.sfstation import SFStationSource
from app.ingestion.sources.sterngrove import SternGroveSource
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
registry.register(SternGroveSource.source_name, SternGroveSource)
registry.register(MinnesotaStreetSource.source_name, MinnesotaStreetSource)
registry.register(RedditSource.source_name, RedditSource)
registry.register(EddiesListSource.source_name, EddiesListSource)
# Official calendars. One registered source per institution (not one source
# iterating campuses/libraries): the worker tracks health, canary history and
# partial-crawl errors per source name, so a Stanford outage must not hide
# behind a healthy SJSU count.
registry.register(StanfordEventsSource.source_name, StanfordEventsSource)
registry.register(SJSUEventsSource.source_name, SJSUEventsSource)
registry.register(OaklandLibrarySource.source_name, OaklandLibrarySource)
registry.register(SanJoseLibrarySource.source_name, SanJoseLibrarySource)

__all__ = [
    "BaseSource",
    "InputAgentSource",
    "BiblioCommonsSource",
    "DoTheBaySource",
    "EddiesListSource",
    "EventbriteSource",
    "FuncheapSFSource",
    "LocalistSource",
    "LumaSource",
    "MeetupSource",
    "MinnesotaStreetSource",
    "NineteenHzSource",
    "OaklandLibrarySource",
    "RedditSource",
    "SFStationSource",
    "SJSUEventsSource",
    "SanJoseLibrarySource",
    "StanfordEventsSource",
    "SternGroveSource",
    "SourceRegistry",
    "TicketmasterSource",
    "registry",
]

"""Ingestion source implementations."""

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

__all__ = [
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
]

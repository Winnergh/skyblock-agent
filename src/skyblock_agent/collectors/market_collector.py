"""Fetch and import Hypixel Bazaar and Auction House data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skyblock_agent.collectors.hypixel_client import HypixelClient
from skyblock_agent.models.market import (
    AuctionListing,
    BazaarProduct,
    filter_auctions,
    filter_bazaar_products,
    parse_auctions,
    parse_bazaar_products,
)
from skyblock_agent.storage.raw_store import save_raw_json


@dataclass
class BazaarSnapshotResult:
    last_updated: int
    products: list[BazaarProduct]
    raw_path: Path
    total_products: int


@dataclass
class AuctionsPageResult:
    page: int
    total_pages: int
    total_auctions: int
    last_updated: int
    auctions: list[AuctionListing]
    raw_path: Path


class MarketCollector:
    def __init__(self, hypixel: HypixelClient | None = None) -> None:
        self.hypixel = hypixel or HypixelClient()

    def fetch_bazaar(self, *, save: bool = True) -> BazaarSnapshotResult:
        payload = self.hypixel.get_bazaar()
        raw_path = Path()
        if save:
            raw_path = save_raw_json("bazaar", "snapshot", payload)

        products = parse_bazaar_products(payload)
        return BazaarSnapshotResult(
            last_updated=int(payload.get("lastUpdated") or 0),
            products=products,
            raw_path=raw_path,
            total_products=len(products),
        )

    def fetch_auctions_page(self, page: int = 0, *, save: bool = True) -> AuctionsPageResult:
        payload = self.hypixel.get_auctions(page)
        raw_path = Path()
        if save:
            raw_path = save_raw_json("auctions", f"page_{page}", payload)

        auctions = parse_auctions(payload)
        return AuctionsPageResult(
            page=int(payload.get("page") or page),
            total_pages=int(payload.get("totalPages") or 0),
            total_auctions=int(payload.get("totalAuctions") or 0),
            last_updated=int(payload.get("lastUpdated") or 0),
            auctions=auctions,
            raw_path=raw_path,
        )

    def search_bazaar(
        self,
        query: str = "",
        *,
        save: bool = True,
    ) -> BazaarSnapshotResult:
        snapshot = self.fetch_bazaar(save=save)
        if query.strip():
            snapshot.products = filter_bazaar_products(snapshot.products, query)
        return snapshot

    def search_auctions_page(
        self,
        page: int = 0,
        query: str = "",
        *,
        bin_only: bool = False,
        save: bool = True,
    ) -> AuctionsPageResult:
        result = self.fetch_auctions_page(page, save=save)
        if query.strip() or bin_only:
            result.auctions = filter_auctions(result.auctions, query, bin_only=bin_only)
        return result

    def close(self) -> None:
        self.hypixel.close()

    def __enter__(self) -> MarketCollector:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

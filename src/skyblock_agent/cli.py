"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys

from skyblock_agent.collectors.hypixel_client import HypixelApiError
from skyblock_agent.collectors.market_collector import MarketCollector
from skyblock_agent.collectors.player_lookup import PlayerLookupService
from skyblock_agent.serializers import (
    build_auctions_payload,
    build_bazaar_payload,
    build_lookup_payload,
    profile_result_to_dict,
)
from skyblock_agent.storage.player_index import list_players
from skyblock_agent.validation.api_recognizer import recognize_player_result


def _format_profile_result(result) -> str:
    s = result.summary
    lines = [
        f"Player: {result.username}",
        f"UUID: {result.uuid}",
        f"Profile: {s.cute_name} ({s.profile_id})",
        f"Selected: {'yes' if s.selected else 'no'}",
        f"Game mode: {s.game_mode or 'normal'}",
        f"Coop members: {s.member_count}",
        f"SkyBlock level: {s.skyblock_level:.2f}" if s.skyblock_level is not None else "SkyBlock level: (unknown)",
        f"Profiles: {', '.join(result.available_profiles)}",
    ]

    if s.skills_api_enabled:
        lines.append("Skills (API enabled):")
        for skill in s.skills:
            if skill.experience is not None:
                lines.append(f"  {skill.name:12} {skill.experience:,.0f} XP")
    else:
        lines.append("Skills: API disabled in-game (player_data hidden)")

    if s.slayers:
        lines.append("Slayers:")
        for slayer in s.slayers:
            if slayer.xp > 0 or slayer.level > 0:
                lines.append(f"  {slayer.name:10} L{slayer.level}  {slayer.xp:,.0f} XP")

    if s.catacombs_level is not None:
        lines.append(f"Catacombs (raw XP/100): {s.catacombs_level:.2f}")

    if result.raw_paths:
        lines.append("Saved files:")
        for path in result.raw_paths:
            lines.append(f"  {path}")

    return "\n".join(lines)


def _format_import_record(record) -> str:
    lines = [
        f"Imported at: {record.last_imported_at}",
        f"Selected profile: {record.selected_profile or '—'}",
        "Saved:",
    ]
    for label, path in record.saved_files.items():
        lines.append(f"  {label}: {path}")
    return "\n".join(lines)


def _format_recognition_report(report) -> str:
    lines = [
        f"Recognition: {report.ok_count}/{report.total_count} fields OK "
        f"({report.pass_rate * 100:.1f}%)",
        f"Required fields OK: {'yes' if report.all_required_ok else 'no'}",
        "",
    ]
    for check in report.checks:
        detail = f" — {check.detail}" if check.detail else ""
        lines.append(f"[{check.status:7}] {check.label}{detail}")
    return "\n".join(lines)


def _run_lookup(args: argparse.Namespace):
    with PlayerLookupService() as service:
        lookup = service.lookup(args.username, profile_name=args.profile)
    report = recognize_player_result(lookup.profile)
    return lookup, report


def cmd_lookup(args: argparse.Namespace) -> int:
    try:
        lookup, report = _run_lookup(args)
    except HypixelApiError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(build_lookup_payload(lookup, report), indent=2, ensure_ascii=False))
    else:
        print(_format_profile_result(lookup.profile))
        print()
        print(_format_import_record(lookup.import_record))
        if args.recognition:
            print()
            print(_format_recognition_report(report))
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    args.recognition = getattr(args, "recognition", False)
    return cmd_lookup(args)


def cmd_test_api(args: argparse.Namespace) -> int:
    try:
        lookup, report = _run_lookup(args)
    except HypixelApiError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    payload = build_lookup_payload(lookup, report)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(_format_profile_result(lookup.profile))
        print()
        print(_format_import_record(lookup.import_record))
        print()
        print(_format_recognition_report(report))

    if report.all_required_ok:
        return 0
    return 3


def cmd_list_players(args: argparse.Namespace) -> int:
    records = list_players()
    if args.json:
        print(json.dumps({"players": [r.to_dict() for r in records]}, indent=2))
        return 0

    if not records:
        print("No imported players yet. Use: skyblock-agent lookup <username>")
        return 0

    for record in records:
        profiles = ", ".join(record.profiles) if record.profiles else "—"
        print(f"{record.username} ({record.uuid})")
        print(f"  imported: {record.last_imported_at}")
        print(f"  profiles: {profiles}")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from skyblock_agent.web.app import run
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Skyblock Agent GUI: http://{args.host}:{args.port}")
    run(host=args.host, port=args.port)
    return 0


def _format_bazaar(snapshot, *, query: str = "", limit: int = 20) -> str:
    products = snapshot.products[:limit]
    lines = [
        f"Bazaar snapshot ({snapshot.total_products} products)",
        f"Last updated: {snapshot.last_updated}",
    ]
    if query:
        lines.append(f"Filter: {query!r} ({len(snapshot.products)} matches)")
    if snapshot.raw_path:
        lines.append(f"Saved: {snapshot.raw_path}")
    lines.append("")
    if not products:
        lines.append("No products matched.")
        return "\n".join(lines)

    lines.append(f"{'Product':<28} {'Buy':>10} {'Sell':>10} {'Spread':>10}")
    for product in products:
        lines.append(
            f"{product.product_id:<28} "
            f"{product.buy_price:>10.2f} "
            f"{product.sell_price:>10.2f} "
            f"{product.spread:>10.2f}"
        )
    if len(snapshot.products) > limit:
        lines.append(f"... and {len(snapshot.products) - limit} more")
    return "\n".join(lines)


def _format_auctions(page, *, query: str = "", bin_only: bool = False, limit: int = 20) -> str:
    auctions = page.auctions[:limit]
    lines = [
        f"Auction House page {page.page + 1}/{page.total_pages} "
        f"({page.total_auctions:,} active auctions)",
        f"Last updated: {page.last_updated}",
    ]
    if query:
        lines.append(f"Filter: {query!r}")
    if bin_only:
        lines.append("BIN only: yes")
    lines.append(f"Matches on this page: {len(page.auctions)}")
    if page.raw_path:
        lines.append(f"Saved: {page.raw_path}")
    lines.append("")
    if not auctions:
        lines.append("No auctions matched on this page.")
        return "\n".join(lines)

    lines.append(f"{'Item':<32} {'Type':>4} {'Price':>12} {'Tier':<10}")
    for auction in auctions:
        kind = "BIN" if auction.bin else "Bid"
        lines.append(
            f"{auction.item_name[:32]:<32} {kind:>4} {auction.price:>12,} {auction.tier:<10}"
        )
    if len(page.auctions) > limit:
        lines.append(f"... and {len(page.auctions) - limit} more on this page")
    return "\n".join(lines)


def cmd_bazaar(args: argparse.Namespace) -> int:
    try:
        with MarketCollector() as collector:
            snapshot = collector.search_bazaar(args.search or "", save=not args.no_save)
    except HypixelApiError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(build_bazaar_payload(snapshot, query=args.search or "", limit=args.limit), indent=2))
    else:
        print(_format_bazaar(snapshot, query=args.search or "", limit=args.limit))
    return 0


def cmd_auctions(args: argparse.Namespace) -> int:
    try:
        with MarketCollector() as collector:
            page = collector.search_auctions_page(
                args.page,
                args.search or "",
                bin_only=args.bin,
                save=not args.no_save,
            )
    except HypixelApiError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                build_auctions_payload(
                    page,
                    query=args.search or "",
                    bin_only=args.bin,
                    limit=args.limit,
                ),
                indent=2,
            )
        )
    else:
        print(_format_auctions(page, query=args.search or "", bin_only=args.bin, limit=args.limit))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skyblock-agent",
        description="Hypixel SkyBlock info collector",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    lookup = sub.add_parser(
        "lookup",
        help="Look up a player by username and import Hypixel API data locally",
    )
    lookup.add_argument("username", help="Minecraft username")
    lookup.add_argument(
        "--profile",
        "-p",
        help="Profile name (e.g. Apple). Defaults to selected profile.",
    )
    lookup.add_argument("--json", action="store_true")
    lookup.add_argument("--recognition", action="store_true")
    lookup.set_defaults(func=cmd_lookup)

    profile = sub.add_parser("profile", help="Alias for lookup")
    profile.add_argument("username", help="Minecraft username")
    profile.add_argument("--profile", "-p", help="Profile cute name")
    profile.add_argument("--json", action="store_true")
    profile.add_argument("--recognition", action="store_true")
    profile.set_defaults(func=cmd_profile)

    test_api = sub.add_parser(
        "test-api",
        help="Lookup a player and print API field recognition results",
    )
    test_api.add_argument("username", help="Minecraft username")
    test_api.add_argument("--profile", "-p", help="Profile cute name")
    test_api.add_argument("--json", action="store_true")
    test_api.set_defaults(func=cmd_test_api)

    players = sub.add_parser("players", help="List locally imported players")
    players.add_argument("--json", action="store_true")
    players.set_defaults(func=cmd_list_players)

    gui = sub.add_parser("gui", help="Launch the local web UI")
    gui.add_argument("--host", default="127.0.0.1")
    gui.add_argument("--port", type=int, default=8765)
    gui.set_defaults(func=cmd_gui)

    bazaar = sub.add_parser("bazaar", help="Fetch Bazaar prices and save a local snapshot")
    bazaar.add_argument("--search", "-s", help="Filter by product id (e.g. ENCHANTED_DIAMOND)")
    bazaar.add_argument("--limit", type=int, default=20, help="Rows to print (default: 20)")
    bazaar.add_argument("--json", action="store_true")
    bazaar.add_argument("--no-save", action="store_true", help="Skip writing raw JSON to data/")
    bazaar.set_defaults(func=cmd_bazaar)

    auctions = sub.add_parser("auctions", help="Fetch Auction House page and prices")
    auctions.add_argument("--page", type=int, default=0, help="Auction page index (0-based)")
    auctions.add_argument("--search", "-s", help="Filter item name/tier/category on this page")
    auctions.add_argument("--bin", action="store_true", help="Show buy-it-now listings only")
    auctions.add_argument("--limit", type=int, default=20, help="Rows to print (default: 20)")
    auctions.add_argument("--json", action="store_true")
    auctions.add_argument("--no-save", action="store_true", help="Skip writing raw JSON to data/")
    auctions.set_defaults(func=cmd_auctions)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

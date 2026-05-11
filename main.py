#!/usr/bin/env python3
"""Physical Kanban board — e-paper tags + GitHub Projects v2 + NFC status updates."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

from config import get_config
from github_client import GitHubClient, ProjectMeta, SprintItem
from nfc import NfcReader
from oepl import OEPLClient
from renderer import render_card
from store import Assignment, Store, TagRecord


# ---------------------------------------------------------------------------
# Sync: pull sprint items from GitHub and refresh tag displays
# ---------------------------------------------------------------------------


def do_sync(
    store: Store,
    oepl: OEPLClient,
    gh: GitHubClient,
    meta: ProjectMeta,
    cfg,
) -> list[SprintItem]:
    """Sync tag displays with current sprint state. Returns unassigned items."""
    print(f"[sync] Fetching sprint: {meta.current_sprint_title}")
    items = gh.get_sprint_items(meta.project_id, meta.current_sprint_id)
    print(f"[sync] {len(items)} items in sprint")

    # Refresh tag list from AP
    raw_tags = oepl.get_tags()
    for t in raw_tags:
        mac: str = t.get("mac", "")
        if not mac:
            continue
        hw_type = t.get("hwType", 0)
        w, h = oepl.get_tag_dimensions(hw_type)
        alias = t.get("alias", "")
        store.upsert_tag(mac, w, h, alias)

    print(f"[sync] {len(raw_tags)} tags known to AP")

    # Build lookup: item_id → SprintItem
    item_map = {i.item_id: i for i in items}

    # Update displays for all assigned tags
    for tag, assignment in store.get_all_assignments():
        item = item_map.get(assignment.github_item_id)
        if item is None:
            print(f"  [sync] tag {tag.mac[:8]}… — assigned item no longer in sprint, skipping")
            continue

        status_changed = item.status != assignment.status
        assignee_changed = (item.assignees[0] if item.assignees else "") != assignment.assignee

        if status_changed or assignee_changed:
            assignee = item.assignees[0] if item.assignees else ""
            store.set_assignment(
                mac=tag.mac,
                item_id=item.item_id,
                issue_number=item.issue_number,
                issue_title=item.title,
                status=item.status,
                status_option_id=item.status_option_id,
                assignee=assignee,
                sprint_id=item.sprint_id,
            )
            _push_display(oepl, tag, item.issue_number, item.title, item.status, assignee, cfg)
            print(f"  [sync] #{item.issue_number} → {item.status}")

    # Identify sprint items not yet assigned to any tag
    assigned_item_ids = {a.github_item_id for _, a in store.get_all_assignments()}
    unassigned = [i for i in items if i.item_id not in assigned_item_ids]
    if unassigned:
        print(f"[sync] {len(unassigned)} sprint items not yet assigned to a tag")

    return unassigned


# ---------------------------------------------------------------------------
# Interactive assignment
# ---------------------------------------------------------------------------


def do_assign(store: Store, oepl: OEPLClient, gh: GitHubClient, cfg):
    meta = gh.get_project_meta()
    unassigned_items = do_sync(store, oepl, gh, meta, cfg)
    unassigned_tags = store.get_unassigned_tags()

    if not unassigned_tags:
        print("[assign] No unassigned tags available.")
        return
    if not unassigned_items:
        print("[assign] All sprint items are already assigned to tags.")
        return

    print("\n=== Available tags ===")
    for i, tag in enumerate(unassigned_tags):
        label = tag.alias or tag.mac
        print(f"  [{i}] {label}  ({tag.width}×{tag.height})")

    print("\n=== Unassigned sprint items ===")
    for j, item in enumerate(unassigned_items):
        assignee = item.assignees[0] if item.assignees else "—"
        print(f"  [{j}] #{item.issue_number}  {item.title[:60]}  [{item.status}]  @{assignee}")

    print("\nEnter pairs as  <tag_index>:<item_index>  (e.g. 0:2 1:0), or blank to skip:")
    raw = input("> ").strip()
    if not raw:
        return

    for pair in raw.split():
        try:
            ti, ii = [int(x) for x in pair.split(":")]
            tag = unassigned_tags[ti]
            item = unassigned_items[ii]
        except (ValueError, IndexError):
            print(f"  skipping malformed pair: {pair!r}")
            continue

        assignee = item.assignees[0] if item.assignees else ""
        store.set_assignment(
            mac=tag.mac,
            item_id=item.item_id,
            issue_number=item.issue_number,
            issue_title=item.title,
            status=item.status,
            status_option_id=item.status_option_id,
            assignee=assignee,
            sprint_id=item.sprint_id,
        )
        _push_display(oepl, tag, item.issue_number, item.title, item.status, assignee, cfg)
        print(f"  assigned #{item.issue_number} → tag {tag.alias or tag.mac[:12]}")


# ---------------------------------------------------------------------------
# NFC registration
# ---------------------------------------------------------------------------


def do_register_nfc(store: Store, nfc_device: str):
    tags_without_nfc = store.get_tags_without_nfc()
    if not tags_without_nfc:
        print("[nfc-register] All tags have NFC UIDs registered.")
        return

    reader = NfcReader(nfc_device)
    reader.start()
    print("[nfc-register] NFC reader started. Tap a sticker when prompted.\n")

    try:
        for tag in tags_without_nfc:
            label = tag.alias or tag.mac
            assignment = store.get_assignment(tag.mac)
            ticket = f"#{assignment.issue_number} {assignment.issue_title}" if assignment else "(unassigned)"
            print(f"Tag: {label}  |  Ticket: {ticket}")
            print("  Tap the NFC sticker on this tag (or press Enter to skip)...")

            uid: Optional[str] = None
            while uid is None:
                # Also check for keyboard skip
                import select as _select
                r, _, _ = _select.select([sys.stdin], [], [], 0.05)
                if r:
                    sys.stdin.readline()
                    break
                uid = reader.poll(timeout=0.05)

            if uid:
                store.set_nfc_uid(tag.mac, uid)
                print(f"  Registered NFC UID {uid} → {label}\n")
            else:
                print("  Skipped.\n")
    finally:
        reader.stop()


# ---------------------------------------------------------------------------
# Continuous service
# ---------------------------------------------------------------------------


def run_service(store: Store, oepl: OEPLClient, gh: GitHubClient, cfg):
    nfc_reader = NfcReader(cfg.nfc_device)
    nfc_reader.start()

    meta = gh.get_project_meta()
    do_sync(store, oepl, gh, meta, cfg)
    last_sync = time.monotonic()

    print(f"[run] Service started. Syncing every {cfg.sync_interval}s. Tap NFC stickers to update status.")

    while True:
        # Handle NFC taps
        uid = nfc_reader.poll(timeout=0.5)
        if uid:
            _handle_nfc_tap(uid, store, oepl, gh, meta, cfg)

        # Periodic sync
        if time.monotonic() - last_sync >= cfg.sync_interval:
            meta = gh.get_project_meta()
            do_sync(store, oepl, gh, meta, cfg)
            last_sync = time.monotonic()


def _handle_nfc_tap(uid: str, store: Store, oepl: OEPLClient, gh: GitHubClient, meta: ProjectMeta, cfg):
    tag = store.get_tag_by_nfc(uid)
    if tag is None:
        print(f"[nfc] Unknown sticker UID {uid} — run 'register-nfc' to register it")
        return

    assignment = store.get_assignment(tag.mac)
    if assignment is None:
        print(f"[nfc] Tag {tag.alias or tag.mac} has no ticket assigned")
        return

    next_status = _next_status(assignment.status, meta.status_options)
    if next_status is None:
        print(f"[nfc] #{assignment.issue_number} is already at final status ({assignment.status})")
        return

    print(f"[nfc] #{assignment.issue_number} {assignment.status!r} → {next_status.name!r}")

    ok = gh.update_item_status(
        meta.project_id,
        assignment.github_item_id,
        meta.status_field_id,
        next_status.id,
    )
    if not ok:
        return

    store.update_assignment_status(tag.mac, next_status.name, next_status.id)

    # Re-render the display with updated status
    _push_display(
        oepl,
        tag,
        assignment.issue_number,
        assignment.issue_title,
        next_status.name,
        assignment.assignee,
        cfg,
    )


def _next_status(current_status: str, options):
    """Return the next status option after current_status, or None if already last."""
    names = [o.name for o in options]
    try:
        idx = names.index(current_status)
    except ValueError:
        return options[0] if options else None
    next_idx = idx + 1
    if next_idx >= len(options):
        return None  # at final status — do not wrap
    return options[next_idx]


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------


def do_status(store: Store):
    assignments = store.get_all_assignments()
    if not assignments:
        print("No assignments yet. Run 'assign' to map tags to tickets.")
        return

    print(f"\n{'TAG':<20} {'NFC':<14} {'TICKET':<8} {'STATUS':<14} {'ASSIGNEE':<14} TITLE")
    print("-" * 90)
    for tag, a in assignments:
        label = (tag.alias or tag.mac)[:18]
        nfc = (tag.nfc_uid or "—")[:12]
        print(
            f"{label:<20} {nfc:<14} #{a.issue_number:<7} {a.status:<14} {a.assignee or '—':<14} {a.issue_title[:30]}"
        )

    unassigned = store.get_unassigned_tags()
    if unassigned:
        print(f"\n{len(unassigned)} unassigned tag(s):")
        for t in unassigned:
            nfc = (t.nfc_uid or "—")[:12]
            print(f"  {t.alias or t.mac}  nfc={nfc}  {t.width}×{t.height}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _push_display(oepl: OEPLClient, tag: TagRecord, issue_number: int, title: str, status: str, assignee: str, cfg):
    if tag.width == 0 or tag.height == 0:
        print(f"  [display] tag {tag.mac[:8]}… — unknown dimensions, skipping render")
        return
    img = render_card(
        width=tag.width,
        height=tag.height,
        issue_number=issue_number,
        title=title,
        status=status,
        assignee=assignee,
        font_path=cfg.font_path,
        font_bold_path=cfg.font_bold_path,
    )
    ok = oepl.push_image(tag.mac, img)
    label = tag.alias or tag.mac[:12]
    if ok:
        print(f"  [display] pushed #{issue_number} to {label}")
    else:
        print(f"  [display] FAILED to push #{issue_number} to {label}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Physical Kanban board via OpenEPaperLink + GitHub Projects"
    )
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("sync", help="One-time sync: fetch sprint, refresh displays")
    sub.add_parser("run", help="Run continuous service (NFC + periodic sync)")
    sub.add_parser("assign", help="Interactive: assign sprint tickets to tags")
    sub.add_parser("register-nfc", help="Register NFC sticker UIDs for each tag")
    sub.add_parser("status", help="Show current tag assignments")
    args = parser.parse_args()

    cfg = get_config()
    store = Store(cfg.db_path)
    oepl = OEPLClient(cfg.ap_host)
    gh = GitHubClient(
        cfg.github_token,
        cfg.github_org,
        cfg.github_project_number,
        cfg.sprint_prefix,
    )

    if args.cmd == "sync":
        meta = gh.get_project_meta()
        do_sync(store, oepl, gh, meta, cfg)

    elif args.cmd == "run":
        try:
            run_service(store, oepl, gh, cfg)
        except KeyboardInterrupt:
            print("\nStopped.")

    elif args.cmd == "assign":
        do_assign(store, oepl, gh, cfg)

    elif args.cmd == "register-nfc":
        do_register_nfc(store, cfg.nfc_device)

    elif args.cmd == "status":
        do_status(store)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

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
from sensor_topology import load_topology
from pn532 import PN532
from renderer import (render_card, render_registered_confirmation, render_registration_prompt,
                      render_train_car, render_unused, render_waiting_prompt, _car_type_for_mac)
from sounds import play_status_sound
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
    force: bool = False,
) -> list[SprintItem]:
    """Sync tag displays with current sprint state. Returns unassigned items."""
    print(f"[sync] Fetching sprint: {meta.current_sprint_title}")
    items = gh.get_sprint_items(meta.project_id, meta.current_sprint_id)
    print(f"[sync] {len(items)} items in sprint")

    # Ensure the meta display is never in the assignment pool (cleans up any prior DB entry)
    store.remove_tag(cfg.meta_display_mac)

    # Refresh tag list from AP, skipping the meta display
    raw_tags = oepl.get_tags()
    for t in raw_tags:
        mac: str = t.get("mac", "")
        if not mac or mac == cfg.meta_display_mac:
            continue
        hw_type = t.get("hwType", 0)
        w, h = oepl.get_tag_dimensions(hw_type)
        alias = t.get("alias", "")
        store.upsert_tag(mac, w, h, alias)

    print(f"[sync] {len(raw_tags)} tags known to AP")

    # Build lookup: item_id → SprintItem
    item_map = {i.item_id: i for i in items}

    # Update displays for all assigned tags
    assignments = store.get_all_assignments()
    print(f"[sync] {len(assignments)} tag assignment(s) in database")

    if not assignments:
        print("[sync] No assignments found — run 'assign' to map tickets to tags")

    for tag, assignment in assignments:
        label = tag.alias or tag.mac[:12]
        item = item_map.get(assignment.github_item_id)
        if item is None:
            store.remove_assignment(tag.mac)
            _push_unused(oepl, tag, cfg)
            print(f"  [sync] {label} — not in current sprint, marked unused")
            continue

        status_changed = item.status != assignment.status
        assignee_changed = (item.assignees[0] if item.assignees else "") != assignment.assignee

        if force or status_changed or assignee_changed:
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
                repo_name=item.repo_name,
            )
            _push_display(oepl, tag, item.issue_number, item.title, item.status, assignee, cfg, item.repo_name)
            print(f"  [sync] pushed #{item.issue_number} ({item.status}) → {label}")
        else:
            print(f"  [sync] #{item.issue_number} ({item.status}) — no change, skipping")

    # Auto-assign any unassigned sprint items to vacant tags
    # Sort by MAC ascending so the lexicographically largest MAC (steam engine) is consumed last
    assigned_item_ids = {a.github_item_id for _, a in store.get_all_assignments()}
    unassigned_items = [i for i in items if i.item_id not in assigned_item_ids]
    vacant_tags = sorted(store.get_unassigned_tags(), key=lambda t: t.mac)

    for item, tag in zip(unassigned_items, vacant_tags):
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
            repo_name=item.repo_name,
        )
        _push_display(oepl, tag, item.issue_number, item.title, item.status, assignee, cfg, item.repo_name)
        label = tag.alias or tag.mac[:12]
        print(f"  [sync] auto-assigned #{item.issue_number} → {label}")

    item_leftover = len(unassigned_items) - len(vacant_tags)
    if item_leftover > 0:
        print(f"[sync] {item_leftover} sprint item(s) have no tag to assign to")

    # Tags still vacant after auto-assignment get a train car display
    used_count = min(len(unassigned_items), len(vacant_tags))
    leftover_tags = vacant_tags[used_count:]
    if leftover_tags:
        steam_mac = max(t.mac for t in leftover_tags)
        for tag in leftover_tags:
            car_type = 0 if tag.mac == steam_mac else _car_type_for_mac(tag.mac)
            _push_unused(oepl, tag, cfg, car_type)
            label = tag.alias or tag.mac[:12]
            print(f"  [sync] no ticket available → {label} marked unused")

    return unassigned_items


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
            repo_name=item.repo_name,
        )
        _push_display(oepl, tag, item.issue_number, item.title, item.status, assignee, cfg, item.repo_name)
        print(f"  assigned #{item.issue_number} → tag {tag.alias or tag.mac[:12]}")


# ---------------------------------------------------------------------------
# NFC registration
# ---------------------------------------------------------------------------

_REGISTRATION_COLUMN = "Ready"


def do_register_nfc(store: Store, oepl: OEPLClient, cfg, force: bool = False):
    """Register NFC sticker UIDs for all e-ink tags that don't have one yet.

    1. Sets all tags to 15-second refresh so the prompt appears quickly.
    2. For each unregistered tag: pushes a 'tap me on READY' prompt to its
       display, then waits for a tap on the PN532 reader at 0x24.
    3. Saves NFC UID → e-ink MAC to the database.
    """
    # Refresh tag list from AP so the store is up to date, skipping the meta display
    for t in oepl.get_tags():
        mac = t.get("mac", "")
        if not mac or mac == cfg.meta_display_mac:
            continue
        hw_type = t.get("hwType", 0)
        w, h = oepl.get_tag_dimensions(hw_type)
        store.upsert_tag(mac, w, h, t.get("alias", ""))

    if force:
        n = store.clear_all_nfc_uids()
        print(f"[register] Cleared {n} existing NFC UID(s) — re-registering all.")

    tags_without_nfc = store.get_tags_without_nfc()
    if not tags_without_nfc:
        print("[register] All tags already have NFC UIDs — nothing to do.")
        return

    print(f"[register] Setting all tags to 40 s refresh …")
    oepl.set_fast_refresh_all(interval_s=40)

    # Find the registration reader from the topology
    topology = load_topology(cfg.sensor_topology_path)
    reg_sensor = next(
        (s for s in topology.sensors if s.status.lower() == _REGISTRATION_COLUMN.lower()),
        None,
    )
    if reg_sensor is None:
        print(f"[register] No '{_REGISTRATION_COLUMN}' sensor found in {cfg.sensor_topology_path}")
        return

    mux_addr, port = reg_sensor.mux_path[-1]
    print(f"[register] {len(tags_without_nfc)} tag(s) to register.")
    print(f"[register] Reader: mux@0x{mux_addr:02X}/port{port}  →  '{reg_sensor.status}'\n")

    # Push a neutral waiting screen to every unregistered tag up front so the
    # active 'tap me' prompt is unambiguous when it appears.
    print("[register] Pushing waiting screen to all unregistered tags …")
    for tag in tags_without_nfc:
        if tag.width and tag.height:
            img = render_waiting_prompt(
                tag.width, tag.height,
                tag_label=tag.alias or tag.mac[-5:],
                font_path=cfg.font_path,
                font_bold_path=cfg.font_bold_path,
            )
            oepl.push_image(tag.mac, img)
    print("[register] Waiting screens queued. Starting registration loop.\n")

    # Open the mux path to the registration reader and hold it open for the
    # duration of registration (we only need one reader at a time here).
    import smbus2 as _smbus2
    from nfc import _MuxGate
    mux_bus = _smbus2.SMBus(topology.i2c_bus)
    gates = {ma: _MuxGate(mux_bus, ma) for ma, _ in reg_sensor.mux_path}
    for ma, ch in reg_sensor.mux_path:
        gates[ma].select(ch)

    try:
        reader = PN532(bus=topology.i2c_bus, address=reg_sensor.address)
        reader.open()
    except Exception as e:
        print(f"[register] Cannot open PN532: {e}")
        for ma, _ in reg_sensor.mux_path:
            gates[ma].close_all()
        mux_bus.close()
        return

    try:
        for i, tag in enumerate(tags_without_nfc, 1):
            label = tag.alias or tag.mac
            assignment = store.get_assignment(tag.mac)
            ticket = (f"#{assignment.issue_number} {assignment.issue_title}"
                      if assignment else "(unassigned)")

            print(f"[{i}/{len(tags_without_nfc)}] {label}  |  {ticket}")

            # Push the registration prompt to this tag's display
            if tag.width and tag.height:
                img = render_registration_prompt(
                    tag.width, tag.height,
                    tag_label=tag.alias or tag.mac[-5:],
                    column=_REGISTRATION_COLUMN,
                    font_path=cfg.font_path,
                    font_bold_path=cfg.font_bold_path,
                )
                oepl.push_image(tag.mac, img)
                print(f"  Prompt pushed to display — waiting for tag check-in …")
            else:
                print(f"  (unknown dimensions — skipping display push)")

            print(f"  Tap the NFC sticker on this tag to the {_REGISTRATION_COLUMN} reader, "
                  f"or press Enter to skip.")

            import select as _select
            uid: Optional[str] = None
            last_seen: Optional[str] = None
            while uid is None:
                r, _, _ = _select.select([sys.stdin], [], [], 0.05)
                if r:
                    sys.stdin.readline()
                    break
                raw_uid = reader.read_passive_target(timeout=0.5)
                if raw_uid is None:
                    last_seen = None  # tag left the field — reset debounce
                    continue
                candidate = raw_uid.hex().upper()
                if candidate == last_seen:
                    continue  # same tap still in the field, ignore
                last_seen = candidate
                existing = store.get_tag_by_nfc(candidate)
                if existing is not None:
                    print(f"  UID {candidate} is already linked to "
                          f"{existing.alias or existing.mac} — try a different sticker.")
                    continue
                uid = candidate

            if uid:
                store.set_nfc_uid(tag.mac, uid)
                print(f"  ✓ Linked  NFC {uid}  →  {label}")
                if tag.width and tag.height:
                    img = render_registered_confirmation(
                        tag.width, tag.height,
                        tag_label=tag.alias or tag.mac[-5:],
                        font_path=cfg.font_path,
                        font_bold_path=cfg.font_bold_path,
                    )
                    oepl.push_image(tag.mac, img)
                print()
            else:
                print(f"  Skipped.\n")
    finally:
        reader.close()
        for ma, _ in reg_sensor.mux_path:
            gates[ma].close_all()
        mux_bus.close()


# ---------------------------------------------------------------------------
# Continuous service
# ---------------------------------------------------------------------------


def run_service(store: Store, oepl: OEPLClient, gh: GitHubClient, cfg):
    topology = load_topology(cfg.sensor_topology_path)
    nfc_reader = NfcReader(topology)
    nfc_reader.start()

    meta = gh.get_project_meta()
    do_sync(store, oepl, gh, meta, cfg, force=True)
    last_sync = time.monotonic()

    print(f"[run] Service started. Syncing every {cfg.sync_interval}s. Tap NFC stickers to update status.")

    try:
        while True:
            result = nfc_reader.poll()
            if result:
                uid, target_status = result
                if _handle_nfc_tap(uid, target_status, store, oepl, gh, meta, cfg):
                    meta = gh.get_project_meta()
                    do_sync(store, oepl, gh, meta, cfg)
                    last_sync = time.monotonic()

            if time.monotonic() - last_sync >= cfg.sync_interval:
                meta = gh.get_project_meta()
                do_sync(store, oepl, gh, meta, cfg)
                last_sync = time.monotonic()
    finally:
        nfc_reader.stop()


def _handle_nfc_tap(uid: str, target_status: str, store: Store, oepl: OEPLClient,
                    gh: GitHubClient, meta: ProjectMeta, cfg) -> bool:
    """Apply a column tap. Returns True if GitHub was updated (triggers a sync)."""
    tag = store.get_tag_by_nfc(uid)
    if tag is None:
        print(f"[nfc] Unknown UID {uid} — run 'register-nfc' to register it")
        return False

    assignment = store.get_assignment(tag.mac)
    if assignment is None:
        print(f"[nfc] Tag {tag.alias or tag.mac} has no ticket assigned")
        return False

    option = next(
        (o for o in meta.status_options if o.name.lower() == target_status.lower()),
        None,
    )
    if option is None:
        print(f"[nfc] '{target_status}' not found in project — "
              f"available: {[o.name for o in meta.status_options]}")
        return False

    print(f"[nfc] #{assignment.issue_number} '{assignment.status}' → '{option.name}'")

    if not gh.update_item_status(
        meta.project_id,
        assignment.github_item_id,
        meta.status_field_id,
        option.id,
    ):
        return False

    store.update_assignment_status(tag.mac, option.name, option.id)
    play_status_sound(option.name)
    _push_display(oepl, tag, assignment.issue_number, assignment.issue_title,
                  option.name, assignment.assignee, cfg, assignment.repo_name)
    return True


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


def _push_unused(oepl: OEPLClient, tag: TagRecord, cfg, car_type: int = 0):
    if tag.width == 0 or tag.height == 0:
        return
    img = render_train_car(tag.width, tag.height, car_type,
                           font_path=cfg.font_path, font_bold_path=cfg.font_bold_path)
    oepl.push_image(tag.mac, img)


def _push_display(oepl: OEPLClient, tag: TagRecord, issue_number: int, title: str, status: str, assignee: str, cfg, repo_name: str = ""):
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
        repo_name=repo_name,
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
    p_sync = sub.add_parser("sync", help="One-time sync: fetch sprint, refresh displays")
    p_sync.add_argument("--force", action="store_true",
                        help="Push all displays regardless of whether status changed")
    sub.add_parser("run", help="Run continuous service (NFC + periodic sync)")
    sub.add_parser("assign", help="Interactive: assign sprint tickets to tags")
    p_reg = sub.add_parser("register-nfc", help="Register NFC sticker UIDs for each tag")
    p_reg.add_argument("--force", action="store_true",
                       help="Clear all existing NFC UIDs and re-register from scratch")
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
        do_sync(store, oepl, gh, meta, cfg, force=args.force)

    elif args.cmd == "run":
        try:
            run_service(store, oepl, gh, cfg)
        except KeyboardInterrupt:
            print("\nStopped.")

    elif args.cmd == "assign":
        do_assign(store, oepl, gh, cfg)

    elif args.cmd == "register-nfc":
        do_register_nfc(store, oepl, cfg, force=args.force)

    elif args.cmd == "status":
        do_status(store)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

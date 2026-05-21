#!/usr/bin/env python3
"""Render sample ticket cards and optionally push to a real tag.

Usage:
    # Render all four status variants and save as PNGs
    python test_render.py

    # Push one card to a real tag (needs OEPL_AP_HOST in .env)
    python test_render.py --push --mac 00000197E5CB3B38 --width 296 --height 128
"""

import argparse
import os

from dotenv import load_dotenv

# Load .env if present, fall back to .env.example for local testing
load_dotenv(".env") or load_dotenv(".env.example")

from renderer import render_card

SAMPLES = [
    (42,  "Implement NFC scanning loop and background status service", "Needs Triage", "kyle"),
    (17,  "Design e-paper card layout for sprint view",                "In Progress", "alice"),
    (8,   "Set up Raspberry Pi service with systemd unit file",        "Done",        "bob"),
    (55,  "Wire up GitHub Projects v2 GraphQL mutation for status",    "In Review",   "kyle"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--push", action="store_true", help="Push cards to a real tag via OEPL AP")
    parser.add_argument("--mac", default="", help="Tag MAC address (required with --push)")
    parser.add_argument("--width", type=int, default=296, help="Tag width in pixels (default 296)")
    parser.add_argument("--height", type=int, default=128, help="Tag height in pixels (default 128)")
    parser.add_argument(
        "--font", default="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )
    parser.add_argument(
        "--font-bold", default="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    )
    args = parser.parse_args()

    for issue_num, title, status, assignee in SAMPLES:
        img = render_card(
            width=args.width,
            height=args.height,
            issue_number=issue_num,
            title=title,
            status=status,
            assignee=assignee,
            font_path=args.font,
            font_bold_path=args.font_bold,
        )
        filename = f"card_{status.lower().replace(' ', '_')}.png"
        img.save(filename)
        print(f"Saved {filename}  ({args.width}×{args.height})  [{status}]")

    if args.push:
        if not args.mac:
            print("ERROR: --mac is required with --push")
            return
        ap_host = os.environ.get("OEPL_AP_HOST")
        if not ap_host:
            print("ERROR: OEPL_AP_HOST not set")
            return

        from oepl import OEPLClient
        client = OEPLClient(ap_host)

        # Push the "In Progress" sample so you see the red footer live
        _, title, status, assignee = SAMPLES[1]
        img = render_card(args.width, args.height, 17, title, status, assignee,
                          args.font, args.font_bold)
        ok = client.push_image(args.mac, img)
        print(f"Push to {args.mac}: {'OK' if ok else 'FAILED'}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import argparse
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesHeaderParser
import json
import os
import re
import struct
import sys

TOC_HEADER_SIZE = 104
TOC_RECORD_SIZE = 218


def load_descmap(dir_path, cache):
    if dir_path in cache:
        return cache[dir_path]
    pce_path = os.path.join(dir_path, "descmap.pce")
    mapping = {}
    if os.path.exists(pce_path):
        with open(pce_path, "r", encoding="iso-8859-1", errors="replace") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 2:
                    logical, phys = parts[0], parts[1]
                    # Eudora Rescue replaces illegal Win32 filename chars with '_'
                    clean = re.sub(r'[?"/\\<>|*:]', "_", logical)
                    if clean.endswith((".", " ")):
                        clean = clean[:-1] + "_"
                    mapping[phys.lower()] = clean
    cache[dir_path] = mapping
    return mapping


def toc_to_tbird_relpath(mail_root, toc_path, descmap_cache):
    rel = os.path.relpath(toc_path, mail_root)
    parts = rel.split(os.sep)
    cur_dir = mail_root
    out_parts = []
    for i, part in enumerate(parts):
        dmap = load_descmap(cur_dir, descmap_cache)
        if i < len(parts) - 1:
            mapped = dmap.get(
                part.lower(), part[:-4] if part.lower().endswith(".fol") else part
            )
            out_parts.append(mapped + ".sbd")
            cur_dir = os.path.join(cur_dir, part)
        else:
            mbx_name = part[:-4] + ".mbx"
            mapped = dmap.get(mbx_name.lower(), part[:-4])
            out_parts.append(mapped)
    return os.path.join(*out_parts)


def extract_header(msg_default, msg_compat, name, is_subject=False):
    val = None
    try:
        val = msg_default.get(name)
    except Exception:
        if name.lower() == "from":
            val = "<failed@conversion.time>"
        else:
            raw_v = msg_compat.get(name)
            if raw_v is not None:
                try:
                    val = str(make_header(decode_header(raw_v)))
                except Exception:
                    val = str(raw_v)
    if val is None:
        return None
    s = str(val)
    s = re.sub(r"[\n\r\v\f\x1c\x1d\x1e\x85]", "", s)
    s = s.encode("utf-16", "surrogatepass").decode("utf-16", errors="replace")
    if not is_subject:
        s = s.encode("iso-8859-1", errors="replace").decode("iso-8859-1")
    return re.sub(r"[\r\n\t]+", " ", s).strip()


def parse_toc_cstr(raw_bytes):
    return raw_bytes.split(b"\x00", 1)[0].decode("iso-8859-1", errors="replace").strip()


def scan_toc_file(
    mail_root, toc_path, parser_default, parser_compat, descmap_cache, results
):
    # Skip Eudora address book TOC files (nndbase.toc)
    if os.path.basename(toc_path).lower() == "nndbase.toc":
        return

    file_size = os.path.getsize(toc_path)
    if (
        file_size < TOC_HEADER_SIZE
        or (file_size - TOC_HEADER_SIZE) % TOC_RECORD_SIZE != 0
    ):
        return

    mbx_path = toc_path[:-4] + ".mbx"
    has_mbx = os.path.exists(mbx_path)
    tbird_rel_path = toc_to_tbird_relpath(mail_root, toc_path, descmap_cache)
    rel_toc_path = os.path.relpath(toc_path, mail_root)

    with open(toc_path, "rb") as toc_fp:
        toc_header = toc_fp.read(TOC_HEADER_SIZE)
        if len(toc_header) < TOC_HEADER_SIZE:
            return

        mbx_fp = open(mbx_path, "rb") if has_mbx else None
        try:
            while True:
                rec = toc_fp.read(TOC_RECORD_SIZE)
                if len(rec) < TOC_RECORD_SIZE:
                    break

                # Offset 186 (0xBA): 2-byte integer for Eudora Label (0 = none, 1..7 = Label ID)
                label_id = struct.unpack_from("<H", rec, 186)[0]
                if label_id == 0:
                    continue

                msg_offset, msg_length = struct.unpack_from("<II", rec, 0)
                toc_date = parse_toc_cstr(rec[18:50])
                toc_who = parse_toc_cstr(rec[50:114])
                toc_subject = parse_toc_cstr(rec[114:178])

                subject = None
                date_str = None
                to_str = None
                from_str = None
                message_id = None

                if mbx_fp is not None:
                    mbx_fp.seek(msg_offset)
                    raw_msg = mbx_fp.read(msg_length)

                    # Skip the mbox "From ???@??? ..." delimiter line
                    from_line_date = None
                    if raw_msg.startswith(b"From "):
                        nl_idx = raw_msg.find(b"\n")
                        if nl_idx != -1:
                            from_line = (
                                raw_msg[:nl_idx]
                                .decode("iso-8859-1", errors="replace")
                                .strip()
                            )
                            parts = from_line.split(None, 2)
                            if len(parts) >= 3:
                                from_line_date = parts[2]
                            raw_msg = raw_msg[nl_idx + 1 :]

                    # Apply same Message-ID bracket cleanup as eudora2tbird.py
                    raw_msg = re.sub(
                        b"^(message-id:\\s*)<[\\[@<](.*?)\\]?>",
                        b"\\g<1><\\g<2>>",
                        raw_msg,
                        flags=re.I | re.M,
                    )
                    msg_def = parser_default.parsebytes(raw_msg)
                    msg_cmp = parser_compat.parsebytes(raw_msg)

                    subject = extract_header(msg_def, msg_cmp, "Subject", is_subject=True)
                    date_str = (
                        extract_header(msg_def, msg_cmp, "Date")
                        or from_line_date
                        or toc_date
                    )
                    to_str = extract_header(msg_def, msg_cmp, "To")
                    from_str = extract_header(msg_def, msg_cmp, "From")
                    message_id = extract_header(msg_def, msg_cmp, "Message-ID")
                else:
                    subject = toc_subject
                    date_str = toc_date
                    from_str = toc_who

                entry = {
                    "toc_path": toc_path,
                    "rel_toc_path": rel_toc_path,
                    "tbird_rel_path": tbird_rel_path,
                    "label_id": label_id,
                    "subject": subject,
                    "date": date_str,
                    "to": to_str,
                    "from": from_str,
                    "message_id": message_id,
                }
                results.append(entry)

                print(f"Mailbox: {toc_path}")
                print(f"  Label ID: {label_id}")
                print(f"  Subject:  {subject if subject is not None else '<None>'}")
                print(f"  Date:     {date_str if date_str is not None else '<None>'}")
                print(f"  To:       {to_str if to_str is not None else '<None>'}")
                print(f"  From:     {from_str if from_str is not None else '<None>'}")
                print()
        finally:
            if mbx_fp is not None:
                mbx_fp.close()


def main():
    parser = argparse.ArgumentParser(
        description="Scan Eudora .toc files recursively, print labeled messages, and save them to JSON."
    )
    parser.add_argument(
        "mail_dir",
        nargs="?",
        default="Mail",
        help="Path to the Eudora Mail folder (default: Mail)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="labeled_messages.json",
        help="Output JSON file path (default: labeled_messages.json)",
    )
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    parser_default = BytesHeaderParser(policy=policy.default)
    parser_compat = BytesHeaderParser(policy=policy.compat32)
    descmap_cache = {}
    results = []

    for root, dirs, files in os.walk(args.mail_dir):
        dirs.sort()
        for fname in sorted(files):
            if fname.lower().endswith(".toc"):
                toc_path = os.path.join(root, fname)
                scan_toc_file(
                    args.mail_dir,
                    toc_path,
                    parser_default,
                    parser_compat,
                    descmap_cache,
                    results,
                )

    with open(args.output, "w", encoding="utf-8") as out_fp:
        json.dump(results, out_fp, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        pass

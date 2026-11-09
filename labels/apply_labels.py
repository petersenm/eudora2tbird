#!/usr/bin/env python3
import argparse
from collections import defaultdict
from datetime import datetime
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesHeaderParser
from email.utils import parsedate_to_datetime
import json
import os
import re
import sys
import tempfile

try:
    from dateutil.parser import parse as _dateutil_parse
except ImportError:
    _dateutil_parse = None


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


def norm_subj(val):
    if not val:
        return ""
    return re.sub(r"\s+", " ", str(val)).strip()


def norm_addr(val):
    if not val:
        return ""
    s = str(val).replace('"', "")
    return re.sub(r"\s+", " ", s).strip()


def norm_date(val):
    if not val:
        return ""
    s = re.sub(r"\s+", " ", str(val)).strip()
    if _dateutil_parse is not None:
        try:
            dt = _dateutil_parse(s)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    try:
        dt = parsedate_to_datetime(s)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    for fmt in ("%a %b %d %H:%M:%S %Y", "%I:%M %p %m/%d/%Y", "%I:%M %p %m/%d/%Y %z"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return s


def make_match_key(subject, date_str, to_str, from_str):
    return (
        norm_subj(subject),
        norm_date(date_str),
        norm_addr(to_str),
        norm_addr(from_str),
    )


def add_important_tag_to_headers(header_lines):
    """
    Ensure the message headers have Thunderbird's 'Important' tag ($label1):
    - Sets X-Mozilla-Keys: $label1 (or adds $label1 to existing X-Mozilla-Keys)
    - Updates X-Mozilla-Status2 label bits (0x0E000000) to 0x02000000 (Label 1 = Important)
    Returns (new_header_lines, modified_bool).
    """
    modified = False
    new_lines = []
    has_mozilla_keys = False
    status2_idx = None
    status1_idx = None

    for line in header_lines:
        if re.match(b"^X-Mozilla-Status:\\s*", line, flags=re.I):
            status1_idx = len(new_lines)
            new_lines.append(line)
        elif re.match(b"^X-Mozilla-Status2:\\s*", line, flags=re.I):
            m = re.match(
                b"^(X-Mozilla-Status2:\\s*)([0-9a-fA-F]+)(.*)",
                line,
                flags=re.I | re.S,
            )
            if m:
                prefix, hex_val, suffix = m.groups()
                val = int(hex_val, 16)
                # Clear 0x0E000000 label bits and set 0x02000000 (Label 1 / Important)
                new_val = (val & ~0x0E000000) | 0x02000000
                new_hex = f"{new_val:08X}".encode("ascii")
                new_line = prefix + new_hex + suffix
                if new_line != line:
                    modified = True
                status2_idx = len(new_lines)
                new_lines.append(new_line)
            else:
                status2_idx = len(new_lines)
                new_lines.append(line)
        elif re.match(b"^X-Mozilla-Keys:", line, flags=re.I):
            has_mozilla_keys = True
            eol = b"\r\n" if line.endswith(b"\r\n") else (b"\n" if line.endswith(b"\n") else b"")
            body = line[: len(line) - len(eol)] if eol else line
            _, _, existing_keys = body.partition(b":")
            tokens = existing_keys.decode("ascii", errors="replace").split()
            if "$label1" not in tokens:
                tokens.insert(0, "$label1")
                new_line = (
                    b"X-Mozilla-Keys: " + " ".join(tokens).encode("ascii") + eol
                )
                new_lines.append(new_line)
                modified = True
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if not has_mozilla_keys:
        # Use the same line ending style as surrounding headers
        sample_eol = b"\n"
        if new_lines and new_lines[0].endswith(b"\r\n"):
            sample_eol = b"\r\n"
        key_line = b"X-Mozilla-Keys: $label1" + sample_eol
        insert_pos = (
            status2_idx + 1
            if status2_idx is not None
            else (status1_idx + 1 if status1_idx is not None else 0)
        )
        new_lines.insert(insert_pos, key_line)
        modified = True

    return new_lines, modified


def process_mailbox(
    tb_path,
    target_entries,
    parser_default,
    parser_compat,
    dry_run=False,
    progress_cb=None,
):
    """
    Scan a Thunderbird mailbox file, match messages against target_entries,
    and add the 'Important' tag ($label1) to matched messages.
    Returns (matched_count, modified_msg_count, unmatched_list).
    """
    # Map match_key -> list of indices in target_entries
    key_to_indices = defaultdict(list)
    for idx, entry in enumerate(target_entries):
        k = make_match_key(
            entry.get("subject"),
            entry.get("date"),
            entry.get("to"),
            entry.get("from"),
        )
        key_to_indices[k].append(idx)

    matched_indices = set()
    modified_msg_count = 0
    any_modified = False
    scanned_mbox_msgs = 0

    dir_name = os.path.dirname(tb_path) or "."
    tmp_fd, tmp_path = (
        (None, None)
        if dry_run
        else tempfile.mkstemp(dir=dir_name, prefix=".tmp_tbird_")
    )

    try:
        out_fp = os.fdopen(tmp_fd, "wb") if not dry_run else None
        with open(tb_path, "rb") as in_fp:
            from_line = None
            header_lines = []
            in_headers = False

            def flush_current_headers():
                nonlocal any_modified, modified_msg_count, scanned_mbox_msgs, header_lines
                if from_line is None:
                    return
                scanned_mbox_msgs += 1
                if out_fp is not None:
                    out_fp.write(from_line)
                if header_lines:
                    fl_str = from_line.decode("iso-8859-1", errors="replace").strip()
                    parts = fl_str.split(None, 2)
                    from_date = parts[2] if len(parts) >= 3 else None

                    raw_h = b"".join(header_lines)
                    m_def = parser_default.parsebytes(raw_h)
                    m_cmp = parser_compat.parsebytes(raw_h)

                    subj = extract_header(m_def, m_cmp, "Subject", is_subject=True)
                    dt = extract_header(m_def, m_cmp, "Date") or from_date
                    to_v = extract_header(m_def, m_cmp, "To")
                    from_v = extract_header(m_def, m_cmp, "From")

                    mk = make_match_key(subj, dt, to_v, from_v)
                    if mk in key_to_indices:
                        prev_cnt = len(matched_indices)
                        for idx in key_to_indices[mk]:
                            matched_indices.add(idx)
                        header_lines, mod = add_important_tag_to_headers(header_lines)
                        if mod:
                            any_modified = True
                            modified_msg_count += 1
                        if progress_cb is not None and len(matched_indices) != prev_cnt:
                            progress_cb(len(matched_indices), scanned_mbox_msgs)
                    elif progress_cb is not None and scanned_mbox_msgs % 200 == 0:
                        progress_cb(len(matched_indices), scanned_mbox_msgs)

                    if out_fp is not None:
                        out_fp.writelines(header_lines)

            for line in in_fp:
                if line.startswith(b"From - "):
                    if in_headers:
                        flush_current_headers()
                    from_line = line
                    header_lines = []
                    in_headers = True
                elif in_headers:
                    if line in (b"\n", b"\r\n"):
                        flush_current_headers()
                        from_line = None
                        header_lines = []
                        in_headers = False
                        if out_fp is not None:
                            out_fp.write(line)
                    else:
                        header_lines.append(line)
                else:
                    if out_fp is not None:
                        out_fp.write(line)

            if in_headers and from_line is not None:
                flush_current_headers()

        if out_fp is not None:
            out_fp.close()
            out_fp = None

        if not dry_run:
            if any_modified:
                orig_mode = os.stat(tb_path).st_mode
                os.chmod(tmp_path, orig_mode)
                os.replace(tmp_path, tmp_path_target := tb_path)
                tmp_path = None
                # Remove stale .msf index file if present so Thunderbird re-indexes the updated mbox
                msf_path = tb_path + ".msf"
                if os.path.exists(msf_path):
                    os.remove(msf_path)
            else:
                os.remove(tmp_path)
                tmp_path = None
    finally:
        if not dry_run and tmp_path is not None and os.path.exists(tmp_path):
            os.remove(tmp_path)

    unmatched = [
        entry
        for idx, entry in enumerate(target_entries)
        if idx not in matched_indices
    ]
    return len(matched_indices), modified_msg_count, unmatched


def main():
    parser = argparse.ArgumentParser(
        description="Read labeled messages JSON and apply the 'Important' tag ($label1) in a Thunderbird mail directory."
    )
    parser.add_argument(
        "-i",
        "--input",
        default="labeled_messages.json",
        help="Input JSON file from scan_labels.py (default: labeled_messages.json)",
    )
    parser.add_argument(
        "-t",
        "--tbird-dir",
        default="Local Folders",
        help="Thunderbird mail directory (default: 'Local Folders')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only check matching without modifying Thunderbird mailbox files",
    )
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    with open(args.input, "r", encoding="utf-8") as fp:
        entries = json.load(fp)

    by_mailbox = defaultdict(list)
    for entry in entries:
        by_mailbox[entry["tbird_rel_path"]].append(entry)

    parser_default = BytesHeaderParser(policy=policy.default)
    parser_compat = BytesHeaderParser(policy=policy.compat32)

    missing_mailboxes = {}
    unmatched_in_existing = []
    total_matched = 0
    total_modified = 0
    existing_mailbox_count = 0

    total_entries = len(entries)
    total_mailboxes = len(by_mailbox)
    processed_entries = 0

    def show_status(mbx_idx, rel_path, in_mbx_done=0, in_mbx_total=0):
        current_done = processed_entries + in_mbx_done
        pct = (current_done * 100.0 / total_entries) if total_entries else 100.0
        short_mbx = rel_path if len(rel_path) <= 38 else "..." + rel_path[-35:]
        msg = (
            f"\r[{current_done}/{total_entries} msgs ({pct:5.1f}%) | "
            f"{mbx_idx}/{total_mailboxes} mbx] {short_mbx:<38}"
        )
        sys.stderr.write(msg)
        sys.stderr.flush()

    for mbx_idx, rel_path in enumerate(sorted(by_mailbox.keys()), start=1):
        target_list = by_mailbox[rel_path]
        tb_path = os.path.join(args.tbird_dir, os.path.normpath(rel_path))
        show_status(mbx_idx, rel_path, 0, len(target_list))

        if not os.path.exists(tb_path) or os.path.isdir(tb_path):
            missing_mailboxes[rel_path] = target_list
            processed_entries += len(target_list)
            show_status(mbx_idx, rel_path, 0, len(target_list))
            continue

        existing_mailbox_count += 1
        matched_cnt, mod_cnt, unmatched = process_mailbox(
            tb_path,
            target_list,
            parser_default,
            parser_compat,
            dry_run=args.dry_run,
            progress_cb=lambda m_cnt, _s_cnt, idx=mbx_idx, rp=rel_path, tot=len(
                target_list
            ): show_status(idx, rp, m_cnt, tot),
        )
        total_matched += matched_cnt
        total_modified += mod_cnt
        unmatched_in_existing.extend(unmatched)
        processed_entries += len(target_list)
        show_status(mbx_idx, rel_path, 0, len(target_list))

    sys.stderr.write("\n\n")
    sys.stderr.flush()

    total_missing_mbx_msgs = sum(len(v) for v in missing_mailboxes.values())

    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"Total labeled messages in JSON:                  {len(entries)}")
    print(f"Mailboxes with labeled messages present:         {existing_mailbox_count}")
    print(f"Messages matched in existing mailboxes:          {total_matched}")
    print(f"  - Newly modified (tag added/updated):          {total_modified}")
    print(f"  - Already had 'Important' tag (unchanged):     {total_matched - total_modified}")
    print(
        f"Messages skipped (mailbox not present):          {total_missing_mbx_msgs} (across {len(missing_mailboxes)} missing mailboxes)"
    )
    print(
        f"Messages not found/matched in existing mailbox:  {len(unmatched_in_existing)}"
    )
    print()

    print("=" * 72)
    print(
        f"1. MISSING MAILBOXES ({len(missing_mailboxes)} mailboxes, {total_missing_mbx_msgs} labeled messages)"
    )
    print("=" * 72)
    if not missing_mailboxes:
        print("  None")
    else:
        for rel_path, msg_list in sorted(missing_mailboxes.items()):
            toc_rel = msg_list[0].get("rel_toc_path", "")
            print(
                f"  Missing Mailbox: {rel_path} (from {toc_rel}) -- {len(msg_list)} labeled message(s)"
            )
    print()

    print("=" * 72)
    print(
        f"2. UNMATCHED MESSAGES IN EXISTING MAILBOXES ({len(unmatched_in_existing)} messages)"
    )
    print("=" * 72)
    if not unmatched_in_existing:
        print("  None")
    else:
        for entry in unmatched_in_existing:
            print(f"  Mailbox:  {entry.get('tbird_rel_path')}")
            print(f"  Label ID: {entry.get('label_id')}")
            print(f"  Subject:  {entry.get('subject') or '<None>'}")
            print(f"  Date:     {entry.get('date') or '<None>'}")
            print(f"  To:       {entry.get('to') or '<None>'}")
            print(f"  From:     {entry.get('from') or '<None>'}")
            print()


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        pass

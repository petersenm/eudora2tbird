Eudora to Thunderbird Label Migration Scripts
=============================================

1. Scan Eudora TOC Files for Labeled Messages (scan_labels.py)
--------------------------------------------------------------
Scans all Eudora .toc/.mbx files recursively in the Mail directory, prints
every message that has a Eudora label associated with it, and writes the
results to a JSON file (default: labeled_messages.json).

Recommended command lines:

  # Run and print all labeled messages to terminal while saving labeled_messages.json:
  python3 scan_labels.py Mail -o labeled_messages.json

  # Run quietly (redirecting printed message list to a log file):
  python3 scan_labels.py Mail -o labeled_messages.json > scan_labels.log


2. Apply 'Important' Tag to Thunderbird Mailboxes (apply_labels.py)
-------------------------------------------------------------------
Reads labeled_messages.json, matches the messages in the converted Thunderbird
mail directory, adds the 'Important' tag ($label1), and outputs a report of
summary counts, missing mailboxes, and any unmatched messages.

Note: Make sure Thunderbird is closed before running apply_labels.py.

Recommended command lines (Linux):

  # Dry run (test matching without modifying any mailbox files):
  python3 apply_labels.py -i labeled_messages.json -t "Local Folders" --dry-run

  # Apply tags in-place and print report to terminal:
  python3 apply_labels.py -i labeled_messages.json -t "Local Folders"

  # Apply tags in-place and save the report to a file (progress still shows in terminal):
  python3 apply_labels.py -i labeled_messages.json -t "Local Folders" > apply_labels_report.txt

Recommended command lines (Windows 11 Command Prompt / PowerShell):

  # Dry run:
  python apply_labels.py -i labeled_messages.json -t "C:\Path\To\Local Folders" --dry-run

  # Apply tags in-place:
  python apply_labels.py -i labeled_messages.json -t "C:\Path\To\Local Folders"

  # Apply tags in-place and save the report to a file:
  python apply_labels.py -i labeled_messages.json -t "C:\Path\To\Local Folders" > apply_labels_report.txt

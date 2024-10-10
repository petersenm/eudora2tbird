# eudora2tbird
Eudora to Thunderbird Conversion Script

This utility, in conjunction with the Eudora Rescue program by Qwerky,
converts Eudora email mailboxes and folders to Thunderbird format.  It
requires a Windows box and Python.  Note: the Python
code has only been tested on a Linux platform (Ubuntu 22.04) but in
principal, should run anywhere (I think...).

## Setup
Create Python 3 venv

Install these packages:
- python-dateutil
- python-magic

## Usage
These instructions assume the Eudora mail directory is called Mail

1.  First, backup your Eudora email.

2.  Create a blank directory for the resuced email:  Mail.rescue

3.  From Windows, run the Eudora Rescue script with the following options
    (modified accordingly for the directory names)

    EUDRESCU.EXE Mail -o=Mail.rescue -x=.mbx -f- -g-

    This massages and fixes the Eudora mailboxes for the next steps.

4.  Create a blank directory for the converted email:  Mail.tbird

5.  Run the eudora2tbird script in the venv created above.

    ./eudora2tbird Mail.rescue/ Mail.tbird/
    
    This will automatically traverse the rescued email and create the 
    thunderbird equivalent mailboxes and folder structures.

6.  Move the mailboxes and folders in Mail.tbird into your Thunderbird
    profile's Mail/Local Folders directory

7.  Open in Thunderbird.  Large mailboxes may take some time to open in 
    Thunderbird as it creates the inital index files.

## Disclaimer
- BACKUP YOUR EMAIL!  Make a complete backup before attempting to run any of
  these scripts.
- Caveat emptor.  No guarantees or warranties are made that these scripts
  will do anything useful, nor that they won't corrupt your email.  Did I
  mention backing up your email?
- I'm using these to convert my email.  Hopefully you find them useful, too. 
  But please do your due diligence and test, test, test before relying on
  them.  Also, did I mention backing up your email?
- Eudora Rescue is simply provided here as a convenience.  Please see the
  [Eudora Rescue](http://qwerky.50webs.com/eudorarescue/) webpage
  for instructions, license, support, etc. for that utility.

## Acknowledgments
- Many thanks to Qwerky, the author of the Eudora Rescue program, for building a great
  utility to do much of the initial heavy lifting.
- All the various contributors to Stack Overflow for the pieces of python
  code I borrowed

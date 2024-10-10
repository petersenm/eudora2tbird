import email
from email import policy
import re
import argparse
import codecs
from datetime import date
from dateutil.parser import parse as dateParse
import magic
import unicodedata

mime = magic.Magic(mime=True)

ESC = '\x1b'
RED     = ESC + '[31m'
GREEN   = ESC + '[32m'
YELLOW  = ESC + '[33m'
BLUE    = ESC + '[34m'
MAGENTA = ESC + '[35m'
CYAN    = ESC + '[36m'
WHITE   = ESC + '[37m'
DEFAULT = ESC + '[39m'

cmdParser = argparse.ArgumentParser()
cmdParser.add_argument("-m", "--mbox", help="Source (Eudora Rescued) mailbox file", required=True)
cmdParser.add_argument("-o", "--outmbox", help="Destination (Re-attached/embedded) mailbox file", required=True)
cmdParser.add_argument("-a", "--attach", help="Attachment directory")
cmdParser.add_argument("-e", "--embed", help="Embedded directory")
args = cmdParser.parse_args()


class MboxReader:
    def __init__(self, filename):
        self.dateHeaderFallback = None
        self.handle = open(filename, 'rb')
        assert self.handle.readline().startswith(b'From ???@??? ')

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.handle.close()

    def __iter__(self):
        return iter(self.__next__())

    def __next__(self):
        lines = []
        self.dateHeaderFallback = None
        while True:
            lineOrig = self.handle.readline()
            line = lineOrig
            # Remove wrapping [] from Message-ID header since that causes exception in email parser
            line = re.sub(b'^(message-id:\s*)<[\[@<](.*?)\]?>', b'\g<1><\g<2>>', line, flags=re.I)
            # Remove multipart/... from content-type if not already removed by Eudora Rescue
            line = re.sub(b'^(content-type:\s*)multipart/\w+;(.*)', b'\g<1>\g<2>', line, flags=re.I)
            if(line != lineOrig):
                print(MAGENTA + "Line modified:\n    " + str(lineOrig) + "\n    " + str(line) + DEFAULT)
            if(re.match(b'date:', line, re.IGNORECASE)):
                # Used when email.message cannot extract the date header correctly (probably due to malformed headers before it)
                dateExtract = re.match(b'date:(.*)', line, re.IGNORECASE)
                self.dateHeaderFallback = dateExtract.group(1)
            # Remove surrogate pairs (https://unicodebook.readthedocs.io/unicode_encodings.html#surrogates)
#            if re.search(b"[\xD8-\xDF][\x00-\xFF]", line) is not None:
#                content = re.sub(b"[\xD8-\xDF][\x00-\xFF]", b"\xFF\xFD", content, flags = re.MULTILINE)
#                print(line)
#                print(MAGENTA + "Removed surrogate pair(s)" + DEFAULT)
            if line == b'' or line.startswith(b'From ???@??? '):
                yield email.message_from_bytes(b''.join(lines), policy=policy.default)
                if line == b'':
                    break
                lines = []
                continue
            lines.append(line)


mboxFile = args.mbox
outFile = args.outmbox
open(outFile, 'w').close()

try:
    mailbox = MboxReader(mboxFile)
except:
    quit()

with mailbox as mbox:
    for message in mbox:
        xhtml = None     # Reset to None so we start fresh on each new message.  Not None means we do something different
        xflowed = None

        msgDateString = message.get('date')
        if(None == msgDateString):
            msgDateString = mbox.dateHeaderFallback
            print(MAGENTA + "Falling back to date: " + str(msgDateString) + DEFAULT)
        try:
            msgDate = dateParse(msgDateString)
        except:
            msgDate = dateParse("1 Jan 1900 00:00:00")
            print(MAGENTA + "Invalid date: " + str(msgDateString) + DEFAULT)
            
        for header in message.keys():
            try:
                msgHeader = message.get(header)
                if(msgHeader is not None):
                    # Sanitize header (remove line boundaries)
                    #   https://docs.python.org/3/library/stdtypes.html#str.splitlines
                    msgHeader = re.sub(r'[\n\r\v\f\x1c\x1d\x1e\x85]', '', msgHeader)

                    # Remove surrogate pairs
                    #   https://unicodebook.readthedocs.io/unicode_encodings.html#surrogates
                    #   https://stackoverflow.com/questions/38147259/how-can-i-convert-surrogate-pairs-to-normal-string-in-python
                    msgHeader = msgHeader.encode('utf-16', 'surrogatepass').decode('utf-16')
                    
                    if('subject' != header.lower()):
                        # Sanitize header (remove non-ASCII characters)
                        msgHeader = msgHeader.encode('iso-8859-1', errors="replace").decode('iso-8859-1')
#                        msgHeader = msgHeader.encode('utf-8', errors="replace").decode('utf-8')

                    message.replace_header(header, msgHeader)
                msgHeader = message.get(header)
            except:
                if('from' == header.lower()):
                    print(MAGENTA + "Failed with header: " + header + DEFAULT)
                    message.replace_header(header, "<failed@conversion.time>")

        try:
            msgFrom = message.get('from')
            if(None == msgFrom):
                msgFrom = '<None>'
        except:
            msgFrom = '<Error>'

#        print(msgFrom)
#        print(str(msgDate))
#        print(message.get('subject') or '<None>')

        print(msgFrom + " -- " + str(msgDate) + " -- " + (message.get('subject') or '<None>'))


        charset = message.get_content_charset()
        if charset is None:
            charset = 'utf-8'
        # Validte the charset string
        try:
            codecs.lookup(charset)
        except:
            # Doesn't exist, so default to UTF-8
            print(MAGENTA + "Invalid charset: " + charset + DEFAULT)
            message.replace_header('content-type', message.get_content_type() + '; charset="utf-8"')
            charset = message.get_content_charset()
        

        # Do From_ quoting for MBOXRD format.  This option does not seem to work in Eudora Rescue.
        content = re.sub(r"^From ", " From ", message.get_content(), flags = re.MULTILINE)

#        print(charset)
#        print(content)

        content = content.encode(encoding=charset, errors="replace")  # Fix any erroneous chars
        content = content.decode(encoding=charset)

        message.set_content(content, subtype=message.get_content_subtype(), charset=charset)

        # Detect unicode and trasform accordingly
#        content = message.get_content().encode(encoding='iso-8859-1') # at this point has the original bytes preserved
        content = message.get_content().encode(encoding=charset) # at this point has the original bytes preserved
        # https://lemire.me/blog/2018/05/09/how-quickly-can-you-check-that-a-string-is-valid-unicode-utf-8/
        if re.search(b"[\xC2-\xDF][\x80-\xBF]|"
                     b"\xE0[\xA0-\xBF][\x80-\xBF]|"
                     b"[\xE1-\xEC][\x80-\xBF][\x80-\xBF]|"
                     b"\xED[\x80-\x9F][\x80-\xBF]|"
                     b"[\xEE-\xEF][\x80-\xBF][\x80-\xBF]|"
                     b"\xF0[\x90-\xBF][\x80-\xBF][\x80-\xBF]|"
                     b"[\xF1-\xF3][\x80-\xBF][\x80-\xBF][\x80-\xBF]|"
                     b"\xF4[\x80-\x8F][\x80-\xBF][\x80-\xBF]", content) is not None:
            print(BLUE + "Unicode text found" + DEFAULT)
            message.set_content(content.decode("utf-8", errors="replace"), subtype=message.get_content_subtype())  # change to unicode

        content = message.get_content()

        body = content
#        body = message.get_body().as_bytes().decode(encoding='iso-8859-1')

        xhtml = next(iter(re.findall(r"<x-html>(.*?)</x-html>", content, re.DOTALL)), None)
        xflowed = next(iter(re.findall(r"<x-flowed>(.*?)</x-flowed>", content, re.DOTALL)), None)
#        print(BLUE + str(xhtml) + DEFAULT)
#        print(MAGENTA + str(xflowed) + DEFAULT)

        if xhtml is not None:
            message.set_content(xhtml, subtype='html')
#            print(message['content-type'])

        if(body.count("\nEmbedded Content: ") > 0):
            contentIds = re.findall(r'"cid:(.+?)"', body)
            contentIds = list(dict.fromkeys(contentIds))  # remove duplicates while preserving order
#            print(contentIds)
            embeddedNames = re.findall(r'\nEmbedded Content: (.+):', body)
#            print(embeddedNames)
            if(len(contentIds) > len(embeddedNames)):
                print(YELLOW + "More ContentIDs than Embedded Objects" + DEFAULT)
            if(len(contentIds) < len(embeddedNames)):
                print(YELLOW + "More Embedded Objects than ContentIDs" + DEFAULT)
            for contentId, embeddedName in zip(contentIds, embeddedNames):
                print("Embedding... " + embeddedName + " (" + contentId + ")")
                embeddedPath = args.embed + '/' + embeddedName
                try:
                    mime_type = mime.from_file(embeddedPath)
                    mime_type_split = mime_type.split('/')
                    with open(embeddedPath, 'rb') as fp:
                        embedData = fp.read()
                    message.add_related(embedData, maintype=mime_type_split[0], subtype=mime_type_split[1], filename=embeddedName, disposition="inline", cid="<"+contentId+">")
                except:
                    print(RED + "Error adding embedded file " + embeddedName + DEFAULT)

        if xflowed is not None:
            message.add_alternative(xflowed, subtype="plain")
            
        if(body.count("\nAttachment Converted: ") > 0):
            for attachment in re.findall(r'\nAttachment Converted: \"(.+)\"', body):
                attachmentName = re.split(r'\\', attachment)[-1]
                print("Attaching... " + attachmentName)
                attachmentPath = args.attach + '/' + attachmentName
                try:
                    mime_type = mime.from_file(attachmentPath)
                    mime_type_split = mime_type.split('/')
                    with open(attachmentPath, 'rb') as fp:
                        attachData = fp.read()
                    message.add_attachment(attachData, maintype=mime_type_split[0], subtype=mime_type_split[1], filename=attachmentName)
                except:
                    print(RED + "Error adding attachment " + attachmentName + DEFAULT)

        with open(outFile, 'ab') as fp:
            fp.write(msgDate.strftime("From - %a %b %d %H:%M:%S %Y\n").encode('utf-8'))  # Recreate the "From - <date>" divider line since it was lost in scanning the mailbox
            fp.write(message.as_bytes())

        print()

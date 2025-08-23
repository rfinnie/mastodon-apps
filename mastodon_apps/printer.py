# SPDX-FileComment: Printer Mastodon bot
# SPDX-FileCopyrightText: Copyright (C) 2023 Ryan Finnie
# SPDX-License-Identifier: MPL-2.0

import io
import logging
import socket
import sys
import textwrap

from bs4 import BeautifulSoup
import dateutil.parser
from PIL import Image, ImageOps
from unidecode import unidecode

try:
    from urlextract import URLExtract
except ImportError as e:
    URLExtract = e
try:
    import blurhash
except ImportError as e:
    blurhash = e

from .mastodon import BaseMastodon


class Printer(BaseMastodon):
    name = "printer"
    calling_file = __file__

    def setup(self):
        urlextract_logger = logging.getLogger("urlextract")
        urlextract_logger.info = urlextract_logger.debug
        if isinstance(URLExtract, ImportError):
            self.url_extractor = None
        else:
            self.url_extractor = URLExtract(cache_dns=False)

    def tobin(self, data):
        if not isinstance(data, (list, tuple)):
            data = [data]
        out = b""
        for part in data:
            if isinstance(part, (bytes, bytearray)):
                out += part
            else:
                out += self.transliterate(part)
        return out

    def transliterate(self, string):
        out = b""
        for char in string:
            try:
                out += char.encode("cp437")
            except UnicodeEncodeError:
                out += unidecode(char, "replace").encode("cp437", "replace")
        return out

    def process_mention(self, mention):
        if self.config.get("mode", "mentions") != "mentions":
            return
        status = mention["status"]
        self.print_status(status)

    def process_update(self, status):
        if self.config.get("mode", "mentions") != "updates":
            return
        if status["reblog"]:
            return
        self.print_status(status)

    def extract_urls(self, line):
        if not self.url_extractor:
            if line.startswith("https://"):
                return [line.strip()]
            return []
        return [
            url for url in self.url_extractor.find_urls(line, check_dns=False, with_schema_only=True) if url.startswith("https://")
        ]

    def print_status(self, status):
        self.logger.info(
            "Received mention from {} (@{})".format(
                status["account"]["display_name"],
                status["account"]["acct"],
            )
        )
        self.logger.info("Post: {}".format(status["url"]))
        out = []
        out.extend([b"\x1b!\x38", self.server["title"], b"\x1b!\x00\n\n"])
        out.extend(
            [
                "From: ",
                b"\x1b!\x08",
                status["account"]["display_name"],
                b"\x1b!\x00",
                " (@{})\n".format(status["account"]["acct"]),
            ]
        )
        for other_mention in status["mentions"]:
            if other_mention["acct"] == self.me["acct"]:
                continue
            if other_mention["acct"] == status["account"]["acct"]:
                continue
            out.extend(
                [
                    "Mentions: ",
                    b"\x1b!\x08",
                    "@" + other_mention["acct"],
                    b"\x1b!\x00",
                ]
            )
            if other_mention["id"] == status["in_reply_to_account_id"]:
                out.append(" (reply)")
            out.append("\n")
        out.append("Date: {}\n".format(dateutil.parser.parse(status["created_at"]).strftime("%c")))
        if status["spoiler_text"]:
            out.append("Spoiler: " + status["spoiler_text"])
        out.append(b"\n")
        lines = []
        content = status["content"]
        soup = BeautifulSoup(content.replace("\n", " "), features="lxml")
        qrs = []
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for para in soup.find_all("p"):
            para = para.get_text().strip()
            qrs.extend(self.extract_urls(para))
            self.logger.debug(repr(para))
            for line in para.split("\n"):
                lines.extend(textwrap.wrap(line, width=48))
            lines.append("")
        lines = lines[:50]
        for line in lines:
            self.logger.debug(repr(line))
            out.append(line + "\n")

        attachment_limit = self.config.get("attachment_limit", 2)
        for attachment in status["media_attachments"][:attachment_limit]:
            out_att = self.process_attachment(attachment)
            if out_att:
                out.extend(out_att)
                out.append(b"\n")

        qr_limit = self.config.get("qr_limit", 1)
        for url in qrs[:qr_limit]:
            out.append(self.get_qrcode_bin(url))
            out.append(b"\n\n")

        out.append(b"\x1b@")  # Reset
        out.append(b"\x1dVB\x96")  # Paper cut, 5 lines bottom margin
        out = self.tobin(out)

        if self.config.get("printer_device"):
            with open(self.config["printer_device"], "wb") as f:
                f.write(out)
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((self.config["printer_host"], self.config.get("printer_port", 9100)))
            sock.send(out)
            sock.close()
        self.logger.info("Print sent to printer, {} bytes".format(len(out)))

        if self.config.get("favorite_printed", True) and (not status["in_reply_to_id"]):
            self.api(
                "{}/api/v1/statuses/{}/favourite".format(self.url_base, status["id"]),
                method="POST",
            )
            self.logger.info("Favorited {}".format(status["url"]))

    def render_image(self, im):
        if im.width > 256 or im.height > 256:
            im.thumbnail((256, 256), Image.LANCZOS)
        bitmap = im.convert("L")  # greyscale
        bitmap = ImageOps.invert(bitmap).convert("1")  # invert + bitmap

        (width, height) = im.size
        width_bytes = (int)((width + 7) / 8)
        header = b"\x1dv0\x03" + bytearray(
            [
                width_bytes % 256,
                width_bytes >> 8,
                height % 256,
                height >> 8,
            ]
        )
        return header + bitmap.tobytes()

    def process_attachment(self, attachment):
        out = []
        if attachment["type"] != "image":
            return
        im = None
        try:
            r = self.session.get(attachment["url"])
            r.raise_for_status()
            im = Image.open(io.BytesIO(r.content))
        except Exception:
            pass
        if (not im) and attachment.get("blurhash") and (not isinstance(blurhash, ImportError)):
            im = blurhash.decode(attachment["blurhash"], width=64, height=64)
        if not im:
            return
        out.append(self.render_image(im))
        if attachment["description"]:
            out.append(b"\n")
            for line in textwrap.wrap("Image description: " + attachment["description"], width=48):
                out.append(line + "\n")
        return out

    def get_qrcode_bin(self, payload):
        out = (
            b"\x1d(k\x04\x00\x31\x41\x32\x00"  # QR model 2
            + b"\x1d(k\x03\x00\x31\x43\x0a"  # QR size 10 dots
            + b"\x1d(k\x03\x00\x31\x45\x31"  # QR error correction level M (15%)
        )
        a = payload.encode("UTF-8")
        store_len = len(a) + 3
        pl = store_len % 256
        ph = int(store_len / 256)
        out += b"\x1d(k" + bytes([pl, ph]) + b"\x31\x50\x30" + a  # QR store
        out += b"\x1d(k\x03\x00\x31\x51\x30"  # QR print
        return out


def main():
    return Printer().main()


if __name__ == "__main__":
    sys.exit(main())

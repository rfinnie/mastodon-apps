# SPDX-FileComment: Jucika Mastodon bot
# SPDX-FileCopyrightText: Copyright (C) 2025 Ryan Finnie
# SPDX-License-Identifier: MPL-2.0

import copy
import datetime
import mimetypes
import pathlib
import random
import sys
import time
import zlib

import dateutil.parser

from .mastodon import BaseMastodon


class Jucika(BaseMastodon):
    name = "jucika"
    calling_file = __file__

    def add_app_args(self, parser):
        parser.add_argument("--random", action="store_true", help="Truly random comic")
        parser.add_argument("--dry-run", action="store_true", help="Do not post")
        parser.add_argument("--datetime-override", help="Date/time override")

    def get_seed(self):
        seed = self.config.get("seed", 0)
        if isinstance(seed, int):
            return seed
        elif isinstance(seed, bytes):
            return zlib.crc32(seed)
        else:
            return zlib.crc32(str(seed).encode("UTF-8"))

    def get_day_comic(self, today):
        comics = copy.copy(self.config["comics"])
        day = (today - datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)).days
        base_seed = self.get_seed()
        # Seed remains the same throughout the run of the comics,
        # but changes for the next run
        seed = base_seed + (day - (day % len(comics)))
        rand = random.Random(seed)
        rand.shuffle(comics)
        pos = day % len(comics)
        comic = comics[pos]
        self.logger.debug("{} is day {}; picked position {} with seed {}".format(today, day, pos, seed))
        return comic

    def backoff_attachment(self, url, timeout=300):
        begin = datetime.datetime.now()
        wait_secs = 1
        while True:
            self.logger.debug("Waiting {}s for attachment processing".format(wait_secs))
            time.sleep(wait_secs)
            res = self.api(url, get_result=True)
            if res.status_code == 200:
                self.logger.debug("Attachment has processed")
                return
            self.logger.debug("Attachment has not yet processed (status code {})".format(res.status_code))
            if (datetime.datetime.now() - begin) >= datetime.timedelta(seconds=timeout):
                raise TimeoutError("Timed out waiting for attachment processing")
            wait_secs *= 1.75

    def run(self):
        if self.args.datetime_override:
            today = dateutil.parser.parse(self.args.datetime_override)
            if today.tzinfo:
                today = today.astimezone(datetime.timezone.utc)
            else:
                today = today.replace(tzinfo=datetime.timezone.utc)
        else:
            today = datetime.datetime.now(tz=datetime.timezone.utc)
        tomorrow = today + datetime.timedelta(days=1)
        if self.args.random:
            comic = random.choice(self.config["comics"])
            next_comic = None
        else:
            comic = self.get_day_comic(today)
            next_comic = self.get_day_comic(tomorrow)

        self.logger.info("Posting for today ({}): {}: {}".format(today, comic["filename"], comic.get("title")))
        if next_comic:
            self.logger.info("Tomorrow ({}) will be: {}: {}".format(tomorrow, next_comic["filename"], next_comic.get("title")))

        if self.args.dry_run:
            return

        f = pathlib.Path(self.config["image_dir"], comic["filename"])
        fh = f.open(mode="rb")
        data = {}
        description = comic.get("description")
        if description:
            data["description"] = description
        attachment_mime = mimetypes.guess_type(f.as_uri())[0]
        attachment_filename = "attachment.{}".format(mimetypes.guess_extension(attachment_mime))
        res = self.api(
            "{}/api/v2/media".format(self.url_base),
            data=data,
            files={
                "file": (attachment_filename, fh, attachment_mime),
            },
            method="POST",
            get_result=True,
        )
        j = res.json()
        attachment_id = j["id"]
        if res.status_code == 202:
            self.logger.debug("Attachment is still processing; checking status occasionally")
            self.backoff_attachment("{}/api/v1/media/{}".format(self.url_base, attachment_id))

        data = [
            ("media_ids[]", attachment_id),
            ("sensitive", ("true" if comic.get("sensitive") else "false")),
            ("visibility", self.config.get("visibility", "public")),
        ]
        title = comic.get("title")
        if title:
            data.append(("status", title))
        self.api(
            "{}/api/v1/statuses".format(self.url_base),
            data=data,
            method="POST",
        )


def main():
    bot = Jucika()
    bot.main(listen=False)
    return bot.run()


if __name__ == "__main__":
    sys.exit(main())

# SPDX-PackageName: mastodon-apps
# SPDX-PackageSupplier: Ryan Finnie <ryan@finnie.org>
# SPDX-PackageDownloadLocation: https://forge.colobox.com/rfinnie/mastodon-apps
# SPDX-FileComment: Jucika Mastodon bot
# SPDX-FileCopyrightText: © 2025 Ryan Finnie <ryan@finnie.org>
# SPDX-License-Identifier: MPL-2.0

import datetime
import mimetypes
import pathlib
import random
import re
import sys
import time
import zlib

from bs4 import BeautifulSoup
import dateutil.parser

from .mastodon import BaseMastodon


class Jucika(BaseMastodon):
    name = "jucika"
    calling_file = __file__
    listen = True
    re_strip_users = re.compile(r"^(\@[a-zA-Z0-9\.@\-_]+ +)+")
    re_strip_dots = re.compile(r"^[\. ]+")

    def setup(self):
        if self.args.daily:
            self.listen = False

    def add_app_args(self, parser):
        parser.add_argument("--daily", action="store_true", help="Daily cron mode")
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

    def get_comics(self, get_generation):
        out = []
        for comic in self.config["comics"]:
            generation = comic.get("generation", 1)
            if generation > get_generation:
                continue
            out.append(comic)
        return out

    def get_generation(self, day):
        generations = self.config.get("generations", [{"generation": 1, "day": 0}])
        for g in sorted(generations, key=lambda x: x["generation"], reverse=True):
            if g["day"] <= day:
                return g["generation"]
        return 1

    def get_day_comic(self, today):
        day = (today - datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)).days
        generation = self.get_generation(day)
        comics = self.get_comics(generation)
        base_seed = self.get_seed()
        # Seed remains the same throughout the run of the comics,
        # but changes for the next run
        day_base = day - (day % len(comics))
        seed = base_seed + day_base
        rand = random.Random()
        rand.seed(seed, version=2)
        rand.shuffle(comics)
        pos = day % len(comics)
        comic = comics[pos]
        self.logger.debug(
            "{} is generation {}, {} base -> {} day; picked position {}/{} with seed {}".format(
                today, generation, day_base, day, pos, len(comics), seed
            )
        )
        return comic

    def backoff_attachments(self, attachment_ids, timeout=300):
        begin = datetime.datetime.now()
        wait_secs = 1
        while attachment_ids:
            self.logger.debug("Waiting {}s for attachment processing".format(wait_secs))
            time.sleep(wait_secs)
            for attachment_id in attachment_ids.copy():
                res = self.api("{}/api/v1/media/{}".format(self.url_base, attachment_id), get_result=True)
                if res.status_code == 200:
                    self.logger.debug("Attachment {} has processed".format(attachment_id))
                    attachment_ids.remove(attachment_id)
                else:
                    self.logger.debug("Attachment {} has not yet processed (status code {})".format(attachment_id, res.status_code))
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

        def get_desc(comic):
            if comic.get("boost"):
                desc = "Boost: {}".format(comic["boost"])
            else:
                desc = "Post: {}".format(comic.get("title"))
            return desc

        self.logger.info("Today ({}): {}".format(today, get_desc(comic)))
        if next_comic:
            self.logger.info("Tomorrow ({}): {}".format(today, get_desc(next_comic)))

        if self.args.dry_run:
            return

        if comic.get("boost"):
            if "/" in comic["boost"]:
                # Allow full URL for posterity, but only needs the ID
                boost_id = comic["boost"].split("/")[-1]
            else:
                boost_id = str(comic["boost"])
            # "unreblog" is idempotent
            self.api(
                "{}/api/v1/statuses/{}/unreblog".format(self.url_base, boost_id),
                method="POST",
            )
            self.api(
                "{}/api/v1/statuses/{}/reblog".format(self.url_base, boost_id),
                method="POST",
            )
            return
        else:
            self.post_comic(comic)

    def post_comic(self, comic, in_reply_to_id=None, status_prefix=None, visibility=None):
        attachments = comic.get("attachments", [])
        backoffs = []
        attachment_ids = []
        for attachment in attachments:
            f = pathlib.Path(self.config["image_dir"], attachment["filename"])
            fh = f.open(mode="rb")
            data = {}
            description = attachment.get("description")
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
            attachment_ids.append(attachment_id)
            if res.status_code == 202:
                backoffs.append(attachment_id)

        if backoffs:
            self.logger.debug("Attachments are still processing; checking status occasionally")
            self.backoff_attachments(backoffs)

        if visibility is None:
            visibility = self.config.get("visibility", "public")
        data = [
            ("sensitive", ("true" if comic.get("sensitive") else "false")),
            ("visibility", visibility),
        ]
        for attachment_id in attachment_ids:
            data.append(("media_ids[]", attachment_id))
        status = comic.get("title", "")
        if status_prefix:
            status = status_prefix + " " + status
        status = status.strip()
        if status:
            data.append(("status", status))
        if in_reply_to_id:
            data.append(("in_reply_to_id", in_reply_to_id))
        self.api(
            "{}/api/v1/statuses".format(self.url_base),
            data=data,
            method="POST",
        )

    def process_mention(self, mention):
        soup = BeautifulSoup(mention["status"]["content"], features="lxml")
        post_text = soup.get_text().strip()
        post_text = self.re_strip_users.sub("", post_text).strip()
        post_text = self.re_strip_dots.sub("", post_text).strip()
        post_text = post_text.lower()
        if "random" in post_text or "please" in post_text or "give me" in post_text or "another comic" in post_text:
            comic = random.choice(self.config["comics"])
            self.post_comic(
                comic,
                in_reply_to_id=mention["status"]["id"],
                status_prefix="@{}".format(mention["status"]["account"]["acct"]),
                visibility="unlisted",
            )
        elif "thank you" in post_text or "thanks" in post_text:
            self.api(
                "{}/api/v1/statuses/{}/favourite".format(self.url_base, mention["status"]["id"]),
                method="POST",
            )


def main():
    return Jucika().main()


if __name__ == "__main__":
    sys.exit(main())

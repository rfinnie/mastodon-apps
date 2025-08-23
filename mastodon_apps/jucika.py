# SPDX-FileComment: Jucika Mastodon bot
# SPDX-FileCopyrightText: Copyright (C) 2025 Ryan Finnie
# SPDX-License-Identifier: MPL-2.0

import copy
import datetime
import random
import sys
import time

import dateutil.parser

from .mastodon import BaseMastodon


class Jucika(BaseMastodon):
    name = "jucika"
    calling_file = __file__

    def add_app_args(self, parser):
        parser.add_argument("--random", action="store_true", help="Truly random comic")
        parser.add_argument("--dry-run", action="store_true", help="Do not post")
        parser.add_argument("--datetime-override", help="Date/time override")

    def get_day_comic(self, today):
        comics = copy.copy(self.config["comics"])
        day = (today - datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)).days
        base_seed = self.config.get("seed", 0)
        # Seed remains the same throughout the run of the comics,
        # but changes for the next run
        seed = base_seed + (day - (day % len(comics)))
        rand = random.Random(seed)
        rand.shuffle(comics)
        pos = day % len(comics)
        comic = comics[pos]
        self.logger.debug("{} is day {}; picked position {} with seed {}".format(today, day, pos, seed))
        return comic

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

        fh = open("{}/{}".format(self.config["image_dir"], comic["filename"]), "rb")
        data = {}
        description = comic.get("description")
        if description:
            data["description"] = description
        res = self.api(
            "{}/api/v2/media".format(self.url_base),
            data=data,
            files={
                "file": ("attachment.jpg", fh, "image/jpeg"),
            },
            method="POST",
            get_result=True,
        )
        if res.status_code == 202:
            # Attachment is still processing
            # Ideally we should actually test when it's processed, but sleeping a minute is fast and easy
            # https://docs.joinmastodon.org/methods/media/
            time.sleep(60)
        j = res.json()
        attachment_id = j["id"]

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

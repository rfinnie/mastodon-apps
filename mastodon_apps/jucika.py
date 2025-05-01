#!/usr/bin/env python3

# SPDX-FileComment: Jucika Mastodon bot
# SPDX-FileCopyrightText: Copyright (C) 2025 Ryan Finnie
# SPDX-License-Identifier: MPL-2.0

import datetime
import random
import sys
import time

from .mastodon import BaseMastodon


class Jucika(BaseMastodon):
    name = "jucika"
    calling_file = __file__

    def add_app_args(self, parser):
        parser.add_argument("--random", action="store_true", help="Truly random comic")
        parser.add_argument("--dry-run", action="store_true", help="Do not post")

    def run(self):
        comics = self.config["comics"]
        day = (
            datetime.datetime.now(tz=datetime.timezone.utc)
            - datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
        ).days
        base_seed = self.config.get("seed")
        if self.args.random or (not base_seed):
            seed = None
        else:
            # Seed remains the same throughout the run of the comics,
            # but changes for the next run
            seed = base_seed + (day - (day % len(comics)))
        rand = random.Random(seed)
        rand.shuffle(comics)
        pos = day % len(comics)
        comic = comics[pos]
        next_pos = (day + 1) % len(comics)
        next_comic = comics[next_pos]

        self.logger.info("Posting {}: {}".format(comic["filename"], comic.get("title")))
        if seed:
            self.logger.info(
                "Tomorrow is scheduled to be {}: {}".format(
                    next_comic["filename"], next_comic.get("title")
                )
            )

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

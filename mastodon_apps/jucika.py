#!/usr/bin/env python3

# SPDX-FileComment: Jucika Mastodon bot
# SPDX-FileCopyrightText: Copyright (C) 2025 Ryan Finnie
# SPDX-License-Identifier: MPL-2.0

import random
import sys
import time

from .mastodon import BaseMastodon


class Jucika(BaseMastodon):
    name = "jucika"
    calling_file = __file__

    def run(self):
        comic = random.choice(self.config["comics"])

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

        self.api(
            "{}/api/v1/statuses".format(self.url_base),
            data=[
                ("media_ids[]", attachment_id),
                ("sensitive", ("true" if comic.get("sensitive") else "false")),
                ("visibility", self.config.get("visibility", "public")),
            ],
            method="POST",
        )


def main():
    bot = Jucika()
    bot.main(listen=False)
    return bot.run()


if __name__ == "__main__":
    sys.exit(main())

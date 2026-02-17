# SPDX-PackageName: mastodon-apps
# SPDX-PackageSupplier: Ryan Finnie <ryan@finnie.org>
# SPDX-PackageDownloadLocation: https://github.com/rfinnie/mastodon-apps
# SPDX-FileComment: Fish! Mastodon bot
# SPDX-FileCopyrightText: © 2023 Ryan Finnie <ryan@finnie.org>
# SPDX-License-Identifier: MPL-2.0

import re
import sys

from bs4 import BeautifulSoup

from .mastodon import BaseMastodon


class Fish(BaseMastodon):
    name = "fish"
    calling_file = __file__
    re_strip_users = re.compile(r"^(\@[a-zA-Z0-9\.@\-_]+ +)+")
    re_strip_dots = re.compile(r"^[\. ]+")
    re_fish = re.compile(r"^fish[\.\?!]*$", re.I)
    re_iwill = re.compile(r"^i will[\.\?!]*$", re.I)

    def process_mention(self, mention):
        soup = BeautifulSoup(mention["status"]["content"], features="lxml")
        post_text = soup.get_text().strip()
        post_text = self.re_strip_users.sub("", post_text).strip()
        post_text = self.re_strip_dots.sub("", post_text).strip()
        if self.re_fish.search(post_text):
            reply_text = "@{} Today's fish is trout à la crème. Enjoy your meal.".format(mention["status"]["account"]["acct"])
            if mention["status"]["visibility"] == "public":
                visibility = "unlisted"
            else:
                visibility = mention["status"]["visibility"]
            self.api(
                "{}/api/v1/statuses".format(self.url_base),
                data={
                    "status": reply_text,
                    "in_reply_to_id": mention["status"]["id"],
                    "visibility": visibility,
                },
                method="POST",
            )
            if not mention["status"]["in_reply_to_id"]:
                self.api(
                    "{}/api/v1/statuses/{}/favourite".format(self.url_base, mention["status"]["id"]),
                    method="POST",
                )
        elif self.re_iwill.search(post_text):
            if mention["status"].get("in_reply_to_account_id") != self.me["id"]:
                return
            self.api(
                "{}/api/v1/statuses/{}/favourite".format(self.url_base, mention["status"]["id"]),
                method="POST",
            )


def main():
    return Fish().main()


if __name__ == "__main__":
    sys.exit(main())

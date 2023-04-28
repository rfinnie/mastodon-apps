#!/usr/bin/env python3

# SPDX-FileComment: Fish! Mastodon bot
# SPDX-FileCopyrightText: Copyright (C) 2023 Ryan Finnie
# SPDX-License-Identifier: MPL-2.0

import json
import logging
import os
import re
import sys
import time

from bs4 import BeautifulSoup
import requests
import yaml


class Fish:
    re_strip_users = re.compile(r"^(\@[a-zA-Z0-9\.@\-_]+ +)+")
    re_strip_dots = re.compile(r"^[\. ]+")
    re_fish = re.compile(r"^fish[\.\?!]*$", re.I)
    re_iwill = re.compile(r"^i will[\.\?!]*$", re.I)

    session = None
    me = None
    config = None

    def __init__(self):
        self.session = requests.Session()
        self.script_dir = os.path.dirname(os.path.realpath(__file__))

    def process_mention(self, mention):
        soup = BeautifulSoup(mention["status"]["content"], features="lxml")
        post_text = soup.get_text().strip()
        post_text = self.re_strip_users.sub("", post_text).strip()
        post_text = self.re_strip_dots.sub("", post_text).strip()
        if self.re_fish.search(post_text):
            reply_text = (
                "@{} Today's fish is trout à la crème. Enjoy your meal.".format(
                    mention["status"]["account"]["acct"]
                )
            )
            if mention["status"]["visibility"] == "public":
                visibility = "unlisted"
            else:
                visibility = mention["status"]["visibility"]
            r = self.session.post(
                "{}/api/v1/statuses".format(self.url_base),
                data={
                    "status": reply_text,
                    "in_reply_to_id": mention["status"]["id"],
                    "visibility": visibility,
                },
            )
            r.raise_for_status()
            if not mention["status"]["in_reply_to_id"]:
                r = self.session.post(
                    "{}/api/v1/statuses/{}/favourite".format(
                        self.url_base, mention["status"]["id"]
                    )
                )
                r.raise_for_status()
        elif self.re_iwill.search(post_text):
            if mention["status"].get("in_reply_to_account_id") != self.me["id"]:
                return
            r = self.session.post(
                "{}/api/v1/statuses/{}/favourite".format(
                    self.url_base, mention["status"]["id"]
                )
            )
            r.raise_for_status()

    def stream_iter_lines(self, r):
        buf = b''
        for buf_in in r.iter_content(chunk_size=8192):
            buf += buf_in
            if b'\n' not in buf:
                continue
            raw_lines = buf.split(b'\n')
            buf = raw_lines[-1]
            for line in [line.decode("UTF-8") for line in raw_lines[:-1]]:
                yield line

    def stream_notifications(self):
        message = {}
        r = self.session.get(
            "{}/api/v1/streaming/user/notification".format(self.url_base), stream=True
        )
        r.raise_for_status()
        for line in self.stream_iter_lines(r)
            if line.startswith(":"):
                continue
            line = line.strip()
            if line:
                k, v = line.split(": ", 1)
                message[k] = v
                continue
            try:
                self.process_message(message)
            except Exception:
                logging.exception("Unexpected exception processing message")
            message = {}

    def process_message(self, message):
        if message.get("event") != "notification":
            return
        try:
            data = json.loads(message.get("data"))
        except (TypeError, json.decoder.JSONDecodeError):
            logging.exception("Exception decoding message data")
            return
        if data.get("type") == "mention":
            self.process_mention(data)

    def main(self):
        logging_format = "%(levelname)s:%(name)s:%(message)s"
        if sys.stderr.isatty():
            logging_format = "%(asctime)s:" + logging_format
        logging_level = logging.DEBUG if sys.stderr.isatty() else logging.INFO
        logging.basicConfig(format=logging_format, level=logging_level)
        with open(os.path.join(self.script_dir, "fish.yaml")) as f:
            self.config = yaml.safe_load(f)
        self.url_base = self.config["url_base"]
        self.session.headers["Authorization"] = "Bearer {}".format(
            self.config["bearer_token"]
        )

        r = self.session.get(
            "{}/api/v1/accounts/verify_credentials".format(self.url_base)
        )
        r.raise_for_status()
        self.me = r.json()

        while True:
            try:
                self.stream_notifications()
            except Exception:
                logging.exception("Unexpected exception")
            time.sleep(30)


if __name__ == "__main__":
    sys.exit(Fish().main())

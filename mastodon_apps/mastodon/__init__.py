#!/usr/bin/env python3

# SPDX-FileComment: Mastodon bot
# SPDX-FileCopyrightText: Copyright (C) 2023 Ryan Finnie
# SPDX-License-Identifier: MPL-2.0

import argparse
import base64
import hashlib
import hmac
import json
import logging
import pathlib
import pickle
import sys
import time

import requests
import yaml


class BaseMastodon:
    name = "mastodon"
    idempotency_key = "rf_mastodon_apps"
    calling_file = __file__
    session = None
    me = None
    instance = None
    args = None
    config = None

    def __init__(self):
        self.session = requests.Session()
        self.stream_session = requests.Session()

    def add_app_args(self, parser):
        pass

    def parse_args(self, argv=None):
        if argv is None:
            argv = sys.argv

        parser = argparse.ArgumentParser(
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            prog=pathlib.Path(argv[0]).name,
        )

        parser.add_argument(
            "--debug", action="store_true", help="Print debugging information"
        )

        parser.add_argument(
            "--config",
            action="append",
            default=[],
            help="YAML configuration file",
            metavar="FILE",
        )

        self.add_app_args(parser)
        return parser.parse_args(args=argv[1:])

    def stream_iter_lines(self, r):
        buf = b""
        for buf_in in r.iter_content(chunk_size=8192):
            buf += buf_in
            if b"\n" not in buf:
                continue
            raw_lines = buf.split(b"\n")
            buf = raw_lines[-1]
            for line in [line.decode("UTF-8") for line in raw_lines[:-1]]:
                yield line

    def stream_listen(self):
        message = {}
        r = self.stream_session.get(
            "{}/api/v1/streaming/user".format(self.url_base),
            headers={"Authorization": "Bearer {}".format(self.config["bearer_token"])},
            stream=True,
        )
        r.raise_for_status()
        for line in self.stream_iter_lines(r):
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
                self.logger.exception("Unexpected exception processing message")
            message = {}

    def process_message(self, message):
        if message.get("event") not in ("notification", "update"):
            return
        try:
            data = json.loads(message.get("data"))
        except (TypeError, json.decoder.JSONDecodeError):
            self.logger.exception("Exception decoding message data")
            return
        if message["event"] == "notification" and data.get("type") == "mention":
            self.process_mention(data)
        elif message["event"] == "update":
            self.process_update(data)

    def process_mention(self, mention):
        pass

    def process_update(self, status):
        pass

    def api(self, url, method="GET", data=None, files=None, get_result=False):
        # Note that this is not cryptographically safe, just to prevent
        # accidental replays.
        # https://docs.joinmastodon.org/methods/statuses/#headers
        idempotency_id = base64.b64encode(
            hmac.HMAC(
                self.idempotency_key.encode("UTF-8"),
                msg=pickle.dumps((url, method, data)),
                digestmod=hashlib.sha256,
            ).digest()
        ).decode("UTF-8")

        kwargs = {}
        if data:
            kwargs["data"] = data
        if files:
            kwargs["files"] = files
        r = self.session.request(
            method,
            url,
            headers={
                "Authorization": "Bearer {}".format(self.config["bearer_token"]),
                "Idempotency-Key": idempotency_id,
            },
            **kwargs,
        )
        r.raise_for_status()
        if get_result:
            return r
        else:
            return r.json()

    def setup(self):
        pass

    def main(self, listen=True):
        self.args = self.parse_args()
        self.logger = logging.getLogger(self.name)
        logging_format = "%(levelname)s:%(name)s:%(message)s"
        if sys.stderr.isatty():
            logging_format = "%(asctime)s:" + logging_format
        logging_level = logging.DEBUG if self.args.debug else logging.INFO
        logging.basicConfig(format=logging_format, level=logging_level)
        if not self.args.config:
            self.args.config.append(
                str(
                    pathlib.Path(self.calling_file)
                    .absolute()
                    .parent.joinpath("{}.yaml".format(self.name))
                )
            )

        def merge_dicts(dest, source):
            for k, v in source.items():
                if k in dest and isinstance(dest[k], dict) and isinstance(v, dict):
                    dest[k] = merge_dicts(dest[k], v)
                else:
                    dest[k] = v
            return dest

        self.config = {}
        for fn in self.args.config:
            with open(fn) as f:
                merge_dicts(self.config, yaml.safe_load(f))
        self.url_base = self.config["url_base"]

        self.server = self.api("{}/api/v2/instance".format(self.url_base))
        self.me = self.api(
            "{}/api/v1/accounts/verify_credentials".format(self.url_base)
        )

        self.setup()

        if not listen:
            return

        while True:
            try:
                self.stream_listen()
            except requests.exceptions.ChunkedEncodingError:
                self.logger.warning("Received chunked encoding error, resetting")
            except Exception:
                self.logger.exception("Unexpected exception")
            time.sleep(30)

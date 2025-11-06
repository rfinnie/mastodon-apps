# SPDX-FileComment: 8:47 Mastodon bot
# SPDX-FileCopyrightText: Copyright (C) 2024 Ryan Finnie
# SPDX-License-Identifier: MPL-2.0

# Run from cron at 1400Z, it will figure out correctly when to post

import datetime
import sys
import time

try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo

import dateutil.parser

from .mastodon import BaseMastodon


class EightFortySeven(BaseMastodon):
    name = "eightfortyseven"
    calling_file = __file__

    tz = zoneinfo.ZoneInfo("America/Denver")
    hm = (8, 47)
    prep = datetime.timedelta(minutes=15)
    current_temp = None
    high_temp = None

    def run(self):
        now = datetime.datetime.now().astimezone(self.tz)
        # fudge = datetime.timedelta(minutes=2)
        # self.hm = ((now + fudge).hour, (now + fudge).minute)

        self.today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        self.t_847 = self.today.replace(hour=self.hm[0], minute=self.hm[1])
        self.t_848 = self.t_847 + datetime.timedelta(minutes=1)
        self.t_prep = self.t_847 - self.prep

        if now > self.t_848:
            self.logger.warning("Too late today to run, moving to tomorrow")
            _d = datetime.timedelta(days=1)
            self.today = self.today + _d
            self.t_847 = self.t_847 + _d
            self.t_848 = self.t_848 + _d
            self.t_prep = self.t_prep + _d

        self.idempotency_key = self.idempotency_key + self.today.strftime("_%Y-%m-%d")

        if now < self.t_prep:
            self.logger.debug("Waiting until {} to prep".format(self.t_prep))
            time.sleep((self.t_prep - now).total_seconds())

        # weather.gov API isn't very reliable, so keep trying ahead of time
        while True:
            now = datetime.datetime.now().astimezone(self.tz)
            if now > self.t_848:
                self.logger.error("Couldn't get temps in time")
                return
            try:
                self.get_temps()
            except Exception:
                time.sleep(100)
                continue
            break

        now = datetime.datetime.now().astimezone(self.tz)
        if now < self.t_847:
            self.logger.debug("Waiting until {} to post".format(self.t_847))
            time.sleep((self.t_847 - now).total_seconds())
        self.post()

    def get_temps(self):
        res = self.session.get("https://api.weather.gov/stations/KCNM/observations/latest")
        res.raise_for_status()
        j = res.json()
        self.current_temp = int(j["properties"]["temperature"]["value"] * 1.8 + 32)

        high_temp = 0
        res = self.session.get("https://api.weather.gov/gridpoints/MAF/42,155")
        res.raise_for_status()
        j = res.json()

        tomorrow = self.today + datetime.timedelta(days=1)

        for tv in j["properties"]["temperature"]["values"]:
            t = dateutil.parser.parse(tv["validTime"].split("/")[0])
            if t < self.today or t >= tomorrow:
                continue
            v = tv["value"] * 1.8 + 32
            if v > high_temp:
                high_temp = v
        self.high_temp = high_temp

        if self.high_temp < self.current_temp:
            self.high_temp = self.current_temp

    def post(self):
        post_text = "The time is 8:47 AM. Current topside temperature is {} degrees, with an estimated high of {}.".format(
            int(self.current_temp), int(self.high_temp)
        )

        self.api(
            "{}/api/v1/statuses".format(self.url_base),
            data={
                "status": post_text,
                "visibility": "public",
            },
            method="POST",
        )


def main():
    bot = EightFortySeven()
    bot.main(listen=False)
    return bot.run()


if __name__ == "__main__":
    sys.exit(main())

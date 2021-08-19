import gpxpy
from datetime import datetime, timedelta
import pytz
import argparse
import sys, os, io
import logging
import rapidjson
import re
import zipfile
import csv
import codecs
import urllib.request, urllib.parse
import copy


from pydub import AudioSegment

# from pydub.playback import play

import pytimeparse
import dateutil.parser
from simplify import Simplify3D

highestQuality = True

RE_INT = re.compile(r"^[-+]?([1-9]\d*|0)$")
RE_FLOAT = re.compile(r"^[-+]?(\d+([.,]\d*)?|[.,]\d+)([eE][-+]?\d+)?$")

skipme = ["seconds_elapsed", "sensor"]
untouchables = ["Metadata"]


def prepare(j):
    try:
        cleaned = {}
        for k, v in j.items():

            if k in skipme:
                continue

            if k in untouchables:
                return j

            if k == "time":
                ns = float(v[10:])
                secs = float(v[0:-9]) + ns * 1e-9
                cleaned[k] = datetime.utcfromtimestamp(secs).replace(tzinfo=pytz.utc)
                continue

            if RE_INT.match(v):
                cleaned[k] = int(v)
                continue

            if RE_FLOAT.match(v):
                cleaned[k] = float(v)
                continue

            cleaned[k] = v
        return cleaned

    except Exception as e:
        logging.debug(f"skipping sample: {j} - {e}")
        return None


def stringify(d):
    text = ""
    for k, v in d.items():
        text += f"{k}: {v}, "
    return text.rstrip(", ")


def gen_gpx(args, gpx_fn, j):
    gpx = gpxpy.gpx.GPX()

    # Create first track in our GPX:
    gpx_track = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(gpx_track)

    # Create first segment in our GPX track:
    gpx_segment = gpxpy.gpx.GPXTrackSegment()
    gpx_track.segments.append(gpx_segment)

    points = []
    for row in j["Location"]:
        points.append(
            [
                row["longitude"],
                row["latitude"],
                row["altitude"],
                row["time"],
                row["horizontalAccuracy"],
                row["verticalAccuracy"],
                row["speed"],
            ]
        )

    pts = points

    if args.tolerance > 0.0:
        s = Simplify3D()
        pts = s.simplify(
            points,
            tolerance=args.tolerance,
            highestQuality=highestQuality,
            returnMarkers=False,
        )
        logging.debug(
            f"simplify3d: {len(points)} -> {len(pts)} points with {args.tolerance=}"
        )

    for p in pts:
        (lat, lon, ele, dt, hdop, vdop, speed) = p
        pt = gpxpy.gpx.GPXTrackPoint(
            lon,
            lat,
            elevation=ele,
            time=dt,
            speed=speed,
            horizontal_dilution=hdop,
            vertical_dilution=vdop,
        )
        gpx_segment.points.append(pt)

    gpx.refresh_bounds()
    metadata = j["Metadata"]
    gpx.creator = f"Sensor Logger, app version {metadata['appVersion']}"

    gpx.author_name = stringify(metadata)
    gpx.description = " ".join(sys.argv)
    gpx_track.name = gpx_fn

    xml = gpx.to_xml(version="1.0")
    logging.debug(f"writing {gpx_fn}, {len(pts)} track points")
    with open(gpx_fn, "w") as f:
        f.write(xml)


def gettime(value, offset=0):
    if isinstance(value, float):
        return datetime.utcfromtimestamp(value + offset).replace(tzinfo=pytz.utc)
    if isinstance(value, str):
        return dateutil.parser.parse(value) + timedelta(seconds=offset)
    if isinstance(value, datetime):
        return value + timedelta(seconds=offset)
    raise Exception(f"invalid type for time: {value} : {type(value)}")


def stats(j):
    sensordict = {}
    metadata = j.get("Metadata", None)
    if metadata:
        sensors = metadata.get("sensors", None)
        rates = metadata.get("sampleRateMs", None)
        if sensors and rates:
            ratelist = rates.split("|")
            sensorlist = sensors.split("|")
            for i in range(len(sensorlist)):
                if RE_FLOAT.match(ratelist[i]):
                    s = sensorlist[i]
                    sensordict[s] = {"nominalrate": float(ratelist[i])}

    txt = "Sensor                     start                      duration"
    txt += " samples   actual    nominal"

    logging.debug(txt)
    logging.debug(" " * 77 + "ms/sample")

    for k in j.keys():
        record = j[k]
        if k == "Metadata":
            continue

        n = len(record)
        if n == 0:
            continue
        start = record[0]["time"]
        end = record[-1]["time"]
        duration = timedelta.total_seconds(end - start)
        ts = gettime(start).isoformat(timespec="seconds")
        te = gettime(end).isoformat(timespec="seconds")
        txt = f"{k:25.25}  {ts} {duration:6.1f}  {n:6d}"

        if abs(duration) < 0.00001:
            txt += "                  "
        else:
            txt += f"      {1000.0/(n/duration):.2f}   "
        if k in sensordict:
            if abs(sensordict[k]["nominalrate"]) < 0.001:
                txt += f" max"
            else:
                txt += f"{sensordict[k]['nominalrate']:6.0f} "
        logging.debug(txt)

    if metadata:
        logging.debug("Metadata:")
        for k, v in metadata.items():
            logging.debug(f"\t{k}: {v}")


def args2range(args, start, end):
    begin = start
    stop = end
    if args.skip:
        begin = start + timedelta(seconds=args.skip)
    if args.begin:
        begin = args.begin
    if args.trim:
        stop = end - timedelta(seconds=args.trim)
    if args.end:
        stop = args.end
    if args.duration:
        stop = begin + timedelta(seconds=args.duration)
    return (args.skip, (stop - start).total_seconds(), begin, stop)


class ParseTimedelta(argparse.Action):
    def __call__(self, parser, args, values, option_string=None):
        delta = pytimeparse.parse(values)
        if delta == None:
            err = f"{values} is not a valid duration. Examples: 20.2s 2h32m"
            logging.error(err)
            raise TypeError(err)
        setattr(args, self.dest, delta)


def main():
    ap = argparse.ArgumentParser(
        usage="%(prog)s ",
        description="reformat/trim/convert a Sensor Logger JSON or zipped CSV file, and optionally convert to GPX or JSON",
    )
    ap.add_argument("-d", "--debug", action="store_true", help="show detailed logging")
    ap.add_argument(
        "-i",
        "--iso",
        action="store_true",
        help="use ISO timestamps in JSON outoput (default Unix timestamps - seconds since epoch)",
    )
    ap.add_argument(
        "-g", "--gpx", action="store_true", help="save GPX file as (basename).gpx"
    )
    ap.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="save reformatted JSON file as (basename)_reformat.json",
    )
    ap.add_argument(
        "--tolerance",
        action="store",
        dest="tolerance",
        default=-1.0,
        type=float,
        help="tolerance value for simplify (see https://github.com/mhaberler/simplify.py)",
    )
    ap.add_argument(
        "--skip",
        action=ParseTimedelta,
        default=0.0,
        help="skip <duration> from start (like '10s' or '1h 20m 12s'",
    )
    ap.add_argument(
        "--trim",
        action=ParseTimedelta,
        default=0.0,
        help="trim <duration> from end (like '10s' or '1h 20m 12s'",
    )
    ap.add_argument(
        "--duration",
        action=ParseTimedelta,
        default=0.0,
        help="set <duration> (like '10s' or '1h 20m 12s'",
    )
    ap.add_argument(
        "--begin",
        type=dateutil.parser.parse,
        help="start extraction at <time> - example: --begin '2021-07-25 13:25'",
    )
    ap.add_argument(
        "--end",
        type=dateutil.parser.parse,
        help="stop extraction at <time> - example: --end '2021-07-25 13:25'",
    )
    ap.add_argument("files", nargs="*")
    args, extra = ap.parse_known_args()

    level = logging.WARNING
    if args.debug:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(funcName)s:%(lineno)s %(message)s")

    logging.debug(f"{args=}")
    if args.skip and args.begin:
        logging.error("--skip and --begin arguments are incompatible")
        sys.exit(1)

    if args.trim and args.end:
        logging.error("--trim and --end arguments are incompatible")
        sys.exit(1)

    if (args.trim or args.end) and args.duration:
        logging.error("--duration is incompatible with both --trim and --end")
        sys.exit(1)

    for filename in args.files:
        result = {}
        a = urllib.parse.urlparse(filename)
        destname = os.path.basename(a.path)
        url = filename if len(a.scheme) else "file:" + filename
        buffer = urllib.request.urlopen(url).read()
        logging.debug(f"{filename} -> {destname} {len(buffer)} bytes")

        if filename.endswith(".json"):
            js = rapidjson.loads(buffer)
            for j in js:
                sensor = j["sensor"]
                if not sensor in result:
                    result[sensor] = []
                c = prepare(j)
                if c:
                    result[sensor].append(c)
            for k, v in result.items():
                logging.debug(f"sensor: {k} {len(v)} samples")

        if filename.endswith(".zip"):
            try:
                ff = io.BytesIO(buffer)
                with zipfile.ZipFile(ff) as zf:
                    fnames = [n for n in zf.namelist()]
                    fnames.sort(key=lambda f: f.rsplit(".", 1)[1])
                    for fn in fnames:
                        basename, ext = fn.rsplit(".", 1)
                        if ext.lower() == "csv":
                            reader = csv.DictReader(
                                codecs.iterdecode(zf.open(fn, "r"), "utf-8")
                            )
                            rows = list(reader)
                            logging.debug(f"read {destname}:member={fn}")
                            l = [prepare(c) for c in rows]
                            if len(l):
                                result[basename] = l
                            continue

                        if ext.lower() == "mp4":
                            buffer = zf.read(fn)
                            logging.debug(f"audio file: {fn} size={len(buffer)}")

                            file_like = io.BytesIO(buffer)
                            file_like.seek(0)
                            sound = AudioSegment.from_file(file_like)
                            logging.debug(
                                f"read {destname}:member={fn}, audio duration={sound.duration_seconds:.1f} seconds, "
                                f"frame rate={sound.frame_rate} channels={sound.channels} bitspersample={sound.sample_width*8}"
                            )
                            # play(sound)
                            start_of_sound = result["Microphone"][0]["time"]
                            (skip, trim, _, _) = args2range(
                                args,
                                start_of_sound,
                                start_of_sound
                                + timedelta(seconds=sound.duration_seconds),
                            )

                            # pydub does things in milliseconds
                            pruned = sound[int(skip * 1000) : int(trim * 1000)]

                            dest = f"{basename}_pruned.wav"
                            logging.debug(
                                f"saving pruned {fn} to {dest},"
                                f"audio duration={pruned.duration_seconds:.1f} seconds"
                            )

                            pruned.export(f"{basename}_pruned.wav", format="wav")
                            continue

            except zipfile.BadZipFile as e:
                logging.error(f"{filename}: {e}")

        # fixup the Metadata record
        if "Metadata" in result and len(result["Metadata"]) == 1:
            result["Metadata"] = result["Metadata"][0]

        if args.skip or args.trim:
            for k in result.keys():
                if k in {"Metadata"}:
                    continue
                if len(result[k]) == 0:
                    logging.debug(f"{k}: no samples - nothing to skip/trim")
                    continue
                nskip = 0
                ntrim = 0
                (_, _, start, end) = args2range(
                    args, result[k][0]["time"], result[k][-1]["time"]
                )
                pruned = []
                for s in result[k]:
                    if s["time"] <= start:
                        nskip += 1
                        continue
                    if s["time"] >= end:
                        ntrim += 1
                        continue
                    pruned.append(s)
                result[k] = pruned
                if nskip or ntrim:
                    logging.debug(f"{k}: skipped {nskip}, trimmed {ntrim} samples")

        if args.json:
            json_fn = os.path.splitext(destname)[0] + "_reformat.json"
            logging.debug(f"writing {json_fn}")
            mode = rapidjson.DM_ISO8601 if args.iso else rapidjson.DM_UNIX_TIME
            with open(json_fn, "w") as f:
                f.write(
                    rapidjson.dumps(
                        result,
                        indent=4,
                        write_mode=rapidjson.WM_PRETTY,
                        datetime_mode=mode,
                    )
                )

        if args.gpx:
            if not "Location" in result:
                logging.error(
                    f"error: can't create GPX from {filename} - no Location records"
                )
                continue

            gpx_fn = os.path.splitext(destname)[0] + ".gpx"
            gen_gpx(args, gpx_fn, result)

        stats(result)


if __name__ == "__main__":
    main()

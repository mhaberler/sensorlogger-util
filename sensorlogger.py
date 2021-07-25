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

from pydub import AudioSegment
from pydub.playback import play

from simplify import Simplify3D

highestQuality = True

# if Location and other samples start more than BUG_THRESHOLD secs
# apart, then use the Location timestamp for that sample series (-t)
BUG_THRESHOLD = 60

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
                    sensordict[s] = {"nominalrate": ratelist[i]}

    for k in j.keys():
        record = j[k]
        if k == "Metadata":
            continue

        n = len(record)
        start = record[0]["time"]
        end = record[-1]["time"]
        duration = timedelta.total_seconds(end - start)
        if abs(duration) < 0.00001:
            logging.debug(f"\t{k}: zero duration")
            continue
        ts = gettime(start).isoformat(timespec="seconds")
        te = gettime(end).isoformat(timespec="seconds")
        txt = f"{k:25.25}: {ts}..{te} {duration:.1f}secs, {n:6d} samples, rate={1000.0/(n/duration):.2f}"
        if k in sensordict:
            txt += f"/{sensordict[k]['nominalrate']}"
        txt += " samples/sec"
        logging.debug(txt)

    if metadata:
        for k, v in metadata.items():
            logging.debug(f"\t{k}: {v}")


def main():
    ap = argparse.ArgumentParser(
        usage="%(prog)s ",
        description="clean a Sensor Logger JSON or zipped CSV files, and optionally convert to GPX",
    )
    ap.add_argument("-d", "--debug", action="store_true", help="show detailed logging")
    ap.add_argument(
        "-i",
        "--iso",
        action="store_true",
        help="use ISO timestamps (default Unix timestamps - seconds since epoch)",
    )
    ap.add_argument(
        "-g", "--gpx", action="store_true", help="save GPX file as (basename).gpx"
    )
    ap.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="save reformatted JSON file as (basename)_fmt.json",
    )
    ap.add_argument(
        "-t",
        "--timestamp-fix",
        action="store_true",
        help="use Location time as start time for all samples (bug workaround)",
    )
    ap.add_argument(
        "--tolerance",
        action="store",
        dest="tolerance",
        default=-1.0,
        type=float,
        help="tolerance value for simplify (see https://github.com/mhaberler/simplify.py)",
    )
    ap.add_argument("files", nargs="*")
    args, extra = ap.parse_known_args()

    level = logging.WARNING
    if args.debug:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(funcName)s:%(lineno)s %(message)s")

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
                    for info in zf.infolist():
                        basename, ext = info.filename.rsplit(".", 1)
                        if ext.lower() == "csv":
                            reader = csv.DictReader(
                                codecs.iterdecode(zf.open(info.filename, "r"), "utf-8")
                            )
                            rows = list(reader)
                            logging.debug(
                                f"read {destname}:member={info.filename}, {len(rows)} samples"
                            )
                            l = [prepare(c) for c in rows]
                            if len(l):
                                result[basename] = l
                            continue

                        if ext.lower() == "mp4":
                            buffer = zf.read(info.filename)
                            logging.debug(
                                f"audio file: {info.filename} size={len(buffer)}"
                            )

                            file_like = io.BytesIO(buffer)
                            file_like.seek(0)
                            # sound = AudioSegment(file_like, format="mp4")
                            # play(sound)
                            continue

            except zipfile.BadZipFile as e:
                logging.error(f"{filename}: {e}")

        # fixup the Metadata record
        if "Metadata" in result and len(result["Metadata"]) == 1:
            result["Metadata"] = result["Metadata"][0]

        if args.timestamp_fix:
            corr = {}
            if "Location" in result:
                # assume location time is correct
                baseline = result["Location"][0]["time"]

                for k in result.keys():
                    if k in {"Location", "Metadata"}:
                        continue
                    first = result[k][0]["time"]
                    delta = baseline - first
                    if abs(delta.total_seconds()) > BUG_THRESHOLD:
                        logging.error(f"warping {k} starttime by {delta}")
                        for e in result[k]:
                            e["time"] += delta
            else:
                logging.error(f"{info.filename}: no Location records - cant fix")

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

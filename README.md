# sensorlogger-util
Utilities for https://www.tszheichoi.com/sensorlogger

```
$ python sensorlogger.py   -h
usage: sensorlogger.py 

reformat/trim/convert a Sensor Logger JSON or zipped CSV file, and optionally convert to GPX or JSON

positional arguments:
  files

optional arguments:
  -h, --help            show this help message and exit
  -d, --debug           show detailed logging
  -i, --iso             use ISO timestamps in JSON outoput (default Unix timestamps - seconds since epoch)
  -g, --gpx             save GPX file as (basename).gpx
  -j, --json            save reformatted JSON file as (basename)_reformat.json
  --tolerance TOLERANCE
                        tolerance value for simplify (see https://github.com/mhaberler/simplify.py)
  --skip SKIP           skip <duration> from start (like '10s' or '1h 20m 12s'
  --trim TRIM           trim <duration> from end (like '10s' or '1h 20m 12s'
  --duration DURATION   set <duration> (like '10s' or '1h 20m 12s'
  --begin BEGIN         start extraction at <time> - example: --begin '2021-07-25 13:25'
  --end END             stop extraction at <time> - example: --end '2021-07-25 13:25'
  -1, --influx1         feed to InfluxDB V1 database
  -2, --influx2         feed to InfluxDB V2 database
  -u URL, --url URL     InfluxDB URL
  --database DATABASE   InfluxDB database
  -t TOKEN, --token TOKEN
                        InfluxDB V2 auth token or username:password for V1
  -b BUCKET, --bucket BUCKET
                        InfluxDB V2 bucket - for V1 use 'database/retentionpolicy'
  -O ORG, --org ORG     InfluxDB org
  -r RETENTION_POLICY, --retention-policy RETENTION_POLICY
                        InfluxDB retention policy
```

## convert a sensorlogger JSON file to GPX
```
python sensorlogger -g <json file>
```

## reformat sensorlogger JSON file
```
python sensorlogger -j <json file>
```

## import into legacy InfluxDB (V1)

```
python sensorlogger.py  -1 [--database sensorlogger] --token username:password --url http://host:8086 2022-06-14_03-15-05.json
```

## import into  InfluxDB (V2)
```
python sensorlogger.py -2 [--bucket sensorlogger] --token xxx  --org yyyy --url http://host:8086 2022-06-14_03-15-05.json
```


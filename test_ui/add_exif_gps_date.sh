#!/bin/bash
exiftool -DateTimeOriginal="$(date +'%Y:%m:%d %H:%M:%S')" -GPSLongitude=$3 -GPSLatitude=$2 $1

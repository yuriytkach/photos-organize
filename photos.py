#!/usr/bin/python3

"""Organize Photos

Inspect directory and organize photos and videos
"""

import sys
import argparse
import os
import time
from time import strftime
import shutil
from tqdm import tqdm
from PIL import Image
from PIL import ExifTags
from datetime import datetime
from os.path import isfile, join
from geopy.geocoders import Nominatim


class CustomFormatter(argparse.RawDescriptionHelpFormatter,
                      argparse.ArgumentDefaultsHelpFormatter):
    pass


cache_loc = {}


# Print iterations progress
def print_progress_bar(iteration, total, prefix='', suffix='', decimals=1, length=100, fill='█', print_end="\r"):
    """
    Call in a loop to create terminal progress bar
    @params:
        iteration   - Required  : current iteration (Int)
        total       - Required  : total iterations (Int)
        prefix      - Optional  : prefix string (Str)
        suffix      - Optional  : suffix string (Str)
        decimals    - Optional  : positive number of decimals in percent complete (Int)
        length      - Optional  : character length of bar (Int)
        fill        - Optional  : bar fill character (Str)
        printEnd    - Optional  : end character (e.g. "\r", "\r\n") (Str)
    """
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + '-' * (length - filled_length)
    print('\r%s |%s| %s%% %s' % (prefix, bar, percent, suffix), end=print_end)
    # Print New Line on Complete
    if iteration == total:
        print()


def parse_args(args):
    """Parse arguments."""
    parser = argparse.ArgumentParser(
        description=sys.modules[__name__].__doc__,
        formatter_class=CustomFormatter)

    g = parser.add_argument_group("photos settings")

    g.add_argument("-d", "--dir",
                   action="store",
                   required=True,
                   help="Directory to scan")

    g.add_argument("--dry-run",
                   action="store_true",
                   help="Perform dry run without changes")

    return parser.parse_args(args)


def organize(options):
    directory = os.path.expanduser(options.dir)
    print(f"Processing {directory}")

    groups = {}

    onlyfiles = [f for f in os.listdir(directory) if isfile(join(directory, f))]
    for f in tqdm(onlyfiles):
        full_path = join(directory, f)
        try:
            stat = os.stat(full_path)
            exif = extract_exif(full_path)
            town = find_town_by_exif_gps(exif, f)
        except Exception as err:
            print(f"Failed to get info about {full_path}: {err}")
        else:
            mod_date = extract_date_from_file_or_exif(exif, stat)

            if mod_date not in groups:
                groups[mod_date] = {}

            if town not in groups[mod_date]:
                groups[mod_date][town] = []

            groups[mod_date][town].append(full_path)

    print("Copying files")

    for key_date in tqdm(groups):
        sub_dir_date = join(directory, key_date)

        if not options.dry_run:
            os.mkdir(sub_dir_date)

        for key_town in tqdm(groups[key_date], leave=False):
            sub_dir_town = join(sub_dir_date, key_town)

            if not options.dry_run:
                os.mkdir(sub_dir_town)

            for f in tqdm(groups[key_date][key_town], leave=False):
                if not options.dry_run:
                    shutil.copy(f, join(sub_dir_town, os.path.basename(f)))


def extract_date_from_file_or_exif(exif, stat):
    mod_date = extract_date_from_exif(exif)
    if not mod_date:
        tt = stat.st_mtime
        mod_date = strftime("%Y-%m-%d", time.localtime(tt))
    return mod_date


def save_to_cache_location(coords, location):
    key = create_cache_loc_key(coords)
    cache_loc[key] = location


def find_cache_location(coords):
    key = create_cache_loc_key(coords)
    return cache_loc[key] if key in cache_loc else None


def create_cache_loc_key(coords):
    lat = round(coords["lat"], 2)
    lon = round(coords["lon"], 2)
    key = f"{lat}-{lon}"
    return key


def find_town_by_exif_gps(exif, filename):
    if exif:
        geotags = get_geotagging(exif)
        if geotags:
            try:
                coords = get_coordinates(geotags)
                if coords["lat"] and coords["lon"]:
                    cached_location = find_cache_location(coords)
                    if cached_location:
                        return cached_location
                    location = find_geo_location(coords)
                else:
                    return "Unknown"
            except Exception as err:
                print(f"Failed to get geo town: {err} : {filename}")
            else:
                addr = location.raw["address"]

                place = find_place(addr, ["theme_park", "museum", "beach", "suburb"])

                city_places = ["village", "town", "city"]
                if "suburb" in addr and place != addr["suburb"]:
                    city_places.insert(0, "suburb")

                city = find_place(addr, city_places)

                if not place and not city:
                    return location.address
                else:
                    if city:
                        city_str = city + '-' if place else city
                    else:
                        city_str = ''
                    place_str = place if place else ''

                    loc = f"{city_str}{place_str}".replace("/", "-").replace(".", "-").replace(":", "-")
                    save_to_cache_location(coords, loc)
                    return loc

    return "Unknown"


def find_geo_location(coords):
    geolocator = Nominatim(user_agent="PhotoGeo")
    location = geolocator.reverse(f"{coords['lat']}, {coords['lon']}")
    time.sleep(1)
    return location


def find_place(addr, place_names):
    for p in place_names:
        if p in addr:
            return addr[p]
    return None


def get_decimal_from_dms(dms, ref):
    degrees = dms[0][0] / dms[0][1]
    minutes = dms[1][0] / dms[1][1] / 60.0
    seconds = dms[2][0] / dms[2][1] / 3600.0

    if ref in ['S', 'W']:
        degrees = -degrees
        minutes = -minutes
        seconds = -seconds

    return round(degrees + minutes + seconds, 5)


def get_coordinates(geotags):
    if 'GPSLatitude' in geotags and 'GPSLatitudeRef' in geotags:
        lat = get_decimal_from_dms(geotags['GPSLatitude'], geotags['GPSLatitudeRef'])
    else:
        lat = None

    if 'GPSLongitude' in geotags and 'GPSLongitudeRef' in geotags:
        lon = get_decimal_from_dms(geotags['GPSLongitude'], geotags['GPSLongitudeRef'])
    else:
        lon = None
    return {"lat": lat, "lon": lon}


def get_geotagging(exif):
    if exif and 'GPSInfo' in exif:
        geotagging = {}
        for (key, val) in ExifTags.GPSTAGS.items():
            if key in exif['GPSInfo']:
                geotagging[val] = exif['GPSInfo'][key]
        return geotagging
    return None


def extract_date_from_exif(exif):
    if exif and "DateTime" in exif:
        try:
            tt = datetime.strptime(exif["DateTime"], '%Y:%m:%d %H:%M:%S')
            return tt.strftime("%Y-%m-%d", )
        except Exception as err:
            print(err)
    return None


def extract_exif(full_path):
    if full_path.lower().endswith(('.jpg', '.jpeg')):
        img = Image.open(full_path)
        return {
            ExifTags.TAGS[k]: v
            for k, v in img._getexif().items()
            if k in ExifTags.TAGS
        }
    else:
        return None


def main(argv):
    try:
        options = parse_args(argv[1:])
        if options.dry_run:
            print("DRY RUN")
            print("-------")

        organize(options)

        print("Finished")
    except Exception as err:
        print(err)


if __name__ == "__main__":
    main(sys.argv)
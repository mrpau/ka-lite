import base
import os
import re
import json
import requests
import threading
import time
from fle_utils.general import ensure_dir
from functools import partial
from khan_api_python.api_models import Khan, APIError

from django.conf import settings

logging = settings.LOG

slug_key = {
    "Topic": "node_slug",
    "Video": "readable_id",
    "Exercise": "name",
    "AssessmentItem": "id",
}

title_key = {
    "Topic": "title",
    "Video": "title",
    "Exercise": "display_name",
    "AssessmentItem": "name"
}

id_key = {
    "Topic": "node_slug",
    "Video": "youtube_id",
    "Exercise": "name",
    "AssessmentItem": "id"
}

iconfilepath = "/images/power-mode/badges/"
iconextension = "-40x40.png"
defaulticon = "default"

attribute_whitelists = {
    "Topic": ["kind", "hide", "description", "id", "topic_page_url", "title", "extended_slug", "children", "node_slug", "in_knowledge_map", "icon_src", "child_data", "render_type", "path", "slug"],
    "Video": ["kind", "description", "title", "duration", "keywords", "youtube_id", "download_urls", "readable_id", "in_knowledge_map", "path", "slug", "format"],
    "Exercise": ["kind", "description", "related_video_readable_ids", "display_name", "live", "name", "seconds_per_fast_problem", "prerequisites", "all_assessment_items", "uses_assessment_items", "path", "slug"],
    "AssessmentItem": ["kind", "name", "item_data", "author_names", "sha", "id"]
}

denormed_attribute_list = {
    "Video": ["kind", "description", "title", "id", "slug", "path"],
    "Exercise": ["kind", "description", "title", "id", "slug", "path"]
}

kind_blacklist = [None, "Separator", "CustomStack", "Scratchpad", "Article"]

slug_blacklist = ["new-and-noteworthy", "talks-and-interviews", "coach-res", "MoMA", "getty-museum", "stanford-medicine", "crash-course1", "mit-k12", "cs", "cc-third-grade-math", "cc-fourth-grade-math", "cc-fifth-grade-math", "cc-sixth-grade-math", "cc-seventh-grade-math", "cc-eighth-grade-math", "hour-of-code"]

# Attributes that are OK for a while, but need to be scrubbed off by the end.
temp_ok_atts = ["x_pos", "y_pos", "icon_src", u'topic_page_url', u'hide', "live", "node_slug", "extended_slug"]

channel_data = {
    "slug_key": slug_key,
    "title_key": title_key,
    "id_key": id_key,
    "iconfilepath": iconfilepath,
    "iconextension":  iconextension,
    "defaulticon": defaulticon,
    "attribute_whitelists": attribute_whitelists,
    "denormed_attribute_list": denormed_attribute_list,
    "kind_blacklist": kind_blacklist,
    "slug_blacklist": slug_blacklist,
    "temp_ok_atts": temp_ok_atts,
    "require_download_link": True,
}

whitewash_node_data = partial(base.whitewash_node_data, channel_data=channel_data)

def denorm_data(node):
    if node:
        kind = node.get("kind", "")
        if channel_data["denormed_attribute_list"].has_key(kind):
            for key in node.keys():
                if key not in channel_data["denormed_attribute_list"][kind] or not node.get(key, "") or isinstance(node.get(key), partial):
                    del node[key]


def build_full_cache(items, id_key="id"):
    """
    Uses list of items retrieved from Khan Academy API to
    create an item cache with fleshed out meta-data.
    """
    for item in items:
        for attribute in item._API_attributes:
            logging.info("Fetching item information for {id}, attribute: {attribute}".format(id=item.get(id_key, "Unknown"), attribute=attribute))
            try:
                dummy_variable_to_force_fetch = item.__getattr__(attribute)
                if isinstance(item[attribute], list):
                    for subitem in item[attribute]:
                        if isinstance(subitem, dict):
                            try:
                                subitem = json.loads(subitem.toJSON())
                            except AttributeError:
                                True
                            if subitem.has_key("kind"):
                                subitem = whitewash_node_data(
                                    {key: value for key, value in subitem.items()})
                                denorm_data(subitem)
                elif isinstance(item[attribute], dict):
                    try:
                        item[attribute] = json.loads(item[attribute].toJSON())
                    except AttributeError:
                        True
                    if item[attribute].has_key("kind"):
                        item[attribute] = whitewash_node_data(
                            {key: value for key, value in item.attribute.items()})
                        denorm_data(item[attribute])
            except APIError as e:
                del item[attribute]
        try:
            item = json.loads(item.toJSON())
        except AttributeError:
            True
        for key in item.keys():
            if hasattr(item[key], '__call__'):
                logging.warn('{kind}: {item} had a function on key {key}'.format(kind=item.get('kind', ''), item=item.get('id', ''), key=key))
                del item[key]
    return {item["id"]: whitewash_node_data(item) for item in items}

def retrieve_API_data(channel=None):
    khan = Khan()

    logging.info("Fetching Khan topic tree")

    topic_tree = khan.get_topic_tree()

    logging.info("Fetching Khan exercises")

    exercises = khan.get_exercises()

    logging.info("Fetching Khan videos")

    content = khan.get_videos()

    # Hack to hardcode the mp4 format flag on Videos.
    for con in content:
        con["format"] = "mp4"

    assessment_items = []

    # Limit number of simultaneous requests
    semaphore = threading.BoundedSemaphore(100)

    def fetch_assessment_data(exercise):
        logging.info("Fetching Assessment Item Data for {exercise}".format(exercise=exercise.display_name))
        for assessment_item in exercise.all_assessment_items:
            counter = 0
            wait = 5
            while wait:
                try:
                    semaphore.acquire()
                    logging.info("Fetching assessment item {assessment}".format(assessment=assessment_item["id"]))
                    assessment_data = khan.get_assessment_item(assessment_item["id"])
                    semaphore.release()
                    if assessment_data.get("item_data"):
                        wait = 0
                        assessment_items.append(assessment_data)
                    else:
                        logging.info("Fetching assessment item {assessment} failed retrying in {wait}".format(assessment=assessment_item["id"], wait=wait))
                        time.sleep(wait)
                        wait = wait*2
                        counter += 1
                except (requests.ConnectionError, requests.Timeout):
                    semaphore.release()
                    time.sleep(wait)
                    wait = wait*2
                    counter += 1
                if counter > 5:
                    logging.info("Fetching assessment item {assessment} failed more than 5 times, aborting".format(assessment=assessment_item["id"]))
                    break

    threads = [threading.Thread(target=fetch_assessment_data, args=(exercise,)) for exercise in exercises]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    return topic_tree, exercises, assessment_items, content

rebuild_topictree = partial(base.rebuild_topictree, whitewash_node_data=whitewash_node_data, retrieve_API_data=retrieve_API_data, channel_data=channel_data)

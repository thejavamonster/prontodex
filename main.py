"""
ProntoUploader: a simple, reusable class for uploading images to Pronto.io
with normalization, polling, retries, and message creation.
Written by Paul Estrada with lots of pain and suffering 
Only works for photos for now but should be easily adaptable to other upload types
"""
import pathlib
import mimetypes
import uuid
import requests
import time
import logging
import random
import os
import csv
import json
from collections import Counter
import re

TOKEN = ""
BUBBLE_ID = "4321430"
warning_message = "" 
last_message_id = ""


class ProntoUploader:
    def __init__(
        self,
        token: str,
        bubble_id: int,
        base_url: str = "https://stanfordohs.pronto.io",
        log_level: int = logging.INFO,
    ):
        self.base_url = base_url.rstrip("/")
        self.bubble_id = bubble_id
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s  %(levelname)-8s %(message)s",
            datefmt="%H:%M:%S",
        )
        self.log = logging.getLogger(self.__class__.__name__)

    def upload_file(self, path: str) -> dict:
        p = pathlib.Path(path)
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        size = p.stat().st_size
        url = f"{self.base_url}/api/files"
        params = {"filename": p.name, "normalize_image": "true"}
        headers = {**self.headers, "Content-Type": mime, "Content-Length": str(size)}

        with p.open("rb") as fh:
            r = requests.put(url, params=params, data=fh, headers=headers)
        r.raise_for_status()
        data = r.json()["data"]
        self.log.info("Uploaded %s → key=%s", p.name, data["key"])
        return data

    def wait_until_ready(
        self,
        orig_key: str,
        preset: str = "PHOTO",
        tries: int = 6,
        delay: float = 0.5,
    ) -> None:
        url = f"{self.base_url}/api/clients/files/{orig_key}/normalized"
        for attempt in range(1, tries + 1):
            r = requests.get(url, params={"preset": preset}, headers=self.headers)
            r.raise_for_status()
            if "normalized" in r.json().get("data", {}):
                self.log.info("✓ normalized (attempt %s)", attempt)
                return
            time.sleep(delay)
        self.log.warning("Normalization incomplete after %s attempts", tries)

    def create_message(
        self,
        orig_key: str = "",
        norm_key: str = "",
        meta: dict = "",
        text: str = "",
        media_type: str = "PHOTO",
        tries: int = 3,
    ) -> int:
        payload_stub = {"uuid": str(uuid.uuid4()), "bubble_id": self.bubble_id}
        url = f"{self.base_url}/api/v1/message.create"
        if (orig_key != "" and norm_key != "" and meta != ""): 

            for attempt in range(1, tries + 1):
                payload = {
                    **payload_stub,
                    "message": text,
                    "messagemedia": [
                        {
                            "mediatype": media_type,
                            "title": meta["name"],
                            "filesize": meta["filesize"],
                            "mimetype": meta["mimetype"],
                            "width": meta["width"],
                            "height": meta["height"],
                            "uuid": norm_key,
                        }
                    ],
                }
                r = requests.post(url, json=payload, headers=self.headers)

                if r.status_code == 400 and "INVALID_ATTACHMENT_FILE_KEY" in r.text:
                    self.log.warning(
                        "Key not ready (%s/%s), retrying…", attempt, tries
                    )
                    self.wait_until_ready(orig_key, tries=3, delay=0.7)
                    continue

                r.raise_for_status()
                msg_id = r.json()["message"]["id"]
                self.log.info("✓ posted – message_id=%s", msg_id)
                return msg_id

            raise RuntimeError("Message creation failed after retries")
        else:
            payload = {
                **payload_stub,
                "message": text,
            }
            r = requests.post(url, json=payload, headers=self.headers)
            r.raise_for_status()
            msg_id = r.json()["message"]["id"]
            self.log.info("✓ posted – message_id=%s", msg_id)
            return msg_id



    def send(self, file_path: str = "", text: str = "") -> int:
        if file_path != "":
            """
            Uploads a file, waits for normalization, and creates a message.
            Returns the message ID.
            """
            # 1. upload and determine original key
            info = self.upload_file(file_path)
            orig_key = info["key"]

            # 2. detect media category from local file or returned metadata
            mime = mimetypes.guess_type(file_path)[0] or ""
            category = mime.split("/", 1)[0]
            # map to Pronto preset/mediatype
            type_map = {"image": "PHOTO", "video": "VIDEO", "audio": "AUDIO"}
            preset = type_map.get(category, "PHOTO")

            # 3. wait for normalization under the chosen preset
            self.wait_until_ready(orig_key, preset=preset)

            # 4. fetch normalized metadata
            r = requests.get(
                f"{self.base_url}/api/clients/files/{orig_key}/normalized",
                params={"preset": preset},
                headers=self.headers,
            )
            r.raise_for_status()
            norm_data = r.json()["data"]["normalized"]

            # 5. prepare meta dict
            meta = {
                "name":     norm_data["name"],
                "filesize": norm_data["filesize"],
                "mimetype": norm_data["mimetype"],
                "width":    norm_data.get("width"),
                "height":   norm_data.get("height"),
            }

            # 6. create message with appropriate media_type
            return self.create_message(orig_key, norm_data["key"], meta, text, media_type=preset)
        else:
            return self.create_message(text=text)


def fetch_latest_message():
    global TOKEN
    global BUBBLE_ID
    api_base_url = "https://stanfordohs.pronto.io/"
    bubbleID = BUBBLE_ID
    global last_message_id

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}",
    }

    """Fetch only the most recent message"""
    url = f"{api_base_url}api/v1/bubble.history"
    data = {"bubble_id": bubbleID}
    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 200:
        messages = response.json().get("messages", [])
        if messages[0]["id"] != last_message_id:
            last_message_id = messages[0]["id"]
            return [messages[0]["message"], messages[0]["user"]["id"], messages[0]["user"]["firstname"] +" "+ messages[0]["user"]["lastname"]]

    else:
        print(f"HTTP error occurred: {response.status_code} - {response.text}")

    return ["","",""]


def ballspawn():
    global TOKEN
    global BUBBLE_ID
    ball = list(csv.reader(open('balls.csv')))[random.randint(1,2)]
    print(ball)
    FILE_PATH = "balls/" + ball[1]
    name = ball[0]
    names = ball[3]
    names = names.split(' ')
    names =[x.lower() for x in names]
    #print(name)
    rarity = ball[2]


    uploader = ProntoUploader(token=TOKEN, bubble_id=BUBBLE_ID)


    try:
        message_id = uploader.send(FILE_PATH, text="A new ball spawned!")
        print("Message sent, ID =", message_id)
    except requests.HTTPError as e:
        uploader.log.error("HTTP error: %s", e)
    except Exception as e:
        uploader.log.exception("Unexpected error: %s", e)
    
    while True:
        msg = fetch_latest_message()
        text = msg[0]
        user_id = str(msg[1])
        user_name = msg[2]
        #print(msg)
        if text.lower()[7:] in names:
            uploader.send(text = f"<@{user_id}> caught {name}")

            try:
                with open("db.json", "r") as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                data = {}

            if user_id not in data:
                data[user_id] = []

            data[user_id].append(name)

            with open("db.json", "w") as f:
                json.dump(data, f, indent=4)

            break




def give_ball_from_input(input_str, giver_id):
    global TOKEN
    global BUBBLE_ID

    uploader = ProntoUploader(token=TOKEN, bubble_id=BUBBLE_ID)

    """
    Parse the input string and call the give function to give the ball.
    input_str is of the form: !give <ball_name> <@Receiver Name>
    giver_id is the ID of the user giving the ball.
    """
    result = None
    # Parse the input string using regular expressions
    match = re.match(r"!give\s+(\S+)\s+<@(.+)>", input_str)
    if not match:
        result =  "Error: Invalid input format. Example: give Gondor @John Doe"
        uploader.send(text = result)
        return result
    
    ball = match.group(1)  # Extract ball name
    print(ball)
    receiver_name = match.group(2).strip()  # Extract receiver's name
    print(receiver_name)

    give(ball, giver_id, receiver_name)
    return result


def give(ball, giver, receiver):
    global TOKEN
    global BUBBLE_ID

    uploader = ProntoUploader(token=TOKEN, bubble_id=BUBBLE_ID)


    result = None
    try:
        # Load the existing data from the JSON file
        with open("db.json", "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    # Check if the giver has the ball
    giver_id = str(giver)
    if giver_id not in data or ball not in data[giver_id]:
        result = f"Error: <@{giver}> doesn't have the ball {ball} to give."
        uploader.send(text = result)
        return result

    # Remove one instance of the ball from the giver's list
    data[giver_id].remove(ball)
    
    # If the receiver doesn't exist in the data, create a new entry
    receiver_id = str(receiver)
    if receiver_id not in data:
        data[receiver_id] = []

    # Add the ball to the receiver's list
    data[receiver_id].append(ball)

    # Save the updated data back to the JSON file
    with open("db.json", "w") as f:
        json.dump(data, f, indent=4)
    
    result = f"<@{giver}> has successfully given {ball} to <@{receiver}>."
    uploader.send(text = result)
    return result
    


def view(ball, user_id):
    global TOKEN
    global BUBBLE_ID
    link = ""
    uploader = ProntoUploader(token=TOKEN, bubble_id=BUBBLE_ID)

    # Step 1: Convert entered name (alternate or main) to official name + get link
    official_name = None
    link = None

    with open("balls.csv", encoding='utf-8') as f:
        next(f)  # skip header
        for line in f:
            parts = line.strip().split(',')
            main_name = parts[0]
            image_link = parts[1]
            alternates = parts[3].split(" ")
            all_names = [main_name] + alternates
            if ball.lower() in [n.lower() for n in all_names]:
                official_name = main_name
                link = image_link
                break

    if not official_name:
        uploader.send(text = "Name not found.")
        return "Name not found."

    # Step 2: Check if the user owns the *official* ball name
    try:
        with open("db.json", "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        result = "There was an error loading the database."
        uploader.send(text=result)
        return result

    giver_id = str(user_id)
    if giver_id not in data or official_name.lower() not in [x.lower() for x in data[giver_id]]:
        result = f"Error: You don't have the ball {official_name}."
        uploader.send(text=result)
        return result

    # Step 3: Show the image
    uploader.send(str("balls/" + link), "")
    return None






def monitor_messages():
    global TOKEN
    global BUBBLE_ID

    uploader = ProntoUploader(token=TOKEN, bubble_id=BUBBLE_ID)
    
    while True:
        msg = fetch_latest_message()
        text = msg[0]
        user_id = str(msg[1])
        user_name = msg[2]
        if text == "!ball":
            ballspawn()
        if text == "!list":
            try:
                with open("db.json", "r") as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                result = "No data found."

            balls = data.get(str(user_id), [])

            if not balls:
                result = f"<@{user_id}> hasn't caught any balls yet."

            ball_counts = Counter(balls)
            result = f"<@{user_id}> has caught the following balls:\n"
            
            for i, (ball, count) in enumerate(ball_counts.items()):
                result += f"{i+1}. {ball} ({count})\n"

            uploader.send("", result)

        if "!give" in text:
            print(text)
            give_ball_from_input(text, user_id)

        if "!view" in text:
            view(text[6:],user_id)
            



    

if __name__ == "__main__":
    #give_ball_from_input("!give Numenor <@5302367>", "5302419")
    monitor_messages()
